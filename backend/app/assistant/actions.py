"""대기 행동 (계약서 5장 actions.execute · 7장 함정 다섯). 비서는 행만 만들고, 실행은 사람이 누른 승인으로만 한다.

- propose(offer): 대상마다 서로 바꾸는 묶음(SWAPS, 없으면 같은 종류)의 열린 제안은 하나다. 같은 (사람, 대상)의
  제안 만들기는 트랜잭션 잠금으로 줄 선다.
  - 같은 제안(종류 · 대상 판 · payload)이 열려 있으면 새로 만들지 않고 그 행을 쓴다(턴 · 먼저 말 걸기가 달라도).
  - 먼저 말 걸기는 같은 종류 · 같은 대상 판의 열린 제안이 있으면 내용이 달라도 그 행을 쓴다(대화에서 고른 것을
    덮지 않는다).
  - 고객이 거절한 제안과 새 사실(대상 판 · 금액 · 날짜)이 같으면 다시 만들지 않고 거절한 행을 돌려준다(피클 규칙:
    사용자가 취소한 일은 다시 시작하지 않는다). 사람이 새로 정한 제안(pressed: 카드 단추 · 이번 턴에 분명히 부탁한
    말)은 만든다.
  - 그 밖이면 같은 묶음의 열린 제안을 만료(replaced)로 바꾸고 새 행을 넣는다. 다른 묶음(예: 직접 할 일 ↔ 실측
    요청)은 같은 공사여도 그대로 둔다.
  - 멱등 키가 같은 행이 열려 있고 기한 전이면 그 행, 승인 · 실행됐으면 그 행을 돌려준다. 닫혔거나 기한이 지난 행이면
    지금 시각을 섞은 키로 새로 만든다(먼저 말 걸기는 턴이 없어 키가 늘 같다).
  commit은 부르는 쪽(도구)이 한다. action 이벤트는 commit 뒤에 보낸다.
- execute(승인): tx1 proposed → approved(조건부 UPDATE, 만료 전) commit → tx2 기능 함수 바로 앞에서
  approved → executed(mark)를 쓰고 기능 함수의 commit으로 같이 확정한다. 기능 함수 안 읽기 도우미의 commit(낡은
  표준견적서 · 예상 공정표 새 판 저장)이 mark를 먼저 확정하지 않게 tx2 첫머리(_ready)에서 미리 맞춘다. AppError면
  rollback하고 새 트랜잭션에서 failed(기능 오류 코드 · 고객에게 준 말)로 바꾼 뒤 409. 견적서가 새 판(quote_changed)이면
  새 판 + 차액으로 새 제안을 만든다.
- executed를 다시 승인하면 같은 결과(200). rejected · expired · failed는 409. approved는 처리 중(409 in_progress).
- 거두기(withdraw, 고정 선 1의 예외): 실행 전(proposed) 카드는 고객 말로 거둔다. 거절과 같게 rejected로 남기고
  result.reason = withdrawn(화면 error_code). 실행된 카드는 거둘 수 없다.
- 직접 할 일(반셀프, 리드 결정 11-22 · QA r3 s6): 직접 할 일 카드를 거두거나 거절하면 저장되지 않은 일, 승인해 칩을
  줄이거나 '없어요'로 저장하면 빠진 일을 말하는 기억 조각도 지운다(tools.diy.forget). 칩이 바뀌면 열린 실측 요청
  카드는 같은 업체 · 같은 조건에 '업체에 알릴 것'만 바꾼 새 판으로 바꾼다(옛 카드는 replaced). 화면에서 칩을 바꾼 뒤
  옛 카드를 누르면 보내지 않고 새 판을 만들어(supersedes) 409 diy_changed로 알린다.
- 만료 sweep: 기한 지난 proposed → expired(due), approved로 2분 넘게 남은 행 → failed 'stalled'(다시 실행 안 함).
  대상 상태가 비서 밖(화면 단추)에서 바뀐 proposed → expired(handled_elsewhere). 열린 줄을 모두(새것부터 쪽마다)
  보고, 시간 예산이 다 되면 멈춘 자리부터 다음 차례가 잇는다.
"""

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
EXPIRED = "기한이 지난 제안이에요. 비서에게 다시 만들어 달라고 해 주세요."
FAILED = "실행하지 못했어요. 다시 해 주세요."  # 기능 오류가 아닌 실패(종류 이름만 로그)
# 닫힌 제안을 누를 때 · 턴 사실 '최근 처리한 카드'의 까닭 말(상태, 만료면 result.reason)
CLOSED = {
    "rejected": "거절한 제안이에요.",
    "withdrawn": "고객이 거둔 제안이에요.",  # 거절과 같게 남기되 까닭은 고객이 말로 거둠
    "expired": EXPIRED,
    "due": EXPIRED,  # 만료 까닭: 기한 지남
    "replaced": "새 카드로 바뀐 제안이에요.",
    "failed": "실행하지 못한 제안이에요. 비서에게 다시 만들어 달라고 해 주세요.",
    "handled_elsewhere": "화면에서 이미 처리했거나 상태가 바뀐 제안이에요.",
}
WITHDRAWN = "withdrawn"  # 고객 말로 거둔 카드(rejected)의 result.reason
# 바꿔치기 묶음: 같은 대상에서 하나를 고르면 다른 것은 뜻이 없어지는 종류끼리만 열린 제안을 바꾼다. 묶음에 없는
# 종류는 같은 종류끼리만 바꾼다(직접 할 일 · 집 정보(home_info)와 실측 요청(visit_request)은 같은 공사여도 따로다)
SWAPS: tuple[frozenset[str], ...] = (
    frozenset({"window_answer", "decline"}),  # 업체: 요청에 기간으로 답하기 ↔ 못 받아요
    frozenset({"dates_accept", "delay_accept"}),  # 고객: 같은 공사 날짜의 수락
)


def swap_kinds(kind: str) -> tuple[str, ...]:
    """kind와 서로 바꾸는 종류(자기 포함, 이름순)."""
    return tuple(sorted(next((g for g in SWAPS if kind in g), frozenset({kind}))))


Mark = Callable[[dict], Awaitable[None]]
Executor = Callable[[AsyncSession, User, AssistantAction, datetime, Mark], Awaitable[object]]


def out(a: AssistantAction) -> ActionOut:
    """행 → 화면 모양. 만료 까닭(due · replaced)과 거둔 카드(withdrawn)는 error_code로 내보낸다(화면 호환).
    target_id는 카드가 가리키는 대상이다(화면이 같은 대상이 처리된 카드의 단추를 숨긴다)."""
    res = a.result or {}
    err = a.error_code or (res.get("reason") if a.status in ("expired", "rejected") else None)
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
        target_id=a.target_id,
        target_ver=a.target_ver,
        expires_at=a.expires_at,
        decided_at=a.decided_at,
        executed_at=a.executed_at,
        error_code=err,
        result=shown,
        supersedes=uuid.UUID(sup) if sup else None,
        replaced_by=uuid.UUID(by) if by else None,
    )


def idem_key(
    turn_id: uuid.UUID | None,
    kind: str,
    target_id: uuid.UUID,
    payload: dict,
    again: datetime | None = None,
) -> str:
    """같은 턴의 같은 제안은 한 행(UNIQUE(user_id, idem_key)). 턴이 다르면 새 행(옛 것은 replaced). 먼저 말 걸기는
    턴이 없어 같은 제안이면 키가 늘 같다: 그 행이 닫힌 뒤 다시 만들 때는 again(지금 시각)을 섞는다."""
    parts = [str(turn_id), kind, str(target_id), payload]
    if again is not None:
        parts.append(again.isoformat())
    raw = json.dumps(parts, sort_keys=True, default=str)
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
    """제안 하나(모듈 머리 규칙). commit은 부르는 쪽이 한다. pressed = 사람이 새로 정한 제안(카드 단추로 고름 ·
    이번 턴에 분명히 해 달라고 함): 거절한 같은 제안도 다시 만든다."""
    key = idem_key(turn_id, kind, target_id, payload)
    got = await repo.action_by_idem(s, user.id, key)
    if got is not None:
        if got.status == "proposed" and got.expires_at > now:
            return Offered(got, [], "same")
        if got.status in ("approved", "executed"):
            return Offered(got, [], got.status)  # 사람이 승인한 같은 제안: 다시 만들지 않는다
        # 닫힌 행(기한 지남 · 바뀜 · 화면에서 처리 · 실패 · 거절) · 기한이 지난 행: 같은 키로는 새 행을 넣을 수 없어
        # 지금 시각을 섞은 키로 새로 만든다. 거절한 같은 제안은 아래 rejected_on이 막는다
        key = idem_key(turn_id, kind, target_id, payload, again=now)
    exp = expires_at or now + DEFAULT_TTL
    if exp <= now:
        raise AppError(409, "expired", "기한이 지나 제안할 수 없어요.")
    body = json.loads(json.dumps(payload, default=str))
    facts = summary.model_dump(mode="json", exclude_none=True)
    await repo.lock_target(s, user.id, target_id)
    for a in await repo.open_on(s, user.id, target_kind, target_id):
        if a.expires_at <= now:  # 정리(2분) 전이라 열려 있는 기한 지난 행: 기한 지남으로 닫는다
            await repo.set_action(s, a.id, ["proposed"], status="expired", result={"reason": "due"})
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
    closed = await repo.replace_open(s, user.id, target_kind, target_id, new_id, swap_kinds(kind))
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
    reason = (a.result or {}).get("reason") if a.status in ("expired", "rejected") else None
    reason = reason or a.status
    code = "expired" if a.status == "expired" and reason == "due" else "action_closed"
    return AppError(409, code, CLOSED.get(reason, CLOSED["failed"]))


async def reject(user: User, action_id: uuid.UUID, surface: str, now: datetime) -> ActionOut:
    """거절: proposed → rejected. 이미 끝난 행동이면 그대로 돌려준다(두 번 눌러도 같음)."""
    async with SessionLocal() as s:
        a = await repo.action_owned(s, user.id, action_id, surface)
        if a is None:
            raise AppError(404, "not_found", NOT_FOUND)
        if a.status == "proposed":
            got = await repo.set_action(s, a.id, ["proposed"], status="rejected", decided_at=now)
            if got is not None:
                await forget_unsaved_diy(s, got, now)
            await s.commit()
            if got is not None:
                return out(got)
            a = await repo.action_owned(s, user.id, action_id, surface)
        return out(a)  # type: ignore[arg-type]


async def withdraw(s: AsyncSession, a: AssistantAction, now: datetime) -> AssistantAction | None:
    """고객 말로 실행 전 카드를 거둔다: proposed → rejected(result.reason withdrawn). 조건부 UPDATE라 같은 때
    승인 · 거절 · 만료가 먼저면 None(부르는 쪽이 지금 상태를 다시 읽는다). 직접 할 일 카드면 거둔 일의 기억도
    지운다. commit은 부르는 쪽이 한다."""
    got = await repo.set_action(
        s, a.id, ["proposed"], status="rejected", decided_at=now, result={"reason": WITHDRAWN}
    )
    if got is not None:
        await forget_unsaved_diy(s, got, now)
    return got


# ---- 직접 할 일(반셀프): 기억 지우기 · 열린 실측 요청 카드 새 판(리드 결정 11-22, QA r3 s6) ----

DIY_CHANGED = "diy_changed"
DIY_CHANGED_TEXT = (
    "직접 할 일이 바뀌어 실측 요청 카드를 새로 만들었어요. 바뀐 카드를 보고 다시 눌러 주세요."
)
DIY_REISSUED = "열려 있던 실측 요청 카드도 바뀐 직접 할 일로 새로 만들었어요"


def _diy_keys(keys) -> list[str]:
    """직접 할 일 칩 키를 칩 순서로(모르는 키는 버려요)."""
    from app.project.diy import DIY

    got = set(keys or ())
    return [k for k in DIY if k in got]


async def _chips_now(s: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """지금 저장된 직접 할 일 칩(아직 안 물음 · 없어요는 빈 목록)."""
    from app.project.diy import diy_for

    return _diy_keys(await diy_for(s, project_id))


async def forget_unsaved_diy(s: AsyncSession, a: AssistantAction, now: datetime) -> None:
    """거두거나 거절한 직접 할 일 카드: 카드가 더하려던 일 중 저장되지 않은 일(카드 목록 − 지금 칩)을 말하는 기억
    조각을 지운다(기억은 원본이 아니에요, 거둔 일이 다음 요청에 다시 들어갔어요). commit은 부르는 쪽."""
    from app.assistant.tools import diy as diy_tools

    fields = (a.payload or {}).get("fields") or {}
    if a.kind != "home_info" or "diy" not in fields or a.project_id is None:
        return
    gone = set(_diy_keys(fields["diy"])) - set(await _chips_now(s, a.project_id))
    await diy_tools.forget(s, a.user_id, gone, now)


async def _remake_request(
    s: AsyncSession, user: User, a: AssistantAction, keys: list[str], now: datetime
) -> AssistantAction | None:
    """실측 요청 카드 a를 같은 업체 · 같은 조건에 '업체에 알릴 것'만 keys(지금 칩)로 바꾼 새 판으로 만든다
    (supersedes = a). '가견적' 줄의 벽지 안내도 지금 칩(벽지 직접 구매)에 맞춰요. 열린 옛 카드는 offer가 replaced로
    닫는다. 새 판을 못 만들면 None. commit은 부르는 쪽."""
    from app.assistant.tools import diy as diy_tools
    from app.assistant.tools.propose import ESTIMATE_LABEL, estimate_row
    from app.project.diy import PAPER_BUY
    from app.quote.service import OWN_PAPER_NOTE

    if a.project_id is None or a.expires_at <= now:
        return None
    payload = {k: v for k, v in (a.payload or {}).items() if k not in ("diy", "supersedes")}
    if keys:
        payload["diy"] = keys
    payload["supersedes"] = str(a.id)
    summary = ActionSummary.model_validate(a.summary)
    paper = estimate_row(OWN_PAPER_NOTE if PAPER_BUY in keys else None)
    summary.rows = [
        paper if r.label == ESTIMATE_LABEL else r
        for r in summary.rows
        if r.label != diy_tools.TOLD_LABEL
    ]
    if (row := diy_tools.told_row(keys)) is not None:
        summary.rows.append(row)
    got = await offer(
        s,
        user,
        surface=a.surface,
        kind=a.kind,
        target_kind=a.target_kind,
        target_id=a.target_id,
        target_ver=a.target_ver,
        payload=payload,
        summary=summary,
        now=now,
        expires_at=a.expires_at,
        project_id=a.project_id,
        turn_id=None,
        origin="turn",  # 고객이 직접 할 일을 바꾼 결과(먼저 말 걸기 카드도 덮어써요)
        pressed=True,  # 거절한 같은 제안이 있어도 열린 카드를 바꿔요
    )
    return got.row if got.state == "new" else None


async def reissue_requests(
    s: AsyncSession, user: User, project_id: uuid.UUID, keys: list[str], now: datetime
) -> int:
    """직접 할 일 칩이 바뀐 뒤(같은 트랜잭션): 이 공사의 열린 실측 요청 카드 중 '업체에 알릴 것'이 지금 칩과 다른
    것을 새 판으로 바꾼다(리드 결정 11-22). 바꾼 수. commit은 부르는 쪽."""
    keys = _diy_keys(keys)
    n = 0
    for a in await repo.open_on(s, user.id, "project", project_id):
        if a.kind != "visit_request" or _diy_keys((a.payload or {}).get("diy")) == keys:
            continue
        n += await _remake_request(s, user, a, keys, now) is not None
    return n


def keeps_lines(a: AssistantAction) -> bool:
    """실행해도 먼저 말 건 줄을 닫지 않는 행동: 추가 금액을 채팅으로 물어봄. 답은 아직이라 화면 단추로 물어봤을
    때처럼 그 줄은 답 기다림으로 남는다(proactive._extra_ctx가 asked를 기다림으로 본다)."""
    return a.kind == "extra_answer" and (a.payload or {}).get("answer") == "ask"


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
            # (채팅으로 묻기는 답 기다림이라 닫지 않는다)
            if not keeps_lines(a):
                await repo.close_lines_of(s, a, kinds=swap_kinds(a.kind))
            marked = True

        try:
            # 기능 함수 안 읽기 도우미의 commit이 mark를 먼저 확정하지 않게 미리 맞춘다
            await _ready(s, user, a, now)
            await EXECUTORS[a.kind](s, user, a, now, mark)
            if not marked:  # 기능 함수가 commit하지 않는 실행(없어야 함)
                raise RuntimeError("실행 표시 없음")
        except AppError as e:
            await s.rollback()
            visit_service.drop_later(s)
            schedule_service.drop_later(s)
            await _fail(user, a, e.code, now, e.message)
            raise AppError(409, e.code, e.message) from None
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 failed로 남긴다(종류 이름만 로그)
            await s.rollback()
            visit_service.drop_later(s)
            schedule_service.drop_later(s)
            log.warning("비서 행동 실행 실패 (%s, %s)", a.kind, type(e).__name__)
            await _fail(user, a, "error", now, FAILED)
            raise AppError(409, "action_failed", FAILED) from None
        await visit_service.flush_later(s)
        await schedule_service.flush_later(s)
        done = await repo.action_owned(s, user.id, a.id, surface)
        return out(done)  # type: ignore[arg-type]


# 기능 함수가 검사 앞에서 읽기 도우미를 부르는 종류: 표준견적서(quote.ensure_standard) · 예상 공정표
# (schedule.ensure_expected). 도우미는 낡았으면 새 판을 저장하고 commit한다
READY_STANDARD = frozenset({"visit_request", "visit_again"})
READY_PLAN = frozenset({"dates_accept", "delay_accept", "date_change"})


async def _ready(s: AsyncSession, user: User, a: AssistantAction, now: datetime) -> None:
    """mark(executed) 앞에서 기능 함수가 읽을 표준견적서 · 예상 공정표를 같은 도우미로 미리 맞춘다. 맞추는 commit이
    mark 뒤에 일어나면 기능 검사가 실패해도 executed가 먼저 확정되기 때문이다(_date_change의 schedule_for와 같음).
    여기 AppError는 기능 오류와 같이 failed로 남는다. schedule · quote service는 그대로 쓴다."""
    from app.project import service as project_service
    from app.quote import service as quote_service
    from app.schedule import service as schedule_service

    today = _day(now)
    if a.kind == "dates":  # 업체 공사 날짜 보내기(propose_dates)는 그 공사의 예상 공정표를 읽는다
        from app.schedule.models import Deal

        d = await s.get(Deal, uuid.UUID(a.payload["deal_id"]))
        if d is not None and d.vendor_id == user.id:
            p = await project_service.get_out(s, d.project_id)
            await schedule_service.ensure_expected(s, p, today)
        return
    if a.project_id is None or a.kind not in READY_STANDARD | READY_PLAN:
        return
    p = await project_service.get_for(s, user, a.project_id)
    if a.kind in READY_STANDARD:
        await quote_service.ensure_standard(s, p)
    if a.kind in READY_PLAN:
        await schedule_service.ensure_expected(s, p, today)


async def _fail(
    user: User, a: AssistantAction, code: str, now: datetime, message: str | None = None
) -> None:
    """approved → failed(code). 고객에게 준 말(message)을 result에 남긴다(턴 사실 '최근 처리한 카드'의 까닭).
    견적서가 새 판이면 새 판으로 다시 제안한다(supersedes)."""
    async with SessionLocal() as s:
        result: dict = {"reason": code}
        if message:
            result["message"] = message
        fresh = None
        if code == "quote_changed" and a.kind == "vendor_confirm":
            try:
                fresh = await _remake_confirm(s, user, a, now)
            except AppError:
                fresh = None
        elif code == DIY_CHANGED and a.kind == "visit_request" and a.project_id is not None:
            try:  # 화면에서 직접 할 일 칩이 바뀌었어요: 지금 칩으로 새 판(supersedes)
                fresh = await _remake_request(s, user, a, await _chips_now(s, a.project_id), now)
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
    from app.assistant.tools.cards import md_week

    rows = []
    if days:
        rows.append(SummaryRow(label="공사 기간", value=f"{days}일"))
    if valid_until:
        rows.append(SummaryRow(label="유효기간", value=f"{md_week(valid_until)}까지"))
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
HANDLED_BATCH = 200  # 한 쪽(읽기 조인 한 번)에 보는 열린 제안 수
HANDLED_SECONDS = 10.0  # 한 차례 시간 예산(sweep 60초 안). 넘으면 멈춘 자리부터 다음 차례가 잇는다
# 예산이 다 돼 멈춘 자리(created_at, id). 이 프로세스에만 둔다(지워져도 처음부터 다시 볼 뿐)
_resume: tuple[datetime, uuid.UUID] | None = None


@dataclass(frozen=True)
class Targets:
    """열린 제안들의 대상 지금 상태 (읽기 조인)"""

    projects: dict[uuid.UUID, tuple[int, bool]]  # 공사 → (rev, 잠김)
    visits: dict[uuid.UUID, str]  # 실측 → 상태
    proposals: dict[uuid.UUID, str]  # 업체가 낸 공사 날짜 → 상태
    dates: dict[uuid.UUID, str]  # 업체 확정 → 공사 날짜 상태(dates_state)
    live: set[tuple[uuid.UUID, str, uuid.UUID | None]]  # 살아 있는 실측 (공사, 공정, 업체)
    diys: dict[uuid.UUID, str] = field(default_factory=dict)  # 공사 → 직접 할 일 칩 지문(diy_ver)


def home_ver(rev: int, fields: dict, picked: list[str] | None) -> str:
    """집 정보 제안의 target_ver: 공사 rev. 직접 할 일(diy)을 바꾸는 제안이면 지금 칩 지문을 붙인다('3:d05').
    칩은 rev를 올리지 않아서, 화면에서 칩을 바꾼 뒤 옛 카드를 승인하면 옛 목록으로 덮지 않게 판으로 본다."""
    from app.project.diy import diy_ver

    return f"{rev}:{diy_ver(picked)}" if "diy" in fields else str(rev)


def moved(a: AssistantAction, t: Targets) -> bool:
    """제안을 만든 때의 대상 상태(target_ver)와 지금 상태가 다르면 True: 이 제안은 더 쓸 데가 없다.
    확정 제안(vendor_confirm)의 target_ver는 견적서 판이라 실측 상태(quoted)로 본다(새 판은 실행이 다시 제안).
    실측 요청 취소(visit_cancel)는 업체가 답해 상태가 바뀌어도 취소할 수 있는 동안은 그대로 둔다."""
    from app.visit.service import CANCELLABLE

    pl = a.payload or {}
    match a.kind:
        case "visit_cancel":
            return t.visits.get(a.target_id) not in CANCELLABLE
        case "home_info" | "visit_request":
            p = t.projects.get(a.target_id)
            rev, _, chips = (a.target_ver or "").partition(":")
            if p is None or str(p[0]) != rev:
                return True
            if a.kind == "home_info":
                if chips and t.diys.get(a.target_id) != chips:  # 화면에서 직접 할 일 칩이 바뀜
                    return True
                # 잠겨도 직접 할 일만 바꾸는 제안은 실행할 수 있다(_home_info와 같음)
                return p[1] and set(pl.get("fields") or {}) != {"diy"}
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


async def _moved_ids(s: AsyncSession, rows: list[AssistantAction]) -> list[uuid.UUID]:
    """열린 제안들 중 대상 상태가 만든 때와 달라진 것(읽기 조인 한 번씩)."""
    from app.project.diy import diy_ver, picked_of
    from app.schedule import service as schedule_service

    def of(kind: str) -> list[uuid.UUID]:
        return list({a.target_id for a in rows if a.target_kind == kind})

    chips = await repo.project_diys(s, of("project"))
    t = Targets(
        projects=await repo.project_states(s, of("project")),
        visits=await repo.visit_states(s, of("visit")),
        proposals=await repo.proposal_states(s, of("proposal")),
        dates=await schedule_service.dates_states(s, of("deal")),
        live=await repo.live_visits(s, of("project")),
        diys={pid: diy_ver(picked_of(chips.get(pid, ()))) for pid in of("project")},
    )
    gone = [a.id for a in rows if moved(a, t)]
    return gone + await aftercare.moved_ids(s, rows)  # 07: 추가 금액 · 공사 끝 확인 · 한 번 더 요청


async def close_handled(limit: int | None = None, seconds: float | None = None) -> int:
    """sweep: 대상(target_kind · target_id)의 상태가 비서 밖(화면 단추 · 상대의 응답)에서 바뀐 열린 제안을 닫는다.
    proposed → expired, result.reason = handled_elsewhere(화면 error_code). 그 행동을 단 먼저 말 걸기 줄도 닫는다.
    바꾸기는 조건부 UPDATE(proposed일 때만)라 같은 때 승인과 겹치면 승인이 이긴다. 닫은 수.
    열린 줄을 모두 본다: 새것부터 한 쪽(limit)씩 읽고(created_at · id 커서) 끝까지 간다(새것 200개 창만 보던 것,
    D2 · 부하 L3). 시간 예산(seconds)이 다 되면 멈춘 자리를 남기고, 다음 차례는 그 자리부터 끝까지 본 뒤 처음(새것)
    부터 한 번 더 돈다."""
    global _resume
    limit = limit or HANDLED_BATCH
    stop = time.monotonic() + (HANDLED_SECONDS if seconds is None else seconds)
    after, again, total = _resume, _resume is not None, 0
    _resume = None
    while True:
        async with SessionLocal() as s:
            rows = await repo.open_actions(s, limit, after=after)
            gone = await _moved_ids(s, rows) if rows else []
            if gone:
                total += len(await repo.close_handled(s, gone, HANDLED))
            await s.commit()
        if len(rows) < limit:  # 가장 오래된 줄까지 봤다
            if not again:
                break
            after, again = None, False  # 멈춘 자리부터 봤으면 처음(새것)부터 한 번 더
            continue
        after = (rows[-1].created_at, rows[-1].id)
        if time.monotonic() > stop:
            _resume = after
            log.warning("비서 화면 처리 정리 시간 예산을 넘겨 다음 차례에 이어요")
            break
    return total


# ---- 실행 함수(EXECUTORS): 행동 종류 → 기능 service 공개 함수. mark()는 기능 함수가 commit하기 바로 앞에서 ----


def _day(now: datetime) -> date:
    return now.astimezone(SEOUL).date()


def _stale(message: str) -> AppError:
    return AppError(409, "stale", message)


async def _home_info(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark):
    """집 정보 칸이 바뀌면 project.service.update(rev가 오르고 철거 범위도 같이 쓴다), 철거 범위만 바뀌면
    모은 조건만 쓴다(set_demolition, rev 그대로). 한 트랜잭션이다. 공사 행을 먼저 잠가 판(rev · 직접 할 일 칩 지문)
    검사와 저장 사이에 화면 저장(PUT /diy · 집 정보 고치기)이 끼지 않게 한다."""
    from pydantic import ValidationError

    from app.calc.dobae import DEMOLITION_KEY
    from app.project import diy
    from app.project import service as project_service
    from app.project.schemas import HomeInfoIn

    pid = a.project_id
    await project_service.lock(s, pid)  # type: ignore[arg-type]
    p = await project_service.get_for(s, user, pid)  # type: ignore[arg-type]
    rev, chipped, _ = (a.target_ver or "").partition(":")  # 칩 지문이 없는 판(옛 카드)은 rev만 본다
    if p.home is None or str(p.rev) != rev:
        raise _stale("집 정보가 그사이 바뀌었어요. 비서에게 다시 물어봐 주세요.")
    fields = dict(a.payload["fields"])
    if chipped and home_ver(p.rev, fields, await diy.diy_for(s, pid)) != a.target_ver:  # type: ignore[arg-type]
        raise _stale("직접 할 일이 화면에서 바뀌었어요. 비서에게 다시 물어봐 주세요.")
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
    done = {"text": "집 정보를 저장했어요", "href": f"/projects/{pid}", "label": "공사 보기"}
    if data is not None:
        await mark(done)
        if diy_keys is not None:  # 저장한 목록에 없는 일의 기억 조각은 지워요(리드 결정 11-22)
            await _forget_left_out(s, user, diy_keys, now)
        await project_service.update(s, user, pid, data, _day(now))  # type: ignore[arg-type]
        return
    if demolition is not None:
        await project_service.set_demolition(s, pid, demolition)  # type: ignore[arg-type]
    if diy_keys is not None:
        from app.visit import flow

        picked = await diy.set_diy(s, pid, list(diy_keys))  # type: ignore[arg-type]
        await _forget_left_out(s, user, picked, now)
        # 실측 요청(확정 전 · 공사 시작 전 확정)의 '업체에 알릴 것'도 맞추고 업체에 알려요(QA r2 c2 · r3 c6)
        synced = await flow.sync_diy(s, pid, picked, now)  # type: ignore[arg-type]
        if synced.told:  # 확정 뒤면 '확정한 업체'(QA r4 c2)
            from app.assistant.tools.propose import chosen_names, told_whom

            who = told_whom(synced.told, await chosen_names(s, pid))  # type: ignore[arg-type]
            done["text"] += f" · {who}({' · '.join(synced.told)})에도 알렸어요"
        if synced.note:
            done["text"] += f" · {synced.note}"
        if await reissue_requests(s, user, pid, picked, now):  # type: ignore[arg-type]
            done["text"] += f" · {DIY_REISSUED}"
    await mark(done)
    await s.commit()


async def _forget_left_out(s: AsyncSession, user: User, picked, now: datetime) -> None:
    """칩을 저장했어요: 저장한 목록에 없는 일(줄인 일 · '없어요')을 말하는 기억 조각을 지운다(리드 결정 11-22)."""
    from app.assistant.tools import diy as diy_tools
    from app.project.diy import DIY

    kept = set(picked or ())
    await diy_tools.forget(s, user.id, [k for k in DIY if k not in kept], now)


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
    # 카드의 '업체에 알릴 것'이 지금 칩과 다르면(화면에서 칩을 바꿈) 보내지 않고 새 판을 만들어요(_fail, 리드 결정
    # 11-22). 공사 행을 잠가 칩 저장(PUT /diy · 집 정보 승인)과 줄 세워 비교와 요청이 같은 칩을 봐요
    await project_service.lock(s, p.id)
    if _diy_keys(pl.get("diy")) != await _chips_now(s, p.id):
        raise AppError(409, DIY_CHANGED, DIY_CHANGED_TEXT)
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


# 실측 요청 취소 까닭 코드(visit.models.CANCEL_CODES 중 고객이 고르는 것) → 카드 글(정해 둔 글). 견적서가 늦어
# 닫음(late_quote)은 늦은 견적서 알림에서만 써서 뺀다. 메모는 넣지 않는다(LLM 글은 업체에 가지 않는다)
CANCEL_REASONS: dict[str, str] = {
    "changed": "일정이 바뀌었어요",
    "other_vendor": "다른 업체로 할래요",
    "other": "그 밖의 까닭",
}


async def _visit_cancel(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark: Mark):
    """고객 실측 요청 취소: POST …/visits/{id}/cancel과 같은 visit.service.cancel(이유 코드, 메모 없음). 잡기 풀기 ·
    담기 칸 비움 · 기한 일 취소 · 업체 알림은 그 함수가 한다. 같은 요청의 다른 열린 카드(반나절 고르기 · 확정 …)는
    쓸 데가 없어 같은 트랜잭션에서 닫는다(handled_elsewhere). 취소할 수 없는 상태 · 남의 것은 기능 오류로 failed."""
    from app.visit import service as visit_service
    from app.visit.schemas import CancelIn

    pl = a.payload
    visit_id = uuid.UUID(pl["visit_id"])
    others = [x.id for x in await repo.open_on(s, user.id, "visit", visit_id) if x.id != a.id]
    text = f"{pl.get('vendor_name') or '업체'}에 보낸 실측 요청을 취소했어요"
    href = f"/projects/{a.project_id}/visits"
    await mark({"text": text, "href": href, "label": "실측 일정 보기"})
    if others:
        await repo.close_handled(s, others, HANDLED)
    data = CancelIn(code=pl["code"])
    await visit_service.cancel(s, user, a.project_id, visit_id, _day(now), data, now)  # type: ignore[arg-type]


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
    "visit_cancel": _visit_cancel,
    "window_answer": _window_answer,
    "decline": _decline,
    "dates": _dates,
    **aftercare.EXECUTORS,  # 07: extra_answer · work_check · visit_again
}
