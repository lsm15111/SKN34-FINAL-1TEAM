"""가견적 받기 흐름: 후보 업체와 받는 길, 앱 안 가견적 요청, 외부 업체 대신 연락.

다른 기능은 그 service의 공개 함수로만 부른다: project(프로젝트) · vendor(앱 업체) · directory(외부 업체).
"""

import uuid
from collections import defaultdict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.config import settings
from app.directory import service as directory_service
from app.directory.address import phone_label
from app.directory.industry import TRADE_LABEL
from app.directory.service import SOURCE_LABEL, ExtCard
from app.project import service as project_service
from app.project.schemas import ProjectOut
from app.quote import repository as repo
from app.quote.models import QuoteRequest, QuoteRequestEvent
from app.quote.schemas import (
    CandidateOut,
    CostOut,
    InboxItemOut,
    LinksOut,
    QuoteRequestIn,
    QuoteRequestOut,
    RequestStateOut,
    SourceOut,
    SourcingOut,
)
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

MAX_EXT = 12  # 외부 업체 후보 최대 수
NO_CANDIDATES = "이 지역 · 공정에 맞는 업체를 아직 찾지 못했어요."
QUOTE_LABEL = {"requested": "요청했어요", "viewed": "업체가 확인했어요"}
# 가견적 요청 상태 전이: 바뀔 상태 → 바꿀 수 있는 지금 상태
QUOTE_MOVES: dict[str, tuple[str, ...]] = {"viewed": ("requested",)}
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
        links=LinksOut(homepage=v.site_url),
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
    await s.close()  # 아래는 DB 없이 만든다
    cards = [_app_card(v, p, states[v.user_id]) for v in app]
    cards += [_ext_card(e, p, states[e.id]) for e in ext]
    return SourcingOut(
        project_id=p.id,
        region=p.region,
        trades=trades,
        facts=request_facts(p),
        candidates=cards,
        proxy_enabled=settings.contact_send_enabled,
        notice=None if cards else NO_CANDIDATES,
    )


async def _states(s: AsyncSession, project_id: uuid.UUID) -> dict[uuid.UUID, list[RequestStateOut]]:
    """업체마다 이 프로젝트에서 보낸 요청의 상태"""
    out: dict[uuid.UUID, list[RequestStateOut]] = defaultdict(list)
    for vendor_id, trade, status in await repo.quote_states(s, project_id):
        out[vendor_id].append(
            RequestStateOut(trade=trade, status=status, label=QUOTE_LABEL[status])
        )
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
