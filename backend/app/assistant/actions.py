"""대기 행동 (계약서 5장 actions.execute · 7장 함정 다섯). 비서는 행만 만들고, 실행은 사람이 누른 승인으로만 한다.

- propose(offer): 대상마다 열린 제안은 하나다. 같은 (사람, 대상)의 제안 만들기는 트랜잭션 잠금으로 줄 선다.
  - 같은 제안(종류 · 대상 판 · payload)이 열려 있으면 새로 만들지 않고 그 행을 쓴다(턴 · 먼저 말 걸기가 달라도).
  - 먼저 말 걸기는 같은 종류 · 같은 대상 판의 열린 제안이 있으면 내용이 달라도 그 행을 쓴다(대화에서 고른 것을
    덮지 않는다).
  - 고객이 거절한 제안과 새 사실(대상 판 · 금액 · 날짜)이 같으면 다시 만들지 않고 거절한 행을 돌려준다(피클 규칙:
    사용자가 취소한 일은 다시 시작하지 않는다). 사람이 카드 단추를 누른 고르기(pressed)는 새로 정한 것이라 만든다.
  - 그 밖이면 열린 제안을 종류와 상관없이 만료(replaced)로 바꾸고 새 행을 넣는다(멱등 키가 같으면 그 행).
  commit은 부르는 쪽(도구)이 한다. action 이벤트는 commit 뒤에 보낸다.
- execute(승인): tx1 proposed → approved(조건부 UPDATE, 만료 전) commit → tx2 기능 함수 바로 앞에서
  approved → executed(mark)를 쓰고 기능 함수의 commit으로 같이 확정한다. AppError면 rollback하고 새 트랜잭션에서
  failed(기능 오류 코드)로 바꾼 뒤 409. 견적서가 새 판(quote_changed)이면 새 판 + 차액으로 새 제안을 만든다.
- executed를 다시 승인하면 같은 결과(200). rejected · expired · failed는 409. approved는 처리 중(409 in_progress).
- 만료 sweep: 기한 지난 proposed → expired(due), approved로 2분 넘게 남은 행 → failed 'stalled'(다시 실행 안 함).
  대상 상태가 비서 밖(화면 단추)에서 바뀐 proposed → expired(handled_elsewhere).
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import aftercare
from app.assistant import repository as repo
from app.assistant.models import AssistantAction
from app.assistant.schemas import ActionOut, ActionResult, ActionSummary, DiffOut, SummaryRow
from app.auth.models import User
from app.db import SessionLocal
from app.shared.clock import SEOUL
from app.shared.errors import AppError
from app.shared.ids import uuid7
from app.shared.korean import euro

log = logging.getLogger(__name__)

STALL = timedelta(minutes=2)  # approved로 이만큼 남으면 멈춘 것으로 본다
DEFAULT_TTL = timedelta(days=3)
NOT_FOUND = "제안을 찾을 수 없어요."
CLOSED = {
    "rejected": "거절한 제안이에요.",
    "expired": "기한이 지난 제안이에요. 비서에게 다시 만들어 달라고 해 주세요.",
    "replaced": "새 카드로 바뀐 제안이에요.",
    "failed": "실행하지 못한 제안이에요. 비서에게 다시 만들어 달라고 해 주세요.",
    "handled_elsewhere": "화면에서 이미 처리했거나 상태가 바뀐 제안이에요.",
}

Mark = Callable[[dict], Awaitable[None]]
Executor = Callable[[AsyncSession, User, AssistantAction, datetime, Mark], Awaitable[object]]


def out(a: AssistantAction) -> ActionOut:
    """행 → 화면 모양. 만료 까닭(due · replaced)은 error_code로 내보낸다(화면 호환)."""
    res = a.result or {}
    err = a.error_code or (res.get("reason") if a.status == "expired" else None)
    shown = (
        ActionResult(text=res["text"], href=res.get("href"), label=res.get("label"))
        if a.status == "executed" and res.get("text")
        else None
    )
    sup = (a.payload or {}).get("supersedes")
    by = (
        res.get("replaced_by")
        if a.status == "expired" and res.get("reason") == "replaced"
        else None
    )
    return ActionOut(
        action_id=a.id,
        kind=a.kind,  # type: ignore[arg-type]
        status=a.status,  # type: ignore[arg-type]
        summary=ActionSummary.model_validate(a.summary),
        target_ver=a.target_ver,
        expires_at=a.expires_at,
        decided_at=a.decided_at,
        executed_at=a.executed_at,
        error_code=err,
        result=shown,
        supersedes=uuid.UUID(sup) if sup else None,
        replaced_by=uuid.UUID(by) if by else None,
    )


def idem_key(turn_id: uuid.UUID | None, kind: str, target_id: uuid.UUID, payload: dict) -> str:
    """같은 턴의 같은 제안은 한 행(UNIQUE(user_id, idem_key)). 턴이 다르면 새 행(옛 것은 replaced)."""
    raw = json.dumps([str(turn_id), kind, str(target_id), payload], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


OfferState = str  # new(새 행) · same(열린 같은 행을 씀) · rejected(거절한 같은 제안) · 그 밖은 멱등 행의 상태


@dataclass
class Offered:
    """제안 만들기 결과: 행 · 이 제안 때문에 닫힌 옛 제안 · 어떻게 됐는지(state)."""

    row: AssistantAction
    closed: list[AssistantAction]
    state: OfferState

    @property
    def live(self) -> bool:
        """승인 카드로 보일 열린 행인지(새 행 · 열린 같은 행)."""
        return self.row.status == "proposed"


def _money(summary: dict) -> tuple:
    """새 사실을 견줄 금액: 합계 · 업체별 금액(계산 엔진 값)."""
    amounts = sorted((str(x.get("label")), x.get("won")) for x in summary.get("amounts") or [])
    return summary.get("amount_won"), amounts


def same_facts(a: AssistantAction, target_ver: str | None, body: dict, summary: dict) -> bool:
    """거절한 제안 a와 새 사실이 같은지: 대상 판 · payload(날짜 · 대상 · 값) · 금액이 모두 같으면 같은 제안이다."""
    if (a.target_ver, a.payload) != (target_ver, body):
        return False
    return _money(a.summary or {}) == _money(summary)


async def offer(
    s: AsyncSession,
    user: User,
    *,
    surface: str,
    kind: str,
    target_kind: str,
    target_id: uuid.UUID,
    target_ver: str | None,
    payload: dict,
    summary: ActionSummary,
    now: datetime,
    expires_at: datetime | None = None,
    project_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    origin: str = "turn",
    pressed: bool = False,
) -> Offered:
    """제안 하나(모듈 머리 규칙). commit은 부르는 쪽이 한다. pressed = 사람이 카드 단추로 고른 제안."""
    key = idem_key(turn_id, kind, target_id, payload)
    got = await repo.action_by_idem(s, user.id, key)
    if got is not None:
        return Offered(got, [], "same" if got.status == "proposed" else got.status)
    exp = expires_at or now + DEFAULT_TTL
    if exp <= now:
        raise AppError(409, "expired", "기한이 지나 제안할 수 없어요.")
    body = json.loads(json.dumps(payload, default=str))
    facts = summary.model_dump(mode="json", exclude_none=True)
    await repo.lock_target(s, user.id, target_id)
    for a in await repo.open_on(s, user.id, target_kind, target_id):
        if a.expires_at <= now:
            continue
        if (a.kind, a.target_ver, a.payload) == (kind, target_ver, body):
            return Offered(a, [], "same")  # 같은 대상의 같은 제안이 열려 있다: 새로 만들지 않는다
        if origin == "nudge" and (a.kind, a.target_ver) == (kind, target_ver):
            return Offered(a, [], "same")  # 먼저 말 걸기는 대화에서 고른 열린 카드를 덮지 않는다
    if not pressed:  # 고객이 거절한 제안: 새 사실 없이 다시 만들지 않는다
        for r in await repo.rejected_on(s, user.id, kind, target_kind, target_id):
            if same_facts(r, target_ver, body, facts):
                return Offered(r, [], "rejected")
    new_id = uuid7()
    closed = await repo.replace_open(s, user.id, target_kind, target_id, new_id)
    row = AssistantAction(
        id=new_id,
        user_id=user.id,
        surface=surface,
        origin=origin,
        kind=kind,
        project_id=project_id,
        target_kind=target_kind,
        target_id=target_id,
        target_ver=target_ver,
        payload=body,
        summary=facts,
        idem_key=key,
        status="proposed",
        expires_at=exp,
        created_at=now,  # 만료 CHECK(expires_at > created_at)를 같은 시계로 본다
    )
    try:
        async with s.begin_nested():  # 넣기만 되돌린다(부르는 쪽 트랜잭션의 다른 쓰기는 그대로)
            s.add(row)
            await s.flush()
    except IntegrityError:  # 잠금 밖에서 거의 같이 제안했다: 먼저 들어간 같은 행을 쓴다
        got = await repo.action_by_idem(s, user.id, key)
        if got is not None:
            return Offered(got, [], "same" if got.status == "proposed" else got.status)
        for a in await repo.open_on(s, user.id, target_kind, target_id):
            if (a.kind, a.target_ver, a.payload) == (kind, target_ver, body):
                return Offered(a, [], "same")
        raise AppError(409, "stale", "다른 제안이 먼저 만들어졌어요. 다시 해 주세요.") from None
    return Offered(row, closed, "new")


async def propose(
    s: AsyncSession,
    user: User,
    *,
    surface: str,
    kind: str,
    target_kind: str,
    target_id: uuid.UUID,
    target_ver: str | None,
    payload: dict,
    summary: ActionSummary,
    now: datetime,
    expires_at: datetime | None = None,
    project_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    origin: str = "turn",
) -> tuple[AssistantAction, list[AssistantAction]]:
    """(제안 행, 그 때문에 닫힌 옛 제안들). 행이 proposed가 아니면 새로 만들지 않은 것이다(거절한 같은 제안 등).
    commit은 부르는 쪽이 한다."""
    got = await offer(
        s,
        user,
        surface=surface,
        kind=kind,
        target_kind=target_kind,
        target_id=target_id,
        target_ver=target_ver,
        payload=payload,
        summary=summary,
        now=now,
        expires_at=expires_at,
        project_id=project_id,
        turn_id=turn_id,
        origin=origin,
    )
    return got.row, got.closed


def _closed(a: AssistantAction) -> AppError:
    reason = (a.result or {}).get("reason") if a.status == "expired" else a.status
    code = "expired" if a.status == "expired" and reason == "due" else "action_closed"
    return AppError(409, code, CLOSED.get(reason or a.status, CLOSED["failed"]))


async def reject(user: User, action_id: uuid.UUID, surface: str, now: datetime) -> ActionOut:
    """거절: proposed → rejected. 이미 끝난 행동이면 그대로 돌려준다(두 번 눌러도 같음)."""
    async with SessionLocal() as s:
        a = await repo.action_owned(s, user.id, action_id, surface)
        if a is None:
            raise AppError(404, "not_found", NOT_FOUND)
        if a.status == "proposed":
            got = await repo.set_action(s, a.id, ["proposed"], status="rejected", decided_at=now)
            await s.commit()
            if got is not None:
                return out(got)
            a = await repo.action_owned(s, user.id, action_id, surface)
        return out(a)  # type: ignore[arg-type]


async def execute(
    user: User, action_id: uuid.UUID, surface: str, seen: str | None, now: datetime
) -> ActionOut:
    """승인 → 실행(두 트랜잭션). 실패하면 failed로 남기고 409(기능 오류 코드)."""
    from app.schedule import service as schedule_service
    from app.visit import service as visit_service

    async with SessionLocal() as s:  # tx1: proposed → approved
        a = await repo.action_owned(s, user.id, action_id, surface)
        if a is None:
            raise AppError(404, "not_found", NOT_FOUND)
        if a.status == "executed":
            return out(a)
        if a.status == "approved":
            raise AppError(409, "in_progress", "처리하고 있어요. 잠시 뒤 다시 확인해 주세요.")
        if a.status != "proposed":
            raise _closed(a)
        if seen is not None and seen != (a.target_ver or ""):
            raise AppError(409, "stale", "카드가 바뀌었어요. 새로 불러올게요.")
        if a.expires_at <= now:
            await repo.set_action(s, a.id, ["proposed"], status="expired", result={"reason": "due"})
            await s.commit()
            raise AppError(409, "expired", CLOSED["expired"])
        got = await repo.set_action(s, a.id, ["proposed"], status="approved", decided_at=now)
        if got is None:  # 다른 승인 · 거절 · 만료가 먼저
            await s.rollback()
            again = await repo.action_owned(s, user.id, action_id, surface)
            if again is not None and again.status == "executed":
                return out(again)
            if again is not None and again.status == "approved":
                raise AppError(409, "in_progress", "처리하고 있어요. 잠시 뒤 다시 확인해 주세요.")
            raise _closed(again) if again is not None else AppError(404, "not_found", NOT_FOUND)
        a = got
        await s.commit()

    async with (
        SessionLocal() as s
    ):  # tx2: 기능 함수 + approved → executed (기능 함수의 commit으로 확정)
        marked = False

        async def mark(result: dict) -> None:
            nonlocal marked
            row = await repo.set_action(
                s, a.id, ["approved"], status="executed", executed_at=now, result=result
            )
            if row is None:
                raise AppError(409, "stale", "그사이 상태가 바뀌었어요. 새로 불러올게요.")
            # 이 대상의 먼저 말 건 줄은 할 일이 끝났다: 정리(2분)를 기다리지 않고 같은 트랜잭션에서 닫는다
            await repo.close_lines_of(s, a)
            marked = True

        try:
            await EXECUTORS[a.kind](s, user, a, now, mark)
            if not marked:  # 기능 함수가 commit하지 않는 실행(없어야 함)
                raise RuntimeError("실행 표시 없음")
        except AppError as e:
            await s.rollback()
            visit_service.drop_later(s)
            schedule_service.drop_later(s)
            await _fail(user, a, e.code, now)
            raise AppError(409, e.code, e.message) from None
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 failed로 남긴다(종류 이름만 로그)
            await s.rollback()
            visit_service.drop_later(s)
            schedule_service.drop_later(s)
            log.warning("비서 행동 실행 실패 (%s, %s)", a.kind, type(e).__name__)
            await _fail(user, a, "error", now)
            raise AppError(409, "action_failed", "실행하지 못했어요. 다시 해 주세요.") from None
        await visit_service.flush_later(s)
        await schedule_service.flush_later(s)
        done = await repo.action_owned(s, user.id, a.id, surface)
        return out(done)  # type: ignore[arg-type]


async def _fail(user: User, a: AssistantAction, code: str, now: datetime) -> None:
    """approved → failed(code). 견적서가 새 판이면 새 판으로 다시 제안한다(supersedes)."""
    async with SessionLocal() as s:
        result: dict = {"reason": code}
        if code == "quote_changed" and a.kind == "vendor_confirm":
            try:
                fresh = await _remake_confirm(s, user, a, now)
            except AppError:
                fresh = None
            if fresh is not None:
                result["superseded_by"] = str(fresh.id)
        await repo.set_action(
            s, a.id, ["approved"], status="failed", error_code=code[:40], result=result
        )
        await s.commit()


async def _remake_confirm(
    s: AsyncSession, user: User, a: AssistantAction, now: datetime
) -> AssistantAction | None:
    """확정 제안의 견적서가 새 판이 됐다: 새 판 금액 · 차액(계산 엔진)으로 새 제안(supersedes)을 만든다."""
    from app.calc import visit_view
    from app.visit import service as visit_service

    pid, visit_id = a.project_id, uuid.UUID(a.payload["visit_id"])
    if pid is None:
        return None
    today = now.astimezone(SEOUL).date()
    cmp = await visit_service.compare(s, user, pid, a.payload["trade"], today)
    row = next((r for r in cmp.vendors if r.visit_id == visit_id), None)
    if row is None or row.latest is None or row.status != "quoted" or row.seen_ver is None:
        return None
    old_total = a.summary.get("amount_won")
    new_total = row.latest.total
    diff = (
        DiffOut(
            label=f"{a.payload.get('version')}판보다",
            from_won=old_total,
            to_won=new_total,
            diff_won=visit_view.grade_diff(new_total, old_total),
        )
        if isinstance(old_total, int) and new_total is not None
        else None
    )
    summary = confirm_summary(
        row.vendor_name, row.latest.version, new_total, row.latest.days, row.latest.valid_until
    )
    summary.diff = diff
    payload = {**a.payload, "version": row.seen_ver, "supersedes": str(a.id)}
    fresh, _ = await propose(
        s,
        user,
        surface=a.surface,
        kind="vendor_confirm",
        target_kind="visit",
        target_id=visit_id,
        target_ver=str(row.seen_ver),
        payload=payload,
        summary=summary,
        now=now,
        expires_at=confirm_expiry(row.latest.valid_until, now),
        project_id=pid,
        turn_id=None,
        origin=a.origin,
    )
    return fresh


def confirm_summary(
    vendor_name: str,
    version: int,
    total: int | None,
    days: int | None,
    valid_until: date | None,
) -> ActionSummary:
    rows = []
    if days:
        rows.append(SummaryRow(label="공사 기간", value=f"{days}일"))
    if valid_until:
        rows.append(SummaryRow(label="유효기간", value=f"{valid_until.isoformat()}까지"))
    return ActionSummary(
        title=f"{euro(vendor_name)} 확정",
        amount_won=total,
        version=f"견적서 {version}판",
        rows=rows,
        note="확정하면 같은 공정의 다른 요청은 닫혀요",
        approve_label=f"{euro(vendor_name)} 확정",
    )


def confirm_expiry(valid_until: date | None, now: datetime) -> datetime:
    """확정 제안 기한: 견적서 유효기간 끝(그날 23:59 서울), 없으면 3일."""
    if valid_until is None:
        return now + DEFAULT_TTL
    end = datetime.combine(valid_until + timedelta(days=1), datetime.min.time(), SEOUL)
    return max(end, now + timedelta(hours=1))


async def expire_due(now: datetime) -> tuple[int, int]:
    """sweep: 기한 지난 제안 → expired, 멈춘 승인 → failed 'stalled'. (만료 수, 멈춤 수)"""
    async with SessionLocal() as s:
        expired = await repo.expire_due(s, now)
        stuck = await repo.fail_stuck(s, now - STALL)
        await s.commit()
    return len(expired), len(stuck)


HANDLED = "handled_elsewhere"  # 사람이 화면 단추로 직접 처리해 대상 상태가 바뀐 제안(result.reason)
HANDLED_BATCH = 200


@dataclass(frozen=True)
class Targets:
    """열린 제안들의 대상 지금 상태 (읽기 조인)"""

    projects: dict[uuid.UUID, tuple[int, bool]]  # 공사 → (rev, 잠김)
    visits: dict[uuid.UUID, str]  # 실측 → 상태
    proposals: dict[uuid.UUID, str]  # 업체가 낸 공사 날짜 → 상태
    dates: dict[uuid.UUID, str]  # 업체 확정 → 공사 날짜 상태(dates_state)
    live: set[tuple[uuid.UUID, str, uuid.UUID | None]]  # 살아 있는 실측 (공사, 공정, 업체)


def moved(a: AssistantAction, t: Targets) -> bool:
    """제안을 만든 때의 대상 상태(target_ver)와 지금 상태가 다르면 True: 이 제안은 더 쓸 데가 없다.
    확정 제안(vendor_confirm)의 target_ver는 견적서 판이라 실측 상태(quoted)로 본다(새 판은 실행이 다시 제안)."""
    pl = a.payload or {}
    match a.kind:
        case "home_info" | "visit_request":
            p = t.projects.get(a.target_id)
            if p is None or str(p[0]) != a.target_ver:
                return True
            if a.kind == "home_info":
                return p[1]
            ids = [uuid.UUID(v) for v in pl.get("vendor_ids", [])]
            return bool(ids) and all((a.target_id, pl.get("trade"), v) in t.live for v in ids)
        case "vendor_confirm":
            return t.visits.get(a.target_id) != "quoted"
        case "visit_slot" | "window_answer" | "decline":
            return t.visits.get(a.target_id) != a.target_ver
        case "dates_accept" | "delay_accept":
            return t.proposals.get(a.target_id) != "pending"
        case "dates":
            return t.dates.get(a.target_id) != a.target_ver
        case "date_change":  # target_ver = '공사 날짜 상태:기준 시작일'
            return t.dates.get(a.target_id) != (a.target_ver or "").split(":")[0]
    return False


async def close_handled() -> int:
    """sweep: 대상(target_kind · target_id)의 상태가 비서 밖(화면 단추 · 상대의 응답)에서 바뀐 열린 제안을 닫는다.
    proposed → expired, result.reason = handled_elsewhere(화면 error_code). 그 행동을 단 먼저 말 걸기 줄도 닫는다.
    바꾸기는 조건부 UPDATE(proposed일 때만)라 같은 때 승인과 겹치면 승인이 이긴다. 닫은 수."""
    from app.schedule import service as schedule_service

    async with SessionLocal() as s:
        rows = await repo.open_actions(s, HANDLED_BATCH)
        if not rows:
            return 0

        def of(kind: str) -> list[uuid.UUID]:
            return list({a.target_id for a in rows if a.target_kind == kind})

        t = Targets(
            projects=await repo.project_states(s, of("project")),
            visits=await repo.visit_states(s, of("visit")),
            proposals=await repo.proposal_states(s, of("proposal")),
            dates=await schedule_service.dates_states(s, of("deal")),
            live=await repo.live_visits(s, of("project")),
        )
        gone = [a.id for a in rows if moved(a, t)]
        gone += await aftercare.moved_ids(s, rows)  # 07: 추가 금액 · 공사 끝 확인 · 한 번 더 요청
        closed = await repo.close_handled(s, gone, HANDLED) if gone else []
        await s.commit()
    return len(closed)


# ---- 실행 함수(EXECUTORS): 행동 종류 → 기능 service 공개 함수. mark()는 기능 함수가 commit하기 바로 앞에서 ----


def _day(now: datetime) -> date:
    return now.astimezone(SEOUL).date()


def _stale(message: str) -> AppError:
    return AppError(409, "stale", message)


async def _home_info(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark):
    """집 정보 칸이 바뀌면 project.service.update(rev가 오르고 철거 범위도 같이 쓴다), 철거 범위만 바뀌면
    모은 조건만 쓴다(set_demolition, rev 그대로). 한 트랜잭션이다."""
    from pydantic import ValidationError

    from app.calc.dobae import DEMOLITION_KEY
    from app.project import service as project_service
    from app.project.schemas import HomeInfoIn

    pid = a.project_id
    p = await project_service.get_for(s, user, pid)  # type: ignore[arg-type]
    if p.home is None or str(p.rev) != a.target_ver:
        raise _stale("집 정보가 그사이 바뀌었어요. 비서에게 다시 물어봐 주세요.")
    fields = dict(a.payload["fields"])
    diy_keys = fields.pop("diy", None)  # 직접 할 일(모은 조건): 요청 뒤에도 바꿀 수 있다
    if p.locked and (fields or diy_keys is None):
        raise AppError(409, "locked", "실측을 요청한 뒤라 집 정보를 고칠 수 없어요.")
    demolition = fields.pop(DEMOLITION_KEY, None)
    data = None
    if fields:
        merged = {**p.home.model_dump(exclude={DEMOLITION_KEY, "diy"}), **fields}
        if demolition is not None:
            merged[DEMOLITION_KEY] = demolition
        if diy_keys is not None:
            merged["diy"] = diy_keys
        try:
            data = HomeInfoIn.model_validate(merged)
        except ValidationError as e:
            raise AppError(409, "invalid", "집 정보 칸을 다시 확인해 주세요.") from e
    await mark({"text": "집 정보를 저장했어요", "href": f"/projects/{pid}", "label": "공사 보기"})
    if data is not None:
        await project_service.update(s, user, pid, data, _day(now))  # type: ignore[arg-type]
        return
    if demolition is not None:
        await project_service.set_demolition(s, pid, demolition)  # type: ignore[arg-type]
    if diy_keys is not None:
        from app.project import diy

        await diy.set_diy(s, pid, list(diy_keys))  # type: ignore[arg-type]
    await s.commit()


async def _visit_request(
    s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark
):
    from app.project import service as project_service
    from app.visit import flow
    from app.visit import service as visit_service
    from app.visit.schemas import ShortlistIn, VisitCreateIn

    pid, pl = a.project_id, a.payload
    p = await project_service.get_for(s, user, pid)  # type: ignore[arg-type]
    if str(p.rev) != a.target_ver:
        raise _stale("집 정보가 그사이 바뀌었어요. 비서에게 다시 물어봐 주세요.")
    vids = [uuid.UUID(x) for x in pl["vendor_ids"]]
    have = {
        x.vendor_id for x in (await visit_service.shortlist_for(s, user, p.id, pl["trade"])).items
    }
    for vid in vids:  # 안 담은 업체만 담는다(담기는 하나씩 commit)
        if vid in have:
            continue
        try:
            await flow.add_shortlist(s, user, p.id, ShortlistIn(trade=pl["trade"], vendor_id=vid))
        except AppError as e:
            if e.code != "already":
                raise
    href = f"/projects/{pid}/visits"
    await mark(
        {"text": f"{len(vids)}곳에 실측 요청을 보냈어요", "href": href, "label": "실측 일정 보기"}
    )
    body = VisitCreateIn(
        trade=pl["trade"],
        vendor_ids=vids,
        wish_start=date.fromisoformat(pl["wish_start"]),
        wish_end=date.fromisoformat(pl["wish_end"]),
    )
    # 승인 카드의 '업체에 알릴 것'(고객이 직접 할 일)을 요청에 고정한다(반셀프, tools.diy.offer_part)
    got = await flow.request(s, user, p.id, body, now, diy=pl.get("diy"))
    if got.failed:  # 일부만 보냈으면 결과 글을 실제 수로 고친다(이미 실행됨)
        text = f"{len(got.created)}곳에 보냈어요 · {len(got.failed)}곳은 보내지 못했어요"
        await repo.set_action(
            s, a.id, ["executed"], result={"text": text, "href": href, "label": "실측 일정 보기"}
        )
        await s.commit()


async def _visit_slot(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark):
    from app.visit import flow
    from app.visit.schemas import SlotIn

    pl = a.payload
    data = SlotIn(day=date.fromisoformat(pl["day"]), half=pl["half"])
    booked = pl["via"] == "proposal" or bool(pl.get("instant"))
    text = "실측을 잡았어요" if booked else "고른 시간을 보냈어요. 업체가 수락하면 확정돼요"
    href = f"/projects/{a.project_id}/visits/{pl['visit_id']}"
    await mark({"text": text, "href": href, "label": "실측 일정 보기"})
    fn = flow.pick_proposal if pl["via"] == "proposal" else flow.pick
    await fn(s, user, a.project_id, uuid.UUID(pl["visit_id"]), data, now)  # type: ignore[arg-type]


async def _vendor_confirm(
    s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark
):
    from app.schedule import service as schedule_service
    from app.schedule.schemas import ConfirmIn

    pl = a.payload
    href = f"/projects/{a.project_id}/quotes"
    text = f"{euro(pl['vendor_name'])} 확정했어요"
    await mark({"text": text, "href": href, "label": "견적서 보기"})
    await schedule_service.confirm(
        s,
        user,
        a.project_id,  # type: ignore[arg-type]
        uuid.UUID(pl["visit_id"]),
        ConfirmIn(seen_ver=int(a.target_ver or 0)),
        _day(now),
    )


async def _dates_accept(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark):
    from app.schedule import service as schedule_service
    from app.schedule.schemas import AcceptIn

    pl = a.payload
    text = "바뀐 공사 날짜를 수락했어요" if a.kind == "delay_accept" else "공사 날짜를 수락했어요"
    await mark({"text": text, "href": f"/projects/{a.project_id}/plan", "label": "공정표 보기"})
    await schedule_service.accept_dates(
        s,
        user,
        a.project_id,  # type: ignore[arg-type]
        uuid.UUID(pl["deal_id"]),
        uuid.UUID(pl["proposal_id"]),
        AcceptIn(seen_version=int(a.target_ver or 0)),
        _day(now),
    )


# 공사 날짜 바꾸기 요청 까닭 코드 → 업체에게 보일 글(정해 둔 글, LLM 글은 업체에 가지 않는다)
CHANGE_REASONS: dict[str, str] = {
    "move": "이사 · 입주 날짜가 바뀌었어요",
    "family": "집안 일정이 생겼어요",
    "other_work": "다른 공사 일정과 맞춰야 해요",
    "other": "공사 날짜를 바꿔야 해요",
}


def change_base(t) -> tuple[date, date] | None:
    """날짜 바꾸기 요청의 기준 날짜(schedule_for의 공정 한 줄 t): 수락한 뒤면 지금 공사 날짜, 수락 전이면 업체가
    낸 날짜. 없으면 None(요청할 수 없음). schedule service의 기준과 같다."""
    d = t.deal
    if d.status == "scheduled" and d.start_date and d.end_date:
        return d.start_date, d.end_date
    if d.status == "confirmed" and t.proposal is not None and t.proposal.status == "pending":
        return t.proposal.start, t.proposal.end
    return None


def change_ver(t) -> str | None:
    """날짜 바꾸기 제안의 target_ver: '공사 날짜 상태:기준 시작일'(상태나 날짜가 바뀌면 새 사실 · 지난 카드)."""
    base = change_base(t)
    return f"{t.dates_state}:{base[0].isoformat()}" if base else None


async def _date_change(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark):
    """고객 공사 날짜 바꾸기 요청: POST …/date-requests와 같은 schedule_service.request_dates. 기준 날짜 · 상태가
    제안 때와 다르면 stale. schedule_for(예상 공정표를 새로 쓸 수 있음)를 mark 앞에서 불러 요청과 같이 확정한다."""
    from app.schedule import service as schedule_service
    from app.schedule.schemas import DateRequestIn

    pl = a.payload
    deal_id = uuid.UUID(pl["deal_id"])
    sch = await schedule_service.schedule_for(s, user, a.project_id, _day(now))  # type: ignore[arg-type]
    t = next((x for x in sch.trades if x.deal.id == deal_id), None)
    if t is None or change_ver(t) != a.target_ver:
        raise _stale("공사 날짜가 그사이 바뀌었어요. 비서에게 다시 물어봐 주세요.")
    data = DateRequestIn(
        wish_dates=[date.fromisoformat(x) for x in pl["wish_dates"]],
        reason=CHANGE_REASONS.get(pl.get("reason") or "other", CHANGE_REASONS["other"]),
    )
    text = "날짜 바꾸기를 요청했어요. 업체가 새 날짜를 올리면 수락할 수 있어요"
    href = f"/projects/{a.project_id}/schedule"
    await mark({"text": text, "href": href, "label": "공사 날짜 보기"})
    await schedule_service.request_dates(s, user, a.project_id, deal_id, data, _day(now))  # type: ignore[arg-type]


async def _window_answer(
    s: AsyncSession, vendor: User, a: AssistantAction, now: datetime, mark: Mark
):
    from app.visit import flow
    from app.visit.schemas import WindowIn

    pl = a.payload
    data = WindowIn(
        start=date.fromisoformat(pl["start"]),
        end=date.fromisoformat(pl["end"]),
        excluded=[date.fromisoformat(x) for x in pl["excluded"]],
        instant=bool(pl["instant"]),
    )
    href = f"/vendor/requests/{pl['visit_id']}"
    text = "기간을 보냈어요. 고객이 날짜를 고르면 알려 드릴게요"
    await mark({"text": text, "href": href, "label": "요청 보기"})
    await flow.answer_window(s, vendor, uuid.UUID(pl["visit_id"]), data, now)


async def _decline(s: AsyncSession, vendor: User, a: AssistantAction, now: datetime, mark: Mark):
    from app.visit import service as visit_service

    pl = a.payload
    href = f"/vendor/requests/{pl['visit_id']}"
    await mark({"text": "이번 요청을 못 받는다고 알렸어요", "href": href, "label": "요청 보기"})
    await visit_service.decline(s, vendor, uuid.UUID(pl["visit_id"]), pl["code"], _day(now))


async def _dates(s: AsyncSession, vendor: User, a: AssistantAction, now: datetime, mark: Mark):
    from app.schedule import service as schedule_service
    from app.schedule.schemas import DatesIn

    pl = a.payload
    data = DatesIn(
        days=[date.fromisoformat(x) for x in pl["days"]],
        crew=int(pl["crew"]),
        kind=pl.get("kind", "initial"),  # 07: 수락한 뒤 날짜 바꾸기 요청에 답하면 change
        request_id=uuid.UUID(pl["request_id"]) if pl.get("request_id") else None,
    )
    href = f"/vendor/jobs/{pl['deal_id']}"
    text = "공사 날짜를 보냈어요. 고객이 수락하면 확정돼요"
    await mark({"text": text, "href": href, "label": "공사 보기"})
    await schedule_service.propose_dates(s, vendor, uuid.UUID(pl["deal_id"]), data, _day(now))


EXECUTORS: dict[str, Executor] = {
    "home_info": _home_info,
    "visit_request": _visit_request,
    "visit_slot": _visit_slot,
    "vendor_confirm": _vendor_confirm,
    "dates_accept": _dates_accept,
    "delay_accept": _dates_accept,
    "date_change": _date_change,
    "window_answer": _window_answer,
    "decline": _decline,
    "dates": _dates,
    **aftercare.EXECUTORS,  # 07: extra_answer · work_check · visit_again
}
