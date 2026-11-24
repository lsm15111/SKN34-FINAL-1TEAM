"""QA 11차 뒤 고침 J1-1(u1 N1, 유료 호출 0회): 일꾼이 죽어 heartbeat가 멈춘 턴이 대화를 약 2분 잠갔어요(다시 보내면
409 turn_running). 새 턴은 같은 대화의 도는 턴 heartbeat가 30초 넘게 멈췄으면 그 턴을 멈춤(stalled)으로 닫고 받아요.
살아 있는 턴은 LLM을 오래 기다려도 heartbeat를 주기마다 올려 지금처럼 409예요."""

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.assistant import runtime, service
from app.assistant.models import AssistantTurn
from app.db import SessionLocal
from app.shared.clock import now_utc
from app.shared.errors import AppError
from tests.conftest import query
from tests.test_v4_assistant_turns import ask, home, ok


def _running(chat_id: uuid.UUID, key: str, beat_ago: timedelta) -> None:
    """같은 대화에 도는 턴 하나(heartbeat는 beat_ago 전). 서버와 같은 시계(now_utc)로 적어요(DB 시계와 달라도 되게)."""
    uid = query("select user_id from assistant_turns limit 1")[0]["user_id"]
    query(
        "insert into assistant_turns (id, user_id, chat_id, surface, client_key, status, mode,"
        " heartbeat_at) values ($1, $2, $3, 'customer', $4, 'running', 'llm', $5)",
        uuid.uuid4(),
        uid,
        chat_id,
        key,
        now_utc() - beat_ago,
    )


def _turn(key: str) -> dict:
    sql = "select status, error_code, ended_at from assistant_turns where client_key = $1"
    return dict(query(sql, key)[0])


def test_dead_turn_frees_chat_without_waiting_two_minutes(api):
    """일꾼이 죽어 heartbeat가 40초 멈춘 턴: 새 턴이 그 턴을 멈춤으로 닫고 돌아요(전에는 2분 동안 409)."""
    _, pid = home(api)
    chat = uuid.UUID(ok(ask(api, pid))[0][1]["chat_id"])
    _running(chat, "dead-turn-1", timedelta(seconds=40))
    ev = ok(ask(api, pid))
    assert ev[-1][0] == "done"
    dead = _turn("dead-turn-1")
    assert (dead["status"], dead["error_code"]) == ("failed", "stalled") and dead["ended_at"]


def test_turn_with_fresh_heartbeat_still_locks_chat(api):
    """heartbeat가 10초 전인 도는 턴(살아 있음): 새 턴은 지금처럼 409이고 그 턴은 그대로 돌아요."""
    _, pid = home(api)
    chat = uuid.UUID(ok(ask(api, pid))[0][1]["chat_id"])
    _running(chat, "live-turn-1", timedelta(seconds=10))
    r = ask(api, pid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "turn_running"
    assert _turn("live-turn-1")["status"] == "running"


def test_long_live_turn_keeps_beating_and_lock(api, monkeypatch):
    """LLM을 멈춤 기준보다 오래 기다리는 살아 있는 턴: heartbeat를 주기마다 올려 다음 요청은 409 그대로예요
    (주기 · 기준을 줄여 봐요)."""
    _, pid = home(api)
    monkeypatch.setattr(service, "BEAT", 0.05)
    monkeypatch.setattr(service, "STALL_NEXT", timedelta(seconds=0.4))
    got: dict = {}
    real = runtime.run_turn

    async def slow(ctx, emit):
        await asyncio.sleep(1.0)  # 멈춤 기준(0.4초)보다 오래 답을 기다려요
        async with SessionLocal() as s:
            beat = await s.scalar(
                select(AssistantTurn.heartbeat_at).where(AssistantTurn.id == ctx.turn_id)
            )
        got["lag"] = (now_utc() - beat).total_seconds()
        try:
            await service.start_turn(
                ctx.user,
                surface="customer",
                client_key="second-key-1",
                text="하나 더 물어요",
                project_id=ctx.project_id,
            )
        except AppError as e:
            got["second"] = (e.status, e.code)
        return await real(ctx, emit)

    monkeypatch.setattr(runtime, "run_turn", slow)
    ev = ok(ask(api, pid))
    assert ev[-1][0] == "done"
    assert got["second"] == (409, "turn_running")
    assert got["lag"] < 0.4
    left = query("select status, error_code from assistant_turns order by created_at")
    assert [(x["status"], x["error_code"]) for x in left] == [("done", None)]
