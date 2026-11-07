"""이 집 기준 업체 고르기 · 업체 자세히 · 실측 요청.

업체는 승인됐고 그 공정을 하고 이 집 지역(구)에서 일하는 곳만 보인다.
가견적은 업체가 확인한 단가 × 이 집 표준견적서 수량(계산 엔진)이다. 확인한 단가가 없거나 이 집에
필요한 줄의 단가가 하나라도 빠졌으면 '가견적 없음'이다. 요청할 때 그 값을 사본으로 고정한다.
실측 요청은 연결만 한다: 업체 연락처를 보여 주고, 고객 연락처는 고객이 고른 업체에만 간다.
연락처를 보여도 되는지는 이 파일의 contact_visible 한 곳에서 정한다.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.calc.quote_diff import percent_vs
from app.calc.schedule import JOB_MAX_DAYS, days_since, years_since
from app.files import service as files_service
from app.notify import service as notify_service
from app.project import service as project_service
from app.project.schemas import ProjectBrief, ProjectOut, WhenIn
from app.quote import ranges
from app.quote import service as quote_service
from app.quote.models import QUOTE_FILES_MAX, VAT_MODES, StandardQuote, StandardQuoteLine
from app.quote.schemas import QuoteBriefOut, QuoteDraftIn, RangeOut
from app.shared.clock import SEOUL, now_utc
from app.shared.errors import AppError
from app.shared.ids import uuid7
from app.shared.korean import i_ga
from app.vendor import service as vendor_service
from app.vendor.schemas import ContactOut, EstimateOut
from app.visit import repository as repo
from app.visit.models import LIVE, SLOTS, Visit, VisitEvent
from app.visit.schemas import (
    CompareOut,
    CompareRowOut,
    CustomerContactOut,
    Direction,
    EstimateDetailOut,
    FailedOut,
    InboxSummaryOut,
    QuoteBoardOut,
    QuoteVersionBrief,
    RecentOut,
    RequestTextOut,
    ReselectIn,
    ReselectOut,
    VendorDetailOut,
    VendorListOut,
    VendorRowOut,
    VendorVisitDetailOut,
    VendorVisitPage,
    VendorVisitRow,
    VisitBrief,
    VisitCreateIn,
    VisitCreateOut,
    VisitFactsOut,
    VisitListOut,
    VisitOut,
    VisitQuotesOut,
)

NOT_LISTED = "이 집에서 고를 수 있는 업체가 아니에요."
# 연락처 보내기 동의 문구 버전. 문구를 바꾸면 올리고, 화면은 요청할 때 이 값을 그대로 보낸다
CONSENT_VER = "2026-11-01"
TRADE_LABEL = {"dobae": "도배", "mokgong": "목공"}
GRADE_LABEL = {"economy": "저가형", "basic": "기본형"}
MOK_LABEL = {
    "molding": "천장 몰딩",
    "base": "걸레받이",
    "door": "방문 교체",
    "flatten": "천장 평탄화",
}
BASIS_SHORT = {"supply": "공급", "exclusive": "전용"}
WEEKDAY = "월화수목금토일"
DONE = ("cancelled", "declined", "closed")  # 끝남 탭
TABS = {"todo": ("requested",), "waiting": ("quoted",), "done": DONE}
RECENT_DAYS = 30


def contact_visible(status: str, contact_until: date | None, today: date) -> bool:
    """연락처를 서로 보여도 되는지: 요청함 · 견적서 옴이면 보이고, 확정이면 contact_until까지
    (없으면 보임), 취소 · 못 받음 · 닫힘이면 가린다. 고객 쪽 · 업체 쪽이 같이 쓴다."""
    if status in ("requested", "quoted"):
        return True
    if status == "chosen":
        return contact_until is None or today <= contact_until
    return False


def customer_contact_visible(v: Visit, today: date) -> bool:
    """업체에게 고객 연락처(이름 · 휴대폰 · 동 · 호수)를 보여도 되는지: 고객이 보내기로 고른 요청만."""
    return v.share_contact and contact_visible(v.status, v.contact_until, today)


def _brief(v: Visit | None) -> VisitBrief | None:
    if v is None:
        return None
    return VisitBrief(
        id=v.id, status=v.status, decline_code=v.decline_code, close_reason=v.close_reason
    )


def _day(at: datetime | None) -> date | None:
    return at.astimezone(SEOUL).date() if at else None


async def _standard(
    s: AsyncSession, user: User, project_id: uuid.UUID, trade: str
) -> tuple[ProjectOut, StandardQuote, list[StandardQuoteLine]]:
    """내 프로젝트(남의 것은 404)와 그 공정의 최신 표준견적서 · 줄"""
    p = await project_service.get_for(s, user, project_id)
    got = await quote_service.standard_trade(s, p, trade)
    if got is None:
        raise AppError(422, "trade", "이 집에서 고른 공정이 아니에요.")
    return p, *got


def _estimate(
    trade: str,
    std: StandardQuote,
    lines: list[StandardQuoteLine],
    cp: vendor_service.ConfirmedPrices | None,
) -> EstimateOut | None:
    """확인한 단가가 없거나 이 집에 필요한 줄의 단가가 빠졌으면 가견적 없음(None)"""
    if cp is None:
        return None
    e = vendor_service.estimate_out(
        trade, lines, cp.prices, grade=std.grade, tax_kind=cp.tax_kind, sources=cp.sources
    )
    return None if e.missing or not e.lines else e


def _vendor_range(
    trade: str,
    std: StandardQuote,
    lines: list[StandardQuoteLine],
    k: ranges.Known,
    e: EstimateOut,
    exempt: bool,
    *,
    explain: bool,
) -> RangeOut:
    """가견적의 실측 뒤 예상 범위: 업체 단가는 알고(실측 보정만), 수량 · '실측 후' 줄은 표준견적서와 같다"""
    amounts = {ln.key: ln.amount for ln in e.lines}
    inp = ranges.range_input(
        trade, std.grade, lines, k, amounts=amounts, vendor_priced=True, exempt=exempt
    )
    return ranges.trade_range(inp, k, explain=explain)


def _vs(total: int, standard: int) -> tuple[Decimal | None, Direction | None]:
    if standard <= 0:
        return None, None
    pct = percent_vs(total, standard)
    return pct, "less" if pct < 0 else "more" if pct > 0 else "same"


async def vendors_for(
    s: AsyncSession, user: User, project_id: uuid.UUID, trade: str
) -> VendorListOut:
    """업체 고르기: 가견적 낮은 순, 가견적 없음은 맨 뒤, 같으면 상호 순."""
    p, std, lines = await _standard(s, user, project_id, trade)
    cards = await vendor_service.list_public(s, trade, p.sido, p.sgg)
    ids = [c.vendor_id for c in cards]
    prices = await vendor_service.confirmed_prices(s, ids, trade)
    visits = await repo.latest_by_vendor(s, p.id, trade, ids) if ids else {}
    k = quote_service.known(p, trade)
    rows = []
    for c in cards:
        cp = prices.get(c.vendor_id)
        e = _estimate(trade, std, lines, cp)
        pct, way = _vs(e.total, std.total) if e else (None, None)
        vr = None
        if e is not None and cp is not None:
            exempt = cp.tax_kind == "exempt"
            vr = _vendor_range(trade, std, lines, k, e, exempt, explain=False)
        rows.append(
            VendorRowOut(
                vendor_id=c.vendor_id,
                biz_name=c.biz_name,
                trades=c.trades,
                areas=c.areas,
                verified_on=_day(c.verified_at),
                visit_fee=c.visit_fee,
                visit_fee_refund=c.visit_fee_refund,
                contact_method=c.contact_method,
                call_start=c.call_start,
                call_end=c.call_end,
                estimate_total=e.total if e else None,
                vs_standard=pct,
                vs_direction=way,
                estimate_range=vr,
                visit=_brief(visits.get(c.vendor_id)),
            )
        )
    rows.sort(key=lambda r: (r.estimate_total is None, r.estimate_total or 0, r.biz_name or ""))
    return VendorListOut(
        project_id=p.id,
        trade=trade,
        region=p.region,
        area_name=p.sgg,
        standard_total=std.total,
        standard_range=ranges.trade_range(
            ranges.range_input(trade, std.grade, lines, k), k, explain=False
        ),
        slots_left=SLOTS - len(await repo.live(s, p.id, trade)),
        consent_ver=CONSENT_VER,
        vendors=rows,
    )


async def vendor_detail(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    vendor_id: uuid.UUID,
    trade: str,
    today: date,
) -> VendorDetailOut:
    p, std, lines = await _standard(s, user, project_id, trade)
    if not await vendor_service.listed(s, vendor_id, trade, p.sido, p.sgg):
        raise AppError(404, "not_found", NOT_LISTED)
    profile = await vendor_service.public_profile(s, vendor_id)
    cp = (await vendor_service.confirmed_prices(s, [vendor_id], trade)).get(vendor_id)
    e = _estimate(trade, std, lines, cp)
    estimate = None
    if e is not None and cp is not None:
        pct, way = _vs(e.total, std.total)
        exempt = cp.tax_kind == "exempt"
        k = quote_service.known(p, trade)
        estimate = EstimateDetailOut(
            **e.model_dump(),
            set_id=cp.set_id,
            confirmed_on=_day(cp.confirmed_at),
            confirmed_at=cp.confirmed_at,
            exempt=exempt,
            vs_standard=pct,
            vs_direction=way,
            range=_vendor_range(trade, std, lines, k, e, exempt, explain=True),
        )
    left = set(e.left_out) if e else set()
    not_included = [ln.name for ln in lines if ln.state == "after_visit" or ln.key in left]
    return VendorDetailOut(
        project_id=p.id,
        trade=trade,
        standard_total=std.total,
        profile=profile,
        verified_on=_day(profile.verified_at),
        years_open=years_since(profile.opened_on, today) if profile.opened_on else None,
        in_area=True,  # 목록 조건(이 집 구가 활동 지역에 있음)을 지난 업체만 여기까지 온다
        area_name=p.sgg,
        dong=None,  # 프로젝트에 읍 · 면 · 동 칸이 아직 없다
        estimate=estimate,
        visit=_brief((await repo.latest_by_vendor(s, p.id, trade, [vendor_id])).get(vendor_id)),
        not_included=not_included,
    )


async def vendor_photo(
    s: AsyncSession, user: User, project_id: uuid.UUID, vendor_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    """이 집에서 고를 수 있는 업체의 시공 사진만 내준다. 근거 파일 · 등록증 · 남의 사진은 404."""
    p = await project_service.get_for(s, user, project_id)
    trades = [t for t in ("dobae", "mokgong") if getattr(p.trades, t) is not None]
    if not any([await vendor_service.listed(s, vendor_id, t, p.sido, p.sgg) for t in trades]):
        raise AppError(404, "not_found", NOT_LISTED)
    f = await vendor_service.portfolio_file(s, vendor_id, file_id)
    if f is None:
        raise AppError(404, "not_found", "사진을 찾을 수 없어요.")
    return await files_service.respond(f)


def _md(d: date) -> str:
    return f"{d.month:02d}.{d.day:02d}({WEEKDAY[d.weekday()]})"


def _number(x: Decimal) -> str:
    """32.0 → 32, 30.8 → 30.8"""
    return format(x.normalize(), "f")


def _when(w: WhenIn) -> str:
    """희망 시기 문구 (요청 문구 · 업체 쪽 자세히가 같이 쓴다)"""
    if w.kind == "date" and w.start:
        return f"{_md(w.start)} ~ {_md(w.end)}" if w.end else f"{_md(w.start)}부터"
    if w.kind == "movein" and w.start:
        return f"이사 {_md(w.start)} 전까지"
    return "1~2달 안" if w.kind == "months" else "아직 몰라요"


def request_text(p: ProjectOut, std: StandardQuote) -> str:
    """업체에 연락할 때 보낼 문구. 평 · 면적은 표준견적서(계산 엔진)에 저장한 값을 쓴다.
    고객 이름 · 연락처 · 동 · 호수는 넣지 않는다. 동네(법정동) 칸이 없어 구까지만 쓴다."""
    if std.trade == "dobae":
        work = f"도배 {GRADE_LABEL.get(std.grade or '', '')}".strip()
    else:
        items = p.trades.mokgong.items if p.trades.mokgong else []
        work = " ".join(["목공", " · ".join(MOK_LABEL[i] for i in items if i in MOK_LABEL)]).strip()
    home = (
        f"{p.sgg} 아파트 {_number(std.pyeong)}평"
        f"({BASIS_SHORT.get(std.area_basis, '')} {_number(std.area_m2)}㎡)"
    )
    occupied = "짐이 있는 집이에요." if p.occupied else "빈 집이에요."
    return (
        f"[믿집] 실측 요청이에요. 요청 번호 {p.code} · {work} · {home}"
        f" · 희망 시기 {_when(p.when)} · {occupied}"
    )


def _visit_out(
    v: Visit,
    contacts: dict[uuid.UUID, ContactOut],
    today: date,
    closed: dict[uuid.UUID, datetime] | None = None,
    quotes: dict[uuid.UUID, QuoteBriefOut] | None = None,
) -> VisitOut:
    visible = contact_visible(v.status, v.contact_until, today)
    return VisitOut(
        id=v.id,
        trade=v.trade,
        vendor_id=v.vendor_id,
        vendor_name=v.vendor_name,
        status=v.status,
        slot=v.slot,
        created_at=v.created_at,
        share_contact=v.share_contact,
        message=v.message,
        decline_code=v.decline_code,
        close_reason=v.close_reason,
        estimate_total=v.estimate_total,
        contact_visible=visible,
        contact=contacts.get(v.vendor_id) if visible and v.vendor_id else None,
        closed_at=(closed or {}).get(v.id) if v.status in DONE else None,
        quote=(quotes or {}).get(v.id),
    )


async def request_visits(
    s: AsyncSession, user: User, project_id: uuid.UUID, data: VisitCreateIn, today: date
) -> VisitCreateOut:
    """실측 요청 보내기. 프로젝트 행을 잠가 같은 집의 요청이 줄 서고, 공정마다 3곳까지만 받는다.
    지금 고를 수 없는 업체 · 이미 요청한 업체는 만들지 않고 failed로 돌려준다."""
    p, std, lines = await _standard(s, user, project_id, data.trade)
    share = set(data.share_contact_ids)
    if share:
        if not user.phone:
            raise AppError(422, "phone_required", "업체에 보내려면 휴대폰 번호가 필요해요.")
        if not (data.apt_name and data.dong and data.ho):
            raise AppError(422, "address_required", "아파트 이름 · 동 · 호수를 적어 주세요.")
        if data.consent_ver != CONSENT_VER:
            raise AppError(409, "consent_changed", "동의 문구가 바뀌었어요. 다시 확인해 주세요.")
    cards = {c.vendor_id: c for c in await vendor_service.list_public(s, data.trade, p.sido, p.sgg)}
    failed = [FailedOut(vendor_id=i, code="unavailable") for i in data.vendor_ids if i not in cards]
    ok = [i for i in data.vendor_ids if i in cards]
    prices = await vendor_service.confirmed_prices(s, ok, data.trade) if ok else {}

    unit = (data.apt_name, data.dong, data.ho) if share else None
    await project_service.lock_for_visit(s, p.id, unit)  # 첫 요청이면 집 정보 고치기를 막는다
    live = await repo.live(s, p.id, data.trade)
    if any(v.status == "chosen" for v in live):  # 확정이 살아 있으면 다시 고르기부터
        raise AppError(409, "already_chosen", NOT_CHOOSABLE["chosen"])
    taken = {v.vendor_id for v in live}
    failed += [FailedOut(vendor_id=i, code="already") for i in ok if i in taken]
    new = [i for i in ok if i not in taken]
    if not new:
        if all(f.code == "already" for f in failed):
            raise AppError(409, "already", "이미 실측을 요청한 업체예요.")
        raise AppError(409, "unavailable", "지금 믿집에서 일할 수 없는 업체예요.")
    free = [n for n in range(1, SLOTS + 1) if n not in {v.slot for v in live}]
    if len(new) > len(free):
        raise AppError(409, "slots_full", "3곳까지 담을 수 있어요. 하나를 빼면 담을 수 있어요.")

    now = now_utc()
    rows: list[Visit] = []
    for vid, slot in zip(new, free, strict=False):
        cp = prices.get(vid)
        e = _estimate(data.trade, std, lines, cp)
        shared = vid in share
        rows.append(
            Visit(
                id=uuid7(),
                project_id=p.id,
                trade=data.trade,
                vendor_id=vid,
                vendor_name=cards[vid].biz_name or "업체",
                slot=slot,
                status="requested",
                share_contact=shared,
                consent_ver=CONSENT_VER if shared else None,
                consent_at=now if shared else None,
                message=data.message,
                estimate_set_id=cp.set_id if e and cp else None,
                estimate_total=e.total if e else None,
                created_at=now,
            )
        )
    try:
        s.add_all(rows)
        await s.flush()
        s.add_all(
            [
                VisitEvent(
                    visit_id=v.id, from_status=None, to_status="requested", by_id=user.id, at=now
                )
                for v in rows
            ]
        )
        for v in rows:  # 업체 알림: 고객 이름 · 연락처는 넣지 않는다
            await notify_service.add(
                s,
                user_id=v.vendor_id,
                kind="visit_requested",
                body=f"새 실측 요청이 왔어요 · {TRADE_LABEL[data.trade]}",
                link=f"/vendor/requests/{v.id}",
                dedup_key=f"visit:{v.id}",
            )
        await s.commit()
    except IntegrityError as exc:  # 칸 · 업체 부분 UQ: 다른 곳에서 먼저 같은 칸을 채웠다
        await s.rollback()
        raise AppError(409, "stale", "다른 곳에서 먼저 요청했어요. 다시 열어 주세요.") from exc
    contacts = await vendor_service.contacts(s, new)
    return VisitCreateOut(created=[_visit_out(v, contacts, today) for v in rows], failed=failed)


async def visits_for(
    s: AsyncSession, user: User, project_id: uuid.UUID, trade: str | None, today: date
) -> VisitListOut:
    """이 집 실측 요청 목록 · 공정마다 보낼 문구 · 남은 칸"""
    p = await project_service.get_for(s, user, project_id)
    trades = [t for t in ("mokgong", "dobae") if getattr(p.trades, t) is not None]
    if trade is not None and trade not in trades:
        raise AppError(422, "trade", "이 집에서 고른 공정이 아니에요.")
    every = await repo.of_project(s, p.id, None)
    rows = [v for v in every if trade is None or v.trade == trade]
    contacts = await vendor_service.contacts(s, [v.vendor_id for v in rows if v.vendor_id])
    closed = await repo.last_events(s, [v.id for v in rows if v.status in DONE])
    quotes = await quote_service.sent_briefs(s, [v.id for v in rows])
    texts = []
    for t in [trade] if trade else trades:
        got = await quote_service.standard_trade(s, p, t)
        if got is not None:
            texts.append(RequestTextOut(trade=t, text=request_text(p, got[0])))
    return VisitListOut(
        project_id=p.id,
        consent_ver=CONSENT_VER,
        slots_left={
            t: SLOTS - sum(1 for v in every if v.trade == t and v.status in LIVE) for t in trades
        },
        request_texts=texts,
        visits=[_visit_out(v, contacts, today, closed, quotes) for v in rows],
    )


# ---- 상태 바꾸기: 고객 취소 · 업체 못 받아요 (허용 전이 → 조건부 UPDATE → 같은 트랜잭션에 이력 · 알림) ----


async def _move(
    s: AsyncSession,
    v: Visit,
    *,
    to: str,
    by: User,
    values: dict | None = None,
    code: str | None = None,
    message: str,
) -> None:
    """requested에서만 바꾼다. 1행이 아니면 409(다른 곳에서 먼저 바꿈)."""
    ok = await repo.set_status(
        s, v.id, allowed_from=("requested",), values={"status": to, **(values or {})}
    )
    if not ok:
        raise AppError(409, "invalid_state", message)
    s.add(VisitEvent(visit_id=v.id, from_status="requested", to_status=to, by_id=by.id, code=code))


async def cancel(
    s: AsyncSession, user: User, project_id: uuid.UUID, visit_id: uuid.UUID, today: date
) -> VisitOut:
    """고객이 요청 취소 (견적서가 오기 전까지). 칸이 비고 연락처는 바로 가려진다."""
    p = await project_service.get_for(s, user, project_id)
    v = await repo.get(s, visit_id)
    if v is None or v.project_id != p.id:
        raise AppError(404, "not_found", "실측 요청을 찾을 수 없어요.")
    if v.status == "quoted":
        raise AppError(409, "invalid_state", "견적서가 온 뒤에는 취소할 수 없어요.")
    await _move(s, v, to="cancelled", by=user, message="이미 닫힌 요청이에요.")
    if v.vendor_id is not None:
        await notify_service.add(
            s,
            user_id=v.vendor_id,
            kind="visit_cancelled",
            body=f"고객이 실측 요청을 취소했어요 · {TRADE_LABEL[v.trade]}",
            link=f"/vendor/requests/{v.id}",
            dedup_key=f"visit:{v.id}:cancelled",
        )
    await s.commit()
    v = await repo.get(s, visit_id)
    closed = await repo.last_events(s, [v.id])
    return _visit_out(v, {}, today, closed)


async def _mine(s: AsyncSession, vendor: User, visit_id: uuid.UUID) -> Visit:
    v = await repo.get(s, visit_id)
    if v is None or v.vendor_id != vendor.id:  # 다른 업체 요청은 있는지도 알려 주지 않는다
        raise AppError(404, "not_found", "실측 요청을 찾을 수 없어요.")
    return v


async def decline(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, code: str, today: date
) -> VendorVisitDetailOut:
    """업체가 이 요청을 못 받아요 (견적서를 보내기 전까지). 고객에게 고른 이유가 보인다."""
    v = await _mine(s, vendor, visit_id)
    await project_service.lock(s, v.project_id)  # 확정 · 다시 고르기와 같은 잠금 순서
    await _move(
        s,
        v,
        to="declined",
        by=vendor,
        values={"decline_code": code},
        code=code,
        message="이미 닫혔거나 견적서를 보낸 요청이에요.",
    )
    owner = (await project_service.briefs(s, [v.project_id]))[v.project_id].owner_id
    await notify_service.add(
        s,
        user_id=owner,
        kind="visit_declined",
        body=f"{i_ga(v.vendor_name)} 이번 요청을 받지 못해요 · 다른 업체를 담아 주세요",
        link=f"/projects/{v.project_id}/visits",
        dedup_key=f"visit:{v.id}:declined",
        project_id=v.project_id,
    )
    await s.commit()
    return await vendor_visit(s, vendor, visit_id, today)


async def mark_seen(s: AsyncSession, vendor: User, visit_id: uuid.UUID) -> None:
    """'새 요청' 표시 지우기: 처음 열었을 때만 시각을 찍는다 (화면이 요청을 열 때 부른다)."""
    v = await _mine(s, vendor, visit_id)
    await repo.mark_seen(s, v.id, now_utc())
    await s.commit()


# ---- 업체 작업함 ----


def _home(sgg: str, std: StandardQuote | None, occupied: bool) -> str:
    """노원구 · 32평 · 빈 집"""
    parts = [sgg]
    if std is not None:
        parts.append(f"{_number(std.pyeong)}평")
    parts.append("짐 있는 집" if occupied else "빈 집")
    return " · ".join(parts)


def _unit(b: ProjectBrief) -> str | None:
    """서울 노원구 상계주공 101동 1203호"""
    if not (b.apt_name and b.dong and b.ho):
        return None
    dong = b.dong if b.dong.endswith("동") else f"{b.dong}동"
    ho = b.ho if b.ho.endswith("호") else f"{b.ho}호"
    return f"{b.region} {b.apt_name} {dong} {ho}"


def _row(
    v: Visit,
    b: ProjectBrief,
    std: StandardQuote | None,
    last: datetime | None,
    today: date,
    *,
    address: bool = False,
) -> dict:
    shown = customer_contact_visible(v, today)
    return {
        "id": v.id,
        "received_at": v.created_at,
        "code": b.code,
        "trade": v.trade,
        "grade": std.grade if std is not None else None,
        "region": b.region,
        "area_name": b.sgg,
        "pyeong": std.pyeong if std is not None else None,
        "status": v.status,
        "new": v.status == "requested" and v.vendor_seen_at is None,
        "share_contact": v.share_contact,
        "closed_at": last if v.status in DONE else None,
        "decline_code": v.decline_code,
        "close_reason": v.close_reason,
        "waiting_days": days_since(last, today) if v.status == "quoted" and last else None,
        "customer": CustomerContactOut(
            name=b.owner_name, phone=b.owner_phone, address=_unit(b) if address else None
        )
        if shown
        else None,
    }


async def _context(
    s: AsyncSession, visits: list[Visit]
) -> tuple[dict[uuid.UUID, ProjectBrief], dict[tuple[uuid.UUID, str], StandardQuote]]:
    ids = list({v.project_id for v in visits})
    return await project_service.briefs(s, ids), await quote_service.latest_of(s, ids)


async def inbox(
    s: AsyncSession,
    vendor: User,
    tab: str,
    today: date,
    before: datetime | None = None,
    limit: int = 20,
) -> VendorVisitPage:
    """할 일: 새 요청부터, 그다음 받은 날 순 · 기다림: 오래 기다린 순 · 끝남: 최근 순(limit씩)."""
    done = tab == "done"
    pairs = await repo.of_vendor(
        s, vendor.id, TABS[tab], before if done else None, limit if done else None
    )
    if tab == "todo":
        pairs.sort(key=lambda x: (x[0].vendor_seen_at is not None, x[0].created_at))
    elif tab == "waiting":
        pairs.sort(key=lambda x: x[1])
    briefs, stds = await _context(s, [v for v, _ in pairs])
    items = [
        VendorVisitRow(
            **_row(v, briefs[v.project_id], stds.get((v.project_id, v.trade)), at, today)
        )
        for v, at in pairs
    ]
    more = done and len(pairs) == limit
    return VendorVisitPage(items=items, next_before=pairs[-1][1] if more else None)


async def inbox_summary(s: AsyncSession, vendor: User) -> InboxSummaryOut:
    n = await repo.counts_of_vendor(s, vendor.id)
    recent = await repo.recent_moves(s, vendor.id, now_utc() - timedelta(days=RECENT_DAYS))
    return InboxSummaryOut(
        todo=n.get("requested", 0),
        waiting=n.get("quoted", 0),
        done=sum(n.get(st, 0) for st in DONE),
        jobs=0,
        recent=RecentOut(
            requested=recent.get("requested", 0),
            quoted=recent.get("quoted", 0),
            chosen=recent.get("chosen", 0),
        ),
    )


async def vendor_visit(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, today: date
) -> VendorVisitDetailOut:
    """업체가 보는 요청 자세히: 집 · 희망 시기 · 남긴 말, 고객이 보낸 연락처(열려 있을 때만)."""
    v = await _mine(s, vendor, visit_id)
    briefs, stds = await _context(s, [v])
    b, std = briefs[v.project_id], stds.get((v.project_id, v.trade))
    last = (await repo.last_events(s, [v.id])).get(v.id)
    return VendorVisitDetailOut(
        **_row(v, b, std, last, today, address=True),
        area_m2=std.area_m2 if std is not None else None,
        area_basis=std.area_basis if std is not None else None,
        occupied=b.occupied,
        home_text=_home(b.sgg, std, b.occupied),
        when_text=_when(b.when),
        message=v.message,
    )


# ---- 업체 실측 견적서: 임시 저장 · 보내기 (견적서 칸은 quote.service, 요청 상태는 여기서) ----

CLOSED_FOR_QUOTE = {
    "cancelled": "고객이 실측 요청을 취소해서 보낼 수 없어요.",
    "declined": "못 받는다고 한 요청이에요.",
    "closed": "닫힌 요청이라 견적서를 보낼 수 없어요.",
    "chosen": "고객이 확정해서 다시 올릴 수 없어요.",
}


async def _locked_mine(s: AsyncSession, vendor: User, visit_id: uuid.UUID) -> Visit:
    v = await repo.lock(s, visit_id)
    if v is None or v.vendor_id != vendor.id:
        raise AppError(404, "not_found", "실측 요청을 찾을 수 없어요.")
    return v


async def quote_board(s: AsyncSession, vendor: User, visit_id: uuid.UUID) -> QuoteBoardOut:
    v = await _mine(s, vendor, visit_id)
    tax = await vendor_service.tax_kind_of(s, vendor.id)
    draft, sent = await quote_service.vendor_quotes(s, v.id)
    return QuoteBoardOut(
        visit_id=v.id,
        visit_status=v.status,
        tax_kind=tax,
        vat_modes=["exempt"] if tax == "exempt" else list(VAT_MODES),
        files_max=QUOTE_FILES_MAX,
        days_max=JOB_MAX_DAYS,
        draft=draft,
        sent=sent,
    )


async def save_quote(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, data: QuoteDraftIn, today: date
) -> QuoteBoardOut:
    """임시 저장 (요청함 · 견적서 옴일 때만). 금액은 계산 엔진이 공급가 · 부가세 · 합계로 나눈다."""
    v = await _locked_mine(s, vendor, visit_id)
    if v.status not in ("requested", "quoted"):
        raise AppError(409, "invalid_state", CLOSED_FOR_QUOTE[v.status])
    exempt = await vendor_service.tax_kind_of(s, vendor.id) == "exempt"
    try:
        await quote_service.save_draft(s, v.id, vendor.id, data, today, exempt)
        await s.commit()
    except IntegrityError as exc:  # 그사이 다른 곳에서 먼저 저장해 DB 제약에 걸렸다
        await s.rollback()
        raise AppError(409, "stale", "다른 곳에서 먼저 바꿨어요. 다시 열어 주세요.") from exc
    return await quote_board(s, vendor, visit_id)


async def send_quote(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, today: date
) -> QuoteBoardOut:
    """견적서 보내기. 처음이면 requested → quoted, 견적서 옴이면 다시 올리기(quoted → quoted).
    다시 올리기는 visits.quote_ver가 지금 본 버전일 때만 새 버전으로 바꾼다(확정 뒤에는 409)."""
    await project_service.lock(s, (await _mine(s, vendor, visit_id)).project_id)  # 프로젝트 → 요청
    v = await _locked_mine(s, vendor, visit_id)
    if v.status not in ("requested", "quoted"):
        raise AppError(409, "invalid_state", CLOSED_FOR_QUOTE[v.status])
    again = v.status == "quoted"
    if again and not await quote_service.has_draft(s, v.id):
        raise AppError(
            409, "already_sent", "이미 보낸 견적서예요. 고쳐서 임시 저장한 뒤 다시 올려 주세요."
        )
    q = await quote_service.seal_draft(s, v.id, today)
    ok = await repo.set_quote_ver(s, v.id, again=again, seen=v.quote_ver, new=q.version)
    if not ok:
        raise AppError(409, "invalid_state", "다른 곳에서 먼저 바꿨어요. 다시 열어 주세요.")
    s.add(
        VisitEvent(
            visit_id=v.id,
            from_status=v.status,
            to_status="quoted",
            by_id=vendor.id,
            code="resent" if again else None,
        )
    )
    verb = "다시 올렸어요" if again else "보냈어요"
    await notify_service.add(
        s,
        user_id=(await project_service.briefs(s, [v.project_id]))[v.project_id].owner_id,
        kind="quote_resent" if again else "quote_sent",
        body=f"{i_ga(v.vendor_name)} 실측 견적서를 {verb} · {TRADE_LABEL[v.trade]}",
        link=f"/projects/{v.project_id}/quotes?trade={v.trade}",
        dedup_key=f"quote:{q.id}",
        project_id=v.project_id,
    )
    await s.commit()
    return await quote_board(s, vendor, visit_id)


# ---- 고객 견적서 비교 · 견적서 파일 내주기 ----

COMPARED = (
    "requested",
    "quoted",
    "chosen",
)  # 기다림 · 받음 · 확정 (닫힌 요청은 비교에 넣지 않는다)


def _changed(latest, before) -> list[str]:
    if before is None:
        return []
    out = [k for k in ("total", "days", "valid_until") if getattr(latest, k) != getattr(before, k)]
    return out + (["files"] if len(latest.files) != len(before.files) else [])


async def compare(
    s: AsyncSession, user: User, project_id: uuid.UUID, trade: str, today: date
) -> CompareOut:
    """한 공정의 실측 견적 비교. 받은 견적서는 처음 받은 순, 그다음 견적서를 기다리는 곳."""
    p, std, _ = await _standard(s, user, project_id, trade)
    every = await repo.of_project(s, p.id, None)
    rows = [v for v in every if v.trade == trade and v.status in COMPARED]
    versions = await quote_service.sent_versions(s, [v.id for v in every])
    out: list[CompareRowOut] = []
    for v in rows:
        sent = versions.get(v.id, [])
        latest = sent[0] if sent else None
        pct, way = _vs(latest.total, std.total) if latest else (None, None)
        out.append(
            CompareRowOut(
                visit_id=v.id,
                vendor_id=v.vendor_id,
                vendor_name=v.vendor_name,
                status=v.status,
                requested_at=v.created_at,
                seen_ver=v.quote_ver,
                latest=latest,
                history=[
                    QuoteVersionBrief(
                        version=q.version,
                        sent_at=q.sent_at,
                        total=q.total,
                        days=q.days,
                        valid_until=q.valid_until,
                        file_count=len(q.files),
                    )
                    for q in sent[1:]
                ],
                changed=_changed(latest, sent[1]) if len(sent) > 1 else [],
                estimate_total=v.estimate_total,
                vs_standard=pct,
                vs_direction=way,
                expired=bool(latest and latest.valid_until and latest.valid_until < today),
            )
        )
    first_sent = {v.id: versions[v.id][-1].sent_at for v in rows if versions.get(v.id)}
    out.sort(
        key=lambda r: (
            r.latest is None,
            first_sent.get(r.visit_id) or r.requested_at,
            r.requested_at,
        )
    )
    trades = [t for t in ("mokgong", "dobae") if getattr(p.trades, t) is not None]
    return CompareOut(
        project_id=p.id,
        trade=trade,
        standard_total=std.total,
        formula_ver=std.formula_ver,
        price_ver=std.price_ver,
        computed_at=std.created_at,
        sent_counts={
            t: sum(1 for v in every if v.trade == t and v.status in COMPARED and versions[v.id])
            for t in trades
        },
        vendors=out,
    )


async def customer_quote_file(
    s: AsyncSession, user: User, project_id: uuid.UUID, quote_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    """그 요청의 고객에게 보낸 버전의 파일만 내준다. 임시 저장본 · 다른 집 파일은 404."""
    p = await project_service.get_for(s, user, project_id)
    got = await quote_service.quote_file(s, file_id, quote_id)
    v = await repo.get(s, got[0].visit_id) if got else None
    if (
        got is None
        or got[0].id != quote_id
        or got[0].sent_at is None
        or v is None
        or v.project_id != p.id
    ):
        raise AppError(404, "not_found", "파일을 찾을 수 없어요.")
    return await files_service.respond(got[1])


async def vendor_quote_file(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    """업체 본인의 견적서 파일 (임시 저장본 포함). 다른 요청 · 다른 업체 파일은 404."""
    v = await _mine(s, vendor, visit_id)
    got = await quote_service.quote_file(s, file_id)
    if got is None or got[0].visit_id != v.id:
        raise AppError(404, "not_found", "파일을 찾을 수 없어요.")
    return await files_service.respond(got[1])


# ---- 업체 확정에 쓰는 공개 함수 (deal은 schedule.service가 만든다) ----

QUOTE_CHANGED = "업체가 견적서를 다시 올렸어요. 새 견적서를 보고 다시 확정해 주세요."
NOT_CHOOSABLE = {
    "requested": "아직 견적서가 오지 않았어요.",
    "cancelled": "취소된 실측의 견적서라 고를 수 없어요.",
    "declined": "업체가 받지 못한 요청이라 고를 수 없어요.",
    "closed": "닫힌 실측의 견적서라 고를 수 없어요.",
    "chosen": "이미 업체를 확정했어요.",
}


async def in_project(s: AsyncSession, project_id: uuid.UUID, visit_id: uuid.UUID) -> Visit:
    """그 집의 요청 (아니면 404). 권한은 부르는 쪽이 프로젝트로 먼저 확인한다."""
    v = await repo.get(s, visit_id)
    if v is None or v.project_id != project_id:
        raise AppError(404, "not_found", "실측 요청을 찾을 수 없어요.")
    return v


async def choose(s: AsyncSession, user: User, v: Visit, seen_ver: int) -> None:
    """견적서 옴 → 확정. 고객이 본 버전(seen_ver)이 지금 버전일 때만 (다시 올렸으면 409)."""
    if v.status != "quoted":
        code = "already_chosen" if v.status == "chosen" else "not_choosable"
        raise AppError(409, code, NOT_CHOOSABLE[v.status])
    if v.quote_ver != seen_ver or not await repo.choose(s, v.id, seen_ver):
        raise AppError(409, "quote_changed", QUOTE_CHANGED)
    s.add(VisitEvent(visit_id=v.id, from_status="quoted", to_status="chosen", by_id=user.id))


async def close_others(
    s: AsyncSession, project_id: uuid.UUID, trade: str, keep: uuid.UUID, by: User
) -> list[uuid.UUID]:
    """다른 업체를 확정하면 같은 공정의 살아 있는 요청을 닫는다(other_chosen). 연락처는 바로 가려진다."""
    closed = []
    for v in await repo.live(s, project_id, trade):
        if v.id == keep or v.status not in ("requested", "quoted"):
            continue
        ok = await repo.set_status(
            s,
            v.id,
            allowed_from=("requested", "quoted"),
            values={"status": "closed", "close_reason": "other_chosen"},
        )
        if not ok:
            raise AppError(409, "stale", "그사이 상태가 바뀌었어요. 새로 불러올게요.")
        s.add(
            VisitEvent(
                visit_id=v.id,
                from_status=v.status,
                to_status="closed",
                by_id=by.id,
                code="other_chosen",
            )
        )
        if v.vendor_id is not None:
            await notify_service.add(
                s,
                user_id=v.vendor_id,
                kind="visit_closed",
                body="고객이 다른 업체로 정했어요",
                link=f"/vendor/requests/{v.id}",
                dedup_key=f"visit:{v.id}:closed",
            )
        closed.append(v.id)
    return closed


async def visits_by_id(s: AsyncSession, visit_ids: list[uuid.UUID]) -> dict[uuid.UUID, Visit]:
    return await repo.by_ids(s, visit_ids)


async def rows_for(
    s: AsyncSession, visit_ids: list[uuid.UUID], today: date
) -> dict[uuid.UUID, VendorVisitRow]:
    """업체 작업함 줄 (공사 탭이 확정 정보를 붙여 쓴다). 고객 연락처 규칙은 그대로."""
    visits = list((await repo.by_ids(s, visit_ids)).values())
    briefs, stds = await _context(s, visits)
    last = await repo.last_events(s, [v.id for v in visits])
    return {
        v.id: VendorVisitRow(
            **_row(
                v, briefs[v.project_id], stds.get((v.project_id, v.trade)), last.get(v.id), today
            )
        )
        for v in visits
    }


# ---- 다시 고르기: 이 공정의 살아 있는 요청을 모두 닫는다 (확정 전은 여기서, 확정 뒤는 schedule.service) ----

RESELECTED = "고객이 업체를 다시 고르기로 했어요"


async def close_for_reselect(
    s: AsyncSession, project_id: uuid.UUID, trade: str, by: User
) -> ReselectOut:
    """요청함 · 견적서 옴 · 확정을 닫는다(reselected). 연락처는 바로 가려지고 칸 3개가 다시 빈다.
    받은 견적서는 지우지 않는다. 확정했던 업체 알림은 부르는 쪽(deal)이 보낸다. commit은 부르는 쪽이."""
    closed = []
    for v in await repo.live(s, project_id, trade):
        ok = await repo.set_status(
            s,
            v.id,
            allowed_from=(v.status,),
            values={"status": "closed", "close_reason": "reselected"},
        )
        if not ok:
            raise AppError(409, "stale", "그사이 상태가 바뀌었어요. 새로 불러올게요.")
        s.add(
            VisitEvent(
                visit_id=v.id,
                from_status=v.status,
                to_status="closed",
                by_id=by.id,
                code="reselected",
            )
        )
        if v.status != "chosen" and v.vendor_id is not None:
            await notify_service.add(
                s,
                user_id=v.vendor_id,
                kind="visit_closed",
                body=RESELECTED,
                link=f"/vendor/requests/{v.id}",
                dedup_key=f"visit:{v.id}:closed",
            )
        closed.append(v.id)
    return ReselectOut(trade=trade, closed=closed, slots_left=SLOTS)


async def reselect(
    s: AsyncSession, user: User, project_id: uuid.UUID, data: ReselectIn
) -> ReselectOut:
    """견적 비교에서 다시 고르기 (확정 전): 프로젝트 잠금 → 이 공정의 요청을 모두 닫기 → 이력 · 알림.
    확정이 살아 있으면 409(공사 날짜 화면의 다시 고르기를 쓴다)."""
    p = await project_service.get_for(s, user, project_id)
    await project_service.lock_for_visit(s, p.id)
    live = await repo.live(s, p.id, data.trade)
    if any(v.status == "chosen" for v in live):
        raise AppError(409, "already_chosen", NOT_CHOOSABLE["chosen"])
    if not live:
        raise AppError(409, "invalid_state", "닫을 실측 요청이 없어요.")
    out = await close_for_reselect(s, p.id, data.trade, user)
    await s.commit()
    return out


async def set_contact_until(s: AsyncSession, visit_id: uuid.UUID, until: date) -> None:
    """확정한 요청의 연락처 기한을 적는다 (업체가 '공사 끝냈어요'를 올릴 때마다 새로).
    서로 연락처를 보여도 되는지는 contact_visible이 이 값으로 정한다. commit은 부르는 쪽이."""
    if not await repo.set_status(
        s, visit_id, allowed_from=("chosen",), values={"contact_until": until}
    ):
        raise AppError(409, "stale", "그사이 상태가 바뀌었어요. 새로 불러올게요.")


# ---- 내 공사 한눈에 · 서류에 쓰는 공개 함수 ----


async def trade_facts(s: AsyncSession, project_id: uuid.UUID) -> dict[str, VisitFactsOut]:
    """공정마다 이번 고르기의 요청 · 견적서 수와 때 (권한은 부르는 쪽이 먼저 확인한다)"""
    every = [
        v
        for v in await repo.of_project(s, project_id, None)
        if not (v.status == "closed" and v.close_reason == "reselected")
    ]
    versions = await quote_service.sent_versions(s, [v.id for v in every])
    last = await repo.last_events(s, [v.id for v in every])
    out: dict[str, VisitFactsOut] = {}
    for t in {v.trade for v in every}:
        mine = sorted((v for v in every if v.trade == t), key=lambda v: v.created_at)
        sent = [v for v in mine if versions.get(v.id)]
        live = [v for v in sent if v.status in ("quoted", "chosen")]
        waiting = [v for v in mine if v.status == "requested"]
        out[t] = VisitFactsOut(
            trade=t,
            asked=len(mine),
            asked_at=mine[0].created_at if mine else None,
            quotes=len(sent),
            waiting=len(waiting),
            quoted_at=max((versions[v.id][0].sent_at for v in sent), default=None),
            quoted_names=[v.vendor_name for v in live],
            waiting_names=[v.vendor_name for v in waiting],
            last_at=max((last[v.id] for v in mine if v.id in last), default=None),
        )
    return out


async def quote_docs(s: AsyncSession, project_id: uuid.UUID) -> list[VisitQuotesOut]:
    """서류: 견적서를 보낸 요청마다 버전들 (닫힌 요청 포함, 처음 받은 순)"""
    every = await repo.of_project(s, project_id, None)
    versions = await quote_service.sent_versions(s, [v.id for v in every])
    rows = [v for v in every if versions.get(v.id)]
    rows.sort(key=lambda v: versions[v.id][-1].sent_at)
    return [
        VisitQuotesOut(
            visit_id=v.id,
            trade=v.trade,
            vendor_name=v.vendor_name,
            status=v.status,
            close_reason=v.close_reason,
            versions=versions[v.id],
        )
        for v in rows
    ]
