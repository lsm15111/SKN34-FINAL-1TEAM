"""대기 행동 (계약서 5장 actions.execute · 7장 함정 다섯). 비서는 행만 만들고, 실행은 사람이 누른 승인으로만 한다.

- propose: 같은 (사람, 종류, 대상)의 열린 제안을 만료(replaced)로 바꾸고 새 행을 넣는다(멱등 키가 같으면 그 행).
  commit은 부르는 쪽(도구)이 한다. action 이벤트는 commit 뒤에 보낸다.
- execute(승인): tx1 proposed → approved(조건부 UPDATE, 만료 전) commit → tx2 기능 함수 바로 앞에서
  approved → executed(mark)를 쓰고 기능 함수의 commit으로 같이 확정한다. AppError면 rollback하고 새 트랜잭션에서
  failed(기능 오류 코드)로 바꾼 뒤 409. 견적서가 새 판(quote_changed)이면 새 판 + 차액으로 새 제안을 만든다.
- executed를 다시 승인하면 같은 결과(200). rejected · expired · failed는 409. approved는 처리 중(409 in_progress).
- 만료 sweep: 기한 지난 proposed → expired(due), approved로 2분 넘게 남은 행 → failed 'stalled'(다시 실행 안 함).
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import repository as repo
from app.assistant.models import AssistantAction
from app.assistant.schemas import ActionOut, ActionResult, ActionSummary, DiffOut, SummaryRow
from app.auth.models import User
from app.db import SessionLocal
from app.shared.clock import SEOUL
from app.shared.errors import AppError
from app.shared.ids import uuid7

log = logging.getLogger(__name__)

STALL = timedelta(minutes=2)  # approved로 이만큼 남으면 멈춘 것으로 본다
DEFAULT_TTL = timedelta(days=3)
NOT_FOUND = "제안을 찾을 수 없어요."
CLOSED = {
    "rejected": "거절한 제안이에요.",
    "expired": "기한이 지난 제안이에요. 비서에게 다시 만들어 달라고 해 주세요.",
    "replaced": "새 카드로 바뀐 제안이에요.",
    "failed": "실행하지 못한 제안이에요. 비서에게 다시 만들어 달라고 해 주세요.",
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
    )


def idem_key(turn_id: uuid.UUID | None, kind: str, target_id: uuid.UUID, payload: dict) -> str:
    """같은 턴의 같은 제안은 한 행(UNIQUE(user_id, idem_key)). 턴이 다르면 새 행(옛 것은 replaced)."""
    raw = json.dumps([str(turn_id), kind, str(target_id), payload], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


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
    """새 제안 행과 그 때문에 닫힌 옛 제안들. commit은 부르는 쪽이 한다."""
    key = idem_key(turn_id, kind, target_id, payload)
    got = await repo.action_by_idem(s, user.id, key)
    if got is not None:
        return got, []
    exp = expires_at or now + DEFAULT_TTL
    if exp <= now:
        raise AppError(409, "expired", "기한이 지나 제안할 수 없어요.")
    new_id = uuid7()
    closed = await repo.replace_open(s, user.id, kind, target_id, new_id)
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
        payload=json.loads(json.dumps(payload, default=str)),
        summary=summary.model_dump(mode="json", exclude_none=True),
        idem_key=key,
        status="proposed",
        expires_at=exp,
        created_at=now,  # 만료 CHECK(expires_at > created_at)를 같은 시계로 본다
    )
    s.add(row)
    try:
        await s.flush()
    except IntegrityError:  # 같은 대상을 거의 같이 제안했다: 먼저 들어간 행을 쓴다
        await s.rollback()
        got = await repo.action_by_idem(s, user.id, key)
        if got is None:
            raise AppError(409, "stale", "다른 제안이 먼저 만들어졌어요. 다시 해 주세요.") from None
        return got, []
    return row, closed


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
        title=f"{vendor_name}로 확정",
        amount_won=total,
        version=f"견적서 {version}판",
        rows=rows,
        note="확정하면 같은 공정의 다른 요청은 닫혀요",
        approve_label=f"{vendor_name}로 확정",
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


# ---- 실행 함수(EXECUTORS): 행동 종류 → 기능 service 공개 함수. mark()는 기능 함수가 commit하기 바로 앞에서 ----


def _day(now: datetime) -> date:
    return now.astimezone(SEOUL).date()


def _stale(message: str) -> AppError:
    return AppError(409, "stale", message)


async def _home_info(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark):
    from pydantic import ValidationError

    from app.project import service as project_service
    from app.project.schemas import HomeInfoIn

    pid = a.project_id
    p = await project_service.get_for(s, user, pid)  # type: ignore[arg-type]
    if p.home is None or str(p.rev) != a.target_ver:
        raise _stale("집 정보가 그사이 바뀌었어요. 비서에게 다시 물어봐 주세요.")
    try:
        data = HomeInfoIn.model_validate({**p.home.model_dump(), **a.payload["fields"]})
    except ValidationError as e:
        raise AppError(409, "invalid", "집 정보 칸을 다시 확인해 주세요.") from e
    await mark({"text": "집 정보를 저장했어요", "href": f"/projects/{pid}", "label": "공사 보기"})
    await project_service.update(s, user, pid, data, _day(now))  # type: ignore[arg-type]


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
    got = await flow.request(s, user, p.id, body, now)
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
    await mark({"text": f"{pl['vendor_name']}로 확정했어요", "href": href, "label": "견적서 보기"})
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
    data = DatesIn(days=[date.fromisoformat(x) for x in pl["days"]], crew=int(pl["crew"]))
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
    "window_answer": _window_answer,
    "decline": _decline,
    "dates": _dates,
}
