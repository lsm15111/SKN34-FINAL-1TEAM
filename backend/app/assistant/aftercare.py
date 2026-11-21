"""비서에게 더 맡기기(07-automation 4.1 · 4.3): 먼저 말 걸기 트리거 6개 · 승인 실행 · 화면에서 처리한 제안 닫기.

- 트리거(TRIGGERS, proactive.TRIGGERS에 등록 줄 하나로 더함). 고르는 건 코드이고 문장만 Haiku(검사에 걸리면 틀)다.
  · vendor_out(고객): 업체가 못 받음 · 48시간 무응답 · 업체 멈춤 · 견적서 늦음 → 다른 업체 추천 + 첫 업체 실측 요청 카드
  · extra_added(고객): 업체가 추가 금액을 올림 → 추가 금액 카드 + 승인 카드(extra_answer)
  · work_done(고객): 업체가 공사를 끝냈다고 올림 · 자동 끝 3일 전(done_remind는 알림 채널) → 점검표 + 끝 확인 카드
  · prep_week(고객, 시간): 공사 시작 7일 전 10시 → 공사 전 할 일 + 이웃 안내문 초안(승인 카드 없음)
  · dates_requested(업체): 고객이 다른 날짜 · 날짜 바꾸기를 요청 → 고객이 고른 시작일로 공사 날 후보 + 날짜 보내기 카드
  · quote_due(업체, 시간): 견적서 기한 24시간 전 · 견적서 없음 → 견적서 체크리스트
- 보낼 때 상태를 다시 본다(context): 상태가 바뀌었으면 None(그 줄은 닫힌다). 대상 id는 알림 dedup_key의 첫 id에서
  푼다(resolve: 공사 끝 이력 → 확정, 날짜 요청 → 확정).
- 이 모듈은 proactive · actions를 모듈 위에서 불러오지 않는다(그 둘이 이 모듈을 부른다).
"""

import re
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import repository as repo
from app.assistant.models import AssistantAction, AssistantNudge
from app.auth.models import User
from app.notify.models import Notification
from app.project.models import Project
from app.quote.models import VendorQuote
from app.schedule.models import DateRequest, Deal, DealEvent, ExtraCharge
from app.shared.clock import SEOUL
from app.shared.korean import i_ga
from app.visit.models import ATTEMPTS_MAX, LIVE, SLOTS, Visit

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TRADE_KO = {"dobae": "도배", "mokgong": "목공"}
PREP_DAYS = 7  # 공사 시작 7일 전에 공사 전 할 일을 챙긴다
PREP_SKIP = 3  # 시작이 3일 안이면 만들지 않는다(공사 전날 알림이 맡는다)
PREP_AT = time(10)  # 그날 10시(지났으면 지금)
QUOTE_BEFORE = timedelta(hours=24)  # 견적서 기한 24시간 전
AGAIN_FROM = (
    "expired",
    "cancelled",
)  # visit.service.AGAIN_FROM과 같다(한 번 더 요청할 수 있는 상태)

# proactive.Trigger(**값). 문장 틀은 {vendor} · {vendor_i_ga} · {trade} · {area} · {out}을 채운다(60자 안, '요'로 끝)
TRIGGERS: tuple[dict, ...] = (
    {
        "name": "vendor_out", "surface": "customer",
        "kinds": ("visit_declined", "visit_reply_expired", "visit_vendor_stopped", "quote_late"),
        "follow": timedelta(days=2), "action": True, "state": "visit",
        "say": "다른 업체 찾아 줘", "why": "요청한 업체가 이번 요청에서 빠졌어요",
        "feed": "{out} 맞는 업체를 더 골라 뒀어요.",
        "notify": "{vendor} 대신 맞는 업체를 골라 뒀어요. 추천을 확인해 주세요.",
    },
    {
        "name": "extra_added", "surface": "customer", "kinds": ("extra_added",),
        "follow": timedelta(days=1), "decision": True, "action": True, "state": "extra",
        "say": "추가 금액 보여 줘", "why": "업체가 추가 금액을 올렸어요",
        "feed": "{vendor_i_ga} 추가 금액을 올렸어요. 금액을 확인해 주세요.",
        "notify": "{vendor_i_ga} 올린 추가 금액이 아직 답을 기다려요.",
    },
    {
        "name": "work_done", "surface": "customer", "kinds": ("work_done", "done_remind"),
        "notify_kinds": ("done_remind",), "action": True, "state": "deal",
        "say": "공사 끝 점검표 보여 줘", "why": "업체가 공사를 끝냈다고 했어요",
        "feed": "{vendor_i_ga} 공사를 끝냈다고 했어요. 점검표로 확인해 주세요.",
        "notify": "{vendor} 공사가 곧 자동으로 끝나요. 점검표로 확인해 주세요.",
    },
    {
        "name": "prep_week", "surface": "customer", "channel": "notify", "state": "deal",
        "say": "공사 전에 할 일 알려 줘", "why": "공사가 일주일 남았어요",
        "notify": "{trade} 공사가 일주일 남았어요. 미리 할 일을 챙겨 볼까요?",
    },
    {
        "name": "dates_requested", "surface": "vendor", "kinds": ("dates_requested",),
        "follow": timedelta(days=1), "decision": True, "action": True, "state": "deal",
        "say": "공사 날짜 다시 볼래요", "why": "고객이 공사 날짜를 바꾸고 싶어 해요",
        "feed": "고객이 공사 날짜를 바꾸고 싶어 해요 · {area}. 새 날짜 후보를 골라 뒀어요.",
        "notify": "고객이 요청한 날짜에 아직 답하지 않았어요 · {area}. 후보를 확인해 주세요.",
    },
    {
        "name": "quote_due", "surface": "vendor", "channel": "notify", "state": "visit",
        "say": "견적서 체크리스트 보여 줘", "why": "견적서 기한이 하루 남았어요",
        "notify": "{area} 견적서 기한이 하루 남았어요. 빠진 항목을 같이 볼까요?",
    },
)  # fmt: skip
NAMES = frozenset(t["name"] for t in TRIGGERS)
RESOLVE = frozenset(
    {"work_done", "dates_requested"}
)  # 알림 dedup_key의 첫 id가 대상(확정)이 아닌 kind


# ---- 대상 · 지금 상태 ----


async def resolve(s: AsyncSession, kind: str, ref: uuid.UUID) -> uuid.UUID | None:
    """알림 dedup_key의 첫 id → 제안 대상 id. 공사 끝(deal_event:{이력}) · 날짜 요청(date_request:{요청})은 그 확정."""
    if kind == "work_done":
        return await s.scalar(select(DealEvent.deal_id).where(DealEvent.id == ref))
    if kind == "dates_requested":
        return await s.scalar(select(DateRequest.deal_id).where(DateRequest.id == ref))
    return ref


async def _source(s: AsyncSession, n: AssistantNudge) -> tuple[datetime | None, uuid.UUID | None]:
    """아웃박스 줄(ev:{알림 id}[:notify])의 근원 알림: (만든 때, 그 알림 dedup_key의 첫 id). 시간 줄이면 (None, None)."""
    m = UUID_RE.search(n.dedup_key) if n.dedup_key.startswith("ev:") else None
    if m is None:
        return None, None
    row = (
        await s.execute(
            select(Notification.created_at, Notification.dedup_key).where(
                Notification.id == uuid.UUID(m.group(0)), Notification.user_id == n.user_id
            )
        )
    ).first()
    if row is None:
        return None, None
    k = UUID_RE.search(row.dedup_key or "")
    return row.created_at, uuid.UUID(k.group(0)) if k else None


def _ctx(project_id, names: dict, due: datetime | None = None):
    from app.assistant.proactive import Ctx

    return Ctx(project_id=project_id, names=names, due=due)


async def _quote_sent(s: AsyncSession, visit_id: uuid.UUID) -> bool:
    return bool(
        await s.scalar(
            select(
                exists().where(VendorQuote.visit_id == visit_id, VendorQuote.sent_at.is_not(None))
            )
        )
    )


async def out_sentence(s: AsyncSession, v: Visit, now: datetime) -> str | None:
    """업체가 빠진 요청이면 까닭 문장(코드 글), 아니면 None. 못 받음 · 48시간 무응답 · 업체 멈춤 · 견적서 늦음."""
    who = i_ga(v.vendor_name)
    if v.status == "declined":
        return f"{who} 이번 요청을 받지 못해요."
    if v.status == "expired" and v.expired_reason == "reply":
        return f"{who} 48시간 안에 답하지 않았어요."
    if v.status == "closed" and v.close_reason == "vendor_stopped":
        return f"{who} 지금 믿집에서 일할 수 없어요."
    late = v.quote_due_at is not None and now > v.quote_due_at
    if v.status in ("booked", "visited") and late and not await _quote_sent(s, v.id):
        return f"{who} 실측 견적서를 아직 보내지 않았어요."
    return None


async def out_room(s: AsyncSession, v: Visit, since: datetime | None) -> bool:
    """다른 업체를 이을 자리: 같은 공정에 확정이 없고, 살아 있는 요청이 칸(3)보다 적고, 업체가 빠진 뒤 새로 만든
    요청이 없을 때만(이미 다른 업체 · 같은 업체에 다시 요청했으면 할 일이 끝났다)."""
    deal = exists().where(
        Deal.project_id == v.project_id, Deal.trade == v.trade, Deal.status != "reselected"
    )
    if await s.scalar(select(deal)):
        return False
    live = await s.scalar(
        select(func.count())
        .select_from(Visit)
        .where(Visit.project_id == v.project_id, Visit.trade == v.trade, Visit.status.in_(LIVE))
    )
    if (live or 0) >= SLOTS:
        return False
    if since is None:
        return True
    newer = exists().where(
        Visit.project_id == v.project_id,
        Visit.trade == v.trade,
        Visit.id != v.id,
        Visit.created_at > since,
    )
    return not await s.scalar(select(newer))


async def asked_vendors(s: AsyncSession, project_id: uuid.UUID, trade: str) -> frozenset:
    """이 공사 · 공정에 한 번이라도 요청한 업체(추천에서 뺀다: 이미 요청 · 확정했거나 빠진 업체)."""
    rows = await s.scalars(
        select(Visit.vendor_id).where(
            Visit.project_id == project_id, Visit.trade == trade, Visit.vendor_id.is_not(None)
        )
    )
    return frozenset(rows.all())


async def _out_ctx(s: AsyncSession, n: AssistantNudge, now: datetime):
    from app.assistant.runtime import RefTable
    from app.assistant.tools import cards

    v = await s.get(Visit, n.ref_id, populate_existing=True)
    if v is None:
        return None
    p = await s.get(Project, v.project_id)
    if p is None or p.owner_id != n.user_id:
        return None
    out = await out_sentence(s, v, now)
    since, _ = await _source(s, n)
    if out is None or not await out_room(s, v, since or n.created_at):
        return None
    user = await s.get(User, n.user_id)
    if user is None:
        return None
    _card, model = await cards.vendor_picks(
        s,
        user,
        p.id,
        v.trade,
        RefTable(uuid.uuid4()),
        exclude=await asked_vendors(s, p.id, v.trade),
    )
    if not model["picks"]:  # 이을 업체가 없으면 '골라 뒀어요'라고 말하지 않는다
        return None
    names = {
        "vendor": v.vendor_name,
        "trade": TRADE_KO.get(v.trade, v.trade),
        "trade_code": v.trade,
        "area": p.sgg,
        "out": out,
    }
    return _ctx(p.id, names)


async def _owned_deal(s: AsyncSession, deal_id: uuid.UUID, user_id: uuid.UUID, vendor: bool):
    d = await s.get(Deal, deal_id, populate_existing=True)
    if d is None:
        return None, None
    p = await s.get(Project, d.project_id)
    if p is None or (d.vendor_id if vendor else p.owner_id) != user_id:
        return None, None
    return d, p


def _deal_names(d: Deal, p: Project, vendor: bool) -> dict:
    from app.notify.catalog import work_name

    return {
        "vendor": d.vendor_name,
        "trade": TRADE_KO.get(d.trade, d.trade),
        "trade_code": d.trade,
        "area": work_name(p.sgg, p.emd, d.trade) if vendor else p.sgg,
    }


async def _extra_ctx(s: AsyncSession, n: AssistantNudge):
    """추가 금액이 아직 답 기다림(최신 판 · pending)이고 다시 고른 공사가 아닐 때만."""
    x = await s.get(ExtraCharge, n.ref_id, populate_existing=True)
    if x is None or x.superseded_at is not None or x.ack != "pending":
        return None
    d, p = await _owned_deal(s, x.deal_id, n.user_id, vendor=False)
    if d is None or d.status == "reselected":
        return None
    return _ctx(p.id, _deal_names(d, p, vendor=False))


async def _done_ctx(s: AsyncSession, n: AssistantNudge):
    """확정이 아직 고객 확인 기다림(checking)일 때만. 기한은 자동 끝(올린 때 + 7일, 계산 엔진)."""
    from app.calc import deadline

    d, p = await _owned_deal(s, n.ref_id, n.user_id, vendor=False)
    if d is None or d.status != "checking" or d.done_posted_at is None:
        return None
    return _ctx(p.id, _deal_names(d, p, vendor=False), deadline.auto_done_at(d.done_posted_at))


def _key_day(dedup_key: str) -> date | None:
    """'prep_week:{확정 id}:{시작일}[:…]'의 시작일."""
    parts = dedup_key.split(":")
    try:
        return date.fromisoformat(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return None


async def _prep_ctx(s: AsyncSession, n: AssistantNudge, today: date):
    """확정이 그대로(scheduled)이고 시작일이 줄을 만든 때와 같고 아직 시작 전일 때만. 기한은 공사 시작일."""
    d, p = await _owned_deal(s, n.ref_id, n.user_id, vendor=False)
    start = _key_day(n.dedup_key)
    if d is None or d.status != "scheduled" or d.start_date is None or d.start_date != start:
        return None
    if d.start_date <= today:
        return None
    due = datetime.combine(d.start_date, time(0), SEOUL)
    return _ctx(p.id, _deal_names(d, p, vendor=False), due)


async def _request_ctx(s: AsyncSession, n: AssistantNudge):
    """업체 쪽: 그 날짜 요청(근원 알림의 요청)이 아직 열려 있을 때만. 기한은 요청 + 48시간(계산 엔진)."""
    d, p = await _owned_deal(s, n.ref_id, n.user_id, vendor=True)
    if d is None or d.status not in ("confirmed", "scheduled"):
        return None
    _, req_id = await _source(s, n)
    q = select(DateRequest).where(DateRequest.deal_id == d.id, DateRequest.status == "open")
    if req_id is not None:
        q = q.where(DateRequest.id == req_id)
    r = (await s.execute(q.execution_options(populate_existing=True))).scalars().first()
    if r is None:
        return None
    return _ctx(None, _deal_names(d, p, vendor=True), r.due_at)


async def _quote_ctx(s: AsyncSession, n: AssistantNudge):
    """업체 쪽: 실측 뒤(booked · visited) 견적서를 아직 안 냈고 기한이 줄을 만든 때와 같을 때만."""
    from app.notify.catalog import work_name

    v = await s.get(Visit, n.ref_id, populate_existing=True)
    if v is None or v.vendor_id != n.user_id or v.status not in ("booked", "visited"):
        return None
    due, parts = v.quote_due_at, n.dedup_key.split(":")  # 'quote_due:{요청 id}:{기한 날}'
    if due is None or len(parts) < 3 or parts[2] != f"{due.astimezone(SEOUL):%Y%m%d}":
        return None
    if await _quote_sent(s, v.id):
        return None
    p = await s.get(Project, v.project_id)
    if p is None:
        return None
    names = {
        "trade": TRADE_KO.get(v.trade, v.trade),
        "trade_code": v.trade,
        "area": work_name(p.sgg, p.emd, v.trade),
    }
    return _ctx(None, names, due)


async def context(s: AsyncSession, t, n: AssistantNudge, now: datetime):
    """07 트리거의 지금 상태(proactive.context가 부른다). 상태가 바뀌었거나 남의 것이면 None."""
    today = now.astimezone(SEOUL).date()
    if t.name == "vendor_out":
        return await _out_ctx(s, n, now)
    if t.name == "extra_added":
        return await _extra_ctx(s, n)
    if t.name == "work_done":
        return await _done_ctx(s, n)
    if t.name == "prep_week":
        return await _prep_ctx(s, n, today)
    if t.name == "dates_requested":
        return await _request_ctx(s, n)
    return await _quote_ctx(s, n)


# ---- 무료 모드가 찾는 대상 ----


async def out_visit(s: AsyncSession, project_id: uuid.UUID, now: datetime) -> Visit | None:
    """업체가 빠졌는데 아직 다른 업체를 잇지 않은 요청(가장 새것). 없으면 None."""
    rows = await s.scalars(
        select(Visit)
        .where(Visit.project_id == project_id)
        .order_by(Visit.created_at.desc())
        .limit(20)
        .execution_options(populate_existing=True)
    )
    for v in rows.all():
        if await out_sentence(s, v, now) is not None and await out_room(s, v, v.created_at):
            # 업체가 빠진 뒤 새 요청이 있는지는 이 요청보다 뒤에 만든 요청으로 본다(무료 모드는 근원 알림이 없다)
            return v
    return None


async def again_visit(s: AsyncSession, project_id: uuid.UUID) -> Visit | None:
    """한 번 더 요청할 수 있는 요청(답 없음 · 고르기 기한 지남 · 취소, 같은 업체 두 번째 전, 가장 새것)."""
    later = Visit.__table__.alias("later")
    rows = await s.scalars(
        select(Visit)
        .where(
            Visit.project_id == project_id,
            Visit.status.in_(AGAIN_FROM),
            Visit.attempt < ATTEMPTS_MAX,
            Visit.vendor_id.is_not(None),
            ~exists().where(
                later.c.project_id == Visit.project_id,
                later.c.trade == Visit.trade,
                later.c.vendor_id == Visit.vendor_id,
                later.c.attempt > Visit.attempt,
            ),
        )
        .order_by(Visit.created_at.desc())
        .limit(1)
    )
    return rows.first()


# ---- 시간 트리거 ----


async def scan_time(s: AsyncSession, now: datetime) -> int:
    """매시간(proactive.scan_time 안, 같은 세션): 공사 1주 전 · 견적서 기한 하루 전 제안을 만든다. 만든 줄 수."""
    today = now.astimezone(SEOUL).date()
    made = 0
    rows = (
        await s.execute(
            select(Deal.id, Deal.project_id, Deal.start_date, Project.owner_id)
            .join(Project, Project.id == Deal.project_id)
            .where(
                Deal.status == "scheduled",
                Deal.start_date > today + timedelta(days=PREP_SKIP),
                Deal.start_date <= today + timedelta(days=PREP_DAYS),
            )
        )
    ).all()
    for did, pid, start, owner in rows:
        at = datetime.combine(start - timedelta(days=PREP_DAYS), PREP_AT, SEOUL)
        made += await repo.insert_nudge(
            s,
            user_id=owner,
            surface="customer",
            project_id=pid,
            trigger="prep_week",
            ref_id=did,
            dedup_key=f"prep_week:{did}:{start.isoformat()}",
            channel="notify",
            due_at=max(now, at),
        )
    sent = exists().where(VendorQuote.visit_id == Visit.id, VendorQuote.sent_at.is_not(None))
    rows = (
        await s.execute(
            select(Visit.id, Visit.vendor_id, Visit.quote_due_at).where(
                Visit.status.in_(("booked", "visited")),
                Visit.vendor_id.is_not(None),
                Visit.quote_due_at > now,
                Visit.quote_due_at <= now + QUOTE_BEFORE,
                ~sent,
            )
        )
    ).all()
    for vid, vendor_id, due in rows:
        made += await repo.insert_nudge(
            s,
            user_id=vendor_id,
            surface="vendor",
            project_id=None,
            trigger="quote_due",
            ref_id=vid,
            dedup_key=f"quote_due:{vid}:{due.astimezone(SEOUL):%Y%m%d}",
            channel="notify",
            due_at=now,
        )
    return made


# ---- 보낼 때 카드 · 승인 카드 ----


async def build(s: AsyncSession, t, n: AssistantNudge, user: User, c, now: datetime, refs):
    """07 트리거의 카드(CardOut JSON, 둘이면 목록) · 승인 카드(origin nudge, 같은 트랜잭션). (카드, 행동 id).
    이름표는 그 사람 비서 대화의 표(refs)에 넣는다. 카드 · 승인 카드를 못 만들면 그 몫만 비운다."""
    from app.assistant import actions
    from app.assistant.tools import ToolError
    from app.assistant.tools import aftercare as tools
    from app.assistant.tools import vendor as vendor_tools
    from app.schedule import service as schedule_service

    today = now.astimezone(SEOUL).date()
    pid = n.project_id
    shown = []
    offer = None
    try:
        if t.name == "vendor_out":
            card, picks, v = await tools.out_card(s, user, pid, n.ref_id, refs)
            if picks:
                shown = [card]
                offer = await tools.out_offer(s, user, pid, v, card, today, now)
        elif t.name == "extra_added":
            tx = await tools.extra_of(s, user, pid, n.ref_id, today)
            shown = [tools.extra_card(*tx, pid, refs)[0]]
            offer = tools.extra_offer(*tx, "approve", now)
        elif t.name == "work_done":
            d = await tools.deal_of(s, user, pid, n.ref_id, today)
            shown = [tools.done_card(d, pid, refs)]
            offer = tools.work_check_offer(d, "done", None, now)
        elif t.name == "prep_week":
            shown = [
                await tools.prep_card(s, user, pid, today),
                (await tools.notice(s, user, pid, today))[0],
            ]
        elif (
            t.name == "dates_requested"
        ):  # 카드 없이 첫 후보로 날짜 보내기 승인 카드(업체 확정 줄과 같음)
            job = await schedule_service.job_for(s, user, n.ref_id, today)
            cands = tools.request_candidates(job, n.ref_id, today)
            if cands:
                offer = tools.request_dates_offer(job, n.ref_id, cands[0], now)
        elif t.name == "quote_due":
            card, *_ = await vendor_tools.checklist(s, user, n.ref_id, today, refs)
            shown = [card]
    except ToolError:
        offer = None
    action_id = None
    if offer is not None:
        row, _ = await actions.propose(
            s,
            user,
            surface=n.surface,
            now=now,
            turn_id=None,
            origin="nudge",
            project_id=pid,
            **offer,
        )
        action_id = row.id if row.status == "proposed" else None
    dumped = [x.model_dump(mode="json") for x in shown]
    return (dumped[0] if len(dumped) == 1 else dumped or None), action_id


def link(name: str, ref_id: uuid.UUID) -> str | None:
    """업체 알림 링크: 날짜 요청은 공사 화면, 견적서 기한은 견적서 화면. 그 밖은 None(proactive 기본)."""
    if name == "dates_requested":
        return f"/vendor/jobs/{ref_id}"
    if name == "quote_due":
        return f"/vendor/requests/{ref_id}/quote"
    return None


# ---- 승인 뒤 실행(actions.EXECUTORS에 더함). mark()는 기능 함수가 commit하기 바로 앞에서 ----

EXTRA_DONE = {
    "approve": "추가 금액을 승인했어요",
    "reject": "추가 금액을 거절했어요",
    "ask": "추가 금액을 채팅으로 물어봤어요",
}


async def extra_answer(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark):
    from app.schedule import service as schedule_service
    from app.schedule.schemas import AnswerIn

    pl = a.payload
    href = f"/projects/{a.project_id}/plan"
    await mark({"text": EXTRA_DONE[pl["answer"]], "href": href, "label": "공사 보기"})
    await schedule_service.answer_extra(
        s,
        user,
        a.project_id,  # type: ignore[arg-type]
        uuid.UUID(pl["deal_id"]),
        uuid.UUID(pl["extra_id"]),
        AnswerIn(answer=pl["answer"]),
    )


async def work_check(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark):
    from app.schedule import service as schedule_service
    from app.schedule.schemas import CheckIn

    pl = a.payload
    done = pl["result"] == "done"
    if done:
        got = {"text": "공사 끝을 확인했어요", "href": f"/projects/{a.project_id}/review"}
        got["label"] = "리뷰 쓰기"
    else:
        got = {"text": "남은 일을 업체에 알렸어요", "href": f"/projects/{a.project_id}/plan"}
        got["label"] = "공사 보기"
    await mark(got)
    await schedule_service.check_work(
        s,
        user,
        a.project_id,  # type: ignore[arg-type]
        uuid.UUID(pl["deal_id"]),
        CheckIn(result=pl["result"], note=None if done else pl.get("note")),
        now.astimezone(SEOUL).date(),
    )


async def visit_again(s: AsyncSession, user: User, a: AssistantAction, now: datetime, mark):
    from app.visit import flow

    pl = a.payload
    text = f"{pl.get('vendor_name') or '업체'}에 한 번 더 요청했어요"
    await mark(
        {"text": text, "href": f"/projects/{a.project_id}/visits", "label": "실측 일정 보기"}
    )
    await flow.again(s, user, a.project_id, uuid.UUID(pl["visit_id"]), now)  # type: ignore[arg-type]


EXECUTORS = {"extra_answer": extra_answer, "work_check": work_check, "visit_again": visit_again}


# ---- 화면에서 직접 처리한 제안 닫기(actions.close_handled가 부른다) ----


async def moved_ids(s: AsyncSession, rows: list[AssistantAction]) -> list[uuid.UUID]:
    """07 행동 중 대상 상태가 만든 때(target_ver)와 달라진 열린 제안 id. 추가 금액: 답 · 새 판, 공사 끝 확인: 확정이
    checking이 아님, 한 번 더 요청: 요청 상태가 바뀌었거나 같은 업체에 다음 요청이 생김."""
    mine = [a for a in rows if a.kind in EXECUTORS]
    if not mine:
        return []
    want = {k: [a.target_id for a in mine if a.kind == k] for k in EXECUTORS}
    xs: dict = {}
    if want["extra_answer"]:
        q = select(
            ExtraCharge.id, ExtraCharge.ack, ExtraCharge.version, ExtraCharge.superseded_at
        ).where(ExtraCharge.id.in_(want["extra_answer"]))
        xs = {i: (ack, ver, gone) for i, ack, ver, gone in await s.execute(q)}
    ds: dict = {}
    if want["work_check"]:
        q = select(Deal.id, Deal.status).where(Deal.id.in_(want["work_check"]))
        ds = {i: st for i, st in await s.execute(q)}
    vs: dict = {}
    if want["visit_again"]:
        later = Visit.__table__.alias("later")
        newer = exists().where(
            later.c.project_id == Visit.project_id,
            later.c.trade == Visit.trade,
            later.c.vendor_id == Visit.vendor_id,
            later.c.attempt > Visit.attempt,
        )
        q = select(Visit.id, Visit.status, newer).where(Visit.id.in_(want["visit_again"]))
        vs = {i: (st, nw) for i, st, nw in await s.execute(q)}
    gone: list[uuid.UUID] = []
    for a in mine:
        if a.kind == "extra_answer":
            x = xs.get(a.target_id)
            ok = x is not None and x[2] is None and f"{x[0]}:{x[1]}" == a.target_ver
        elif a.kind == "work_check":
            ok = ds.get(a.target_id) == "checking"
        else:
            v = vs.get(a.target_id)
            ok = v is not None and v[0] == a.target_ver and not v[1]
        if not ok:
            gone.append(a.id)
    return gone
