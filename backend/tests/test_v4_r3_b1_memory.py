"""QA 3차 고침 B1(기억 미루기, f1): 리드 결정 11-22. 무료 모드(LLM 꺼짐 · 비용 상한)에 한 말은 기억 뽑기를
미뤘다가 LLM이 돌아오면 한 번 뽑아요. 같은 kind(assistant_memory)로 뒤 시각의 일 한 줄을 넣고(dedup …:laterN),
하루 상한이면 다음 서울 날, 말한 때부터 3일이 지나면 더 미루지 않아요. 미뤘다 뽑은 말은 그 뒤에 바뀐 기억 · 저장한
칩을 덮지 않아요. 지시문(물음 · 가정 · 부사)은 test_v4_r3_b1_memory_prompt가 봐요.
유료 호출 0회(무료 모드 · Claude 대본)."""

from datetime import UTC, date, datetime, time, timedelta
from functools import partial

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.calc import deadline
from app.shared.clock import SEOUL
from tests.conftest import query
from tests.test_v4_assistant_diy import chips
from tests.test_v4_assistant_turns import ask, home, ok

WEEKEND = "제가 평일엔 회사에 있어서요. 실측은 주말에만 돼요."
KIND = "assistant_memory"


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def run(api, fn, *args, **kw):
    return api.portal.call(partial(fn, *args, **kw))


def sweep(api, at: datetime):
    from app import worker

    return run(api, worker.sweep, at)


def say_free(api, pid: str, text: str) -> dict:
    """무료 모드 턴(대본 없음 + LLM_LIVE=false) 하나. 그 고객 메시지 줄."""
    llm.clear_stubs()
    ok(ask(api, pid, text))
    (msg,) = query(
        "select id, created_at from chat_messages where role = 'user'"
        " order by created_at desc limit 1"
    )
    return dict(msg)


def jobs_of(msg_id) -> list[dict]:
    rows = query(
        "select status, run_at, dedup_key from jobs where kind = $1 and ref_id = $2"
        " order by created_at",
        KIND,
        msg_id,
    )
    return [dict(r) for r in rows]


def memory(key: str) -> str | None:
    rows = query("select value from assistant_memory where key = $1", key)
    return rows[0]["value"] if rows else None


def item(key: str, value: str, quote: str) -> dict:
    return {"key": key, "value": value, "evidence_quote": quote}


# ---- 4. 무료 모드 기억 미루기(f1) ----


def test_later_time_steps_next_day_and_limit():
    said = datetime(2026, 11, 22, 1, 0, tzinfo=UTC)  # 서울 10:00
    now = said + timedelta(minutes=1)
    steps = [deadline.memory_later_at(now, said, n, next_day=False) for n in range(1, 6)]
    assert steps[:4] == [now + x for x in deadline.MEMORY_LATER] and steps[4] is None
    got = deadline.memory_later_at(now, said, 1, next_day=False, spread_minutes=7)
    assert got == now + timedelta(minutes=37)
    nxt = deadline.memory_later_at(now, said, 1, next_day=True, spread_minutes=7)
    # 다음 서울 날 0시 10분 + 7분
    assert nxt == datetime.combine(date(2026, 11, 23), time(0, 17), SEOUL)
    late = said + timedelta(days=2, hours=20)
    assert deadline.memory_later_at(late, said, 1, next_day=True) is None  # 3일을 넘어요
    assert deadline.memory_later_at(late, said, 3, next_day=False) is None
    with pytest.raises(ValueError):
        deadline.memory_later_at(datetime(2026, 11, 22), said, 1, next_day=False)


def test_free_mode_words_are_remembered_once_when_llm_returns_qa_r3_f1(api, script):
    _, pid = home(api)
    msg = say_free(api, pid, WEEKEND)
    now = datetime.now(UTC)
    assert sweep(api, now) == {(KIND, "skipped"): 1}  # LLM 꺼짐: 기억 없이 미뤄요
    first, later = jobs_of(msg["id"])
    assert first["status"] == "skipped" and later["status"] == "pending"
    assert later["dedup_key"] == f"{KIND}:{msg['id']}:later1"
    assert now + timedelta(minutes=30) <= later["run_at"] < now + timedelta(minutes=60)
    assert memory("avail_days") is None
    assert sweep(api, now + timedelta(minutes=10)) == {}  # 때가 안 됐어요
    log = script([{"json": {"items": [item("avail_days", "주말에만", "실측은 주말에만 돼요")]}}])
    assert sweep(api, now + timedelta(hours=2)) == {(KIND, "done"): 1}  # LLM이 돌아왔어요
    assert len(log) == 1 and memory("avail_days") == "주말에만"
    assert [j["status"] for j in jobs_of(msg["id"])] == ["skipped", "done"]  # 같은 말은 한 번만
    assert sweep(api, now + timedelta(days=2)) == {}


def test_still_off_keeps_deferring_then_stops(api):
    _, pid = home(api)
    msg = say_free(api, pid, WEEKEND)
    now = datetime.now(UTC)
    at = now
    for n in range(1, 6):
        assert sweep(api, at) == {(KIND, "skipped"): 1}
        rows = jobs_of(msg["id"])
        if n <= len(deadline.MEMORY_LATER):
            assert rows[-1]["status"] == "pending" and rows[-1]["dedup_key"].endswith(f"later{n}")
            at = rows[-1]["run_at"] + timedelta(seconds=1)
        else:  # 간격을 다 썼어요: 더 미루지 않아요
            assert all(r["status"] == "skipped" for r in rows) and len(rows) == n
    assert sweep(api, at + timedelta(days=1)) == {}


def test_daily_cap_defers_to_the_next_seoul_day(api, monkeypatch):
    _, pid = home(api)
    msg = say_free(api, pid, WEEKEND)

    async def over(*_a, **_k):
        raise llm.OverBudget("user_day")

    monkeypatch.setattr(llm, "claude_json", over)
    now = datetime.now(UTC)
    assert sweep(api, now) == {(KIND, "skipped"): 1}
    later = jobs_of(msg["id"])[-1]
    start = datetime.combine(now.astimezone(SEOUL).date() + timedelta(days=1), time(0, 10), SEOUL)
    assert later["status"] == "pending" and start <= later["run_at"] < start + timedelta(minutes=30)


def test_late_words_do_not_overwrite_newer_memory(api, script):
    _, pid = home(api)
    old = say_free(api, pid, "주말에만 시간이 돼요")
    now = datetime.now(UTC)
    sweep(api, now)  # 무료 모드: 미뤄요
    new = say_free(api, pid, "생각해 보니 평일 오후가 편해요")
    script([{"json": {"items": [item("avail_days", "평일", "평일 오후가 편해요")]}}])
    assert sweep(api, now + timedelta(minutes=1)) == {(KIND, "done"): 1}  # 새 말은 바로 뽑혀요
    assert memory("avail_days") == "평일"
    log = script([{"json": {"items": [item("avail_days", "주말에만", "주말에만 시간이 돼요")]}}])
    assert sweep(api, now + timedelta(hours=2)) == {(KIND, "skipped"): 1}  # 옛 말이 늦게 뽑혀도
    assert len(log) == 1 and memory("avail_days") == "평일"  # 새 기억을 덮지 않아요
    assert jobs_of(old["id"])[-1]["status"] == "skipped"
    assert jobs_of(new["id"])[-1]["status"] == "done"


def test_late_diy_words_yield_to_chips_saved_meanwhile(api, script):
    _, pid = home(api)
    msg = say_free(api, pid, "문틀 페인트는 제가 직접 칠할게요. 주말에만 돼요.")
    now = datetime.now(UTC)
    sweep(api, now)
    chips(api, pid, [])  # 그사이 화면에서 '없어요'로 저장
    script(
        [
            {
                "json": {
                    "items": [
                        item("diy", "문틀 페인트 직접", "문틀 페인트는 제가 직접 칠할게요"),
                        item("avail_days", "주말에만", "주말에만 돼요"),
                    ]
                }
            }
        ]
    )
    assert sweep(api, now + timedelta(hours=2)) == {(KIND, "done"): 1}
    assert memory("diy") is None  # 칩이 원본이라 옛 말의 직접 할 일은 버려요
    assert memory("avail_days") == "주말에만"  # 다른 기억은 남아요
    assert jobs_of(msg["id"])[-1]["status"] == "done"
