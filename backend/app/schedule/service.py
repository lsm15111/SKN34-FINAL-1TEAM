"""공정표: 예상 공정표(집 정보로 계산) · 확정 공정표 · 업체 확정.

예상 공정표는 처음 볼 때 계산해 저장하고, 집 정보(rev) · 산식 버전이 그대로면 저장본을 쓴다.
날짜 · 기간은 모두 계산 엔진(calc.schedule)이 만든다.
"""

import logging
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.responses import Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.calc import deadline, work_view
from app.calc import diy as calc_diy
from app.calc.common import FORMULA_VERSION, VAT_RATE, Money, add_money, from_entered, sum_won
from app.calc.progress import TradeFacts, first_todo, progress, project_phase
from app.calc.quote_diff import budget_gap
from app.calc.schedule import (
    JOB_MAX_DAYS,
    WEEKEND,
    Dated,
    TradePlan,
    busy_days,
    contact_until,
    count_workdays,
    days_since,
    fix_plan,
    free_range,
    is_off,
    job_days,
    lay_out,
    order_conflicts,
    overlap_days,
    start_choices,
    trade_days,
    wishes_blocked,
    workdays,
)
from app.files import service as files_service
from app.files.models import File
from app.jobs import service as jobs_service
from app.jobs.service import StatePush
from app.notify import catalog
from app.notify import service as notify_service
from app.project import service as project_service
from app.project.models import Project
from app.project.schemas import ProjectOut
from app.quote import service as quote_service
from app.quote.models import VendorQuote
from app.quote.schemas import BudgetOut
from app.realtime import service as realtime
from app.refprice.holidays import HOLIDAYS, days_off
from app.review.models import Review
from app.schedule import history, inbox
from app.schedule.models import (
    DEAL_FILES_MAX,
    OPEN_DEALS,
    DateProposal,
    DateRequest,
    Deal,
    DealEvent,
    DealFile,
    ExtraCharge,
    ExtraChargeFile,
    Plan,
    PlanDay,
    PlanStep,
)
from app.schedule.schemas import (
    AcceptIn,
    AckIn,
    AfterStepOut,
    AnswerIn,
    CheckIn,
    CompareDealOut,
    ConfirmIn,
    ConfirmOut,
    DateRequestIn,
    DateRequestOut,
    DatesIn,
    DealOut,
    DocsOut,
    DoneIn,
    ExtraIn,
    ExtraOut,
    ExtraPhotoOut,
    ExtraPreviewOut,
    FitOut,
    HolidayOut,
    InboxPageOut,
    InboxRowOut,
    JobOut,
    LogItemOut,
    MoneyOut,
    MoneySumOut,
    MyProjectOut,
    NeedOut,
    NextOut,
    OtherTradeOut,
    OverviewOut,
    PeriodOut,
    PlanBlockOut,
    PlanChangeOut,
    PlanDayOut,
    PlanDocOut,
    PlanOut,
    PlanRedo,
    PreviewOut,
    ProposalOut,
    QuoteDocOut,
    QuoteVersionDocOut,
    ScheduleOut,
    StandardDocOut,
    StartOptionOut,
    StepNeedOut,
    StepOut,
    TodoOut,
    TradeDatesOut,
    TradeExtrasOut,
    TradeMoneyOut,
    TradeProgressOut,
    VendorContactOut,
    VendorStepOut,
)
from app.shared.clock import SEOUL, now_utc
from app.shared.errors import AppError, app_error
from app.shared.ids import uuid7
from app.shared.korean import i_ga
from app.thread import service as thread_service
from app.vendor import service as vendor_service
from app.visit import service as visit_service
from app.visit.models import LIVE, Visit, VisitChange, VisitEvent, VisitProposal
from app.visit.schemas import (
    InboxSummaryOut,
    RecentOut,
    ReselectOut,
    StateTagOut,
    VendorNextOut,
)

log = logging.getLogger(__name__)

LEAD_DAYS = 14  # 공사 시기를 아직 모를 때: 오늘부터 2주 뒤 첫 일하는 날에 시작한다고 잡는다
REDO_LOCKED = (
    "업체를 확정한 뒤에는 날짜를 바꿔 볼 수 없어요. 공사 날짜 화면에서 다른 날짜를 요청해 주세요."
)
LABEL = {"mokgong": "목공", "dobae": "도배"}


def _field(loc: str, message: str) -> AppError:
    """칸 하나가 틀린 422 (화면은 fields[].loc로 칸을 찾는다)"""
    return app_error("invalid", message, fields=[{"loc": [loc], "msg": message}])


def _to_vendor(body: str, p: ProjectOut, trade: str) -> str:
    """업체 알림 본문 끝에 공사 이름 ('… · 노원구 상계동 도배', catalog.work_name, B2b 9)"""
    return f"{body} · {catalog.work_name(p.sgg, p.emd, trade)}"


Card = tuple[uuid.UUID, int]  # 대화에 넣은 시스템 카드 (대화 id, seq)
# commit 뒤에 보낼 화면 신호('인자 없는 async 함수')를 남기는 s.info 칸. schedule router의 Session이
# 엔드포인트가 끝나면(응답 전에) flush_later로 보내고, 오류로 끝나면 버린다. service를 바로 부르는 곳(시연
# 데이터 · asyncio.run 테스트)은 보내지 않는다: 신호는 지워져도 되는 것이고, 다른 이벤트 루프에서 공용
# Redis 연결을 만들어 남기지 않게 (visit.service LATER와 같은 방식).
LATER = "schedule_signals"


def _push(
    s: AsyncSession,
    states: Iterable[StatePush],
    unread: Iterable[uuid.UUID | None] = (),
    cards: Iterable[Card] = (),
) -> None:
    """commit 뒤 신호를 남긴다: 화면 신호(state) · 안 읽은 알림 수(notif) · 시스템 카드(msg,
    thread.service.notify_message). 보내기는 flush_later."""
    pushes, targets = list(states), [u for u in unread if u is not None]
    posted = list(cards)

    async def send() -> None:
        for p in pushes:
            await realtime.push_state(p.user_ids, p.kind, p.ref_id, p.project_id)
        if targets:
            await notify_service.push_unread(s, targets)
        for tid, seq in posted:
            await thread_service.notify_message(s, tid, seq)

    s.info.setdefault(LATER, []).append(send)


def drop_later(s: AsyncSession) -> None:
    s.info.pop(LATER, None)


async def flush_later(s: AsyncSession) -> None:
    """남긴 신호를 보낸다. 변경은 이미 저장됐으니 실패해도 요청을 실패로 만들지 않고 로그만 남긴다."""
    for fn in s.info.pop(LATER, None) or ():
        try:
            await fn()
        except Exception as exc:  # noqa: BLE001 - 신호는 지워져도 되는 것(화면은 다시 읽어 맞춘다)
            log.warning("화면 신호 실패: %s", type(exc).__name__)


async def _card(
    s: AsyncSession, project_id: uuid.UUID, vendor_id: uuid.UUID | None, code: str, ref_id
) -> list[Card]:
    """(공사, 업체) 대화가 있으면 시스템 카드 한 줄. 돌려주는 값: commit 뒤 알릴 카드 (없으면 빈 목록)."""
    tid = await thread_service.find(s, project_id, vendor_id) if vendor_id else None
    if tid is None:
        return []
    return [(tid, await thread_service.post_system(s, tid, code=code, ref_id=ref_id))]


async def _visit_refs(s: AsyncSession, visit_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """끝난 요청을 가리키는 기한 일 대상 id: 요청 · 다른 날 제안 · 바꾸기 요청 · 실측 견적서 (읽기 조인).
    id가 uuid7이라 jobs.cancel_refs에 같이 넘겨도 다른 표의 일과 섞이지 않는다."""
    if not visit_ids:
        return []
    out = list(visit_ids)
    for model in (VisitProposal, VisitChange, VendorQuote):
        q = select(model.id).where(model.visit_id.in_(visit_ids))
        out += list((await s.execute(q)).scalars())
    return out


async def _end_threads(
    s: AsyncSession, project_id: uuid.UUID, visits: Iterable[Visit], reason: str
) -> list[Card]:
    """끝난 요청의 업체 대화를 읽기만으로 (thread.service, visit.service가 이미 닫았으면 그대로).
    다른 업체 확정(other_chosen)이면 그 대화에 시스템 카드를 한 줄 남긴다 (요청마다 한 번 닫히니 한 번).
    돌려주는 값: commit 뒤 알릴 카드."""
    cards: list[Card] = []
    for v in visits:
        if v.vendor_id is None:
            continue
        await thread_service.set_read_only(
            s, reason=reason, project_id=project_id, vendor_id=v.vendor_id
        )
        if reason == "other_chosen":
            cards += await _card(s, project_id, v.vendor_id, "other_chosen", v.id)
    return cards


def _off(start: date) -> frozenset[date]:
    return days_off(start, start + timedelta(days=400))


def _compute(p: ProjectOut, start: date, weekend_work: bool):
    calcs = quote_service.calc_trades(p)
    trades = [TradePlan(c.trade, c.steps, c.crew) for c in calcs]
    weekend = () if weekend_work else (5, 6)
    return lay_out(trades, start, _off(start), weekend), {c.trade: c.man_day for c in calcs}


def default_start(p: ProjectOut, today: date) -> date:
    """집 정보의 공사 시기로 시작일을 잡는다. 이사 날짜만 있으면 그 전날까지 끝나게 거꾸로 잡는다."""
    earliest = workdays(today + timedelta(days=1), 1, _off(today))[0]
    if p.when.kind == "date" and p.when.start:
        return max(p.when.start, earliest)
    if p.when.kind == "movein" and p.when.start:
        start = p.when.start
        for _ in range(8):  # 끝나는 날이 이사 전날 안쪽이 될 때까지 앞당긴다
            plan, _ = _compute(p, start, False)
            over = (plan.end - p.when.start).days + 1
            if over <= 0:
                break
            start -= timedelta(days=over)
        return max(start, earliest)
    return workdays(today + timedelta(days=LEAD_DAYS), 1, _off(today))[0]


async def _latest(s: AsyncSession, project_id: uuid.UUID, kind: str) -> Plan | None:
    q = (
        select(Plan)
        .where(Plan.project_id == project_id, Plan.kind == kind)
        .order_by(Plan.version.desc())
        .limit(1)
    )
    return (await s.scalars(q)).first()


def _add_parts(
    s: AsyncSession,
    row: Plan,
    plan,
    man_days: dict[str, Decimal],
    deal_of: dict[str, uuid.UUID] | None = None,
) -> None:
    """공정표 칸 · 날짜별 할 일 행을 더한다. deal_of: 확정 공정표에서 수락한 공정의 업체 확정."""
    deal_of = deal_of or {}
    s.add_all(
        [
            PlanStep(
                plan_id=row.id,
                trade=b.trade,
                kind=b.kind,
                label=b.label or LABEL.get(b.trade or "", ""),
                start_date=b.start,
                end_date=b.end,
                days=b.days,
                crew=b.crew,
                man_day=man_days.get(b.trade) if b.trade else None,
                sort=i,
                deal_id=deal_of.get(b.trade or ""),
            )
            for i, b in enumerate(plan.blocks)
        ]
    )
    s.add_all(
        [
            PlanDay(plan_id=row.id, day=d.day, trade=d.trade, kind=d.kind, names=list(d.names))
            for d in plan.days
        ]
    )


async def _save(
    s: AsyncSession, p: ProjectOut, start: date, weekend_work: bool, prev: Plan | None
) -> None:
    plan, man_days = _compute(p, start, weekend_work)
    row = Plan(
        project_id=p.id,
        kind="expected",
        version=(prev.version + 1) if prev else 1,
        project_rev=p.rev,
        formula_ver=FORMULA_VERSION,
        start_date=plan.start,
        end_date=plan.end,
        work_days=plan.work_days,
        weekend_work=weekend_work,
    )
    s.add(row)
    try:
        await s.flush()
        _add_parts(s, row, plan, man_days)
        await s.commit()
    except IntegrityError:  # 동시에 두 번 만들면 먼저 저장한 버전을 쓴다
        await s.rollback()


async def ensure_expected(s: AsyncSession, p: ProjectOut, today: date) -> Plan:
    prev = await _latest(s, p.id, "expected")
    if prev and prev.project_rev == p.rev and prev.formula_ver == FORMULA_VERSION:
        return prev
    await _save(s, p, default_start(p, today), False, prev)
    got = await _latest(s, p.id, "expected")
    assert got is not None
    return got


async def _period(s: AsyncSession, plan: Plan) -> PeriodOut:
    """공정표 행 → 기간(처음 · 마지막 날 · 일하는 날 수 · 업체 공사 끝날). 업체 공사 끝날은 공정표 화면의 '공사 처음 ~
    끝'과 같은 값이에요(마지막 날은 자연 건조 · 입주 청소까지라 보드가 '공사'로 보이면 공정표와 달랐어요, QA r6 화면 M8)."""
    work_end = await s.scalar(
        select(func.max(PlanStep.end_date)).where(
            PlanStep.plan_id == plan.id, PlanStep.kind == "work"
        )
    )
    return PeriodOut(
        kind=plan.kind,
        start=plan.start_date,
        end=plan.end_date,
        work_days=plan.work_days,
        work_end=work_end,
    )


async def period_now(s: AsyncSession, p: ProjectOut) -> PeriodOut | None:
    """지금 공정표 기간(읽기만, 저장하지 않음): 확정 공정표가 있으면 그것, 없으면 지금 공사 판(rev)으로 만든 예상
    공정표. 예상이 낡았거나(공사 정보가 바뀐 뒤 아직 다시 안 만듦) 없으면 None. 비서 턴 사실처럼 트랜잭션 중간에
    쓰기 없이 빨리 읽는 곳이 쓴다(다시 만들기는 보드 · 공정표 읽기의 ensure_expected)."""
    plan = await _latest(s, p.id, "final")
    if plan is None:
        plan = await _latest(s, p.id, "expected")
        if plan is None or plan.project_rev != p.rev or plan.formula_ver != FORMULA_VERSION:
            return None
    return await _period(s, plan)


async def _out(s: AsyncSession, plan: Plan) -> PlanOut:
    steps = (
        await s.scalars(select(PlanStep).where(PlanStep.plan_id == plan.id).order_by(PlanStep.sort))
    ).all()
    days = (
        await s.scalars(select(PlanDay).where(PlanDay.plan_id == plan.id).order_by(PlanDay.day))
    ).all()
    return PlanOut(
        project_id=plan.project_id,
        kind=plan.kind,
        version=plan.version,
        project_rev=plan.project_rev,
        start=plan.start_date,
        end=plan.end_date,
        work_days=plan.work_days,
        weekend_work=plan.weekend_work,
        computed_at=plan.created_at,
        blocks=[
            PlanBlockOut(
                trade=st.trade,
                kind=st.kind,
                label=st.label,
                start=st.start_date,
                end=st.end_date,
                days=st.days,
                crew=st.crew,
                man_day=st.man_day,
            )
            for st in steps
        ],
        days=[
            PlanDayOut(
                day=d.day,
                trade=d.trade,
                kind=d.kind,
                names=list(d.names),
                holiday=HOLIDAYS.get(d.day),
            )
            for d in days
        ],
    )


async def plan_for(
    s: AsyncSession, user: User, project_id: uuid.UUID, today: date, kind: str | None = None
) -> PlanOut:
    """GET /projects/{id}/plan: 만든 사람 · 관리자만. 공사 날짜를 하나라도 수락했으면 확정 공정표,
    아니면 예상 공정표. kind로 골라 볼 수 있다. 고객이 고른 직접 할 일은 '고객이 직접' 줄로 얹는다."""
    p = await project_service.get_for(s, user, project_id)
    expected = await ensure_expected(s, p, today)
    final = await _latest(s, p.id, "final")
    if kind == "expected" or (kind is None and final is None):
        return await _with_diy(s, p, await _out(s, expected), today)
    if final is None:
        raise AppError(
            404, "not_found", "확정 공정표가 아직 없어요. 공사 날짜를 수락하면 만들어져요."
        )
    return await _with_diy(s, p, await _final_out(s, p, expected, final, today), today)


# ---- 반셀프 직접 할 일: 공정표 '고객이 직접' 줄(읽을 때 계산 엔진으로 얹고 저장하지 않는다) ----


def move_in_of(p: ProjectOut) -> date | None:
    return p.when.start if p.when.kind == "movein" else None


def diy_tasks(
    plan: PlanOut,
    keys: Iterable[str],
    today: date,
    *,
    free: calc_diy.Free = "any",
    move_in: date | None = None,
    occupied: bool = False,
) -> list[calc_diy.DiyTask]:
    """공정표 블록(공사 날 · 자연 건조 · 입주 청소) → 직접 할 일 '언제부터 · 언제까지'(calc.diy).
    free는 고객이 할 수 있는 날(any · weekend: 주말 · 공휴일)이에요. occupied(사는 집)면 공사 뒤 일의 마감이
    공사 뒤 첫 주말까지예요(calc.diy diy_v3)."""
    work = {b.trade: (b.start, b.end) for b in plan.blocks if b.kind == "work" and b.trade}
    dry = next(((b.start, b.end) for b in plan.blocks if b.kind == "dry"), None)
    clean = next(((b.start, b.end) for b in plan.blocks if b.kind == "clean"), None)
    lo = min([today, *(a for a, _ in work.values())])
    return calc_diy.plan(
        keys,
        work,
        today,
        dry=dry,
        clean=clean,
        move_in=move_in,
        free=free,
        days_off=_off(lo),
        occupied=occupied,
    )


def diy_day_name(t: calc_diy.DiyTask) -> str:
    """공정표 날 칸 이름: '페인트(문틀 · 몰딩) 칠하기 · 고객이 직접'(입주 청소 줄과 같은 꼴)."""
    return f"{t.name} · {calc_diy.SELF}"


# '고객이 직접' 줄 이름에 붙이는 표시(계산 엔진 why). 영어 값 대신 화면 말이에요(비서 diy WHY_NOTE와 같은 뜻)
DIY_NOTE = {"short": "날이 빠듯해요", "no_free_day": "날이 빠듯해요", "late": "마감이 지났어요"}
# 시작이 날짜 없는 앞 공사 뒤인 일(calc.diy after, diy_v4): 줄은 마감 날 하루라 '…뒤 · 마감'을 붙여요
DIY_AFTER = {"mokgong": "목공이 끝난 뒤 · 마감"}


def diy_label(t: calc_diy.DiyTask) -> str:
    """'고객이 직접' 줄 이름: 빠듯하거나 마감이 지난 일은 표시를 붙여요('페인트(문틀 · 몰딩) 칠하기 · 날이 빠듯해요').
    시작이 날짜 없는 목공 뒤인 일은 '페인트(문틀 · 몰딩) 칠하기 · 목공이 끝난 뒤 · 마감'(줄 날짜는 마감 날)이에요."""
    note = DIY_NOTE.get(t.why) or (DIY_AFTER.get(t.after) if t.after else None)
    return f"{t.name} · {note}" if note else t.name


async def _with_diy(s: AsyncSession, p: ProjectOut, out: PlanOut, today: date) -> PlanOut:
    """고른 직접 할 일(project.diy 칩)을 '고객이 직접' 블록(kind diy, 할 수 있는 기간)과 날 칸 이름으로 얹는다.
    입주 청소는 공정표에 이미 '고객이 직접' 줄이 있어 더하지 않는다. 날 칸이 공정표 밖(도배 전 페인트 마감 등)이면
    그날을 kind diy로 더한다. 빠듯한 일 · 마감이 지난 일은 줄 이름에 표시를 붙이고(계산 엔진 day 하루) 날 칸에는
    두지 않는다(그날 할 일이 아니에요, QA r1 D5). 칩이 없으면 그대로."""
    from app.project.diy import diy_for

    keys = await diy_for(s, p.id)
    if not keys:
        return out
    got = diy_tasks(out, keys, today, move_in=move_in_of(p), occupied=bool(p.occupied))
    tasks = [t for t in got if t.key != "clean"]
    days = {d.day: d for d in out.days}
    blocks = list(out.blocks)
    for t in tasks:
        if t.day is None:
            continue
        ok = t.fit and not t.late
        name = diy_day_name(t)
        a, b = (t.start, t.end) if ok and t.start and t.end and t.start <= t.end else (t.day, t.day)
        blocks.append(
            PlanBlockOut(
                trade=None,
                kind="diy",
                label=diy_label(t),
                start=a,
                end=b,
                days=(b - a).days + 1,
                crew=None,
                man_day=None,
            )
        )
        if not ok:
            continue
        d = days.get(t.day)
        if d is None:
            days[t.day] = PlanDayOut(
                day=t.day, trade=None, kind="diy", names=[name], holiday=HOLIDAYS.get(t.day)
            )
        else:
            kind = "diy" if d.kind == "off" else d.kind
            days[t.day] = d.model_copy(update={"kind": kind, "names": [*d.names, name]})
    return out.model_copy(update={"blocks": blocks, "days": [days[k] for k in sorted(days)]})


async def redo(
    s: AsyncSession, user: User, project_id: uuid.UUID, data: PlanRedo, today: date
) -> PlanOut:
    """날짜 바꿔 보기: 시작일 · 주말 공사를 바꿔 예상 공정표 새 버전을 만든다.
    업체를 확정한 뒤에는 막는다. 최신 예상 공정표의 시작일 · 주말 공사가 업체가 낼 날짜의 규칙과
    확정 공정표의 예상 자리에 쓰여서, 그 뒤 날짜는 공사 날짜 요청으로만 바꾼다."""
    p = await project_service.get_for(s, user, project_id)
    if user.role != "customer":
        raise AppError(403, "forbidden", "고객만 공정표를 다시 계산할 수 있어요.")
    if data.start <= today or data.start > today + timedelta(days=730):
        raise AppError(422, "start", "내일부터 2년 안의 날짜를 골라 주세요.")
    dealt = select(Deal.id).where(Deal.project_id == p.id, Deal.status != "reselected").limit(1)
    if await s.scalar(dealt) is not None:
        raise AppError(409, "dates_locked", REDO_LOCKED)
    prev = await _latest(s, p.id, "expected")
    await _save(s, p, data.start, data.weekend_work, prev)
    got = await _latest(s, p.id, "expected")
    assert got is not None
    return await _with_diy(s, p, await _out(s, got), today)


# ---- 업체 확정: 고객이 누른 요청으로만. 요청 상태는 visit.service, 확정(deal)은 여기서 ----

TRADE_LABEL = LABEL
ALREADY = "이미 업체를 확정했어요."
QUOTE_EXPIRED = "견적서 유효기간이 지났어요. '다시 받기'로 새 견적서를 받은 뒤 확정해 주세요."


async def _open_deal(s: AsyncSession, project_id: uuid.UUID, trade: str) -> Deal | None:
    q = select(Deal).where(
        Deal.project_id == project_id, Deal.trade == trade, Deal.status != "reselected"
    )
    return (await s.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


async def _deal_out(
    s: AsyncSession, deals: list[Deal], today: date, now: datetime
) -> list[DealOut]:
    quotes = await quote_service.briefs_by_id(s, [d.quote_id for d in deals])
    visits = await visit_service.visits_by_id(s, [d.visit_id for d in deals])
    shown = [
        d.vendor_id
        for d in deals
        if d.vendor_id
        and d.visit_id in visits
        and visit_service.contact_visible(
            visits[d.visit_id].status, visits[d.visit_id].contact_until, today
        )
    ]
    contacts = await vendor_service.contacts(s, shown)
    ids = [d.id for d in deals]
    pend, reqs = await _pending(s, ids), await _open_requests(s, ids)
    notes = await _fixing_notes(s, [d.id for d in deals if d.status == "fixing"])
    photos = await _done_photos(s, ids)
    reviews = await _review_ids(s, [d.id for d in deals if d.status == "done"])
    threads = await _threads(s, deals)
    approved = await _approved_extras(s, ids)
    return [
        DealOut(
            id=d.id,
            trade=d.trade,
            status=d.status,
            vendor_id=d.vendor_id,
            vendor_name=d.vendor_name,
            owner_name=contacts[d.vendor_id].owner_name if d.vendor_id in contacts else None,
            visit_id=d.visit_id,
            quote=quotes[d.quote_id],
            confirmed_at=d.created_at,
            dates_due_at=d.dates_due_at,
            overdue=_overdue(d, pend.get(d.id), reqs.get(d.id), now),
            start_date=d.start_date,
            end_date=d.end_date,
            work_done_on=d.work_done_on,
            contact_until=visits[d.visit_id].contact_until if d.visit_id in visits else None,
            fixing_note=notes.get(d.id),
            work_days=list(d.work_days or []),
            done_note=d.done_note,
            done_posted_at=d.done_posted_at,
            auto_done_at=_auto_done_at(d),
            done_remind_at=_done_remind_at(d),
            review_open=d.status == "done" and d.id not in reviews,
            review_id=reviews.get(d.id),
            thread_id=threads.get(d.id),
            done_photos=photos.get(d.id, []),
            grand_total=work_view.grand_total(quotes[d.quote_id].total, approved.get(d.id, [])),
        )
        for d in deals
    ]


def _auto_done_at(d: Deal) -> datetime | None:
    """고객 확인을 기다리는 동안만: 올린 때 + 7일 (D24, 계산 엔진)"""
    if d.status != "checking" or d.done_posted_at is None:
        return None
    return deadline.auto_done_at(d.done_posted_at)


def _done_remind_at(d: Deal) -> datetime | None:
    """고객 확인을 기다리는 동안만: 올린 때 + 4일, 자동으로 끝나기 전 한 번 알림 (D24 · C38, 계산 엔진)"""
    if d.status != "checking" or d.done_posted_at is None:
        return None
    return deadline.done_remind_at(d.done_posted_at)


async def _done_photos(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    if not deal_ids:
        return {}
    q = select(DealFile).where(DealFile.deal_id.in_(deal_ids)).order_by(DealFile.sort)
    out: dict[uuid.UUID, list] = {}
    for f in (await s.execute(q)).scalars():
        out.setdefault(f.deal_id, []).append(f.file_id)
    return out


async def _review_ids(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """끝난 공사마다 쓴 리뷰 id (리뷰 쓰기 열림 = 끝남 + 아직 안 씀). 리뷰(B1b)는 schedule보다 위층이라
    service는 부르지 않고 models만 읽기 조인으로 본다."""
    if not deal_ids:
        return {}
    q = select(Review.deal_id, Review.id).where(Review.deal_id.in_(deal_ids))
    return {deal_id: rid for deal_id, rid in (await s.execute(q)).all()}


async def _threads(s: AsyncSession, deals: Iterable[Deal]) -> dict[uuid.UUID, uuid.UUID]:
    """공사마다 이 업체와의 채팅 (실측이 확정되면 열린다, thread.service.find)"""
    out = {}
    for d in deals:
        if d.vendor_id is not None:
            tid = await thread_service.find(s, d.project_id, d.vendor_id)
            if tid is not None:
                out[d.id] = tid
    return out


async def confirm(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: ConfirmIn,
    today: date,
) -> ConfirmOut:
    """업체 확정 (한 트랜잭션, C34): 프로젝트 잠금 → 요청 quoted → chosen → 그 버전으로 확정 →
    같은 공정의 다른 요청 닫기(visit.service) · 그 업체 대화 읽기만(other_chosen) · 기한 일 취소 →
    공사 날짜 기한 일(deal_dates_due) · 이력 · 알림. 공정마다 살아 있는 확정은 하나(부분 UQ).
    유효기간이 지난 견적서는 확정하지 못한다(409 expired, D20 '다시 받기')."""
    p = await project_service.get_for(s, user, project_id)
    await project_service.lock_for_visit(s, p.id)  # 같은 집의 확정 · 요청이 줄 선다
    v = await visit_service.in_project(s, p.id, visit_id)
    if await _open_deal(s, p.id, v.trade) is not None:
        raise AppError(409, "already_chosen", ALREADY)
    await visit_service.choose(s, user, v, data.seen_ver)
    quote = await quote_service.sent_by_version(s, v.id, data.seen_ver)
    if quote is None:
        raise AppError(409, "quote_changed", visit_service.QUOTE_CHANGED)
    if quote.valid_until is not None and quote.valid_until < today:
        raise app_error("expired", QUOTE_EXPIRED)
    now = now_utc()
    deal = Deal(
        id=uuid7(),
        project_id=p.id,
        trade=v.trade,
        vendor_id=v.vendor_id,
        vendor_name=v.vendor_name,
        visit_id=v.id,
        quote_id=quote.id,
        status="confirmed",
        dates_due_at=deadline.dates_due(now),
        created_at=now,
    )
    try:
        s.add(deal)
        await s.flush()
        s.add(
            DealEvent(
                deal_id=deal.id,
                from_status=None,
                to_status="confirmed",
                by_id=user.id,
                code="confirmed",
                at=now,
            )
        )
        closed = await visit_service.close_others(s, p.id, v.trade, v.id, user)
        others = list((await visit_service.visits_by_id(s, closed)).values())
        cards = await _end_threads(s, p.id, others, "other_chosen")
        # 확정한 요청 · 닫힌 요청의 실측 기한 일은 이제 필요 없다 (처리 함수도 상태를 다시 보지만 미리 지운다)
        await jobs_service.cancel_refs(s, now=now, ref_ids=await _visit_refs(s, [v.id, *closed]))
        await jobs_service.add(s, kind="deal_dates_due", ref_id=deal.id, run_at=deal.dates_due_at)
        if v.vendor_id is not None:
            cards += await _card(s, p.id, v.vendor_id, "deal_confirmed", deal.id)
            await notify_service.add(
                s,
                user_id=v.vendor_id,
                kind="deal_confirmed",
                body=_to_vendor("고객이 확정했어요 · 공사 날짜를 내 주세요", p, v.trade),
                link=catalog.link("deal_confirmed", did=deal.id),
                dedup_key=f"deal:{deal.id}",
            )
        await s.commit()
    except IntegrityError as exc:  # 같은 공정을 동시에 두 번 확정하면 부분 UQ가 막는다
        await s.rollback()
        raise AppError(409, "already_chosen", ALREADY) from exc
    _push(
        s,
        [StatePush((user.id, v.vendor_id), "deal", deal.id, p.id)]
        + [StatePush((o.vendor_id,), "visit", o.id, p.id) for o in others],
        [v.vendor_id, *[o.vendor_id for o in others]],
        cards,
    )
    deal = await _open_deal(
        s, p.id, v.trade
    )  # 저장된 값으로 다시 읽는다 (시각 표기를 읽기와 맞춘다)
    (out,) = await _deal_out(s, [deal], today, now)
    return ConfirmOut(deal=out, closed=closed, quote_expired=False)


AFTER_DATES = "공사 날짜를 수락한 뒤에는 업체를 다시 고를 수 없어요."


async def reselect(
    s: AsyncSession, user: User, project_id: uuid.UUID, deal_id: uuid.UUID
) -> ReselectOut:
    """다시 고르기 (공사 날짜 수락 전만, 한 트랜잭션): 프로젝트 잠금 → 확정 confirmed → reselected →
    확정한 요청 · 남은 살아 있는 요청 닫기(reselected, visit.service) · 그 업체 대화 읽기만(cancelled) ·
    공사 · 실측 기한 일 취소 → 이력 · 알림. 공정의 칸 3개가 다시 빈다."""
    p = await project_service.get_for(s, user, project_id)
    await project_service.lock_for_visit(s, p.id)  # 같은 집의 확정 · 요청 · 다시 고르기가 줄 선다
    deal = await s.get(Deal, deal_id, populate_existing=True)
    if deal is None or deal.project_id != p.id:
        raise AppError(404, "not_found", "업체 확정을 찾을 수 없어요.")
    if deal.status == "reselected":
        raise AppError(409, "invalid_state", "이미 업체를 다시 고르기로 했어요.")
    if deal.status != "confirmed":
        raise AppError(409, "invalid_state", AFTER_DATES)
    res = await s.execute(
        update(Deal)
        .where(Deal.id == deal.id, Deal.status == "confirmed")
        .values(status="reselected")
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # 그사이 공사 날짜를 수락했다
        raise AppError(409, "invalid_state", AFTER_DATES)
    now = now_utc()
    s.add(
        DealEvent(
            deal_id=deal.id,
            from_status="confirmed",
            to_status="reselected",
            by_id=user.id,
            code="reselected",
            at=now,
        )
    )
    reqs = list(
        (await s.execute(select(DateRequest.id).where(DateRequest.deal_id == deal.id))).scalars()
    )
    await _close_dates(s, deal.id, now)  # 업체가 낸 공사 날짜도 없어진다
    out = await visit_service.close_for_reselect(s, p.id, deal.trade, user)
    gone = list((await visit_service.visits_by_id(s, out.closed)).values())
    await _end_threads(s, p.id, gone, "cancelled")
    refs = [deal.id, *reqs, *await _visit_refs(s, out.closed)]
    await jobs_service.cancel_refs(s, now=now, ref_ids=refs)
    if deal.vendor_id is not None:
        await notify_service.add(
            s,
            user_id=deal.vendor_id,
            kind="deal_reselected",
            body=_to_vendor(visit_service.RESELECTED, p, deal.trade),
            link=f"/vendor/requests/{deal.visit_id}",
            dedup_key=f"deal:{deal.id}:reselected",
        )
    await s.commit()
    _push(
        s,
        [StatePush((user.id, deal.vendor_id), "deal", deal.id, p.id)]
        + [StatePush((g.vendor_id,), "visit", g.id, p.id) for g in gone],
        [g.vendor_id for g in gone],
    )
    return out


async def deals_for(
    s: AsyncSession, user: User, project_id: uuid.UUID, trade: str | None, today: date
) -> list[DealOut]:
    """이 집의 업체 확정 (다시 고르기 한 것은 빼고)"""
    p = await project_service.get_for(s, user, project_id)
    q = select(Deal).where(Deal.project_id == p.id, Deal.status != "reselected")
    if trade:
        q = q.where(Deal.trade == trade)
    deals = list((await s.execute(q.order_by(Deal.created_at))).scalars().all())
    return await _deal_out(s, deals, today, now_utc())


async def compare(
    s: AsyncSession, user: User, project_id: uuid.UUID, trade: str, today: date
) -> CompareDealOut:
    base = await visit_service.compare(s, user, project_id, trade, today)
    deal = await _open_deal(s, project_id, trade)
    out = (await _deal_out(s, [deal], today, now_utc()))[0] if deal else None
    return CompareDealOut(**base.model_dump(), deal=out)


INBOX_RECENT_DAYS = 30  # 요약의 '최근 30일' (받은 요청 · 보낸 견적서 · 확정)
HALF_ORDER = {"am": 0, "pm": 1}


async def vendor_inbox(
    s: AsyncSession,
    vendor: User,
    tab: str,
    today: date,
    before: datetime | None,
    limit: int,
    sort: str | None = None,
) -> InboxPageOut:
    """업체 작업함 v3 (V03 · V08 · D04): 할 일 · 기다림 · 일정 · 공사 · 끝남. 줄 칸 · 상태 · 기한은
    inbox.row(visit models 읽기 조인 + calc.deadline), 공사 탭은 업체 확정 상태로 덮는다. 고객 이름 ·
    연락처 · 동 · 호는 없다. 정렬: 없으면 탭마다 처음 정한 순, due = 기한 가까운 순(기한 없는 줄은 뒤),
    new = 받은 때 최근 순. 끝남만 before 커서로 limit씩."""
    now = now_utc()
    if tab == "done":
        return await _done_tab(s, vendor, today, before, limit, now)
    if tab == "jobs":
        pairs = await _job_rows(s, vendor, today, now)
    else:
        pairs = await _board_rows(s, vendor, tab, today, now)
    return InboxPageOut(items=_sort_rows(pairs, sort), next_before=None)


def _sort_rows(pairs: list[tuple[tuple, InboxRowOut]], sort: str | None) -> list[InboxRowOut]:
    """pairs: (탭의 처음 정한 순 키, 줄)"""
    if sort == "due":
        far = datetime.max.replace(tzinfo=SEOUL)

        def due_key(p):
            due = p[1].next.due_at if p[1].next else None
            return (due is None, due or far, p[1].received_at)

        pairs = sorted(pairs, key=due_key)
    elif sort == "new":
        pairs = sorted(pairs, key=lambda p: p[1].received_at, reverse=True)
    else:
        pairs = sorted(pairs, key=lambda p: p[0])
    return [r for _, r in pairs]


async def _board_rows(
    s: AsyncSession, vendor: User, tab: str, today: date, now: datetime
) -> list[tuple[tuple, InboxRowOut]]:
    """할 일 · 기다림 · 일정: 살아 있는 요청(확정 빼고) + 할 일에 남긴 답 기한 지남을 탭으로 나눈다.
    처음 정한 순: 할 일은 새 요청부터 받은 순, 기다림은 오래 기다린 순, 일정은 실측 날 · 반나절 순."""
    q = select(Visit).where(Visit.vendor_id == vendor.id, inbox.board_cond(now))
    visits = list((await s.execute(q.execution_options(populate_existing=True))).scalars())
    fx = await inbox.facts(s, visits)
    out = []
    for v in visits:
        f = fx[v.id]
        if inbox.vendor_view(f, now)[0] != tab:
            continue
        if tab == "todo":
            key = (v.vendor_seen_at is not None, v.created_at)
        elif tab == "waiting":
            key = (f.last_at or v.created_at,)
        else:
            key = (v.booked_day or today, HALF_ORDER.get(v.booked_half or "am", 0), v.created_at)
        out.append((key, InboxRowOut(**inbox.row(f, now, today))))
    return out


def _deal_view(
    d: Deal, x: DateProposal | None, r: DateRequest | None, today: date, now: datetime
) -> tuple[StateTagOut, VendorNextOut]:
    """공사 탭 줄의 상태 아이콘 + 글자 · 다음 일 (V03 '공사' 탭 카드 · V23)"""

    def tag(icon, label, nxt, due=None):
        over = due is not None and deadline.is_over(now, due)
        return (
            StateTagOut(icon="late" if over else icon, label=label),
            VendorNextOut(label=nxt, due_at=due, overdue=over),
        )

    if r is not None:
        return tag("todo", "다른 날짜 요청", "새 날짜 올리기", r.due_at)
    if d.status == "confirmed":
        if x is not None:
            return tag("wait", "고객 차례", "고객 수락 기다림")
        return tag("todo", "공사 날짜 올리기", "공사 날짜 올리기", d.dates_due_at)
    if d.status == "scheduled":
        if x is not None:
            return tag("wait", "고객 차례", "바꾼 날짜 수락 기다림")
        if d.end_date is not None and today >= d.end_date:
            return tag("todo", "공사 끝 알리기", "공사 끝냈어요")
        if d.start_date is not None and today >= d.start_date and d.end_date is not None:
            return tag("ok", "공사 중", f"{_md(d.end_date)}까지 공사")
        start = _md(d.start_date) if d.start_date else ""
        return tag("ok", "공사 확정", f"{start} 공사 시작".strip())
    if d.status == "checking":
        state, _ = tag("wait", "고객 확인 기다림", "")
        return state, VendorNextOut(
            label="고객 확인 기다림", due_at=_auto_done_at(d), overdue=False
        )
    if d.status == "fixing":
        return tag("todo", "남은 일", "남은 일 하고 알리기")
    return tag("done", "공사 끝", "끝난 공사")


async def _deal_rows(
    s: AsyncSession, deals: list[Deal], today: date, now: datetime
) -> dict[uuid.UUID, InboxRowOut]:
    """업체 확정 줄: 요청 줄 칸(inbox.row) + 확정 · 공사 날짜 · 추가 금액 칸. 확정 id → 줄."""
    visits = await visit_service.visits_by_id(s, [d.visit_id for d in deals])
    fx = await inbox.facts(s, visits.values())
    ids = [d.id for d in deals]
    pend, reqs = await _pending(s, ids), await _open_requests(s, ids)
    waiting = await _extras_pending(s, ids)
    notes = await _fixing_notes(s, [d.id for d in deals if d.status == "fixing"])
    quotes = await quote_service.briefs_by_id(s, [d.quote_id for d in deals])
    out = {}
    for d in deals:
        f = fx.get(d.visit_id)
        if f is None:
            continue
        x, r = pend.get(d.id), reqs.get(d.id)
        state, nxt = _deal_view(d, x, r, today, now)
        base = {**inbox.row(f, now, today), "state": state, "next": nxt}
        out[d.id] = InboxRowOut(
            **base,
            deal_id=d.id,
            deal_status=d.status,
            confirmed_at=d.created_at,
            dates_due_at=d.dates_due_at,
            overdue=_overdue(d, x, r, now),
            start_date=d.start_date,
            end_date=d.end_date,
            dates_state=_state(d, x, r),
            proposed_start=x.start_date if x else None,
            proposed_end=x.end_date if x else None,
            proposed_days=days_since(x.created_at, today) if x else None,
            wish_dates=list(r.wish_dates) if r else [],
            request_due_at=r.due_at if r else None,
            extras_pending=waiting.get(d.id, 0),
            work_done_on=d.work_done_on,
            contact_until=f.v.contact_until,
            fixing_note=notes.get(d.id),
            work_days=list(d.work_days or []),
            deal_total=quotes[d.quote_id].total if d.quote_id in quotes else None,
        )
    return out


async def _job_rows(
    s: AsyncSession, vendor: User, today: date, now: datetime
) -> list[tuple[tuple, InboxRowOut]]:
    """공사 탭: 확정한 공사(끝남 · 다시 고르기 빼고). 처음 정한 순은 확정한 순 최근 먼저."""
    q = select(Deal).where(Deal.vendor_id == vendor.id, Deal.status.in_(OPEN_DEALS))
    deals = list((await s.execute(q.execution_options(populate_existing=True))).scalars().all())
    rows = await _deal_rows(s, deals, today, now)
    return [((-d.created_at.timestamp(),), rows[d.id]) for d in deals if d.id in rows]


async def vendor_summary(s: AsyncSession, vendor: User) -> InboxSummaryOut:
    """탭별 수 (줄 수와 같다) · 최근 30일 받은 요청 · 보낸 견적서 · 확정"""
    now = now_utc()
    q = select(Visit).where(Visit.vendor_id == vendor.id, inbox.board_cond(now))
    visits = list((await s.execute(q)).scalars())
    fx = await inbox.facts(s, visits)
    tabs = [inbox.vendor_view(fx[v.id], now)[0] for v in visits]
    jobs = await s.scalar(
        select(func.count())
        .select_from(Deal)
        .where(Deal.vendor_id == vendor.id, Deal.status.in_(OPEN_DEALS))
    )
    done_visits = await s.scalar(
        select(func.count())
        .select_from(Visit)
        .where(Visit.vendor_id == vendor.id, inbox.done_cond(now))
    )
    done_deals = await s.scalar(
        select(func.count())
        .select_from(Deal)
        .where(Deal.vendor_id == vendor.id, Deal.status == "done")
    )
    since = now - timedelta(days=INBOX_RECENT_DAYS)
    moved = dict(
        (
            await s.execute(
                select(VisitEvent.to_status, func.count())
                .join(Visit, Visit.id == VisitEvent.visit_id)
                .where(Visit.vendor_id == vendor.id, VisitEvent.at >= since)
                .group_by(VisitEvent.to_status)
            )
        ).all()
    )
    return InboxSummaryOut(
        todo=tabs.count("todo"),
        waiting=tabs.count("waiting"),
        sched=tabs.count("sched"),
        jobs=int(jobs or 0),
        done=int(done_visits or 0) + int(done_deals or 0),
        recent=RecentOut(
            requested=moved.get("requested", 0),
            quoted=moved.get("quoted", 0),
            chosen=moved.get("chosen", 0),
        ),
    )


# ---- 공사 날짜: 업체가 내고 고객이 수락하거나 다른 날짜를 요청한다. 날짜 · 기간 · 기한은 calc가 만든다 ----

ORDER = ("mokgong", "dobae")  # 앞 공정이 끝난 다음 날부터 뒤 공정을 한다
AFTER_DATES_ACCEPTED = ("scheduled", "checking", "fixing", "done")
DATE_JOBS = ("deal_dates_due", "deal_request_due")  # 공사 날짜 기한 일 (ref = 확정 · 요청 id)
DONE_JOBS = ("deal_done_remind", "deal_auto_done")  # 공사 끝 기한 일 (ref = 확정 id, D24)
REQUESTS_MAX = 2  # deals.date_request_count CHECK와 같다
OPTIONS = 5  # 다른 날짜 요청 후보 수
HOLIDAY_DAYS = 180  # 화면 달력에 보여 줄 공휴일 범위
AHEAD_DAYS = 365  # 날짜는 1년 안으로
TEAMS = 1  # 업체 팀 수 칸이 아직 없다: 한 팀으로 본다(하루에 공사 한 건)
NO_DEAL = "공사를 찾을 수 없어요."
STALE = "그사이 상태가 바뀌었어요. 새로 불러올게요."


async def _pending(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, DateProposal]:
    if not deal_ids:
        return {}
    q = select(DateProposal).where(
        DateProposal.deal_id.in_(deal_ids), DateProposal.status == "pending"
    )
    rows = (await s.execute(q.execution_options(populate_existing=True))).scalars()
    return {x.deal_id: x for x in rows}


async def _open_requests(
    s: AsyncSession, deal_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DateRequest]:
    if not deal_ids:
        return {}
    q = select(DateRequest).where(DateRequest.deal_id.in_(deal_ids), DateRequest.status == "open")
    rows = (await s.execute(q.execution_options(populate_existing=True))).scalars()
    return {r.deal_id: r for r in rows}


async def _changed(s: AsyncSession, deal_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """앞서 낸 날짜를 바꿔 다시 낸 공사"""
    if not deal_ids:
        return set()
    q = select(DateProposal.deal_id).where(
        DateProposal.deal_id.in_(deal_ids), DateProposal.status == "superseded"
    )
    return set((await s.execute(q)).scalars())


def _state(d: Deal, pending: DateProposal | None, req: DateRequest | None) -> str:
    if d.status == "reselected":
        return "closed"
    if d.status == "confirmed":
        if req is not None:
            return "requested"
        return "proposed" if pending is not None else "waiting"
    if d.status == "scheduled":  # 수락한 뒤 날짜 바꾸기
        if req is not None:
            return "change_requested"
        if pending is not None:
            return "change_proposed"
    return "scheduled"


async def dates_states(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """업체 확정마다 지금 공사 날짜 상태(dates_state). 읽기만 한다(비서 sweep이 열린 제안과 견준다)."""
    if not deal_ids:
        return {}
    deals = (await s.scalars(select(Deal).where(Deal.id.in_(deal_ids)))).all()
    pend, reqs = await _pending(s, deal_ids), await _open_requests(s, deal_ids)
    return {d.id: _state(d, pend.get(d.id), reqs.get(d.id)) for d in deals}


def _overdue(d: Deal, pending: DateProposal | None, req: DateRequest | None, now: datetime) -> bool:
    """기한 지남(상태가 아님): 날짜를 아직 안 냈는데 확정 기한이 지났거나, 열린 요청의 기한이 지났다."""
    if req is not None:  # 날짜 요청 · 바꾸기 요청 모두 기한이 있다
        return now > req.due_at
    return d.status == "confirmed" and pending is None and now > d.dates_due_at


def _weekend(plan: Plan | None) -> tuple[int, ...]:
    return () if plan is not None and plan.weekend_work else WEEKEND


def _holidays(today: date) -> list[HolidayOut]:
    end = today + timedelta(days=HOLIDAY_DAYS)
    return [HolidayOut(day=d, name=n) for d, n in sorted(HOLIDAYS.items()) if today <= d <= end]


def _proposal_out(x: DateProposal, changed: bool, weekend: tuple[int, ...]) -> ProposalOut:
    return ProposalOut(
        id=x.id,
        start=x.start_date,
        end=x.end_date,
        workdays=len(x.days)
        if x.days
        else count_workdays(x.start_date, x.end_date, _off(x.start_date), weekend),
        days=list(x.days or []),
        crew=x.crew,
        method=x.method,
        call_on=x.call_on,
        kind=x.kind,
        reason=x.reason,
        status=x.status,
        request_id=x.request_id,
        changed=changed,
        created_at=x.created_at,
        decided_at=x.decided_at,
    )


def _request_out(r: DateRequest, now: datetime) -> DateRequestOut:
    return DateRequestOut(
        id=r.id,
        wish_dates=list(r.wish_dates),
        reason=r.reason,
        due_at=r.due_at,
        overdue=r.status == "open" and now > r.due_at,
        status=r.status,
        created_at=r.created_at,
    )


def _other(d: Deal) -> OtherTradeOut:
    return OtherTradeOut(
        trade=d.trade, vendor_name=d.vendor_name, start=d.start_date, end=d.end_date
    )


async def _others(s: AsyncSession, project_id: uuid.UUID, trade: str) -> list[Deal]:
    """이 집 다른 공정에서 고객이 수락한 공사 날짜"""
    q = select(Deal).where(
        Deal.project_id == project_id,
        Deal.trade != trade,
        Deal.status.in_(AFTER_DATES_ACCEPTED),
        Deal.start_date.is_not(None),
    )
    return list((await s.execute(q)).scalars().all())


def _fit(
    trade: str, start: date, end: date, others: list[Deal], weekend: tuple[int, ...], today: date
) -> FitOut:
    dated = [Dated(trade, start, end)] + [Dated(o.trade, o.start_date, o.end_date) for o in others]
    hit = {a if b == trade else b for a, b in order_conflicts(dated, ORDER) if trade in (a, b)}
    off = _off(min([today, start] + [o.start_date for o in others]))
    start_from, end_by = free_range(trade, dated, ORDER, off, weekend)
    return FitOut(
        conflicts=[_other(o) for o in others if o.trade in hit],
        start_from=start_from,
        end_by=end_by,
    )


def _check_range(start: date, end: date, today: date, weekend: tuple[int, ...]) -> int:
    """업체가 낼 날짜: 내일부터 1년 안, 끝 ≥ 시작, 120일 안, 시작 · 끝은 일하는 날. 일하는 날 수."""
    if start <= today or start > today + timedelta(days=AHEAD_DAYS):
        raise AppError(422, "start", "시작일은 내일부터 1년 안으로 골라 주세요.")
    if end < start:
        raise AppError(422, "end", "끝나는 날은 시작일과 같거나 뒤로 골라 주세요.")
    if (end - start).days > JOB_MAX_DAYS:
        raise AppError(422, "end", f"공사 날짜는 {JOB_MAX_DAYS}일 안으로 골라 주세요.")
    off = _off(start)
    if is_off(start, off, weekend) or is_off(end, off, weekend):
        raise AppError(
            422, "off_day", "시작일과 끝나는 날은 일하는 날로 골라 주세요. 주말 · 공휴일은 쉬어요."
        )
    return count_workdays(start, end, off, weekend)


def _check_days(
    days: list[date], today: date, weekend: tuple[int, ...], quote_days: int | None
) -> list[date]:
    """v3 공사 날 목록(V11): 내일부터 1년 안 · 처음 ~ 마지막 120일 안 · 모두 일하는 날(주말 · 공휴일은
    계산 엔진 is_off) · 날 수 = 견적서 공사 기간. 틀리면 422(days). 돌려주는 값: 날 순으로 줄 세운 목록."""
    got = sorted(days)
    if got[0] <= today or got[-1] > today + timedelta(days=AHEAD_DAYS):
        raise _field("days", "공사 날은 내일부터 1년 안으로 골라 주세요.")
    if (got[-1] - got[0]).days > JOB_MAX_DAYS:
        raise _field("days", f"공사 날은 처음부터 마지막까지 {JOB_MAX_DAYS}일 안으로 골라 주세요.")
    off = _off(got[0])
    if any(is_off(d, off, weekend) for d in got):
        raise _field("days", "주말 · 공휴일은 공사 날로 고를 수 없어요.")
    if quote_days is not None and len(got) != quote_days:
        raise _field("days", f"고른 날 수가 견적서 공사 기간({quote_days}일)과 같아야 해요.")
    return got


def _range_workdays(start: date, end: date, weekend: tuple[int, ...]) -> list[date]:
    """시작 ~ 끝 사이의 일하는 날 (옛 길: 범위로 낸 날짜를 날 목록으로, 계산 엔진)"""
    off = _off(start)
    return workdays(start, count_workdays(start, end, off, weekend), off, weekend)


def _gaps(spans: Iterable[tuple[date, date, list[date] | None]]) -> set[date]:
    """날을 하나씩 고른 공사의 처음 ~ 마지막 사이에서 빠진 날. 공정표 계산(fix_plan)에서 쉬는 날로
    넘겨 그날에 작업 칸을 두지 않는다. 날 목록이 처음 · 마지막 날과 어긋나면(옛 행) 범위로 본다."""
    out: set[date] = set()
    for start, end, days in spans:
        if not days or min(days) != start or max(days) != end:
            continue
        picked = set(days)
        span = (start + timedelta(days=i) for i in range((end - start).days + 1))
        out |= {d for d in span if d not in picked}
    return out


def _need(p: ProjectOut, trade: str, crew: int | None) -> NeedOut:
    """그 인원으로 센 필요한 기간 (없으면 믿집 가정 인원)"""
    got = [
        c for c in quote_service.calc_trades(p, {trade: crew} if crew else None) if c.trade == trade
    ]
    if not got:
        raise AppError(409, "trade", "이 집에서 고른 공정이 아니에요.")
    c = got[0]
    return NeedOut(
        man_day=c.man_day,
        crew=c.crew,
        days=trade_days(c.steps),
        steps=[StepNeedOut(name=st.name, half_days=st.half_days) for st in c.steps],
    )


async def _lock_deal(s: AsyncSession, deal_id: uuid.UUID) -> Deal | None:
    q = select(Deal).where(Deal.id == deal_id).with_for_update()
    return (await s.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


async def _close_dates(s: AsyncSession, deal_id: uuid.UUID, now: datetime) -> None:
    """다시 고르기: 수락 기다리는 날짜 · 열린 요청을 withdrawn으로 (부르는 쪽 트랜잭션 안에서)"""
    await s.execute(
        update(DateProposal)
        .where(DateProposal.deal_id == deal_id, DateProposal.status == "pending")
        .values(status="withdrawn", decided_at=now)
        .execution_options(synchronize_session=False)
    )
    await s.execute(
        update(DateRequest)
        .where(DateRequest.deal_id == deal_id, DateRequest.status == "open")
        .values(status="withdrawn", closed_at=now)
        .execution_options(synchronize_session=False)
    )


async def _set(s: AsyncSession, model, row_id: uuid.UUID, frm: str, values: dict) -> None:
    """지금 상태가 frm일 때만 바꾼다. 1행이 아니면 409."""
    res = await s.execute(
        update(model)
        .where(model.id == row_id, model.status == frm)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise AppError(409, "stale", STALE)


# 다른 날짜 요청의 기준 날짜: 처음 · 끝 · 하나씩 고른 공사 날(v3, 없으면 범위로 낸 날짜)
Base = tuple[date, date, list[date] | None]


def _base(d: Deal, x: DateProposal | None) -> Base | None:
    """다른 날짜 요청의 기준 날짜: 수락 전이면 낸 날짜, 수락 뒤면 지금 날짜 (그와 같은 일하는 날 수로 고른다)"""
    if d.status == "scheduled" and d.start_date and d.end_date:
        return d.start_date, d.end_date, d.work_days
    if d.status == "confirmed" and x is not None:
        return x.start_date, x.end_date, x.days
    return None


def _job_workdays(start: date, end: date, days: list[date] | None, weekend: tuple[int, ...]) -> int:
    """공사 일하는 날 수: 날을 하나씩 고른 공사(v3)는 고른 날 수(사이 빈 날은 세지 않아요, QA r1 D8), 범위로 낸
    날짜(옛 길)는 처음 ~ 끝의 일하는 날 수(계산 엔진). 날 목록이 처음 · 마지막 날과 어긋나면(옛 행) 범위로 본다(_gaps와 같음)."""
    if days and min(days) == start and max(days) == end:
        return len(set(days))
    return count_workdays(start, end, _off(start), weekend)


def _start_options(
    trade: str, base: Base, others: list[Deal], weekend: tuple[int, ...], today: date
) -> list[StartOptionOut]:
    """요청 후보: 기준과 같은 일하는 날 수, 다른 공정과 겹치지 않는 자리(앞 공정 다음 날부터 뒤 공정
    전날까지) 안에서 내일부터. 기준 시작일은 뺀다."""
    tomorrow = today + timedelta(days=1)
    room = _fit(trade, base[0], base[1], others, weekend, today)
    first = max(tomorrow, room.start_from or tomorrow)
    n = _job_workdays(*base, weekend)
    return [
        StartOptionOut(start=a, end=b)
        for a, b in start_choices(
            first, max(n, 1), OPTIONS, {base[0]}, _off(first), weekend, room.end_by
        )
    ]


async def schedule_for(
    s: AsyncSession, user: User, project_id: uuid.UUID, today: date
) -> ScheduleOut:
    """GET /projects/{id}/schedule: 공정마다 업체 확정 · 낸 날짜 · 다른 날짜 요청 · 겹침 · 요청 후보"""
    p = await project_service.get_for(s, user, project_id)
    plan = await ensure_expected(s, p, today)
    weekend = _weekend(plan)
    q = select(Deal).where(Deal.project_id == p.id, Deal.status != "reselected")
    deals = sorted(
        (await s.execute(q.execution_options(populate_existing=True))).scalars().all(),
        key=lambda d: ORDER.index(d.trade),
    )
    now = now_utc()
    outs = await _deal_out(s, deals, today, now)
    ids = [d.id for d in deals]
    pend, reqs, changed = (
        await _pending(s, ids),
        await _open_requests(s, ids),
        await _changed(s, ids),
    )
    accepted = [d for d in deals if d.status in AFTER_DATES_ACCEPTED and d.start_date]
    extras = await _extras(s, deals)
    trades = []
    for d, out in zip(deals, outs, strict=True):
        x, r = pend.get(d.id), reqs.get(d.id)
        others = [o for o in accepted if o.trade != d.trade]
        fit = _fit(d.trade, x.start_date, x.end_date, others, weekend, today) if x else None
        base = _base(d, x)
        options = _start_options(d.trade, base, others, weekend, today) if base else []
        trades.append(
            TradeDatesOut(
                deal=out,
                dates_state=_state(d, x, r),
                proposal=_proposal_out(x, d.id in changed, weekend) if x else None,
                request=_request_out(r, now) if r else None,
                requests_left=REQUESTS_MAX - d.date_request_count,
                fit=fit,
                start_options=options,
                extras=extras[d.id],
            )
        )
    final = await _latest(s, p.id, "final")
    return ScheduleOut(
        project_id=p.id,
        weekend_work=plan.weekend_work,
        holidays=_holidays(today),
        final_version=final.version if final else 0,
        trades=trades,
        request_due_preview=deadline.date_request_due(now),  # 보내기 전 '…까지 새 날짜를 올려요'
    )


CHANGEABLE = ("confirmed", "scheduled")  # 공사 끝냈어요(24번) 전까지 날짜를 내고 바꾼다
DONE_DATES = "공사를 끝냈다고 올린 뒤에는 날짜를 바꿀 수 없어요."


def _changeable(d: Deal) -> None:
    if d.status == "reselected":
        raise AppError(409, "invalid_state", "다시 고른 업체의 공사예요.")
    if d.status not in CHANGEABLE:
        raise AppError(409, "invalid_state", DONE_DATES)


def _iso(a: date, b: date) -> str:
    return f"{a.isoformat()}~{b.isoformat()}"


async def _accepted_crews(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """수락한 날짜의 하루 인원 (가장 최근에 수락한 것)"""
    if not deal_ids:
        return {}
    q = (
        select(DateProposal)
        .where(DateProposal.deal_id.in_(deal_ids), DateProposal.status == "accepted")
        .order_by(DateProposal.deal_id, DateProposal.decided_at.desc())
    )
    out: dict[uuid.UUID, int] = {}
    for x in (await s.execute(q)).scalars():
        out.setdefault(x.deal_id, x.crew)
    return out


def _compose(
    p: ProjectOut,
    fixed: dict[str, tuple[date, date]],
    crews: dict[str, int],
    expected: Plan,
    today: date,
    picked: dict[str, list[date] | None] | None = None,
):
    """정한 날짜는 그대로, 날짜 없는 공정은 예상 자리에 놓은 공정표 (계산 엔진).
    picked: 날을 하나씩 고른 공정(v3 work_days)은 그 날에만 작업 칸을 둔다(사이 빈 날은 쉬는 날)."""
    calcs = quote_service.calc_trades(p, crews)
    trades = [TradePlan(c.trade, c.steps, c.crew) for c in calcs]
    start = max(expected.start_date, today + timedelta(days=1))
    off = _off(min([start, today] + [f[0] for f in fixed.values()]))
    picked = picked or {}
    off = off | _gaps((a, b, picked.get(t)) for t, (a, b) in fixed.items())
    return fix_plan(trades, fixed, start, off, _weekend(expected)), {
        c.trade: c.man_day for c in calcs
    }


def _plan_parts(plan, man_days, states: dict[str, str], deals: dict[str, Deal]):
    blocks = [
        PlanBlockOut(
            trade=b.trade,
            kind=b.kind,
            label=b.label or LABEL.get(b.trade or "", ""),
            start=b.start,
            end=b.end,
            days=b.days,
            crew=b.crew,
            man_day=man_days.get(b.trade) if b.trade else None,
            state=states.get(b.trade or "", "expected"),
            deal_id=deals[b.trade].id if b.trade in deals else None,
            vendor_name=deals[b.trade].vendor_name if b.trade in deals else None,
        )
        for b in plan.blocks
    ]
    days = [
        PlanDayOut(
            day=d.day,
            trade=d.trade,
            kind=d.kind,
            names=list(d.names),
            holiday=HOLIDAYS.get(d.day),
            state=states.get(d.trade or "", "expected"),
        )
        for d in plan.days
    ]
    return blocks, days


async def _final_parts(s: AsyncSession, project_id: uuid.UUID):
    """살아 있는 확정 · 수락한 확정 · 수락 기다리는 날짜 · 인원"""
    q = select(Deal).where(Deal.project_id == project_id, Deal.status != "reselected")
    deals = list((await s.execute(q.execution_options(populate_existing=True))).scalars().all())
    accepted = [d for d in deals if d.status in AFTER_DATES_ACCEPTED and d.start_date]
    ids = [d.id for d in deals]
    pend = await _pending(s, ids)
    crews = await _accepted_crews(s, [d.id for d in accepted])
    return deals, accepted, pend, crews


async def _save_final(
    s: AsyncSession, p: ProjectOut, expected: Plan, seen: int, today: date
) -> Plan:
    """확정 공정표 새 버전 (부르는 쪽 트랜잭션 안, 확정 날짜를 바꾼 뒤). 본 버전이 최신이 아니면 409.
    (project, final, version) UQ가 동시에 둘이 만드는 것도 막는다."""
    latest = await _latest(s, p.id, "final")
    if (latest.version if latest else 0) != seen:
        raise AppError(409, "plan_changed", "공정표가 바뀌었어요. 새로 불러올게요.")
    _, accepted, _, crews = await _final_parts(s, p.id)
    fixed = {d.trade: (d.start_date, d.end_date) for d in accepted}
    plan, man_days = _compose(
        p,
        fixed,
        {d.trade: crews[d.id] for d in accepted if d.id in crews},
        expected,
        today,
        {d.trade: d.work_days for d in accepted},
    )
    row = Plan(
        project_id=p.id,
        kind="final",
        version=seen + 1,
        project_rev=p.rev,
        formula_ver=FORMULA_VERSION,
        start_date=plan.start,
        end_date=plan.end,
        work_days=plan.work_days,
        weekend_work=expected.weekend_work,
    )
    s.add(row)
    await s.flush()
    _add_parts(s, row, plan, man_days, {d.trade: d.id for d in accepted})
    return row


async def _final_out(
    s: AsyncSession, p: ProjectOut, expected: Plan, final: Plan, today: date
) -> PlanOut:
    """확정 공정표: 수락한 날짜(확정) · 수락 기다리는 첫 날짜(수락 전) · 날짜 없는 공정(예상)을
    계산 엔진으로 얹는다. 수락한 날짜를 바꾸자는 새 날짜는 changes에 바꾼 뒤 모습으로."""
    deals, accepted, pend, crews = await _final_parts(s, p.id)
    by = {d.trade: d for d in deals}
    fixed = {d.trade: (d.start_date, d.end_date) for d in accepted}
    states = {d.trade: "confirmed" for d in accepted}
    use = {d.trade: crews[d.id] for d in accepted if d.id in crews}
    picked = {d.trade: d.work_days for d in accepted}
    for d in deals:
        x = pend.get(d.id)
        if d.status == "confirmed" and x is not None:
            fixed[d.trade], states[d.trade], use[d.trade] = (
                (x.start_date, x.end_date),
                "pending",
                x.crew,
            )
            picked[d.trade] = x.days
    plan, man_days = _compose(p, fixed, use, expected, today, picked)
    blocks, days = _plan_parts(plan, man_days, states, by)
    weekend = _weekend(expected)
    changed = await _changed(s, [d.id for d in accepted])
    changes = []
    for d in accepted:
        x = pend.get(d.id)
        if x is None:
            continue
        moved = {**fixed, d.trade: (x.start_date, x.end_date)}
        plan2, md2 = _compose(
            p, moved, {**use, d.trade: x.crew}, expected, today, {**picked, d.trade: x.days}
        )
        b2, d2 = _plan_parts(plan2, md2, {**states, d.trade: "pending"}, by)
        others = [o for o in accepted if o.trade != d.trade]
        changes.append(
            PlanChangeOut(
                trade=d.trade,
                deal_id=d.id,
                vendor_name=d.vendor_name,
                current_start=d.start_date,
                current_end=d.end_date,
                proposal=_proposal_out(x, d.id in changed, weekend),
                fit=_fit(d.trade, x.start_date, x.end_date, others, weekend, today),
                start=plan2.start,
                end=plan2.end,
                work_days=plan2.work_days,
                blocks=b2,
                days=d2,
            )
        )
    return PlanOut(
        project_id=p.id,
        kind="final",
        version=final.version,
        project_rev=final.project_rev,
        start=plan.start,
        end=plan.end,
        work_days=plan.work_days,
        weekend_work=expected.weekend_work,
        computed_at=final.created_at,
        blocks=blocks,
        days=days,
        changes=changes,
        extras=list((await _extras(s, deals)).values()),
        deals=await _deal_out(
            s, sorted(deals, key=lambda d: ORDER.index(d.trade)), today, now_utc()
        ),
    )


async def accept_dates(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    deal_id: uuid.UUID,
    proposal_id: uuid.UUID,
    data: AcceptIn,
    today: date,
) -> ScheduleOut:
    """고객이 낸 날짜 수락 (한 트랜잭션). 잠금 순서: 프로젝트 → 확정 → 제안 · 요청 → 공정표(insert).
    처음이면 확정 confirmed → scheduled, 수락한 뒤 바꾸기면 scheduled 그대로 날짜만 바꾼다(이력 note).
    열린 요청은 닫고, 확정 공정표 새 버전을 만든다(본 버전 + 1)."""
    p = await project_service.get_for(s, user, project_id)
    expected = await ensure_expected(s, p, today)
    await project_service.lock_for_visit(s, p.id)  # 다른 공정 수락과 겹침 확인 · 버전이 줄 선다
    d = await _lock_deal(s, deal_id)
    if d is None or d.project_id != p.id:
        raise AppError(404, "not_found", NO_DEAL)
    x = await s.get(DateProposal, proposal_id, populate_existing=True)
    if x is None or x.deal_id != d.id:
        raise AppError(404, "not_found", "공사 날짜를 찾을 수 없어요.")
    if d.status == "reselected":
        raise AppError(409, "invalid_state", "다시 고른 업체의 날짜라 수락할 수 없어요.")
    if d.status not in CHANGEABLE:
        raise AppError(409, "invalid_state", DONE_DATES)
    if x.status == "superseded":
        raise AppError(409, "dates_changed", "날짜가 바뀌었어요. 새 날짜를 확인해 주세요.")
    if x.status == "accepted":
        raise AppError(409, "invalid_state", "이미 공사 날짜를 수락했어요.")
    if x.status != "pending":
        raise AppError(409, "invalid_state", "수락할 수 없는 날짜예요.")
    if x.start_date < today:
        raise AppError(409, "start_passed", "시작일이 지났어요. 다른 날짜를 요청해 주세요.")
    others = await _others(s, p.id, d.trade)
    if _fit(d.trade, x.start_date, x.end_date, others, _weekend(expected), today).conflicts:
        raise AppError(409, "overlap", "겹치는 날이 있어 수락할 수 없어요.")
    now = now_utc()
    first = d.status == "confirmed"
    weekend = _weekend(expected)
    try:
        await _set(s, DateProposal, x.id, "pending", {"status": "accepted", "decided_at": now})
        dates = {
            "start_date": x.start_date,
            "end_date": x.end_date,
            # v3: 업체가 하나씩 고른 날. 옛 길(범위)은 그 사이 일하는 날로 (계산 엔진)
            "work_days": list(x.days)
            if x.days
            else _range_workdays(x.start_date, x.end_date, weekend),
        }
        await _set(s, Deal, d.id, d.status, {"status": "scheduled", **dates})
        s.add(
            DealEvent(
                deal_id=d.id,
                from_status=d.status,
                to_status="scheduled",
                by_id=user.id,
                note=None
                if first
                else f"날짜 바꿈 {_iso(d.start_date, d.end_date)} → {_iso(x.start_date, x.end_date)}",
                code="dates_accepted" if first else "dates_changed",
                at=now,
            )
        )
        reqs = list((await _open_requests(s, [d.id])).values())
        await s.execute(
            update(DateRequest)
            .where(DateRequest.deal_id == d.id, DateRequest.status == "open")
            .values(status="withdrawn", closed_at=now)
            .execution_options(synchronize_session=False)
        )
        await jobs_service.cancel_refs(
            s, now=now, ref_ids=[d.id, *[r.id for r in reqs]], kinds=DATE_JOBS
        )
        await _save_final(s, p, expected, data.seen_version, today)
        if d.vendor_id is not None:
            await notify_service.add(
                s,
                user_id=d.vendor_id,
                kind="dates_accepted",
                body=_to_vendor(
                    "고객이 공사 날짜를 수락했어요"
                    if first
                    else "고객이 새 공사 날짜를 수락했어요",
                    p,
                    d.trade,
                ),
                link=f"/vendor/jobs/{d.id}",
                dedup_key=f"date_proposal:{x.id}:accepted",
            )
        await s.commit()
    except IntegrityError as exc:  # 확정 공정표 버전 UQ
        await s.rollback()
        raise AppError(409, "plan_changed", "공정표가 바뀌었어요. 새로 불러올게요.") from exc
    _push(s, [StatePush((user.id, d.vendor_id), "deal", d.id, p.id)], [d.vendor_id])
    return await schedule_for(s, user, project_id, today)


async def request_dates(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    deal_id: uuid.UUID,
    data: DateRequestIn,
    today: date,
) -> ScheduleOut:
    """다른 날짜 요청 · 수락한 날짜 바꾸기 요청 (합쳐 2번까지): 지금 날짜는 그대로 두고 업체가
    요청 + 48시간 안에 새 날짜를 낸다(v3, calc.deadline.date_request_due · 기한 일 deal_request_due).
    수락한 뒤에는 이유가 필수다."""
    p = await project_service.get_for(s, user, project_id)
    weekend = _weekend(await ensure_expected(s, p, today))
    off = _off(today)
    for w in data.wish_dates:
        if w <= today or w > today + timedelta(days=AHEAD_DAYS):
            raise AppError(422, "wish_dates", "시작해도 되는 날은 내일부터 1년 안으로 골라 주세요.")
        if is_off(w, off, weekend):
            raise AppError(422, "wish_dates", "시작해도 되는 날은 일하는 날로 골라 주세요.")
    await project_service.lock_for_visit(s, p.id)
    d = await _lock_deal(s, deal_id)
    if d is None or d.project_id != p.id:
        raise AppError(404, "not_found", NO_DEAL)
    _changeable(d)
    change = d.status == "scheduled"
    if change and data.reason is None:
        raise AppError(422, "reason", "날짜를 바꾸고 싶은 이유를 적어 주세요.")
    x = (await _pending(s, [d.id])).get(d.id)
    if not change and x is None:
        raise AppError(409, "no_dates", "업체가 공사 날짜를 낸 뒤에 요청할 수 있어요.")
    base = _base(d, x)
    # 고른 날에 같은 기간으로 하면 수락한 다른 공정과 겹치는지 (겹치면 수락할 수 없다)
    if base is not None:
        others = await _others(s, p.id, d.trade)
        n = max(_job_workdays(*base, weekend), 1)
        for w in data.wish_dates:
            end = workdays(w, n, _off(w), weekend)[-1]
            if _fit(d.trade, w, end, others, weekend, today).conflicts:
                raise AppError(
                    422,
                    "wish_dates",
                    "다른 공정과 겹치는 날이 있어요. 고를 수 있는 날 중에서 골라 주세요.",
                )
    if (await _open_requests(s, [d.id])).get(d.id) is not None:
        raise AppError(
            409, "already_requested", "이미 다른 날짜를 요청했어요. 업체 답을 기다려 주세요."
        )
    used = "다른 날짜 요청은 2번까지 할 수 있어요."
    if d.date_request_count >= REQUESTS_MAX:
        raise AppError(409, "requests_used", used)
    now = now_utc()
    try:
        res = await s.execute(
            update(Deal)
            .where(
                Deal.id == d.id,
                Deal.status == d.status,
                Deal.date_request_count < REQUESTS_MAX,
            )
            .values(date_request_count=Deal.date_request_count + 1)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            raise AppError(409, "requests_used", used)
        req = DateRequest(
            id=uuid7(),
            deal_id=d.id,
            reason=data.reason,
            wish_dates=sorted(data.wish_dates),
            due_at=deadline.date_request_due(now),
            by_id=user.id,
            created_at=now,
        )
        s.add(req)
        await s.flush()
        await jobs_service.add(s, kind="deal_request_due", ref_id=req.id, run_at=req.due_at)
        if d.vendor_id is not None:
            await notify_service.add(
                s,
                user_id=d.vendor_id,
                kind="dates_requested",
                body=_to_vendor(
                    "고객이 공사 날짜 바꾸기를 요청했어요"
                    if change
                    else "고객이 다른 공사 날짜를 요청했어요",
                    p,
                    d.trade,
                ),
                link=f"/vendor/jobs/{d.id}",
                dedup_key=f"date_request:{req.id}",
            )
        await s.commit()
    except IntegrityError as exc:  # 열린 요청은 하나 (부분 UQ)
        await s.rollback()
        raise AppError(409, "already_requested", "이미 다른 날짜를 요청했어요.") from exc
    _push(s, [StatePush((user.id, d.vendor_id), "deal", d.id, p.id)], [d.vendor_id])
    return await schedule_for(s, user, project_id, today)


def _request_options(
    d: Deal, r: DateRequest | None, weekend: tuple[int, ...]
) -> list[StartOptionOut]:
    """수락한 날짜 바꾸기 요청: 고객이 고른 시작일마다 지금과 같은 일하는 날 수로 끝나는 날"""
    if r is None or d.status != "scheduled" or d.start_date is None:
        return []
    n = _job_workdays(d.start_date, d.end_date, d.work_days, weekend)
    off = _off(min(r.wish_dates))
    return [
        StartOptionOut(start=w, end=workdays(w, max(n, 1), off, weekend)[-1])
        for w in sorted(r.wish_dates)
    ]


async def _wishes_taken(
    s: AsyncSession, d: Deal, r: DateRequest, today: date, count: int, weekend: tuple[int, ...]
) -> bool:
    """고객이 고른 시작일이 모두 막혔다: 지났거나, 그날부터 일하는 날 count개(업체가 낸 날 수)를 이으면 같은 업체의
    다른 공사로 팀이 모두 나간 날(계산 엔진 busy_days)에 걸린다. 비서 공사 날 후보(request_candidates)와 같은 판정
    (calc.schedule.wishes_blocked, QA r2 c6 리드 결정 5)이라 비서가 낸 다른 날 제안을 실행이 막지 않는다."""
    busy = await _busy(s, d, today)
    off = _off(today)
    until = today + timedelta(days=AHEAD_DAYS)
    return wishes_blocked(r.wish_dates, max(count, 1), today, busy, off, weekend, until)


async def _vendor_deal(s: AsyncSession, vendor: User, deal_id: uuid.UUID) -> Deal:
    d = await s.get(Deal, deal_id, populate_existing=True)
    if d is None or d.vendor_id != vendor.id:
        raise AppError(404, "not_found", NO_DEAL)
    return d


async def _busy(s: AsyncSession, d: Deal, today: date) -> list[date]:
    """같은 업체의 다른 공사(이 공사 빼고)로 팀이 모두 나간 날, 내일부터 1년(계산 엔진 busy_days). 공사마다
    수락한 날 · 수락 기다리는 낸 날을 합쳐 한 건으로 센다. 공사 날짜 화면 경고 · 미리보기 · 비서 공사 날 후보가 쓴다."""
    if d.vendor_id is None:
        return []
    q = select(Deal).where(
        Deal.vendor_id == d.vendor_id, Deal.id != d.id, Deal.status.in_(OPEN_DEALS)
    )
    deals = list((await s.execute(q)).scalars().all())
    pend = await _pending(s, [o.id for o in deals])
    jobs: list[set[date]] = []
    for o in deals:
        got: set[date] = set()
        if o.start_date is not None and o.end_date is not None:
            got.update(job_days(o.start_date, o.end_date, o.work_days))
        x = pend.get(o.id)
        if x is not None:
            got.update(job_days(x.start_date, x.end_date, x.days))
        jobs.append(got)
    lo, hi = today + timedelta(days=1), today + timedelta(days=AHEAD_DAYS)
    return sorted(x for x in busy_days(jobs, TEAMS) if lo <= x <= hi)


async def job_for(s: AsyncSession, vendor: User, deal_id: uuid.UUID, today: date) -> JobOut:
    """GET /vendor/jobs/{id}: 공사 날짜 내기 화면 (내 확정만)"""
    d = await _vendor_deal(s, vendor, deal_id)
    p = await project_service.get_out(s, d.project_id)
    plan = await ensure_expected(s, p, today)
    weekend = _weekend(plan)
    block = (
        await s.scalars(
            select(PlanStep).where(
                PlanStep.plan_id == plan.id, PlanStep.trade == d.trade, PlanStep.kind == "work"
            )
        )
    ).first()
    visit = await visit_service.vendor_visit(s, vendor, d.visit_id, today)  # B3: 연락처 칸 없음
    now = now_utc()
    (out,) = await _deal_out(s, [d], today, now)
    extras = (await _extras(s, [d]))[d.id]
    x = (await _pending(s, [d.id])).get(d.id)
    r = (await _open_requests(s, [d.id])).get(d.id)
    return JobOut(
        deal_id=d.id,
        trade=d.trade,
        status=d.status,
        confirmed_at=d.created_at,
        dates_due_at=d.dates_due_at,
        overdue=out.overdue,
        start_date=d.start_date,
        end_date=d.end_date,
        visit=visit,
        quote=out.quote,
        plan_version=plan.version,
        plan_start=block.start_date if block else None,
        plan_end=block.end_date if block else None,
        need=_need(p, d.trade, None),
        others=[_other(o) for o in await _others(s, d.project_id, d.trade)],
        weekend_work=plan.weekend_work,
        holidays=_holidays(today),
        dates_state=_state(d, x, r),
        proposal=_proposal_out(x, d.id in await _changed(s, [d.id]), weekend) if x else None,
        request=_request_out(r, now) if r else None,
        requests_left=REQUESTS_MAX - d.date_request_count,
        request_options=_request_options(d, r, weekend),
        extras=extras,
        accepted_crew=(await _accepted_crews(s, [d.id])).get(d.id),
        work_done_on=d.work_done_on,
        contact_until=out.contact_until,
        fixing_note=out.fixing_note,
        can_finish=d.status in FINISHABLE and d.end_date is not None and today >= d.end_date,
        work_days=out.work_days,
        done_note=out.done_note,
        done_posted_at=out.done_posted_at,
        auto_done_at=out.auto_done_at,
        done_photos=out.done_photos,
        thread_id=out.thread_id,
        grand_total=extras.grand_total,
        day_no=work_view.day_no(d.work_days or [], today),
        busy_days=await _busy(s, d, today),
    )


async def preview_dates(
    s: AsyncSession,
    vendor: User,
    deal_id: uuid.UUID,
    start: date,
    end: date,
    crew: int,
    today: date,
) -> PreviewOut:
    """낼 날짜 미리 계산 (저장하지 않음): 일하는 날 · 그 인원의 필요한 기간 · 다른 공정과 겹침 ·
    우리 업체의 다른 공사와 겹치는 날(막지 않고 알린다)"""
    d = await _vendor_deal(s, vendor, deal_id)
    p = await project_service.get_out(s, d.project_id)
    weekend = _weekend(await ensure_expected(s, p, today))
    n = _check_range(start, end, today, weekend)
    need = _need(p, d.trade, crew)
    others = await _others(s, d.project_id, d.trade)
    return PreviewOut(
        workdays=n,
        need=need,
        short=n < need.days,
        fit=_fit(d.trade, start, end, others, weekend, today),
        overlaps=overlap_days(_range_workdays(start, end, weekend), await _busy(s, d, today)),
    )


async def propose_dates(
    s: AsyncSession, vendor: User, deal_id: uuid.UUID, data: DatesIn, today: date
) -> JobOut:
    """업체가 공사 날짜 내기 (한 트랜잭션). 잠금 순서: 프로젝트 → 확정 → 제안 · 요청.
    앞서 낸 날짜 superseded → 새 날짜 pending → 열린 요청 answered → 고객 알림. 옛 길(시작 ~ 끝)은
    겹쳐도 낼 수 있다(수락이 막힌다). v3 날 목록(days, V11)은 날 수 = 견적서 공사 기간 · 주말 · 공휴일 ·
    다른 공정과 겹침을 계산 엔진으로 보고 422. 수락한 뒤(scheduled)에는 바꾸기(change): 고객 요청에
    답하면 고객이 고른 시작일 중에서, 스스로 바꾸면 이유 필수. 수락하기 전까지 지금 날짜는 그대로다."""
    d = await _vendor_deal(s, vendor, deal_id)
    p = await project_service.get_out(s, d.project_id)
    _need(p, d.trade, None)  # 응답(job_for)의 필요한 기간을 못 세는 공정이면 저장하기 전에 409
    plan = await ensure_expected(s, p, today)
    weekend = _weekend(plan)
    picked: list[date] | None = None
    if data.days is not None:
        quote = (await quote_service.briefs_by_id(s, [d.quote_id]))[d.quote_id]
        picked = _check_days(data.days, today, weekend, quote.days)
        start, end = picked[0], picked[-1]
    else:
        assert data.start is not None and data.end is not None  # DatesIn이 지킨다
        _check_range(data.start, data.end, today, weekend)
        start, end = data.start, data.end
    if data.method == "call":
        if data.call_on is None:
            raise AppError(422, "call_on", "통화한 날을 골라 주세요.")
        if data.call_on > today:
            raise AppError(422, "call_on", "통화한 날은 오늘까지만 고를 수 있어요.")
    await project_service.lock(s, d.project_id)  # 잠금 순서: 프로젝트 → 확정 → 제안 · 요청
    d = await _lock_deal(s, d.id)
    if d is None or d.vendor_id != vendor.id:
        raise AppError(404, "not_found", NO_DEAL)
    if d.status == "reselected":
        raise AppError(409, "invalid_state", "고객이 업체를 다시 고르기로 했어요.")
    if d.status not in CHANGEABLE:
        raise AppError(409, "invalid_state", DONE_DATES)
    change = d.status == "scheduled"
    if change and data.kind == "initial":  # 그사이 고객이 수락했다
        raise AppError(409, "invalid_state", "고객이 이미 공사 날짜를 수락했어요.")
    if not change and data.kind == "change":
        raise AppError(
            409, "invalid_state", "고객이 아직 수락하지 않은 날짜예요. 날짜 다시 내기로 내 주세요."
        )
    x = (await _pending(s, [d.id])).get(d.id)
    r = (await _open_requests(s, [d.id])).get(d.id)
    if data.request_id is not None and (r is None or r.id != data.request_id):
        raise AppError(409, "request_changed", "고객 요청이 바뀌었어요. 새로 불러올게요.")
    if change and r is not None:
        if picked is None:
            allowed = {(o.start, o.end) for o in _request_options(d, r, weekend)}
            if (start, end) not in allowed:
                raise AppError(
                    422, "request_dates", "고객이 고른 시작일 중에서 같은 기간으로 골라 주세요."
                )
        elif start not in set(r.wish_dates) and not await _wishes_taken(
            s, d, r, today, len(picked), weekend
        ):
            # 고른 날이 모두 지났거나 우리 업체의 다른 공사로 찼으면 다른 날로 답할 수 있다(고객이 수락해야 바뀐다)
            raise _field("days", "고객이 고른 시작일 중 하루에 시작해 주세요.")
    if change and r is None and data.reason is None:
        raise AppError(422, "reason", "날짜를 바꾸는 이유를 적어 주세요. 고객에게 보여요.")
    if picked is not None:  # v3: 다른 공정과 겹치는 날은 낼 수 없다 (계산 엔진 order_conflicts)
        others = await _others(s, d.project_id, d.trade)
        if _fit(d.trade, start, end, others, weekend, today).conflicts:
            raise _field("days", "다른 공정과 겹치는 날이 있어요. 겹치지 않는 날로 골라 주세요.")
    owner = (await project_service.briefs(s, [d.project_id]))[d.project_id].owner_id
    now = now_utc()
    try:
        if x is not None:
            await _set(
                s, DateProposal, x.id, "pending", {"status": "superseded", "decided_at": now}
            )
        new = DateProposal(
            id=uuid7(),
            deal_id=d.id,
            start_date=start,
            end_date=end,
            days=picked,
            crew=data.crew,
            method=data.method,
            call_on=data.call_on if data.method == "call" else None,
            request_id=r.id if r else None,
            kind="change" if change else "initial",
            reason=data.reason if change else None,
            plan_version=plan.version,
            by_id=vendor.id,
            created_at=now,
        )
        s.add(new)
        await s.flush()
        if r is not None:
            await _set(s, DateRequest, r.id, "open", {"status": "answered", "closed_at": now})
        # 날짜가 왔으니 '공사 날짜 기한' · 답한 요청의 기한 일은 필요 없다
        await jobs_service.cancel_refs(
            s, now=now, ref_ids=[d.id, r.id if r else None], kinds=DATE_JOBS
        )
        who, label = i_ga(d.vendor_name), LABEL[d.trade]
        if not change:
            again = "다시 " if x is not None else ""
            body, link = f"{who} 공사 날짜를 {again}냈어요 · {label}", "schedule?trade=" + d.trade
        elif r is not None:  # 바꾸기 답 · 바꾸자는 날짜는 공사 날짜 화면에서 바로 답해요(QA r6)
            body, link = f"{who} 새 {label} 날짜를 올렸어요", "schedule?view=dates"
        else:
            body, link = f"{who} {label} 날짜를 바꾸자고 했어요", "schedule?view=dates"
        await notify_service.add(
            s,
            user_id=owner,
            kind="dates_proposed",
            body=body,
            link=f"/projects/{d.project_id}/{link}",
            dedup_key=f"date_proposal:{new.id}",
            project_id=d.project_id,
        )
        await s.commit()
    except IntegrityError as exc:  # 수락 기다리는 날짜는 하나 (부분 UQ)
        await s.rollback()
        raise AppError(409, "stale", STALE) from exc
    _push(s, [StatePush((owner, vendor.id), "deal", d.id, d.project_id)], [owner])
    return await job_for(s, vendor, deal_id, today)


# ---- 공사 중 추가 금액: 업체가 알리고 고객이 확인하거나 이야기하자고 한다. 결제 · 계약은 하지 않는다 ----

EXTRA_OPEN = ("scheduled", "fixing")  # 공사 날짜를 수락한 뒤 · 남은 일을 하는 동안
# v3(0030)에서 DB 답 값을 바꿨다(D23). 옛 길(/ack · ok · talk)은 바꿔 읽고 쓴다. v3 값은 ExtraOut.answer
ACK_NEW = {"ok": "approved", "talk": "asked"}
ACK_OLD = {"pending": "pending", "approved": "ok", "asked": "talk", "rejected": "talk"}


def _money(m: Money) -> MoneyOut:
    return MoneyOut(supply=m.supply, vat=m.vat, total=m.total)


async def _extras(s: AsyncSession, deals: list[Deal]) -> dict[uuid.UUID, TradeExtrasOut]:
    """공사마다 추가 금액 · 확인한 것 · 기다리는 것 · 이야기 중인 것 합계(계산 엔진)"""
    ids = [d.id for d in deals]
    rows = []
    photos: dict[uuid.UUID, list[ExtraPhotoOut]] = {}
    if ids:
        q = select(ExtraCharge).where(ExtraCharge.deal_id.in_(ids)).order_by(ExtraCharge.created_at)
        rows = list((await s.execute(q.execution_options(populate_existing=True))).scalars())
    if rows:
        q = (
            select(ExtraChargeFile, File)
            .join(File, File.id == ExtraChargeFile.file_id)
            .where(ExtraChargeFile.extra_id.in_([x.id for x in rows]))
            .order_by(ExtraChargeFile.sort)
        )
        for link, f in (await s.execute(q)).all():
            photos.setdefault(link.extra_id, []).append(
                ExtraPhotoOut(
                    file_id=f.id, filename=f.filename, content_type=f.content_type, size=f.size
                )
            )
    quotes = await quote_service.briefs_by_id(s, [d.quote_id for d in deals])
    out = {}
    for d in deals:
        mine = [x for x in rows if x.deal_id == d.id]

        def sum_of(ack: str, mine=mine) -> MoneyOut:
            # 합계에는 최신 판만 (고친 앞 판은 빠진다, D23)
            return _money(
                add_money(
                    Money(x.supply, x.vat, x.total)
                    for x in mine
                    if x.ack == ack and x.superseded_at is None
                )
            )

        ok = sum_of("approved")
        base = quotes[d.quote_id].total if d.quote_id in quotes else None
        grand = work_view.grand_total(base, [ok.total]) if base is not None else None

        def after(x: ExtraCharge, grand=grand) -> int | None:
            """승인하면 공사 금액: 답을 기다리거나 물어본 최신 판만 (C37)"""
            waiting = x.ack in ("pending", "asked") and x.superseded_at is None
            return (
                work_view.grand_total(grand, [x.total]) if waiting and grand is not None else None
            )

        out[d.id] = TradeExtrasOut(
            trade=d.trade,
            deal_id=d.id,
            vendor_name=d.vendor_name,
            deal_total=base,
            grand_total=grand,
            items=[
                ExtraOut(
                    id=x.id,
                    title=x.title,
                    reason=x.reason,
                    vat_mode=x.vat_mode,
                    entered_amount=x.entered_amount,
                    supply=x.supply,
                    vat=x.vat,
                    total=x.total,
                    ack=ACK_OLD[x.ack],
                    answer=x.ack,
                    group_id=x.group_id,
                    version=x.version,
                    superseded=x.superseded_at is not None,
                    acked_at=x.acked_at,
                    created_at=x.created_at,
                    photos=photos.get(x.id, []),
                    after_total=after(x),
                )
                for x in mine
            ],
            ok=ok,
            pending=sum_of("pending"),
            talk=sum_of("asked"),
        )
    return out


async def work_money(s: AsyncSession, user: User, project_id: uuid.UUID) -> list[TradeExtrasOut]:
    """공정마다 지금 공사 금액(비서 보드 · 도구가 읽는다): 확정 금액(deal_total) · 승인한 추가 금액(ok) ·
    확정 금액 + 승인한 추가 금액(grand_total). 만든 사람 · 관리자만, 다시 고른 확정은 빼요. 값은 계산 엔진이 더한 것."""
    p = await project_service.get_for(s, user, project_id)
    q = select(Deal).where(Deal.project_id == p.id, Deal.status != "reselected")
    deals = sorted(
        (await s.execute(q.execution_options(populate_existing=True))).scalars().all(),
        key=lambda d: ORDER.index(d.trade),
    )
    return list((await _extras(s, deals)).values())


async def _approved_extras(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    """공사마다 고객이 승인한 추가 금액(최신 판, 부가세 포함). 더하기는 계산 엔진(work_view)."""
    if not deal_ids:
        return {}
    q = select(ExtraCharge.deal_id, ExtraCharge.total).where(
        ExtraCharge.deal_id.in_(deal_ids),
        ExtraCharge.ack == "approved",
        ExtraCharge.superseded_at.is_(None),
    )
    out: dict[uuid.UUID, list] = {}
    for deal_id, total in (await s.execute(q)).all():
        out.setdefault(deal_id, []).append(total)
    return out


async def _extras_pending(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not deal_ids:
        return {}
    q = (
        select(ExtraCharge.deal_id, func.count())
        .where(
            ExtraCharge.deal_id.in_(deal_ids),
            ExtraCharge.ack == "pending",
            ExtraCharge.superseded_at.is_(None),
        )
        .group_by(ExtraCharge.deal_id)
    )
    return {deal_id: int(n) for deal_id, n in (await s.execute(q)).all()}


def _extra_money(amount: int, mode: str, tax_kind: str) -> Money:
    """간이 업체는 부가세를 따로 붙이지 않는다(L02, 계약 4.7): 세율 0으로 계산 엔진을 부른다."""
    rate = Decimal(0) if tax_kind == "simplified" else VAT_RATE
    return from_entered(amount, mode, rate=rate)


async def _extra_by_key(
    s: AsyncSession, deal_id: uuid.UUID, client_key: uuid.UUID
) -> ExtraCharge | None:
    q = select(ExtraCharge).where(
        ExtraCharge.deal_id == deal_id, ExtraCharge.client_key == client_key
    )
    return (await s.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


REVISED = "이미 고친 판이 있어요. 새로 불러올게요."
EXEMPT_ONLY = "면세 업체는 면세로만 적을 수 있어요."


async def preview_extra(
    s: AsyncSession, vendor: User, deal_id: uuid.UUID, entered_amount: int, vat_mode: str
) -> ExtraPreviewOut:
    """GET /vendor/jobs/{id}/extras/preview: 보내기 전 공급가 · 부가세 · 합계와 승인하면 공사 금액
    (계산 엔진, 저장하지 않는다). 간이 업체는 부가세 0, 면세 업체는 면세만(422)."""
    d = await _vendor_deal(s, vendor, deal_id)
    tax = await vendor_service.tax_kind_of(s, vendor.id)
    if tax == "exempt" and vat_mode != "exempt":
        raise _field("vat_mode", EXEMPT_ONLY)
    money = _extra_money(entered_amount, vat_mode, tax)
    grand = (await _extras(s, [d]))[d.id].grand_total
    return ExtraPreviewOut(
        supply=money.supply,
        vat=money.vat,
        total=money.total,
        tax_kind=tax,
        grand_total=grand,
        after_total=work_view.grand_total(grand, [money.total]) if grand is not None else None,
    )


async def add_extra(
    s: AsyncSession, vendor: User, deal_id: uuid.UUID, data: ExtraIn, today: date
) -> tuple[JobOut, bool]:
    """업체가 추가 금액 알리기 · 고친 판 올리기 (한 트랜잭션). 잠금 순서: 프로젝트 → 확정 → 사진 → 추가 금액.
    금액은 업체가 적은 값이고 공급가 · 부가세 · 합계는 계산 엔진(from_entered)이 만든다. 간이 업체는
    부가세 0(L02). v3: client_key가 같으면 처음 줄을 그대로 돌려준다(200). replaces(앞 판 id)면 같은
    묶음의 새 판(version + 1)이고 앞 판은 superseded가 된다(D23, 답 · 합계는 최신 판만).
    돌려주는 값: (공사 한 건 화면, 새로 만들었는지)."""
    d = await _vendor_deal(s, vendor, deal_id)
    # 응답(job_for)의 필요한 기간을 못 세는 공정이면 저장하기 전에 409
    _need(await project_service.get_out(s, d.project_id), d.trade, None)
    if data.client_key is not None and await _extra_by_key(s, d.id, data.client_key):
        return await job_for(s, vendor, deal_id, today), False
    tax = await vendor_service.tax_kind_of(s, vendor.id)
    if tax == "exempt" and data.vat_mode != "exempt":
        raise AppError(422, "vat_mode", EXEMPT_ONLY)
    money = _extra_money(data.entered_amount, data.vat_mode, tax)
    await project_service.lock(s, d.project_id)
    d = await _lock_deal(s, d.id)
    if d is None or d.vendor_id != vendor.id:
        raise AppError(404, "not_found", NO_DEAL)
    if data.client_key is not None and await _extra_by_key(s, d.id, data.client_key):
        return await job_for(s, vendor, deal_id, today), False  # 잠금을 기다리는 동안 먼저 저장됨
    if d.status == "reselected":
        raise AppError(409, "invalid_state", "다시 고른 업체의 공사예요.")
    if d.status not in EXTRA_OPEN:
        raise AppError(
            409, "invalid_state", "공사 날짜를 수락한 뒤 공사하는 동안에만 알릴 수 있어요."
        )
    prev = None
    if data.replaces is not None:
        prev = await s.get(ExtraCharge, data.replaces, populate_existing=True)
        if prev is None or prev.deal_id != d.id:
            raise AppError(404, "not_found", "고칠 추가 금액을 찾을 수 없어요.")
        if prev.superseded_at is not None:
            raise app_error("stale", REVISED)
    files = await files_service.owned(s, vendor.id, data.file_ids, lock=True)
    if any(i not in files or files[i].kind != "work_photo" for i in data.file_ids):
        raise AppError(422, "file", "올린 공사 사진을 다시 확인해 주세요.")
    used = "다른 추가 금액에 붙인 사진이에요."
    if data.file_ids:
        q = select(ExtraChargeFile.file_id).where(ExtraChargeFile.file_id.in_(data.file_ids))
        if (await s.execute(q)).first():
            raise AppError(409, "file_used", used)
    owner = (await project_service.briefs(s, [d.project_id]))[d.project_id].owner_id
    now = now_utc()
    try:
        if prev is not None:  # 앞 판을 먼저 내려야 '최신 판 하나' 부분 UQ를 지난다
            res = await s.execute(
                update(ExtraCharge)
                .where(ExtraCharge.id == prev.id, ExtraCharge.superseded_at.is_(None))
                .values(superseded_at=now)
                .execution_options(synchronize_session=False)
            )
            if res.rowcount != 1:
                raise app_error("stale", REVISED)
        xid = uuid7()
        x = ExtraCharge(
            id=xid,
            group_id=prev.group_id if prev else xid,  # 첫 판은 자기 id가 판 묶음이다 (D23)
            version=prev.version + 1 if prev else 1,
            deal_id=d.id,
            title=data.title,
            reason=data.reason,
            vat_mode=data.vat_mode,
            entered_amount=data.entered_amount,
            supply=money.supply,
            vat=money.vat,
            total=money.total,
            by_id=vendor.id,
            client_key=data.client_key,
            created_at=now,
        )
        s.add(x)
        await s.flush()
        s.add_all(
            [ExtraChargeFile(extra_id=x.id, file_id=i, sort=n) for n, i in enumerate(data.file_ids)]
        )
        cards = await _card(s, d.project_id, vendor.id, "extra_sent", x.id)
        verb = "고쳐 올렸어요" if prev else "알렸어요"
        await notify_service.add(
            s,
            user_id=owner,
            kind="extra_added",
            body=f"{i_ga(d.vendor_name)} 추가 금액을 {verb} · {LABEL[d.trade]}",
            link=f"/projects/{d.project_id}/plan",
            dedup_key=f"extra:{x.id}",
            project_id=d.project_id,
        )
        await s.commit()
    except IntegrityError as exc:  # 같은 키 · 같은 판 동시 · 사진 하나는 한 줄에만 (UQ)
        await s.rollback()
        if data.client_key is not None and await _extra_by_key(s, deal_id, data.client_key):
            return await job_for(s, vendor, deal_id, today), False
        if prev is not None:
            raise app_error("stale", REVISED) from exc
        raise AppError(409, "file_used", used) from exc
    _push(s, [StatePush((owner, vendor.id), "extra", x.id, d.project_id)], [owner], cards)
    return await job_for(s, vendor, deal_id, today), True


ANSWERS = {"approve": "approved", "reject": "rejected", "ask": "asked"}
# 답할 수 있는 지금 값: 묻기는 처음 한 번, 승인 · 거절은 기다림 · 물어본 뒤 (data-model 5장)
ANSWER_FROM = {
    "approved": ("pending", "asked"),
    "rejected": ("pending", "asked"),
    "asked": ("pending",),
}
ANSWER_TEXT = {
    "approved": "고객이 추가 금액을 승인했어요",
    "rejected": "고객이 추가 금액을 거절했어요 · 고쳐서 다시 올릴 수 있어요",
    "asked": "고객이 추가 금액을 채팅으로 물어봤어요",
}


async def answer_extra(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    deal_id: uuid.UUID,
    extra_id: uuid.UUID,
    data: AnswerIn,
) -> TradeExtrasOut:
    """v3 추가 금액 답 (C37, D23): 승인 · 거절 · 채팅으로 묻기. 최신 판에만(고친 앞 판은 409 stale).
    잠금 순서: 프로젝트 → 확정 → 추가 금액. 조건부 UPDATE(1행이 아니면 409). 묻기면 채팅에 시스템 카드."""
    p = await project_service.get_for(s, user, project_id)
    await project_service.lock(s, p.id)
    d = await _lock_deal(s, deal_id)
    if d is None or d.project_id != p.id:
        raise AppError(404, "not_found", NO_DEAL)
    x = await s.get(ExtraCharge, extra_id, populate_existing=True)
    if x is None or x.deal_id != d.id:
        raise AppError(404, "not_found", "추가 금액을 찾을 수 없어요.")
    if d.status == "reselected":
        raise app_error("locked", "다시 고른 업체의 공사라 답할 수 없어요.")
    if x.superseded_at is not None:
        raise app_error("stale", "업체가 고친 새 판이 있어요. 새 판에 답해 주세요.")
    to = ANSWERS[data.answer]
    if x.ack not in ANSWER_FROM[to]:
        raise app_error("already", "이미 답한 추가 금액이에요.")
    now = now_utc()
    res = await s.execute(
        update(ExtraCharge)
        .where(
            ExtraCharge.id == x.id,
            ExtraCharge.ack.in_(ANSWER_FROM[to]),
            ExtraCharge.superseded_at.is_(None),
        )
        .values(ack=to, acked_at=now)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise app_error("stale")
    cards = await _card(s, p.id, d.vendor_id, "extra_asked", x.id) if to == "asked" else []
    if d.vendor_id is not None:
        await notify_service.add(
            s,
            user_id=d.vendor_id,
            kind="extra_acked",
            body=_to_vendor(ANSWER_TEXT[to], p, d.trade),
            link=catalog.link("extra_acked", did=d.id),
            dedup_key=f"extra:{x.id}:{to}",
        )
    await s.commit()
    _push(s, [StatePush((user.id, d.vendor_id), "extra", x.id, p.id)], [d.vendor_id], cards)
    return (await _extras(s, [d]))[d.id]


async def ack_extra(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    deal_id: uuid.UUID,
    extra_id: uuid.UUID,
    data: AckIn,
) -> TradeExtrasOut:
    """고객이 추가 금액에 답하기 (확인 기다림에서만 한 번). 잠금 순서: 프로젝트 → 확정 → 추가 금액."""
    p = await project_service.get_for(s, user, project_id)
    await project_service.lock(s, p.id)
    d = await _lock_deal(s, deal_id)
    if d is None or d.project_id != p.id:
        raise AppError(404, "not_found", NO_DEAL)
    x = await s.get(ExtraCharge, extra_id, populate_existing=True)
    if x is None or x.deal_id != d.id:
        raise AppError(404, "not_found", "추가 금액을 찾을 수 없어요.")
    answered = "이미 답한 추가 금액이에요."
    if x.superseded_at is not None:
        raise AppError(409, "invalid_state", "업체가 고친 새 판이 있어요. 새 판에 답해 주세요.")
    if x.ack != "pending":
        raise AppError(409, "invalid_state", answered)
    res = await s.execute(
        update(ExtraCharge)
        .where(
            ExtraCharge.id == x.id,
            ExtraCharge.ack == "pending",
            ExtraCharge.superseded_at.is_(None),
        )
        .values(ack=ACK_NEW[data.ack], acked_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise AppError(409, "invalid_state", answered)
    if d.vendor_id is not None:
        await notify_service.add(
            s,
            user_id=d.vendor_id,
            kind="extra_acked",
            body=_to_vendor(
                "고객이 추가 금액을 확인했어요"
                if data.ack == "ok"
                else "고객이 추가 금액을 이야기하고 싶어 해요",
                p,
                d.trade,
            ),
            link=f"/vendor/jobs/{d.id}",
            dedup_key=f"extra:{x.id}:ack",
        )
    await s.commit()
    _push(s, [StatePush((user.id, d.vendor_id), "extra", x.id, p.id)], [d.vendor_id])
    return (await _extras(s, [d]))[d.id]


async def _extra_photo(
    s: AsyncSession, deal: Deal, extra_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    q = (
        select(File)
        .join(ExtraChargeFile, ExtraChargeFile.file_id == File.id)
        .join(ExtraCharge, ExtraCharge.id == ExtraChargeFile.extra_id)
        .where(
            ExtraChargeFile.extra_id == extra_id,
            ExtraChargeFile.file_id == file_id,
            ExtraCharge.deal_id == deal.id,
        )
    )
    f = (await s.execute(q)).scalar_one_or_none()
    if f is None:
        raise AppError(404, "not_found", "사진을 찾을 수 없어요.")
    return await files_service.respond(f)


async def customer_extra_photo(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    deal_id: uuid.UUID,
    extra_id: uuid.UUID,
    file_id: uuid.UUID,
) -> Response:
    p = await project_service.get_for(s, user, project_id)
    d = await s.get(Deal, deal_id)
    if d is None or d.project_id != p.id:
        raise AppError(404, "not_found", NO_DEAL)
    return await _extra_photo(s, d, extra_id, file_id)


async def vendor_extra_photo(
    s: AsyncSession, vendor: User, deal_id: uuid.UUID, extra_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    return await _extra_photo(s, await _vendor_deal(s, vendor, deal_id), extra_id, file_id)


async def _done_photo(s: AsyncSession, deal: Deal, file_id: uuid.UUID) -> Response:
    """'공사 끝냈어요' 사진은 그 공사의 고객 · 업체만 (architecture 7장). 다른 공사 사진은 404."""
    q = (
        select(File)
        .join(DealFile, DealFile.file_id == File.id)
        .where(DealFile.deal_id == deal.id, DealFile.file_id == file_id)
    )
    f = (await s.execute(q)).scalar_one_or_none()
    if f is None:
        raise AppError(404, "not_found", "사진을 찾을 수 없어요.")
    return await files_service.respond(f)


async def customer_done_photo(
    s: AsyncSession, user: User, project_id: uuid.UUID, deal_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    p = await project_service.get_for(s, user, project_id)
    d = await s.get(Deal, deal_id)
    if d is None or d.project_id != p.id:
        raise AppError(404, "not_found", NO_DEAL)
    return await _done_photo(s, d, file_id)


async def vendor_done_photo(
    s: AsyncSession, vendor: User, deal_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    return await _done_photo(s, await _vendor_deal(s, vendor, deal_id), file_id)


# ---- 공사 끝냈어요 · 고객 확인 · 남은 일: 연락처는 업체가 마지막으로 끝냈다고 올린 날부터 1년 ----

FINISHABLE = ("scheduled", "fixing")  # 공사 중 · 남은 일


async def _fixing_notes(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """남은 일: 공사마다 가장 최근에 고객이 적은 글"""
    if not deal_ids:
        return {}
    q = (
        select(DealEvent)
        .where(DealEvent.deal_id.in_(deal_ids), DealEvent.to_status == "fixing")
        .order_by(DealEvent.deal_id, DealEvent.at.desc())
    )
    out: dict[uuid.UUID, str] = {}
    for e in (await s.execute(q)).scalars():
        if e.note:
            out.setdefault(e.deal_id, e.note)
    return out


async def _done_files(
    s: AsyncSession, vendor: User, deal_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """'공사 끝냈어요' 사진: 내가 올린 done_photo만 · 다른 공사에 붙인 사진은 409 · 이 공사에 이미 붙은 것은
    건너뛴다 · 모두 합쳐 10장까지(422). 돌려주는 값: 새로 붙일 사진 (잠금 순서: 확정 → 사진)."""
    if len(set(ids)) != len(ids):
        raise _field("photo_file_ids", "같은 사진을 두 번 붙였어요.")
    files = await files_service.owned(s, vendor.id, ids, lock=True)
    if any(i not in files or files[i].kind != "done_photo" for i in ids):
        raise _field("photo_file_ids", "올린 공사 끝 사진을 다시 확인해 주세요.")
    q = select(DealFile.deal_id, DealFile.file_id).where(
        or_(DealFile.file_id.in_(ids), DealFile.deal_id == deal_id)
    )
    linked = (await s.execute(q)).all()
    if any(did != deal_id for did, _ in linked):
        raise app_error("already", "다른 공사에 붙인 사진이에요.")
    mine = {fid for _, fid in linked}
    new = [i for i in ids if i not in mine]
    if len(mine) + len(new) > DEAL_FILES_MAX:
        raise _field("photo_file_ids", f"공사 끝 사진은 {DEAL_FILES_MAX}장까지 붙일 수 있어요.")
    return new


async def finish(
    s: AsyncSession, vendor: User, deal_id: uuid.UUID, today: date, data: DoneIn | None = None
) -> JobOut:
    """업체 '공사 끝냈어요' · '남은 일 다 했어요' (한 트랜잭션, V13). 잠금 순서: 프로젝트 → 확정 → 사진.
    마지막 공사일부터. 확정 → checking, 끝낸 날(비우면 오늘) · 남길 말 · 사진(done_photo) · 올린 때,
    연락처 기한 = 오늘 + 1년(calc), 수락 기다리던 날짜 바꾸기는 닫는다. 기한 일: '3일 뒤 자동으로
    끝나요'(+4일) · 자동 끝(+7일, D24). 고객 알림."""
    data = data or DoneIn()
    d = await _vendor_deal(s, vendor, deal_id)
    # 응답(job_for)의 필요한 기간을 못 세는 공정이면 저장하기 전에 409
    _need(await project_service.get_out(s, d.project_id), d.trade, None)
    await project_service.lock(s, d.project_id)
    d = await _lock_deal(s, d.id)
    if d is None or d.vendor_id != vendor.id:
        raise AppError(404, "not_found", NO_DEAL)
    if d.status == "checking":
        raise AppError(409, "invalid_state", "이미 끝냈다고 올렸어요. 고객 확인을 기다려요.")
    if d.status == "done":
        auto = await _done_code(s, d.id) == "auto_done"
        raise AppError(409, "invalid_state", DONE_AUTO_VENDOR if auto else DONE_CHECKED_VENDOR)
    if d.status not in FINISHABLE:
        raise AppError(409, "invalid_state", "공사 날짜를 수락한 뒤에 올릴 수 있어요.")
    if d.end_date is None or today < d.end_date:
        raise AppError(409, "too_early", "마지막 공사일부터 누를 수 있어요.")
    done_on = data.done_on or today
    if done_on > today or (d.start_date is not None and done_on < d.start_date):
        raise _field("done_on", "끝낸 날은 공사 시작일부터 오늘까지 골라 주세요.")
    new_photos = await _done_files(s, vendor, d.id, data.photo_file_ids)
    again = d.status == "fixing"
    now = now_utc()
    values = {"status": "checking", "work_done_on": done_on, "done_posted_at": now}
    if data.note is not None:
        values["done_note"] = data.note
    await _set(s, Deal, d.id, d.status, values)
    ev = DealEvent(
        id=uuid7(),
        deal_id=d.id,
        from_status=d.status,
        to_status="checking",
        by_id=vendor.id,
        code="done_posted",
        at=now,
    )
    s.add(ev)
    start = len((await _done_photos(s, [d.id])).get(d.id, []))
    s.add_all([DealFile(deal_id=d.id, file_id=f, sort=start + n) for n, f in enumerate(new_photos)])
    await _close_dates(s, d.id, now)  # 끝낸 뒤에는 날짜를 바꾸지 않는다
    await jobs_service.cancel_refs(s, now=now, ref_ids=[d.id], kinds=DONE_JOBS)  # 앞서 올린 것
    for kind, run_at in (
        ("deal_done_remind", deadline.done_remind_at(now)),
        ("deal_auto_done", deadline.auto_done_at(now)),
    ):  # 올림(이력)마다 이름 하나: 남은 일 뒤 같은 분에 다시 올려도 취소된 앞 일과 겹치지 않는다
        await jobs_service.add(
            s, kind=kind, ref_id=d.id, run_at=run_at, dedup_key=f"{kind}:{ev.id}"
        )
    await visit_service.set_contact_until(s, d.visit_id, contact_until(today))
    owner = (await project_service.briefs(s, [d.project_id]))[d.project_id].owner_id
    who = i_ga(d.vendor_name)
    body = (
        f"{who} 남은 일을 다 했다고 알렸어요 · 확인해 주세요"
        if again
        else f"{who} 공사를 끝냈다고 알렸어요 · 확인해 주세요"
    )
    await notify_service.add(
        s,
        user_id=owner,
        kind="work_done",
        body=body,
        link=f"/projects/{d.project_id}/plan",
        dedup_key=f"deal_event:{ev.id}",  # 끝냄 · 확인은 여러 번 오갈 수 있어 이력마다
        project_id=d.project_id,
    )
    try:
        await s.commit()
    except IntegrityError as exc:  # 같은 사진을 두 공사에 동시에 붙임 (file UQ)
        await s.rollback()
        raise app_error("already", "다른 공사에 붙인 사진이에요.") from exc
    _push(s, [StatePush((owner, vendor.id), "deal", d.id, d.project_id)], [owner])
    return await job_for(s, vendor, deal_id, today)


# 끝난 공사 문구: 7일 자동 끝(deal_events code auto_done)과 고객 확인을 나눈다
DONE_AUTO_VENDOR = "고객 확인 없이 7일이 지나 자동으로 끝난 공사예요."
DONE_CHECKED_VENDOR = "고객이 확인해서 끝난 공사예요."
DONE_AUTO_CUSTOMER = "업체가 끝냈다고 올린 뒤 7일 동안 확인이 없어 자동으로 끝난 공사예요."
DONE_CHECKED_CUSTOMER = "이미 공사 끝을 확인한 공사예요."
FIXING_CUSTOMER = "남은 일을 업체에 알렸어요. 업체가 다 하고 다시 끝냈다고 올리면 확인할 수 있어요."


async def _done_code(s: AsyncSession, deal_id: uuid.UUID) -> str | None:
    """끝난 공사의 마지막 끝 이력 code(auto_done 자동 끝 · checked 고객 확인). 없으면 None."""
    return await s.scalar(
        select(DealEvent.code)
        .where(DealEvent.deal_id == deal_id, DealEvent.to_status == "done")
        .order_by(DealEvent.at.desc())
        .limit(1)
    )


async def _not_checking(s: AsyncSession, d: Deal) -> str:
    """고객이 공사 끝을 확인할 수 없는 까닭(지금 상태 그대로): 자동으로 끝남 · 확인해서 끝남 · 남은 일 하는 중 ·
    업체가 아직 안 올림."""
    if d.status == "done":
        auto = await _done_code(s, d.id) == "auto_done"
        return DONE_AUTO_CUSTOMER if auto else DONE_CHECKED_CUSTOMER
    if d.status == "fixing":
        return FIXING_CUSTOMER
    return "업체가 공사를 끝냈다고 올린 뒤에 확인할 수 있어요."


async def check_work(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    deal_id: uuid.UUID,
    data: CheckIn,
    today: date,
) -> DealOut:
    """고객이 공사 끝남 확인 (끝냈다고 올린 뒤에만): 끝났어요 → done, 남은 일이 있어요 → fixing(남은 일
    글은 이력 note). 잠금 순서: 프로젝트 → 확정. 업체 알림."""
    p = await project_service.get_for(s, user, project_id)
    if data.result == "fixing" and data.note is None:
        raise AppError(422, "note", "남은 일을 적어 주세요.")
    await project_service.lock(s, p.id)
    d = await _lock_deal(s, deal_id)
    if d is None or d.project_id != p.id:
        raise AppError(404, "not_found", NO_DEAL)
    if d.status != "checking":
        raise AppError(409, "invalid_state", await _not_checking(s, d))
    now = now_utc()
    await _set(s, Deal, d.id, "checking", {"status": data.result})
    ev = DealEvent(
        id=uuid7(),
        deal_id=d.id,
        from_status="checking",
        to_status=data.result,
        by_id=user.id,
        note=data.note if data.result == "fixing" else None,
        code="checked" if data.result == "done" else "fixing",
        at=now,
    )
    s.add(ev)
    # 고객이 답했으니 '자동으로 끝나요' 알림 · 자동 끝은 필요 없다 (남은 일 뒤 다시 올리면 새로 넣는다)
    await jobs_service.cancel_refs(s, now=now, ref_ids=[d.id], kinds=DONE_JOBS)
    if d.vendor_id is not None:
        await notify_service.add(
            s,
            user_id=d.vendor_id,
            kind="work_checked",
            body=_to_vendor(
                "고객이 공사 끝남을 확인했어요"
                if data.result == "done"
                else "고객이 남은 일이 있대요",
                p,
                d.trade,
            ),
            link=f"/vendor/jobs/{d.id}",
            dedup_key=f"deal_event:{ev.id}",  # 끝냄 · 확인은 여러 번 오갈 수 있어 이력마다
        )
    await s.commit()
    _push(s, [StatePush((user.id, d.vendor_id), "deal", d.id, p.id)], [d.vendor_id])
    d = await s.get(Deal, d.id, populate_existing=True)
    (out,) = await _deal_out(s, [d], today, now_utc())
    return out


async def _done_tab(
    s: AsyncSession,
    vendor: User,
    today: date,
    before: datetime | None,
    limit: int,
    now: datetime,
) -> InboxPageOut:
    """끝남 탭: 지난 요청(못 받음 · 기한 지남 · 취소 · 안 옴 · 닫힘, 할 일에 남긴 답 기한 지남 빼고) +
    끝난 공사(고객 확인 · 자동 끝), 끝난 때 최근 순으로 limit씩 (before 커서)."""
    last = (
        select(VisitEvent.visit_id, func.max(VisitEvent.at).label("at"))
        .group_by(VisitEvent.visit_id)
        .subquery()
    )
    vq = (
        select(Visit, last.c.at)
        .join(last, last.c.visit_id == Visit.id)
        .where(Visit.vendor_id == vendor.id, inbox.done_cond(now))
    )
    if before is not None:
        vq = vq.where(last.c.at < before)
    vpairs = list(
        (await s.execute(vq.order_by(last.c.at.desc(), Visit.id.desc()).limit(limit))).all()
    )
    at = (
        select(DealEvent.deal_id, func.max(DealEvent.at).label("at"))
        .where(DealEvent.to_status == "done")
        .group_by(DealEvent.deal_id)
        .subquery()
    )
    q = (
        select(Deal, at.c.at)
        .join(at, at.c.deal_id == Deal.id)
        .where(Deal.vendor_id == vendor.id, Deal.status == "done")
    )
    if before is not None:
        q = q.where(at.c.at < before)
    pairs = list((await s.execute(q.order_by(at.c.at.desc()).limit(limit))).all())
    fx = await inbox.facts(s, [v for v, _ in vpairs])
    deal_rows = await _deal_rows(s, [d for d, _ in pairs], today, now)
    items = [InboxRowOut(**inbox.row(fx[v.id], now, today)) for v, _ in vpairs] + [
        deal_rows[d.id].model_copy(update={"closed_at": done_at})
        for d, done_at in pairs
        if d.id in deal_rows
    ]
    items.sort(key=lambda r: r.closed_at, reverse=True)
    items = items[:limit]
    more = len(items) == limit
    return InboxPageOut(items=items, next_before=items[-1].closed_at if more else None)


# ---- 내 공사 한눈에 · 목록 · 서류: visit · quote · project 공개 함수로 모은다. 단계 판정은 calc ----

STEP_LABEL = {
    "house": "집 정보 · 공정",
    "standard": "기준 금액",
    "pick": "업체 고르기",
    "visit": "실측",
    "deal": "업체 확정",
    "dates": "공사 날짜",
}
WEEKDAY = "월화수목금토일"


def _md(d: date) -> str:
    return f"{d:%m.%d}({WEEKDAY[d.weekday()]})"


def _mdt(at: datetime) -> str:
    x = at.astimezone(SEOUL)
    return f"{_md(x.date())} {x:%H:%M}"


def _day(at: datetime | None) -> date | None:
    return at.astimezone(SEOUL).date() if at else None


def _todo_out(pid: uuid.UUID, code: str, trade: str, d: Deal | None, ctx: dict) -> TodoOut:
    """calc가 고른 할 일 코드 → 판 문구 · 버튼 · 화면"""
    label = LABEL[trade]
    who = i_ga(d.vendor_name) if d else ""
    base = f"/projects/{pid}"
    x, r, f = ctx.get("proposal"), ctx.get("request"), ctx["facts"]
    texts = {
        "check": (
            f"{who} {label} 공사를 끝냈다고 알렸어요 · 확인해 주세요",
            "확인하기",
            f"{base}/plan",
        ),
        "dates_received": (
            f"{who} {label} 공사 날짜를 냈어요 — {_md(x.start_date)} ~ {_md(x.end_date)}"
            if x
            else "",
            "날짜 확인하기",
            f"{base}/schedule?trade={trade}",
        ),
        "dates_change": (
            f"{who} {label} 날짜를 {_md(x.start_date)} ~ {_md(x.end_date)}으로 바꾸자고 했어요"
            if x
            else "",
            "확인하기",
            f"{base}/schedule?view=dates",
        ),
        "extra": (f"{who} 추가 금액을 알렸어요 · 확인해 주세요", "확인하기", f"{base}/plan"),
        "quotes_arrived": (
            f"실측 견적서 {f.quotes if f else 0}개가 왔어요 · {label}",
            "비교하기",
            f"{base}/quotes?trade={trade}",
        ),
        "quotes_partial": (
            f"{' · '.join(f.quoted_names)} 견적서가 왔어요 · "
            f"{' · '.join(f.waiting_names)} 견적서를 기다리는 중이에요"
            if f
            else "",
            "비교하기",
            f"{base}/quotes?trade={trade}",
        ),
        "dates_overdue": (
            f"{who} {_mdt(d.dates_due_at)}까지 공사 날짜를 내지 않았어요" if d else "",
            "확인하기",
            f"{base}/schedule?trade={trade}",
        ),
        "pick": (
            f"업체를 골라 실측을 요청하세요 · {label}",
            "업체 고르기",
            f"{base}/vendors?trade={trade}",
        ),
        "visit_requested": (
            f"업체와 실측 날짜를 맞추는 중이에요 · {label}",
            "실측 일정 보기",
            f"{base}/visits?trade={trade}",
        ),
        "before_work": (
            f"{label} 공사는 {_md(d.start_date)}에 시작해요 · 공사 전에 할 일을 확인하세요"
            if d and d.start_date
            else "",
            "공정표 보기",
            f"{base}/plan",
        ),
        "dates_waiting": (
            f"{who} 공사 날짜를 정하고 있어요 · {_mdt(d.dates_due_at)}까지" if d else "",
            "공사 날짜 보기",
            f"{base}/schedule?trade={trade}",
        ),
        "dates_requested": (
            f"다른 날짜를 요청했어요 · {d.vendor_name} 답을 기다려요 · {_mdt(r.due_at)}까지"
            if d and r
            else "",
            "공사 날짜 보기",
            f"{base}/schedule?trade={trade}",
        ),
        "working": (
            f"{label} 공사 중이에요 · {_md(d.end_date)}까지" if d and d.end_date else "",
            "공정표 보기",
            f"{base}/plan",
        ),
        "fixing": (f"{who} 남은 일을 하고 있어요 · {label}", "공정표 보기", f"{base}/plan"),
        "done": (
            f"공사가 끝났어요 · 하자가 보이면 {d.vendor_name}에 전화해요" if d else "",
            "연락처 보기",
            base,
        ),
    }
    text, action, link = texts[code]
    days = _todo_days(code, d, x, r)
    return TodoOut(code=code, trade=trade, text=text, action=action, link=link, days=days)


def _todo_days(code: str, d: Deal | None, x, r) -> list[date]:
    """할 일 아래에 보일 날 (C43 '1월 4일(월) · 5일(화)'): 업체가 낸 날 · 수락한 공사 날 · 고른 날"""
    if code in ("dates_received", "dates_change"):
        return list(x.days) if x is not None and x.days else []
    if code in ("before_work", "working"):
        return list(d.work_days or []) if d is not None else []
    if code == "dates_requested":
        return sorted(r.wish_dates) if r is not None else []
    return []


def _next(trade: str, d: Deal | None, r: DateRequest | None, x, today: date) -> NextOut | None:
    if d is None:
        return None
    if r is not None:
        return NextOut(kind="request_due", trade=trade, day=_day(r.due_at), at=r.due_at)
    if d.status == "confirmed" and x is None:
        return NextOut(kind="dates_due", trade=trade, day=_day(d.dates_due_at), at=d.dates_due_at)
    if d.status in ("scheduled", "fixing") and d.start_date and d.end_date:
        if today < d.start_date:
            return NextOut(kind="start", trade=trade, day=d.start_date, at=None)
        return NextOut(kind="end", trade=trade, day=d.end_date, at=None)
    return None


async def _accepted_on(s: AsyncSession, deal_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """처음 공사 날짜를 수락한 때"""
    if not deal_ids:
        return {}
    q = (
        select(DealEvent.deal_id, func.min(DealEvent.at))
        .where(DealEvent.deal_id.in_(deal_ids), DealEvent.to_status == "scheduled")
        .group_by(DealEvent.deal_id)
    )
    return {k: v for k, v in (await s.execute(q)).all()}


async def _progress_of(s: AsyncSession, p: ProjectOut, today: date, now: datetime):
    """공정마다 (calc 판정, 확정, 할 일 문맥). 목공 → 도배 순."""
    trades = [t for t in ORDER if getattr(p.trades, t) is not None]
    std = await quote_service.ensure_standard(s, p)
    facts = await visit_service.trade_facts(s, p.id)
    q = select(Deal).where(Deal.project_id == p.id, Deal.status != "reselected")
    deals = {
        d.trade: d for d in (await s.execute(q.execution_options(populate_existing=True))).scalars()
    }
    ids = [d.id for d in deals.values()]
    pend, reqs = await _pending(s, ids), await _open_requests(s, ids)
    waiting = await _extras_pending(s, ids)
    accepted = await _accepted_on(s, ids)
    out = []
    for t in trades:
        f, d = facts.get(t), deals.get(t)
        x = pend.get(d.id) if d else None
        r = reqs.get(d.id) if d else None
        tf = TradeFacts(
            trade=t,
            created_on=_day(p.created_at),
            standard_on=_day(std[t].created_at) if t in std else None,
            asked=f.asked if f else 0,
            asked_on=_day(f.asked_at) if f else None,
            quotes=f.quotes if f else 0,
            waiting=f.waiting if f else 0,
            quoted_on=_day(f.quoted_at) if f else None,
            deal_status=d.status if d else None,
            deal_on=_day(d.created_at) if d else None,
            dates_due_at=d.dates_due_at if d else None,
            proposed=x is not None,
            proposed_on=_day(x.created_at) if x else None,
            request_open=r is not None,
            accepted_on=_day(accepted.get(d.id)) if d else None,
            start=d.start_date if d else None,
            end=d.end_date if d else None,
            work_done_on=d.work_done_on if d else None,
            extras_pending=waiting.get(d.id, 0) if d else 0,
        )
        ctx = {"proposal": x, "request": r, "facts": f}
        out.append((progress(tf, today, now), d, ctx, f))
    return out, std, deals


def _trade_out(pid: uuid.UUID, pr, d: Deal | None, ctx: dict, today: date) -> TradeProgressOut:
    x = ctx["proposal"]
    return TradeProgressOut(
        trade=pr.trade,
        vendor_name=d.vendor_name if d else None,
        deal_id=d.id if d else None,
        deal_status=d.status if d else None,
        phase=pr.phase,
        current=pr.current,
        steps=[
            StepOut(key=st.key, label=STEP_LABEL[st.key], state=st.state, on=st.on, count=st.count)
            for st in pr.steps
        ],
        todo=_todo_out(pid, pr.todo, pr.trade, d, ctx),
        overdue=pr.overdue,
        start_date=d.start_date if d else None,
        end_date=d.end_date if d else None,
        proposed_start=x.start_date if x else None,
        proposed_end=x.end_date if x else None,
        next=_next(pr.trade, d, ctx["request"], x, today),
    )


def _soonest(items: list[NextOut | None]) -> NextOut | None:
    got = [n for n in items if n is not None]
    return min(got, key=lambda n: n.day) if got else None


async def overview_for(
    s: AsyncSession, user: User, project_id: uuid.UUID, today: date
) -> OverviewOut:
    """GET /projects/{id}/overview: 지금 할 일 · 공정별 단계 · 낼 금액 · 공사 기간 · 연락처 · 체크.
    공정표 기간은 값으로 먼저 꺼내요: 예상 공정표 · 표준견적서를 처음 만들 때 다른 요청과 겹치면 저장이 되돌려지고
    (rollback) 이 세션의 ORM 칸이 모두 만료돼서, 그 전에 읽은 행을 다시 읽으면 MissingGreenlet 500이었어요(화면 QA H2:
    가입 뒤 첫 보드). 표준견적서 · 확정은 공정표 뒤에 읽어 그 뒤에는 되돌리는 저장이 없어요."""
    p = await project_service.get_for(s, user, project_id)
    now = now_utc()
    final = await _latest(s, p.id, "final")
    period = await _period(s, final or await ensure_expected(s, p, today))
    rows, std, deals = await _progress_of(s, p, today, now)
    trades = [_trade_out(p.id, pr, d, ctx, today) for pr, d, ctx, _ in rows]
    top = first_todo([pr for pr, *_ in rows])
    quotes = await quote_service.briefs_by_id(s, [d.quote_id for d in deals.values()])
    by_trade = [
        TradeMoneyOut(trade=t.trade, total=quotes[deals[t.trade].quote_id].total, source="deal")
        if t.trade in deals
        else TradeMoneyOut(trade=t.trade, total=std[t.trade].total, source="standard")
        for t in trades
        if t.trade in deals or t.trade in std
    ]
    total = sum_won(m.total for m in by_trade)
    budget = None
    if p.budget:
        status, over = budget_gap(total, p.budget)
        budget = BudgetOut(band=p.budget, status=status, over_by=over)
    visits = await visit_service.visits_by_id(s, [d.visit_id for d in deals.values()])
    shown = {
        d.trade: d
        for d in deals.values()
        if d.vendor_id
        and d.visit_id in visits
        and visit_service.contact_visible(
            visits[d.visit_id].status, visits[d.visit_id].contact_until, today
        )
    }
    contacts = await vendor_service.contacts(s, [d.vendor_id for d in shown.values()])
    std_any = next(iter(std.values()), None)
    return OverviewOut(
        project_id=p.id,
        code=p.code,
        region=p.region,
        sgg=p.sgg,
        pyeong=std_any.pyeong if std_any else None,
        phase=project_phase([pr for pr, *_ in rows]),
        todo=next((t.todo for t in trades if top and t.trade == top.trade), None),
        next=_soonest([t.next for t in trades]),
        trades=trades,
        money=MoneySumOut(
            total=total,
            by_trade=by_trade,
            all_confirmed=bool(by_trade) and all(m.source == "deal" for m in by_trade),
            budget=budget,
        ),
        period=period,
        contacts=[
            VendorContactOut(
                trade=t,
                vendor_name=d.vendor_name,
                contact=contacts[d.vendor_id],
                contact_until=visits[d.visit_id].contact_until,
            )
            for t, d in sorted(shown.items(), key=lambda kv: ORDER.index(kv[0]))
            if d.vendor_id in contacts
        ],
        checks=await project_service.checks(s, p.id),
        after_steps=_after_steps(rows, top),
        vendors=await _vendor_steps(s, p.id, now, live_only=False),
    )


AFTER_LABEL = {
    "quote": "견적서 비교",
    "confirm": "업체 확정",
    "dates": "공사 날짜",
    "work": "공사",
    "check": "끝 확인",
}


def _after_steps(rows, top) -> list[AfterStepOut]:
    """실측 뒤 작은 단계 5칸 (C43): 견적서 비교 · 업체 확정 · 공사 날짜 · 공사 · 끝 확인.
    지금 할 일이 있는 공정(없으면 확정이 있는 공정, 그것도 없으면 첫 공정) 기준, '지금'은 하나."""
    if not rows:
        return []
    pick = next((r for r in rows if top is not None and r[0].trade == top.trade), None)
    pick = pick or next((r for r in rows if r[1] is not None), rows[0])
    _, d, _, f = pick
    if d is None:
        quoted = f is not None and f.quotes > 0
        state = {"quote": "now" if quoted else "todo"}
    else:
        st = d.status
        state = {
            "quote": "done",
            "confirm": "done",
            "dates": "done" if st in AFTER_DATES_ACCEPTED else "now",
            "work": "done" if st in ("checking", "done") else "now" if st in FINISHABLE else "todo",
            "check": "done" if st == "done" else "now" if st == "checking" else "todo",
        }
    return [
        AfterStepOut(key=k, label=label, state=state.get(k, "todo"))
        for k, label in AFTER_LABEL.items()
    ]


async def _vendor_steps(
    s: AsyncSession, project_id: uuid.UUID, now: datetime, *, live_only: bool
) -> list[VendorStepOut]:
    """업체별 요약 + 다음 할 일 · 기한 (C42 · C43). live_only면 살아 있는 요청만(내 공사 목록),
    아니면 다시 고르기로 닫힌 것을 빼고 업체마다 가장 최근 시도(한 공사 화면 '업체')."""
    q = select(Visit).where(Visit.project_id == project_id)
    visits = list((await s.execute(q.execution_options(populate_existing=True))).scalars())
    if live_only:
        visits = [v for v in visits if v.status in LIVE]
    else:
        latest: dict[tuple, Visit] = {}
        for v in visits:
            if v.status == "closed" and v.close_reason == "reselected":
                continue
            k = (v.trade, v.vendor_id)
            if k not in latest or v.attempt > latest[k].attempt:
                latest[k] = v
        visits = list(latest.values())
    visits.sort(key=lambda v: (ORDER.index(v.trade), v.created_at, v.slot))
    fx = await inbox.facts(s, visits)
    quotes = await quote_service.sent_briefs(s, [v.id for v in visits])
    return [
        VendorStepOut(
            visit_id=v.id,
            vendor_id=v.vendor_id,
            vendor_name=v.vendor_name,
            trade=v.trade,
            status=v.status,
            next=inbox.customer_next(fx[v.id], now),
            total=quotes[v.id].total if v.id in quotes else None,
        )
        for v in visits
    ]


async def _updated_at(s: AsyncSession, p: ProjectOut, deals: dict[str, Deal], facts) -> datetime:
    """바뀐 날: 만든 때 · 요청 상태 · 확정 이력 · 낸 날짜 · 추가 금액 중 가장 늦은 때"""
    ids = [d.id for d in deals.values()]
    times = [p.created_at] + [f.last_at for f in facts if f and f.last_at]
    if ids:
        for col, model in (
            (DealEvent.at, DealEvent),
            (DateProposal.created_at, DateProposal),
            (ExtraCharge.created_at, ExtraCharge),
        ):
            got = await s.scalar(select(func.max(col)).where(model.deal_id.in_(ids)))
            if got:
                times.append(got)
    return max(times)


async def my_projects(s: AsyncSession, user: User, today: date) -> list[MyProjectOut]:
    """GET /projects: 내 공사 목록 · 단계 요약 · 지금 할 일 · 다음 날짜 (바뀐 날 최근 순)"""
    if user.role != "customer":
        raise AppError(403, "forbidden", "고객만 볼 수 있어요.")
    now = now_utc()
    out = []
    for item in await project_service.list_mine(s, user):
        p = await project_service.get_for(s, user, item.id)
        rows, _, deals = await _progress_of(s, p, today, now)
        prs = [pr for pr, *_ in rows]
        top = first_todo(prs)
        todo = None
        if top is not None:
            pr, d, ctx, _ = next(r for r in rows if r[0].trade == top.trade)
            todo = _todo_out(p.id, pr.todo, pr.trade, d, ctx)
        nexts = [
            _next(pr.trade, d, ctx["request"], ctx["proposal"], today) for pr, d, ctx, _ in rows
        ]
        out.append(
            MyProjectOut(
                **item.model_dump(),
                phase=project_phase(prs),
                current=min((pr.current for pr in prs), default=1),
                todo=todo,
                next=_soonest(nexts),
                updated_at=await _updated_at(s, p, deals, [f for *_, f in rows]),
                grades={t: getattr(getattr(p.trades, t), "grade", None) for t in item.trades},
                emd=await s.scalar(select(Project.emd).where(Project.id == p.id)),
                vendors=await _vendor_steps(s, p.id, now, live_only=True),
            )
        )
    out.sort(key=lambda m: m.updated_at, reverse=True)
    return out


# ---- v3 기록 탭 · 캘린더 파일 (읽기만, schedule.history) ----


async def log_for(s: AsyncSession, user: User, project_id: uuid.UUID) -> list[LogItemOut]:
    """GET /projects/{id}/log (C63, I2): 이 집 실측 요청 · 견적서 · 공사 기록을 시간 순으로 (만든 사람 ·
    관리자). B5 도구도 이 함수를 읽는다(계약 5장)."""
    p = await project_service.get_for(s, user, project_id)
    owner = (await project_service.briefs(s, [p.id]))[p.id].owner_id
    visit_ids = list((await s.execute(select(Visit.id).where(Visit.project_id == p.id))).scalars())
    deal_ids = list((await s.execute(select(Deal.id).where(Deal.project_id == p.id))).scalars())
    return await history.items(s, owner_id=owner, visit_ids=visit_ids, deal_ids=deal_ids)


async def job_log(s: AsyncSession, vendor: User, deal_id: uuid.UUID) -> list[LogItemOut]:
    """GET /vendor/jobs/{did}/log (V23): 내 확정 한 건의 기록 (그 요청 · 확정만, 다른 업체 기록 없음)"""
    d = await _vendor_deal(s, vendor, deal_id)
    owner = (await project_service.briefs(s, [d.project_id]))[d.project_id].owner_id
    return await history.items(s, owner_id=owner, visit_ids=[d.visit_id], deal_ids=[d.id])


async def plan_ics(s: AsyncSession, user: User, project_id: uuid.UUID, today: date) -> str:
    """GET /projects/{id}/plan.ics (I1 · C36): 확정 공정표의 공사 날 (하루짜리 일정, 주소 · 연락처 없음).
    확정 공정표가 아직 없으면 404."""
    p = await project_service.get_for(s, user, project_id)
    if await _latest(s, p.id, "final") is None:
        raise AppError(404, "not_found", "확정 공정표가 아직 없어요. 공사 날짜를 수락하면 생겨요.")
    weekend = _weekend(await ensure_expected(s, p, today))
    q = select(Deal).where(
        Deal.project_id == p.id,
        Deal.status.in_(AFTER_DATES_ACCEPTED),
        Deal.start_date.is_not(None),
    )
    events = []
    for d in sorted((await s.execute(q)).scalars(), key=lambda d: ORDER.index(d.trade)):
        days = d.work_days or _range_workdays(d.start_date, d.end_date, weekend)
        events += [
            (f"{d.id}-{day:%Y%m%d}@mitjip", day, f"{LABEL[d.trade]} 공사 · {d.vendor_name}")
            for day in days
        ]
    return history.calendar("믿집 공정표", events, now_utc())


async def docs_for(s: AsyncSession, user: User, project_id: uuid.UUID, today: date) -> DocsOut:
    """GET /projects/{id}/docs: 표준견적서 · 예상 · 확정 공정표 버전, 받은 실측 견적서 버전(닫힌 것도
    기록으로), 확정한 버전, 추가 금액 기록. 각 줄에 여는 화면 · 파일 주소."""
    p = await project_service.get_for(s, user, project_id)
    latest_std = await quote_service.ensure_standard(s, p)
    await ensure_expected(s, p, today)
    base = f"/projects/{p.id}"
    stds = await quote_service.standard_versions(s, p.id)
    plans = list(
        (
            await s.execute(
                select(Plan).where(Plan.project_id == p.id).order_by(Plan.kind, Plan.version)
            )
        ).scalars()
    )
    top = {
        k: max((x.version for x in plans if x.kind == k), default=0) for k in ("expected", "final")
    }
    q = select(Deal).where(Deal.project_id == p.id)
    deals = list((await s.execute(q)).scalars())
    chosen = {d.quote_id for d in deals if d.status != "reselected"}
    quotes = []
    for v in await visit_service.quote_docs(s, p.id):
        quotes.append(
            QuoteDocOut(
                visit_id=v.visit_id,
                trade=v.trade,
                vendor_name=v.vendor_name,
                status=v.status,
                close_reason=v.close_reason,
                closed=v.status not in ("quoted", "chosen"),
                versions=[
                    QuoteVersionDocOut(
                        id=q.id,
                        code=q.code,
                        version=q.version,
                        sent_at=q.sent_at,
                        total=q.total,
                        confirmed=q.id in chosen,
                        files=q.files,
                        file_links=[f"/api{base}/quotes/{q.id}/files/{f.file_id}" for f in q.files],
                    )
                    for q in v.versions
                ],
            )
        )
    live = [d for d in deals if d.status != "reselected"]
    return DocsOut(
        project_id=p.id,
        code=p.code,
        region=p.region,
        standard=[
            StandardDocOut(
                trade=x.trade,
                version=x.version,
                total=x.total,
                computed_at=x.created_at,
                latest=latest_std.get(x.trade) is not None and latest_std[x.trade].id == x.id,
                link=f"{base}/standard?trade={x.trade}",
            )
            for x in stds
        ],
        standard_total=sum_won(x.total for x in latest_std.values()),
        plans=[
            PlanDocOut(
                kind=x.kind,
                version=x.version,
                start=x.start_date,
                end=x.end_date,
                created_at=x.created_at,
                latest=x.version == top[x.kind],
                link=f"{base}/plan?kind={x.kind}",
            )
            for x in plans
        ],
        quotes=quotes,
        extras=list((await _extras(s, live)).values()),
    )
