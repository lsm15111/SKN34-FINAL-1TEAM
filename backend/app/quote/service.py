"""가견적 받기 흐름: 후보 업체와 받는 길, 앱 안 가견적 요청, 외부 업체 대신 연락.

다른 기능은 그 service의 공개 함수로만 부른다: project(프로젝트) · vendor(앱 업체) · directory(외부 업체).
"""

import hashlib
import json
import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.agent import sourcing as sourcing_agent
from app.agent.llm import LlmError
from app.auth.models import User
from app.config import settings
from app.directory import service as directory_service
from app.directory.address import phone_label
from app.directory.industry import TRADE_LABEL
from app.directory.service import SOURCE_LABEL, ExtCard
from app.project import service as project_service
from app.project.schemas import ProjectOut
from app.quote import outbox
from app.quote import repository as repo
from app.quote.models import ContactRequest, ContactRequestEvent, QuoteRequest, QuoteRequestEvent
from app.quote.schemas import (
    CandidateOut,
    ContactRequestIn,
    ContactRequestOut,
    CostOut,
    InboxItemOut,
    LinksOut,
    QuoteRequestIn,
    QuoteRequestOut,
    RequestStateOut,
    SentRequestOut,
    SourceOut,
    SourcingOut,
)
from app.quote.sender import Outgoing, Sender, SendError
from app.quote.sourcing import (
    ROUTE_LABEL,
    Facts,
    call_checklist,
    choose,
    cost_label,
    project_trades,
    request_facts,
)
from app.shared.clock import now_utc
from app.shared.errors import AppError
from app.shared.regions import SIDO, region_label
from app.vendor import service as vendor_service
from app.vendor.schemas import VendorCard

log = logging.getLogger(__name__)

MAX_EXT = 12  # 외부 업체 후보 최대 수
NO_CANDIDATES = "이 지역 · 공정에 맞는 업체를 아직 찾지 못했어요."
NOTES_FAILED = "설명을 만들지 못했어요. 업체 목록과 받는 길만 보여 드려요."
NOTES_TTL_S = 86400
QUOTE_LABEL = {"requested": "요청했어요", "viewed": "업체가 확인했어요"}
# 상태 전이: 바뀔 상태 → 바꿀 수 있는 지금 상태 (하나뿐이라 이력의 이전 상태가 정해진다)
QUOTE_MOVES: dict[str, tuple[str]] = {"viewed": ("requested",)}
CONTACT_MOVES: dict[str, tuple[str]] = {
    "queued": ("draft",),
    "sending": ("queued",),  # 보내기 전에 선점
    "sent": ("sending",),
    "test_sent": ("sending",),
    "failed": ("sending",),
    "blocked": ("queued",),
}
DRY_RUN_LABEL = "시험으로 기록만 했어요 (실제로 보내지 않았어요)"
STUCK_LABEL = "보냈는지 확인이 필요해요"
CONTACT_LABEL = {
    "draft": "작성 중이에요",
    "queued": "보내기 전이에요",
    "sending": "보내는 중이에요",
    "sent": "보냈어요",
    "test_sent": DRY_RUN_LABEL,
    "failed": "보내지 못했어요",
    "blocked": "보낼 수 없는 업체예요",
}
STUCK_AFTER = timedelta(minutes=15)  # sending에 이보다 오래 있으면 보냈는지 모르는 것으로 본다
OFF_NOTICE = "대신 요청은 아직 꺼져 있어요. 요청은 저장해 두었고, 켜지면 보내요."
NIGHT_NOTICE = "밤 9시부터 아침 8시까지는 보내지 않아요. 아침에 보내요."
QUEUED_NOTICE = "곧 보내요."
BIZ_LABEL = {
    "active": "계속 사업 중 (국세청 확인)",
    "suspended": "휴업 중 (국세청 확인)",
    "closed": "폐업 (국세청 확인)",
    "unknown": "국세청에서 확인되지 않아요",
}


def _region(sido: str | None, sgg: str | None) -> str:
    if sido and sgg:
        return region_label(sido, sgg)
    return SIDO[sido][0] if sido in SIDO else "지역 정보 없음"


def _registration(e: ExtCard) -> str | None:
    if e.reg_kind == "construction" and e.industries:
        return " · ".join(e.industries) + " 등록 (건설업)"
    if e.reg_kind == "business":
        return "사업자등록 확인"
    return f"업종: {e.industries[0]}" if e.industries else None


def _app_card(v: VendorCard, p: ProjectOut, states: list[RequestStateOut]) -> CandidateOut:
    c = choose(Facts(is_app=True), proxy_enabled=settings.contact_send_enabled)
    return CandidateOut(
        id=v.user_id,
        kind="app",
        name=v.name,
        trades=v.trades,
        region=p.region,
        near=True,
        route=c.route,
        route_label=ROUTE_LABEL[c.route],
        cost=CostOut(kind=c.cost, amount=c.fee, label=cost_label(c)),
        source=SourceOut(kind="app", label="믿집 승인 업체", fetched_at=v.approved_at),
        links=LinksOut(homepage=v.site_url, portfolio=v.portfolio_urls),
        registration="사업자등록증 확인 (믿집 관리자 승인)",
        biz_status=None,
        phone=None,
        proxy_off=False,
        checklist=[],
        requests=states,
    )


def _ext_card(e: ExtCard, p: ProjectOut, states: list[RequestStateOut]) -> CandidateOut:
    facts = Facts(
        is_app=False,
        has_consented_contact=bool(e.channels),
        opted_out=e.opted_out,
        quote_url=e.quote_url,
        phone=e.phone,
        visit_fee=e.visit_fee,
    )
    c = choose(facts, proxy_enabled=settings.contact_send_enabled)
    return CandidateOut(
        id=e.id,
        kind="ext",
        name=e.name,
        trades=e.trades,
        region=_region(e.sido, e.sgg),
        near=e.sgg == p.sgg,
        route=c.route,
        route_label=ROUTE_LABEL[c.route],
        cost=CostOut(kind=c.cost, amount=c.fee, label=cost_label(c)),
        source=SourceOut(kind=e.source, label=SOURCE_LABEL[e.source], fetched_at=e.fetched_at),
        links=LinksOut(
            homepage=e.homepage, portfolio=e.portfolio_urls, quote=e.quote_url, place=e.place_url
        ),
        registration=_registration(e),
        biz_status=BIZ_LABEL.get(e.biz_status or ""),
        phone=phone_label(e.phone) if e.phone else None,
        proxy_off=c.proxy_off,
        checklist=call_checklist(e.trades) if c.route == "phone" else [],
        requests=states,
    )


async def sourcing(s: AsyncSession, user: User, project_id: uuid.UUID) -> SourcingOut:
    """프로젝트 공정 · 지역에 맞는 앱 업체와 외부 업체, 업체마다 받는 길 · 비용 · 출처."""
    p = await project_service.get_for(s, user, project_id)  # 남의 프로젝트는 404
    trades = project_trades(p)
    app = await vendor_service.candidates(s, trades, p.sido, p.sgg)
    ext = await directory_service.candidates(s, trades, p.sido, p.sgg, limit=MAX_EXT)
    states = await _states(s, p.id)
    await s.close()  # LLM을 기다리는 동안 DB 연결을 붙잡지 않는다
    cards = [_app_card(v, p, states[v.user_id]) for v in app]
    cards += [_ext_card(e, p, states[e.id]) for e in ext]
    facts = request_facts(p)
    notice = NO_CANDIDATES if not cards else await _explain(facts, cards)
    return SourcingOut(
        project_id=p.id,
        region=p.region,
        trades=trades,
        facts=facts,
        candidates=cards,
        proxy_enabled=settings.contact_send_enabled,
        notice=notice,
        prompt_version=sourcing_agent.PROMPT_VERSION if cards and notice is None else None,
    )


def _basis(c: CandidateOut) -> str:
    """LLM에 줄 근거 (코드가 가진 사실만)"""
    parts = [c.registration] if c.registration else []
    parts += ["같은 시 · 군 · 구"] if c.near else []
    parts += ["견적 창구 있음"] if c.links.quote else []
    parts += ["포트폴리오 링크 있음"] if c.links.portfolio else []
    return ", ".join(parts) or "등록 정보 없음"


async def _explain(facts: list[str], cards: list[CandidateOut]) -> str | None:
    """후보마다 이유 한 줄, 받는 길마다 요청문 초안을 붙인다. 실패하면 설명 없이 알림만."""
    head = cards[: sourcing_agent.MAX_NOTES]
    cands = [
        sourcing_agent.Candidate(
            key=k,
            name=c.name,
            kind="앱" if c.kind == "app" else "외부",
            trades=" · ".join(TRADE_LABEL[t] for t in c.trades),
            region=c.region,
            route=c.route,
            cost=c.cost.label,
            basis=_basis(c),
        )
        for k, c in zip(sourcing_agent.keys(len(head)), head, strict=True)
    ]
    routes = [r for r in sourcing_agent.DRAFT_ROUTES if any(c.route == r for c in head)]
    key = (
        "sourcing:"
        + hashlib.sha256(
            (sourcing_agent.PROMPT_VERSION + sourcing_agent.render(facts, cands, routes)).encode()
        ).hexdigest()
    )
    notes = await _cached(key)
    if notes is None:
        try:
            notes, _ = await sourcing_agent.explain(facts, cands, routes)
        except LlmError:
            return NOTES_FAILED
        await _cache(key, notes)
    for c, cand in zip(head, cands, strict=True):
        c.why = notes.why.get(cand.key)
    for c in cards:
        c.draft = notes.drafts.get(c.route)
    return None


async def _cached(key: str) -> sourcing_agent.Notes | None:
    try:
        raw = await queue.redis.get(key)
    except RedisError:
        return None
    if not raw:
        return None
    data = json.loads(raw)
    return sourcing_agent.Notes(why=data["why"], drafts=data["drafts"], dropped=0)


async def _cache(key: str, notes: sourcing_agent.Notes) -> None:
    """같은 입력이면 하루 동안 LLM을 다시 부르지 않는다 (지워져도 되는 짧은 캐시)."""
    try:
        await queue.redis.set(
            key, json.dumps({"why": notes.why, "drafts": notes.drafts}), ex=NOTES_TTL_S
        )
    except RedisError:
        pass


async def _states(s: AsyncSession, project_id: uuid.UUID) -> dict[uuid.UUID, list[RequestStateOut]]:
    """업체마다 이 프로젝트에서 보낸 요청의 상태"""
    out: dict[uuid.UUID, list[RequestStateOut]] = defaultdict(list)
    for vendor_id, trade, status in await repo.quote_states(s, project_id):
        out[vendor_id].append(
            RequestStateOut(trade=trade, status=status, label=QUOTE_LABEL[status])
        )
    for vendor_id, trade, status, reason in await repo.contact_states(s, project_id):
        label = STUCK_LABEL if reason == "stuck" else CONTACT_LABEL[status]
        out[vendor_id].append(RequestStateOut(trade=trade, status=status, label=label))
    return out


# ── 앱 안 가견적 요청 ──


async def create_quote_request(
    s: AsyncSession, user: User, project_id: uuid.UUID, data: QuoteRequestIn
) -> QuoteRequestOut:
    """고객 → 승인 업체. 그 공정 · 시군구를 맡는 승인 업체에만 보낼 수 있다."""
    p = await project_service.get_for(s, user, project_id)  # 남의 프로젝트는 404
    if data.trade not in project_trades(p):
        raise AppError(422, "trade", "이 프로젝트에 없는 공정이에요.")
    eligible = await vendor_service.candidates(s, [data.trade], p.sido, p.sgg)
    if data.vendor_id not in {v.user_id for v in eligible}:
        raise AppError(422, "vendor", "이 업체에는 가견적을 요청할 수 없어요.")
    now = now_utc()
    req = QuoteRequest(
        project_id=p.id,
        trade=data.trade,
        vendor_id=data.vendor_id,
        message=data.message.strip(),
        status="requested",
        created_at=now,
    )
    try:
        s.add(req)
        await s.flush()
        s.add(
            QuoteRequestEvent(
                request_id=req.id, from_status=None, to_status="requested", actor_id=user.id, at=now
            )
        )
        await s.commit()
    except IntegrityError as exc:  # 같은 업체 · 공정에 두 번 (동시에 눌러도) → 고유 제약이 막는다
        await s.rollback()
        raise AppError(409, "already_requested", "이미 이 업체에 가견적을 요청했어요.") from exc
    return QuoteRequestOut(
        id=req.id,
        trade=req.trade,
        vendor_id=req.vendor_id,
        status="requested",
        created_at=req.created_at,
    )


async def sent_requests(s: AsyncSession, user: User, project_id: uuid.UUID) -> list[SentRequestOut]:
    """고객이 이 프로젝트에서 앱 업체에 보낸 가견적 요청과 지금 상태 (새 것부터)"""
    p = await project_service.get_for(s, user, project_id)  # 남의 프로젝트는 404
    return [
        SentRequestOut(
            id=r.id,
            trade=r.trade,
            trade_label=TRADE_LABEL[r.trade],
            vendor_id=r.vendor_id,
            vendor_name=name or vendor_service.NO_NAME,
            status=r.status,
            status_label=QUOTE_LABEL[r.status],
            created_at=r.created_at,
            viewed_at=r.viewed_at,
        )
        for r, name in await repo.sent(s, p.id)
    ]


async def _approved_vendor(s: AsyncSession, user: User) -> None:
    if not await vendor_service.is_approved(s, user.id):
        raise AppError(403, "vendor_not_approved", "승인된 업체만 쓸 수 있어요.")


async def _inbox_item(s: AsyncSession, r: QuoteRequest) -> InboxItemOut:
    p = await project_service.read(s, r.project_id)  # 이 업체가 받은 요청의 프로젝트만 읽는다
    return InboxItemOut(
        id=r.id,
        trade=r.trade,
        trade_label=TRADE_LABEL[r.trade],
        status=r.status,
        status_label=QUOTE_LABEL[r.status],
        region=p.region if p else "",
        facts=request_facts(p, [r.trade]) if p else [],
        message=r.message,
        created_at=r.created_at,
        viewed_at=r.viewed_at,
    )


async def vendor_inbox(s: AsyncSession, user: User) -> list[InboxItemOut]:
    await _approved_vendor(s, user)
    return [await _inbox_item(s, r) for r in await repo.inbox(s, user.id)]


async def mark_viewed(s: AsyncSession, user: User, request_id: uuid.UUID) -> InboxItemOut:
    """업체가 요청을 확인했다 (requested → viewed). 업체가 누른 요청으로만 바뀐다."""
    await _approved_vendor(s, user)
    if await repo.quote_for_vendor(s, request_id, user.id) is None:
        raise AppError(404, "not_found", "가견적 요청을 찾을 수 없어요.")
    await _move_quote(s, request_id, to="viewed", actor=user.id)
    await s.commit()
    r = await repo.quote_for_vendor(s, request_id, user.id)
    return await _inbox_item(s, r)


async def _move_quote(s: AsyncSession, request_id: uuid.UUID, *, to: str, actor: uuid.UUID) -> None:
    """상태를 바꾸는 한 곳: 허용 전이 확인 → 조건부 UPDATE(1행이 아니면 409) → 같은 트랜잭션에 이력."""
    allowed = QUOTE_MOVES[to]
    now = now_utc()
    values = {"viewed_at": now} if to == "viewed" else {}
    if not await repo.move_quote(s, request_id, to=to, allowed_from=allowed, values=values):
        await s.rollback()
        raise AppError(409, "invalid_state", "이미 처리한 요청이에요.")
    s.add(
        QuoteRequestEvent(
            request_id=request_id, from_status=allowed[0], to_status=to, actor_id=actor, at=now
        )
    )


# ── 외부 업체 대신 연락 (아웃박스) ──


async def _move_contact(
    s: AsyncSession,
    request_id: uuid.UUID,
    *,
    to: str,
    now: datetime,
    reason: str | None = None,
    actor: uuid.UUID | None = None,
    values: dict | None = None,
) -> None:
    """대신 연락 상태를 바꾸는 한 곳: 허용 전이 → 조건부 UPDATE(1행이 아니면 409) → 같은 트랜잭션에 이력."""
    allowed = CONTACT_MOVES[to]
    if not await repo.move_contact(s, request_id, to=to, allowed_from=allowed, values=values or {}):
        await s.rollback()
        raise AppError(409, "invalid_state", "이미 처리한 요청이에요.")
    s.add(
        ContactRequestEvent(
            request_id=request_id,
            from_status=allowed[0],
            to_status=to,
            reason=reason,
            actor_id=actor,
            at=now,
        )
    )


async def create_contact_request(
    s: AsyncSession, user: User, data: ContactRequestIn
) -> ContactRequestOut:
    """고객이 동의한 글을 아웃박스에 넣는다 (draft → queued). 꺼져 있으면 보내지 않고 queued에 둔다."""
    p = await project_service.get_for(s, user, data.project_id)  # 남의 프로젝트는 404
    if data.trade not in project_trades(p):
        raise AppError(422, "trade", "이 프로젝트에 없는 공정이에요.")
    card = await directory_service.card(s, data.vendor_id)
    if card is None or card.sido != p.sido or data.trade not in card.trades:
        raise AppError(422, "vendor", "이 업체에는 대신 요청할 수 없어요.")
    if card.opted_out:
        raise AppError(422, "opted_out", "연락을 원하지 않는 업체예요.")
    channel = directory_service.best_channel(card.channels)
    if channel is None:
        raise AppError(
            422, "no_contact", "연락처에 동의한 업체가 아니에요. 업체 링크나 전화를 써 주세요."
        )
    now = now_utc()
    # 같은 고객 · 같은 업체의 요청을 줄 세워 하루 한도를 정확히 센다 (늘 고객 → 업체 순으로 잠근다)
    await repo.lock(s, f"contact:customer:{user.id}")
    await repo.lock(s, f"contact:vendor:{card.id}")
    today = outbox.day_start(now)
    if (
        await repo.contacts_since(s, today, customer_id=user.id)
        >= settings.contact_daily_per_customer
    ):
        raise AppError(
            429, "contact_limit", "오늘은 대신 요청을 더 보낼 수 없어요. 내일 다시 해 주세요."
        )
    if await repo.contacts_since(s, today, vendor_id=card.id) >= settings.contact_daily_per_vendor:
        raise AppError(
            429, "contact_limit", "이 업체에는 오늘 더 요청할 수 없어요. 내일 다시 해 주세요."
        )
    req = ContactRequest(
        customer_id=user.id,
        project_id=p.id,
        trade=data.trade,
        vendor_id=card.id,
        channel=channel,
        body=data.body,
        consented_at=now,
        status="draft",
        created_at=now,
    )
    try:
        s.add(req)
        await s.flush()
        s.add(ContactRequestEvent(request_id=req.id, to_status="draft", actor_id=user.id, at=now))
        await _move_contact(s, req.id, to="queued", now=now, reason="consent", actor=user.id)
        await s.commit()
    except IntegrityError as exc:  # 같은 업체 · 공정에 두 번 → 고유 제약
        await s.rollback()
        raise AppError(409, "already_requested", "이미 이 업체에 대신 요청했어요.") from exc
    enabled = settings.contact_send_enabled
    notice = OFF_NOTICE if not enabled else NIGHT_NOTICE if outbox.is_night(now) else QUEUED_NOTICE
    return ContactRequestOut(
        id=req.id,
        project_id=p.id,
        trade=req.trade,
        vendor_id=card.id,
        channel=channel,
        status="queued",
        send_enabled=enabled,
        notice=notice,
    )


async def _try_move_contact(s: AsyncSession, request_id: uuid.UUID, **kw) -> bool:
    """작업(worker)용: _move_contact로 바꾸고 commit. 다른 쪽이 먼저 바꿨으면(409) False."""
    try:
        await _move_contact(s, request_id, **kw)
    except AppError as exc:
        if exc.status != 409:
            raise
        return False
    await s.commit()
    return True


async def dispatch_contacts(
    s: AsyncSession, sender: Sender, *, now: datetime, limit: int = 50
) -> dict[str, int | str]:
    """queued인 대신 연락을 먼저 선점하고 보낸다. 꺼져 있거나 · 발신자 연락처가 없거나 · 밤이면 아무것도 안 한다.

    한 건마다: 수신거부 · 출처에서 빠짐 · 동의를 다시 본다(아니면 blocked) → 업체당 하루 한도를 넘으면
    다음 날로 미룬다 → queued → sending 선점을 commit → 보내기(멱등 키 = 요청 id) →
    sent · test_sent(시험 발송) · failed. 선점한 뒤 멈추면 sending에 남고 다시 보내지 않는다
    (fail_stuck_contacts가 failed로 돌린다). 작업이 겹쳐도 선점은 한 쪽만 된다.
    보내는 동안에는 DB 트랜잭션을 열어 두지 않는다.
    """
    if not settings.contact_send_enabled:
        return {"skipped": "disabled"}
    if not settings.contact_sender_contact:
        return {"skipped": "no_sender_contact"}
    if outbox.is_night(now):
        return {"skipped": "night"}
    due = await repo.queued_contacts(s, limit)
    await s.rollback()
    seen: Counter[str] = Counter()
    today = outbox.day_start(now)
    for req_id, vendor_id, channel, body in due:
        target = await directory_service.contact_target(s, vendor_id, channel)
        if isinstance(target, str):  # 수신거부 · 출처에서 빠짐 · 동의 철회
            moved = await _try_move_contact(s, req_id, to="blocked", now=now, reason=target)
            seen["blocked" if moved else "taken"] += 1
            continue
        # 업체마다 줄을 세워 오늘 보낸 수를 세고 선점까지 한 트랜잭션에 한다 (겹쳐도 한도를 넘지 않게)
        await repo.lock(s, f"contact:vendor:{vendor_id}")
        if await repo.claimed_since(s, vendor_id, today) >= settings.contact_daily_per_vendor:
            await s.rollback()
            seen["deferred"] += 1
            continue
        claim = {"claimed_at": now, "sender": sender.name}
        if not await _try_move_contact(s, req_id, to="sending", now=now, values=claim):
            seen["taken"] += 1  # 다른 작업이 먼저 가져갔다
            continue
        link = outbox.optout_url(settings.web_url, target.optout_token)
        text = outbox.compose(
            body, sender_contact=settings.contact_sender_contact, optout_link=link
        )
        msg = Outgoing(channel=target.channel, to=target.value, text=text)
        try:
            await sender.send(msg, idempotency_key=str(req_id))
        except SendError:
            to, values, reason = "failed", {}, "send_error"
        else:
            to, values, reason = ("test_sent" if sender.test else "sent"), {"sent_at": now}, None
        if await _try_move_contact(s, req_id, to=to, now=now, reason=reason, values=values):
            seen[to] += 1
        else:  # 그사이 멈춘 발송으로 정리됐다 (이력에 stuck으로 남아 있다)
            log.warning("대신 연락 결과를 남기지 못했어요 (이미 정리됨): %s", to)
            seen["late"] += 1
    return dict(seen)


async def fail_stuck_contacts(s: AsyncSession, *, now: datetime) -> dict[str, int]:
    """sending에 STUCK_AFTER보다 오래 멈춘 대신 연락을 failed(이유 stuck, 확인 필요)로 돌린다.

    보냈는지 모르므로 자동으로 다시 보내지 않는다. 사람이 발송사 기록을 보고 판단한다.
    """
    ids = await repo.stuck_contacts(s, now - STUCK_AFTER)
    await s.rollback()
    moved = 0
    for req_id in ids:
        moved += await _try_move_contact(s, req_id, to="failed", now=now, reason="stuck")
    return {"stuck": moved}
