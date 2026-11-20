"""비서 서비스 (계약서 3장 · 4장): 턴 시작 · 끝 · SSE · 승인 · 거절 · 대화 기록 · 보드 · 오늘 · 업체 브리핑.

- start_turn(짧은 세션): 같은 client_key면 되돌림(done) 또는 409(running) → 권한(남의 공사 · 요청 404) → 시간당
  요청 제한 → 비서 대화(chats.kind=assistant) → 멈춘 턴 정리 → running 행(대화 잠금, 부분 UNIQUE → 409
  turn_running) → 최근 12줄 · 열린 제안 · 턴 사실 → commit. 세션을 닫은 뒤 LLM을 부른다.
- finish_turn(한 트랜잭션): rev 올리기(조건부) → 가린 질문 · 검사한 답 두 줄 → 턴 done → commit → done 이벤트.
- SSE: 모든 data에 seq, 머리에 id {turn_id}:{seq}. action은 행 commit 뒤, done은 대화 저장 commit 뒤.
  스트림을 열기 전 오류(404 · 409 · 429)는 같은 오류 모양이다. 화면이 끊어도 턴은 끝까지 돌려 저장한다.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.assistant import actions, policy, runtime
from app.assistant import repository as repo
from app.assistant.models import AssistantTurn
from app.assistant.runtime import RefTable, TurnCtx, TurnResult
from app.assistant.schemas import (
    ActionOut,
    ActionPart,
    ApproveIn,
    AssistantItem,
    AssistantThreadOut,
    BoardMoneyOut,
    BoardOut,
    BoardPeriod,
    BoardVendorRow,
    BoardVendors,
    CardOut,
    CardPart,
    ErrorOut,
    FeedPage,
    HealthOut,
    LinkOut,
    QuoteChecklistData,
    TextPart,
    TodayData,
    TurnContextIn,
    TurnOut,
    UserItem,
    VendorBriefData,
    VendorTodayData,
)
from app.auth.models import User
from app.chat import repository as chat_repo
from app.chat.models import Chat, ChatMessage
from app.config import settings
from app.db import SessionLocal
from app.shared.clock import now_utc, today_seoul
from app.shared.errors import AppError

log = logging.getLogger(__name__)

TURNS_PER_HOUR = 60  # 사용자별 시간당 턴 수(APP_ENV=local이면 세지 않음, v3와 같음)
HISTORY = 12  # 지난 글 줄 수(계약서 4장 1)
STALL = timedelta(minutes=2)  # heartbeat가 이만큼 멈추면 failed 'stalled'
FEED_LIMIT = 30
RUNNING = "앞 답을 만드는 중이에요. 끝나면 다시 보내 주세요."
TOO_MANY = "비서에게 너무 많이 물었어요. 잠시 뒤에 다시 해 주세요."
FAILED = "답을 끝까지 만들지 못했어요. 다시 해 주세요."
CARDS_ONLY = "(카드를 보여 줬어요"
_BACKGROUND: set[asyncio.Task] = set()  # 화면이 끊어도 끝까지 도는 턴


# ---- 턴 시작 ----


def _history(rows: list[ChatMessage]) -> list[dict]:
    out = [{"role": m.role, "content": m.text} for m in rows if m.text.strip()]
    while out and out[0]["role"] != "user":  # Claude는 user로 시작한다
        out.pop(0)
    return out


async def _customer_facts(s, user: User, pid: uuid.UUID, today, opened: list) -> str:
    from app.assistant.tools import cards

    _, home = await cards.home(s, user, pid)
    lines = [
        f"오늘: {today.isoformat()}",
        "화면: 고객 비서",
        "단계: " + ("실측 요청 뒤(집 정보는 잠김)" if home["locked"] else "실측 요청 전"),
        "집: " + " · ".join(home["facts"]),
    ]
    if opened:
        lines.append("승인 기다리는 카드: " + " · ".join(a.summary["title"] for a in opened))
    return "\n".join(lines)


def _vendor_facts(today, visit_ref: str | None, opened: list) -> str:
    lines = [f"오늘: {today.isoformat()}", "화면: 업체 비서"]
    if visit_ref:
        lines.append(f"지금 보는 요청: {visit_ref}")
    if opened:
        lines.append("승인 기다리는 카드: " + " · ".join(a.summary["title"] for a in opened))
    return "\n".join(lines)


def _choices(ctx: TurnContextIn | None) -> list[str]:
    if ctx is None or ctx.choice is None:
        return []
    return [ctx.choice] if isinstance(ctx.choice, str) else list(ctx.choice)[:5]


async def start_turn(
    user: User,
    *,
    surface: str,
    client_key: str,
    text: str,
    project_id: uuid.UUID | None = None,
    visit_id: uuid.UUID | None = None,
    context: TurnContextIn | None = None,
) -> TurnCtx | AssistantTurn:
    """돌 턴의 문맥, 또는 같은 client_key로 이미 끝난 턴(되돌림). 오류는 스트림을 열기 전에 난다."""
    from app.project import service as project_service
    from app.shared import ratelimit
    from app.visit import service as visit_service

    now, today = now_utc(), today_seoul()
    masked = policy.mask_in(text)
    async with SessionLocal() as s:
        old = await repo.turn_by_key(s, user.id, client_key)
        if old is not None:
            if old.surface != surface:
                raise AppError(404, "not_found", "대화를 찾을 수 없어요.")
            if old.status == "running":
                raise AppError(409, "turn_running", RUNNING)
            return old
        if surface == "customer":
            await project_service.get_for(s, user, project_id)  # 남의 공사 · 없는 공사 404
            await project_service.lock(s, project_id)  # 같은 공사의 대화 만들기가 줄 선다
        elif visit_id is not None:
            await visit_service.vendor_visit(s, user, visit_id, today)  # 남의 요청 404
        if settings.app_env != "local":
            await ratelimit.hit(
                ratelimit.key("assistant-turn", str(user.id)), TURNS_PER_HOUR, 3600, TOO_MANY
            )
        chat = await repo.assistant_chat(s, user.id, project_id)
        if chat is None:
            chat = await chat_repo.insert_chat(s, user.id, project_id=project_id, kind="assistant")
        await repo.fail_stalled(s, now, now - STALL, chat_id=chat.id)
        turn = AssistantTurn(
            user_id=user.id,
            chat_id=chat.id,
            surface=surface,
            project_id=project_id,
            visit_id=visit_id,
            client_key=client_key,
            status="running",
            mode="llm",
            heartbeat_at=now,
            created_at=now,
        )
        s.add(turn)
        try:
            await s.flush()
        except IntegrityError as e:
            await s.rollback()
            if "uq_assistant_turns_running" in str(e.orig):
                raise AppError(409, "turn_running", RUNNING) from None
            old = await repo.turn_by_key(s, user.id, client_key)  # 같은 키가 거의 같이 왔다
            if old is None or old.status == "running":
                raise AppError(409, "turn_running", RUNNING) from None
            return old
        rows = await repo.messages(s, chat.id, HISTORY)
        opened = await repo.actions_of(
            s, user.id, surface, project_id=project_id, status="proposed", limit=5
        )
        refs = await RefTable.load(chat.id)
        visit_ref = (
            refs.put("visit", {"id": str(visit_id)}) if surface == "vendor" and visit_id else None
        )
        facts = (
            await _customer_facts(s, user, project_id, today, opened)
            if surface == "customer"
            else _vendor_facts(today, visit_ref, opened)
        )
        rev = chat.rev
        await s.commit()
    choice = [r for r in _choices(context) if refs.known(r)]
    return TurnCtx(
        turn_id=turn.id,
        chat_id=chat.id,
        user=user,
        surface=surface,
        project_id=project_id,
        visit_id=visit_id,
        today=today,
        now=now,
        text=masked,
        choice=choice,
        history=_history(rows),
        facts=facts,
        rev=rev,
        refs=refs,
        client_key=client_key,
        card_id=context.card_id if context else None,
    )


# ---- 턴 끝 ----


async def finish_turn(ctx: TurnCtx, res: TurnResult) -> int:
    """대화 저장과 턴 끝을 한 트랜잭션으로. 새 rev를 돌려준다."""
    now = now_utc()
    ms = int((now - ctx.now).total_seconds() * 1000)
    async with SessionLocal() as s:
        if not await chat_repo.bump_rev(s, ctx.user.id, ctx.chat_id, ctx.rev, None):
            await s.rollback()
            raise AppError(409, "conflict", "다른 질문이 먼저 저장됐어요. 다시 물어봐 주세요.")
        chat_repo.add_turn(s, ctx.chat_id, ctx.rev, ctx.text, res.text, None)
        ended = await repo.end_turn(
            s,
            ctx.turn_id,
            now,
            status=res.status,
            mode=res.mode,
            tool_calls=min(res.tool_calls, policy.TOOL_MAX),
            cost_micros=res.cost_micros,
            trace=res.trace(ctx.rev, ms),
            cards=res.cards,
        )
        if not ended:  # sweep이 멈춤(stalled)으로 닫았다
            await s.rollback()
            raise AppError(409, "turn_stalled", "답이 너무 오래 걸려 멈췄어요. 다시 물어봐 주세요.")
        await s.commit()
    await ctx.refs.save()
    return ctx.rev + 1


async def fail_turn(ctx: TurnCtx, code: str, res: TurnResult | None = None) -> None:
    try:
        async with SessionLocal() as s:
            await repo.end_turn(
                s,
                ctx.turn_id,
                now_utc(),
                status="failed",
                error_code=code[:40],
                mode=res.mode if res else "llm",
                tool_calls=min(res.tool_calls, policy.TOOL_MAX) if res else 0,
                cost_micros=res.cost_micros if res else 0,
                cards=res.cards if res else [],
                trace=res.trace(ctx.rev, 0) if res else {"rev": None},
            )
            await s.commit()
    except Exception as e:  # noqa: BLE001 - 실패 기록 실패는 sweep이 stalled로 닫는다
        log.warning("비서 턴 실패 기록 실패 (%s)", type(e).__name__)


def _sse(turn_id: uuid.UUID, name: str, seq: int, data: dict) -> str:
    body = json.dumps({**data, "seq": seq}, ensure_ascii=False, default=str)
    return f"id: {turn_id}:{seq}\nevent: {name}\ndata: {body}\n\n"


async def stream(ctx: TurnCtx) -> AsyncIterator[str]:
    """한 턴의 SSE. 일은 따로 돈다(화면이 끊어도 저장까지 간다)."""
    q: asyncio.Queue[str | None] = asyncio.Queue()
    seq = 0

    async def emit(name: str, data: dict) -> None:
        nonlocal seq
        seq += 1
        q.put_nowait(_sse(ctx.turn_id, name, seq, data))

    async def work() -> None:
        res: TurnResult | None = None
        try:
            await emit(
                "ack",
                {
                    "turn_id": str(ctx.turn_id),
                    "chat_id": str(ctx.chat_id),
                    "at": ctx.now.isoformat(),
                },
            )
            res = await runtime.run_turn(ctx, emit)
            rev = await finish_turn(ctx, res)
            await emit(
                "done",
                {
                    "rev": rev,
                    "mode": res.mode,
                    "cards": [c["card_id"] for c in res.cards],
                    "actions": res.actions,
                    "stopped": res.status == "stopped",
                    "chips": res.chips,
                },
            )
        except AppError as e:
            await fail_turn(ctx, e.code, res)
            await emit("error", {"code": e.code, "message": e.message})
        except Exception as e:  # noqa: BLE001 - 스트림이 열린 뒤라 error 이벤트로 알린다(종류 이름만 로그)
            log.warning("비서 턴 실패 (%s)", type(e).__name__)
            await fail_turn(ctx, "failed", res)
            await emit("error", {"code": "failed", "message": FAILED})
        finally:
            q.put_nowait(None)

    task = asyncio.create_task(work())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    while (item := await q.get()) is not None:
        yield item


async def replay(user: User, turn: AssistantTurn) -> AsyncIterator[str]:
    """같은 client_key의 끝난 턴을 다시 보낸다(카드 · 행동 지금 상태 · 저장한 답 · done 또는 error)."""
    async with SessionLocal() as s:
        text = await _answer_text(s, turn)
        ids = [uuid.UUID(x) for x in (turn.trace or {}).get("actions", [])]
        acts = await repo.actions_by_id(s, user.id, ids)
        chat = await s.get(Chat, turn.chat_id)
    seq = 0

    def ev(name: str, data: dict) -> str:
        nonlocal seq
        seq += 1
        return _sse(turn.id, name, seq, data)

    yield ev(
        "ack",
        {"turn_id": str(turn.id), "chat_id": str(turn.chat_id), "at": turn.created_at.isoformat()},
    )
    for c in turn.cards or []:
        yield ev("card", c)
    for i in ids:
        if i in acts:
            yield ev("action", actions.out(acts[i]).model_dump(mode="json"))
    if turn.status == "failed":
        yield ev("error", {"code": turn.error_code or "failed", "message": FAILED})
        return
    if text and turn.mode == "llm" and not text.startswith(CARDS_ONLY):
        yield ev("token", {"text": text})
    r = (turn.trace or {}).get("rev")
    rev = r + 1 if isinstance(r, int) else (chat.rev if chat else 1)
    yield ev(
        "done",
        {
            "rev": rev,
            "mode": turn.mode,
            "cards": [c["card_id"] for c in turn.cards or []],
            "actions": [str(i) for i in ids],
            "stopped": turn.status == "stopped",
            "chips": runtime.chips_for(turn.cards or []),
        },
    )


async def _answer_text(s, turn: AssistantTurn) -> str | None:
    rev = (turn.trace or {}).get("rev")
    if rev is None:
        return None
    return await s.scalar(
        select(ChatMessage.text).where(
            ChatMessage.chat_id == turn.chat_id,
            ChatMessage.turn == rev,
            ChatMessage.role == "assistant",
        )
    )


async def turn_out(user: User, turn_id: uuid.UUID, surface: str) -> TurnOut:
    async with SessionLocal() as s:
        t = await repo.turn_owned(s, user.id, turn_id)
        if t is None or t.surface != surface:
            raise AppError(404, "not_found", "대화를 찾을 수 없어요.")
        ids = [uuid.UUID(x) for x in (t.trace or {}).get("actions", [])]
        acts = await repo.actions_by_id(s, user.id, ids)
        text = await _answer_text(s, t)
    return TurnOut(
        turn_id=t.id,
        chat_id=t.chat_id,
        surface=t.surface,  # type: ignore[arg-type]
        status=t.status,  # type: ignore[arg-type]
        mode=t.mode,  # type: ignore[arg-type]
        tool_calls=t.tool_calls,
        text=text,
        cards=[CardOut.model_validate(c) for c in t.cards or []],
        actions=[actions.out(acts[i]) for i in ids if i in acts],
        error_code=t.error_code,
        created_at=t.created_at,
        ended_at=t.ended_at,
    )


async def latest_thread(user: User, project_id: uuid.UUID) -> AssistantThreadOut | None:
    from app.project import service as project_service

    async with SessionLocal() as s:
        await project_service.get_for(s, user, project_id)
        chat = await repo.assistant_chat(s, user.id, project_id)
    return (
        AssistantThreadOut(chat_id=chat.id, rev=chat.rev, updated_at=chat.updated_at)
        if chat
        else None
    )


# ---- 행동 ----


async def approve(user: User, action_id: uuid.UUID, body: ApproveIn, surface: str) -> ActionOut:
    return await actions.execute(user, action_id, surface, body.seen, now_utc())


async def reject(user: User, action_id: uuid.UUID, surface: str) -> ActionOut:
    return await actions.reject(user, action_id, surface, now_utc())


async def actions_for(
    user: User, surface: str, project_id: uuid.UUID | None, status: str | None
) -> list[ActionOut]:
    from app.project import service as project_service

    async with SessionLocal() as s:
        if project_id is not None:
            await project_service.get_for(s, user, project_id)
        rows = await repo.actions_of(s, user.id, surface, project_id=project_id, status=status)
    return [actions.out(a) for a in rows]


# ---- 대화 기록 ----


async def feed_for(
    user: User,
    surface: str,
    project_id: uuid.UUID | None,
    before: int | None = None,
    limit: int = FEED_LIMIT,
) -> FeedPage:
    """대화 기록 한 쪽(오래된 것부터). 카드는 턴에 남긴 것, 승인 카드는 지금 상태(새 판이면 새 행동)로 그린다."""
    from app.project import service as project_service

    now = now_utc()
    async with SessionLocal() as s:
        if surface == "customer":
            await project_service.get_for(s, user, project_id)
        chat = await repo.assistant_chat(s, user.id, project_id)
        if chat is None:
            return FeedPage(items=[], before=None, rev=1, chips=[], now=now)
        rows = await repo.messages(s, chat.id, limit, before)
        turns = {
            t.trace.get("rev"): t for t in await repo.turns_of(s, chat.id, [m.turn for m in rows])
        }
        ids = {uuid.UUID(x) for t in turns.values() for x in (t.trace or {}).get("actions", [])}
        acts = await repo.actions_by_id(s, user.id, list(ids))
        later = {
            uuid.UUID(a.result["superseded_by"])
            for a in acts.values()
            if a.result and a.result.get("superseded_by")
        }
        acts.update(await repo.actions_by_id(s, user.id, list(later - set(acts))))
        failed = (
            await repo.failed_turns(s, chat.id, rows[-1].created_at if rows else None, 3)
            if before is None
            else []
        )
    items: list = []
    for m in rows:
        if m.role == "user":
            items.append(UserItem(id=f"u-{m.id}", at=m.created_at, text=m.text))
            continue
        t = turns.get(m.turn)
        parts: list = [CardPart(card=CardOut.model_validate(c)) for c in (t.cards if t else [])]
        for x in (t.trace or {}).get("actions", []) if t else []:
            a = acts.get(uuid.UUID(x))
            nxt = (a.result or {}).get("superseded_by") if a else None
            a = acts.get(uuid.UUID(nxt), a) if nxt else a
            if a is not None:
                parts.append(ActionPart(action=actions.out(a)))
        if t is not None and t.mode == "llm" and not m.text.startswith(CARDS_ONLY):
            parts.append(TextPart(text=m.text, src="ai"))
        elif t is None:
            parts.append(TextPart(text=m.text, src="guide"))
        items.append(
            AssistantItem(
                id=f"a-{m.id}",
                at=m.created_at,
                turn_id=t.id if t else None,
                parts=parts,
                mode=t.mode if t else None,  # type: ignore[arg-type]
            )
        )
    for t in reversed(failed):
        items.append(
            AssistantItem(
                id=f"f-{t.id}",
                at=t.created_at,
                turn_id=t.id,
                parts=[CardPart(card=CardOut.model_validate(c)) for c in t.cards or []],
                mode=t.mode,  # type: ignore[arg-type]
                error=ErrorOut(code=t.error_code or "failed", message=FAILED),
            )
        )
    last = turns.get(max(turns)) if turns else None
    more = len(rows) == limit and rows and rows[0].turn > 1
    return FeedPage(
        items=items,
        before=rows[0].turn if more else None,
        rev=chat.rev,
        chips=runtime.chips_for(last.cards) if last else [],
        now=now,
    )


# ---- 보드 · 오늘 ----

STEP = {"house": 0, "standard": 1, "pick": 2, "visit": 3, "deal": 4, "dates": 5}


async def board_for(user: User, project_id: uuid.UUID) -> BoardOut:
    """내 공사 보드(우리 집 · 지금 단계 · 낼 금액 · 업체 · 기간 · 서류). 값은 기능 service(계산 엔진) 그대로."""
    from app.assistant.tools import cards
    from app.project import service as project_service
    from app.schedule import service as schedule_service

    today = today_seoul()
    async with SessionLocal() as s:
        p = await project_service.get_for(s, user, project_id)
        _, home = await cards.home(s, user, project_id)
        o = await schedule_service.overview_for(s, user, project_id, today)
        opened = await repo.open_count(s, user.id, project_id)
    tr = next((t for t in o.trades if t.trade == "dobae"), o.trades[0] if o.trades else None)
    now_key = next((x.key for x in tr.steps if x.state == "now"), "house") if tr else "house"
    step = 6 if o.phase in ("work", "done") else STEP.get(now_key, 0)
    m = o.money
    dealt = any(x.source == "deal" for x in m.by_trade)
    label = (
        "확정 금액 · 부가세 포함"
        if m.all_confirmed
        else "낼 금액 · 부가세 포함"
        if dealt
        else "표준견적서 · 부가세 포함"
    )
    rows = [
        BoardVendorRow(
            name=v.vendor_name,
            state="need"
            if v.next.who == "customer"
            else "waiting"
            if v.next.who == "vendor"
            else "done",
            text=cards.NEXT_TEXT.get(v.next.kind, "끝났어요"),
            won=v.total,
        )
        for v in o.vendors
    ]
    final = o.period.kind == "final"
    docs = [
        LinkOut(label="표준견적서", href=cards.href(p.id, "/standard")),
        LinkOut(label="확정 공정표" if final else "예상 공정표", href=cards.href(p.id, "/plan")),
    ]
    if any(v.total is not None for v in o.vendors):
        docs.append(LinkOut(label="실측 견적서", href=cards.href(p.id, "/quotes")))
    return BoardOut(
        project_name=f"{p.sgg} 아파트 도배",
        step=step,
        facts=home["facts"],
        confirmed=p.home is not None,
        todo=opened + (1 if o.todo else 0),
        waiting=sum(1 for v in o.vendors if v.next.who == "vendor"),
        money=BoardMoneyOut(label=label, won=m.total) if m.by_trade else None,
        vendors=BoardVendors(title="업체", rows=rows) if rows else None,
        period=BoardPeriod(
            label="공사" if final else "예상 공사",
            value=f"{o.period.start.isoformat()} ~ {o.period.end.isoformat()}",
            sub=f"일하는 날 {o.period.work_days}일",
        )
        if o.period.start
        else None,
        docs=docs,
        plan_example=not final,
        today_pin=opened,
    )


async def today_for(user: User, project_id: uuid.UUID) -> TodayData:
    from app.assistant.tools import cards

    async with SessionLocal() as s:
        card, _ = await cards.today(
            s, user, project_id, today_seoul(), now_utc(), RefTable(uuid.uuid4())
        )
    return TodayData.model_validate(card.data)


# ---- 업체 ----


async def brief_for(vendor: User, visit_id: uuid.UUID) -> VendorBriefData:
    """업체 요청 브리핑(REST). 요청함이면 추천 기간 답하기 제안 행을 만든다(실행은 승인 뒤)."""
    from app.assistant.tools import vendor as vendor_tools

    async with SessionLocal() as s:
        _, _, data, _, _ = await vendor_tools.brief(
            s, vendor, visit_id, today_seoul(), now_utc(), RefTable(uuid.uuid4())
        )
    return data


async def checklist_for(vendor: User, visit_id: uuid.UUID) -> QuoteChecklistData:
    from app.assistant.tools import vendor as vendor_tools

    async with SessionLocal() as s:
        _, _, data = await vendor_tools.checklist(
            s, vendor, visit_id, today_seoul(), RefTable(uuid.uuid4())
        )
    return data


async def vendor_today(vendor: User) -> VendorTodayData:
    from app.assistant.tools import vendor as vendor_tools

    async with SessionLocal() as s:
        return await vendor_tools.vendor_today(s, vendor, today_seoul())


# ---- 상태 · 정리 ----


async def health(user: User) -> HealthOut:
    from app.agent import llm

    breaker = await runtime.breaker_open()
    ok = True if breaker else await llm.budget_ok(user.id, "health")
    mode, reason = policy.mode_for(available=llm.available(), budget_ok=ok, breaker=breaker)
    return HealthOut(mode=mode, reason=reason)


async def sweep(now: datetime) -> dict[str, int]:
    """worker assistant_sweep(2분): 만료 제안 · 멈춘 승인 · 멈춘 턴. (먼저 말 걸기 · 기억은 0042 담당)"""
    expired, stuck = await actions.expire_due(now)
    async with SessionLocal() as s:
        stalled = await repo.fail_stalled(s, now, now - STALL)
        await s.commit()
    return {"expired": expired, "stuck": stuck, "stalled": stalled}
