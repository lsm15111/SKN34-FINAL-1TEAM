"""가견적 받기 흐름: 후보 업체와 받는 길, 앱 안 가견적 요청, 외부 업체 대신 연락.

다른 기능은 그 service의 공개 함수로만 부른다: project(프로젝트) · vendor(앱 업체) · directory(외부 업체).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.config import settings
from app.directory import service as directory_service
from app.directory.address import phone_label
from app.directory.service import SOURCE_LABEL, ExtCard
from app.project import service as project_service
from app.project.schemas import ProjectOut
from app.quote.schemas import (
    CandidateOut,
    CostOut,
    LinksOut,
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
from app.shared.regions import SIDO, region_label
from app.vendor import service as vendor_service
from app.vendor.schemas import VendorCard

MAX_EXT = 12  # 외부 업체 후보 최대 수
NO_CANDIDATES = "이 지역 · 공정에 맞는 업체를 아직 찾지 못했어요."
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
    await s.close()  # 아래는 DB 없이 만든다
    cards = [_app_card(v, p, []) for v in app] + [_ext_card(e, p, []) for e in ext]
    return SourcingOut(
        project_id=p.id,
        region=p.region,
        trades=trades,
        facts=request_facts(p),
        candidates=cards,
        proxy_enabled=settings.contact_send_enabled,
        notice=None if cards else NO_CANDIDATES,
    )
