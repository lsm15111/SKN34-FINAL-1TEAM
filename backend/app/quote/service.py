"""표준견적서(믿집 계산)와 업체 실측 견적서.

표준견적서는 처음 볼 때 계산해 저장하고, 집 정보(rev) · 산식 · 단가 · 시장 가격 · 공간 몫 판이 그대로면
저장본을 쓴다. 하나라도 바뀌면 새 버전을 쌓는다(예전 버전은 남는다). 숫자는 모두 계산 엔진이 만든다.
v3(C07 · C60 · D01): 도배는 calc.dobae.standard_v3 — 도배지 줄만 벽지 평 × 시장 평균 가격(market_ver 고정),
부분 공사는 공간 몫 표(share_ver 고정)로 벽 · 천장 면적을 줄인다. v2 공사는 전체 공사(벽 + 천장)로 본다.
v4(ADR 0004): 도배 단가 판은 계산 엔진(calc.dobae.pick_profile)이 공사 조건(고른 목공 항목 · 모은 조건)으로
고른 기준의 판이다. 모은 조건이 바뀌어 기준이 바뀌면 판(price_ver)이 달라져 새 버전을 쌓는다.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import column, delete, func, select, table, text, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.calc import deadline, dobae, mokgong
from app.calc.common import FORMULA_VERSION, Money, Step, from_entered, sum_days, sum_won
from app.calc.quote_diff import budget_fit, budget_gap
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.calc.standard_quote import house_area, house_pyeong
from app.files import service as files_service
from app.files.models import File
from app.jobs import service as jobs_service
from app.notify import catalog
from app.notify import service as notify_service
from app.notify.models import Notification
from app.project import service as project_service
from app.project.schemas import ProjectOut
from app.quote.models import (
    StandardQuote,
    StandardQuoteLine,
    VendorQuote,
    VendorQuoteFile,
)
from app.quote.schemas import (
    BudgetOut,
    QuoteBriefOut,
    QuoteDraftIn,
    QuoteFileOut,
    StandardLineOut,
    StandardOut,
    StandardTradeOut,
    VendorQuoteOut,
)
from app.refprice.book import DOBAE_BY_VER, DOBAE_PROFILES, MOKGONG_2026H2
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market
from app.shared.clock import SEOUL, now_utc
from app.shared.errors import AppError
from app.shared.ids import uuid7
from app.vendor import service as vendor_service

ROOM = "방"  # 방문 개수: 목공을 고른 공간 중 이름에 '방'이 든 곳
FULL_FACES = ("wall", "ceiling")
VALID_SOON = "quote_valid_soon"  # 기한 일 kind (jobs.models.KINDS) · 알림 kind (notify.catalog)


@dataclass(frozen=True)
class TradeCalc:
    """공정 하나를 이 집 정보로 계산한 결과(저장하기 전)."""

    trade: str
    grade: str | None
    lines: list
    supply: int
    vat: int
    total: int
    man_day: Decimal
    crew: int
    steps: list[Step]
    notes: list[str]
    # v3: 만든 때 범위 · 면 · 고른 공간 사본, 공간 몫 표 판(부분만) · 벽지 시장 가격 판(도배만)
    scope: str = "full"
    faces: tuple[str, ...] = FULL_FACES
    spaces: tuple[str, ...] = ()
    share_ver: str | None = None
    market_ver: str | None = None
    days: Decimal | None = None  # 이 공정만 했을 때 예상 일수 (계산 엔진, 반나절 단위)
    price_ver: str = MOKGONG_2026H2.version  # 이 공정 단가 판 (도배는 고른 기준의 판)


def _area(p: ProjectOut) -> tuple[Decimal, str]:
    return house_area(p.size.band, p.size.m2, p.size.basis, HOUSE_2026H2)


def home_v3(p: ProjectOut, grade: str | None = None) -> dobae.HomeV3:
    """저장한 공사 → v3 도배 계산 입력. v2 공사(기본 정보가 없음)는 전체 공사(벽 + 천장)로 본다.
    grade를 주면 그 벽지로 바꿔 센다(다른 벽지 미리 보기)."""
    area, basis = _area(p)
    h = p.home
    g = grade or (h.grade if h else None) or (p.trades.dobae.grade if p.trades.dobae else None)
    g = g or "basic"
    if h is None:
        return dobae.HomeV3(area, basis, g, p.occupied, balcony_ext=p.balcony_ext)
    return dobae.HomeV3(
        area, basis, g, p.occupied, h.scope, tuple(h.spaces), tuple(h.faces), p.balcony_ext, h.rooms
    )


def work_facts(p: ProjectOut, said: Mapping[str, str] | None = None) -> dobae.WorkFacts:
    """기준 고르기 입력: 공사에 고른 목공 항목 + 모은 조건(project.service.conditions)."""
    items = tuple(p.trades.mokgong.items) if p.trades.mokgong else ()
    return dobae.WorkFacts(items, dict(said or {}))


def standard_v3(
    h: dobae.HomeV3, crew: int | None = None, pick: dobae.ProfilePick | None = None
) -> dobae.StandardV3:
    """v3 도배 표준견적서 (계산 엔진 + refprice 판). 손님 계산 · 가견적도 같은 함수 꼴을 쓴다.
    pick(기준 고르기 결과)이 없으면 공사 조건이 없는 집으로 보고 계산 엔진이 고른 기준(도배만 하는 공사)."""
    pick = pick or dobae.pick_profile(dobae.WorkFacts())
    base = DOBAE_PROFILES[pick.profile]
    dp = replace(base, crew=crew) if crew else base
    return dobae.standard_v3(
        h, dp, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2, pick.why
    )


def calc_trades(
    p: ProjectOut,
    crews: Mapping[str, int] | None = None,
    said: Mapping[str, str] | None = None,
) -> list[TradeCalc]:
    """이 집 정보로 고른 공정을 계산한다(목공 → 도배 순서). 공정표도 이 결과를 쓴다.
    crews를 주면 그 공정의 하루 인원을 바꿔 기간을 센다(업체가 적은 인원).
    said(모은 조건)는 도배 기준 고르기에 쓴다. 품 · 기간은 기준과 상관없어 공정표는 비워도 같다."""
    crews = crews or {}
    mp = replace(MOKGONG_2026H2, crew=crews["mokgong"]) if "mokgong" in crews else MOKGONG_2026H2
    pick = dobae.pick_profile(work_facts(p, said))
    dp = DOBAE_PROFILES[pick.profile]
    dp = replace(dp, crew=crews["dobae"]) if "dobae" in crews else dp
    area, basis = _area(p)
    out: list[TradeCalc] = []
    if p.trades.mokgong:
        names = {sp.id: sp.name for sp in p.spaces}
        rooms = sum(1 for sid in p.trades.mokgong.spaces if ROOM in names.get(sid, ""))
        items = tuple(p.trades.mokgong.items)
        m = mokgong.quote(
            mokgong.MokgongInput(
                area, basis, items, p.occupied, doors=max(rooms, 1) if "door" in items else 0
            ),
            mp,
        )
        notes = list(m.assumptions)
        if "door" in items:
            notes.append(f"방문은 목공을 고른 방 수({max(rooms, 1)}개)로 잡았어요.")
        out.append(
            TradeCalc(
                "mokgong",
                None,
                m.lines,
                m.subtotal,
                m.vat,
                m.total,
                m.man_days,
                mp.crew,
                m.steps,
                notes,
                days=m.days,
                price_ver=mp.version,
            )
        )
    if p.trades.dobae:
        h = home_v3(p)
        v = standard_v3(h, crews.get("dobae"), pick)
        d = v.quote
        out.append(
            TradeCalc(
                "dobae",
                h.grade,
                d.lines,
                d.subtotal,
                d.vat,
                d.total,
                d.man_days,
                dp.crew,
                d.steps,
                list(d.assumptions),
                scope=h.scope,
                faces=tuple(h.faces),
                spaces=tuple(h.spaces),
                share_ver=v.share_ver,
                market_ver=v.market_ver,
                days=d.days,
                price_ver=dp.version,
            )
        )
    return out


async def _latest(s: AsyncSession, project_id: uuid.UUID) -> dict[str, StandardQuote]:
    sub = (
        select(StandardQuote.trade, func.max(StandardQuote.version).label("v"))
        .where(StandardQuote.project_id == project_id)
        .group_by(StandardQuote.trade)
        .subquery()
    )
    q = select(StandardQuote).join(
        sub, (StandardQuote.trade == sub.c.trade) & (StandardQuote.version == sub.c.v)
    )
    q = q.where(StandardQuote.project_id == project_id)
    return {row.trade: row for row in (await s.scalars(q)).all()}


def _fresh(row: StandardQuote, p: ProjectOut, c: TradeCalc) -> bool:
    return (
        row.project_rev == p.rev
        and row.formula_ver == FORMULA_VERSION
        and row.price_ver == c.price_ver
        and row.market_ver == c.market_ver
        and row.share_ver == c.share_ver
    )


async def ensure_standard(s: AsyncSession, p: ProjectOut) -> dict[str, StandardQuote]:
    """이 집의 최신 표준견적서(공정별). 없거나 바뀌었으면 새 버전을 저장하고 commit한다.
    도배 기준은 모은 조건까지 읽어 고른다(조건이 바뀌어 기준 판이 바뀌면 새 버전)."""
    latest = await _latest(s, p.id)
    said = await project_service.conditions(s, p.id)
    wanted = {t.trade: t for t in calc_trades(p, said=said)}
    stale = [t for t in wanted if t not in latest or not _fresh(latest[t], p, wanted[t])]
    if not stale:
        return {t: latest[t] for t in wanted}
    area, basis = _area(p)
    pyeong = house_pyeong(p.size.band, p.size.m2, p.size.basis, HOUSE_2026H2)
    try:
        for trade in stale:
            c = wanted[trade]
            row = StandardQuote(
                project_id=p.id,
                trade=trade,
                version=(latest[trade].version + 1) if trade in latest else 1,
                project_rev=p.rev,
                formula_ver=FORMULA_VERSION,
                price_ver=c.price_ver,
                grade=c.grade,
                area_m2=area,
                area_basis=basis,
                pyeong=pyeong,
                supply=c.supply,
                vat=c.vat,
                total=c.total,
                man_day=c.man_day,
                crew=c.crew,
                notes=c.notes,
                scope=c.scope,
                faces=list(c.faces),
                space_keys=list(c.spaces),
                share_ver=c.share_ver,
                market_ver=c.market_ver,
            )
            s.add(row)
            await s.flush()
            s.add_all(
                [
                    StandardQuoteLine(
                        quote_id=row.id,
                        key=ln.key,
                        name=ln.name,
                        qty=ln.qty,
                        unit=ln.unit,
                        unit_price=ln.unit_price,
                        amount=ln.amount,
                        state=ln.state,
                        basis=ln.basis,
                        source=ln.source[:120],
                        sort=i,
                    )
                    for i, ln in enumerate(c.lines)
                ]
            )
        await s.commit()
    except IntegrityError:  # 같은 집을 동시에 두 번 열면 먼저 저장한 버전을 쓴다
        await s.rollback()
    latest = await _latest(s, p.id)
    return {t: latest[t] for t in wanted if t in latest}


async def _lines(s: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[StandardQuoteLine]]:
    rows = (
        await s.scalars(
            select(StandardQuoteLine)
            .where(StandardQuoteLine.quote_id.in_(ids))
            .order_by(StandardQuoteLine.sort)
        )
    ).all()
    out: dict[uuid.UUID, list[StandardQuoteLine]] = {i: [] for i in ids}
    for ln in rows:
        out[ln.quote_id].append(ln)
    return out


async def latest_of(
    s: AsyncSession, project_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, str], StandardQuote]:
    """프로젝트 · 공정마다 저장된 최신 표준견적서 (새로 계산하지 않는다). 평 · 면적 표시에 쓴다."""
    if not project_ids:
        return {}
    sub = (
        select(
            StandardQuote.project_id,
            StandardQuote.trade,
            func.max(StandardQuote.version).label("v"),
        )
        .where(StandardQuote.project_id.in_(project_ids))
        .group_by(StandardQuote.project_id, StandardQuote.trade)
        .subquery()
    )
    q = select(StandardQuote).join(
        sub,
        (StandardQuote.project_id == sub.c.project_id)
        & (StandardQuote.trade == sub.c.trade)
        & (StandardQuote.version == sub.c.v),
    )
    return {(r.project_id, r.trade): r for r in (await s.scalars(q)).all()}


async def standard_trade(
    s: AsyncSession, p: ProjectOut, trade: str
) -> tuple[StandardQuote, list[StandardQuoteLine]] | None:
    """이 집 최신 표준견적서 한 공정과 그 줄 (그 공정을 고르지 않았으면 None). 가견적 수량에 쓴다."""
    row = (await ensure_standard(s, p)).get(trade)
    if row is None:
        return None
    return row, (await _lines(s, [row.id]))[row.id]


def profile_out(row: StandardQuote) -> dict[str, str | None]:
    """저장한 표준견적서의 도배 기준(판에 든 것, ADR 0004). 목공 · 옛 판(2026H2-rooms)은 비운다."""
    dp = DOBAE_BY_VER.get(row.price_ver) if row.trade == "dobae" else None
    pf = dp.profile if dp is not None else None
    return {"profile": pf.key if pf else None, "profile_name": pf.name if pf else None}


async def standard_for(s: AsyncSession, user: User, project_id: uuid.UUID) -> StandardOut:
    """GET /projects/{id}/standard: 만든 사람 · 관리자만(남의 것은 404)."""
    p = await project_service.get_for(s, user, project_id)
    rows = await ensure_standard(s, p)
    order = [t for t in ("mokgong", "dobae") if t in rows]
    lines = await _lines(s, [rows[t].id for t in order])
    trades = [
        StandardTradeOut(
            trade=t,
            version=rows[t].version,
            grade=rows[t].grade,
            lines=[
                StandardLineOut(
                    key=ln.key,
                    name=ln.name,
                    qty=ln.qty,
                    unit=ln.unit,
                    unit_price=ln.unit_price,
                    amount=ln.amount,
                    state=ln.state,
                    source=ln.source,
                    basis=ln.basis,
                )
                for ln in lines[rows[t].id]
            ],
            supply=rows[t].supply,
            vat=rows[t].vat,
            total=rows[t].total,
            man_day=rows[t].man_day,
            crew=rows[t].crew,
            notes=list(rows[t].notes),
            **profile_out(rows[t]),
        )
        for t in order
    ]
    supply = sum_won(x.supply for x in trades)
    vat = sum_won(x.vat for x in trades)
    total = sum_won(x.total for x in trades)
    budget = None
    if p.budget:
        status, over = budget_gap(total, p.budget)
        budget = BudgetOut(band=p.budget, status=status, over_by=over)
    first = rows[order[0]]
    main = rows.get("dobae", first)  # v3 범위 · 면 · 판은 도배 줄에서
    # 예상 일수는 저장 칸이 없어 같은 집 정보로 계산 엔진을 다시 돌린다(위 저장 행과 같은 판 · 같은 값)
    calc_days = {c.trade: c.days for c in calc_trades(p)}
    days = sum_days(calc_days[t] or Decimal(0) for t in order)
    return StandardOut(
        project_id=p.id,
        code=p.code,
        project_rev=p.rev,
        formula_ver=first.formula_ver,
        price_ver=first.price_ver,
        computed_at=max(rows[t].created_at for t in order),
        area_m2=first.area_m2,
        area_basis=first.area_basis,
        pyeong=first.pyeong,
        trades=trades,
        supply=supply,
        vat=vat,
        total=total,
        budget=budget,
        scope=main.scope,
        spaces=list(main.space_keys),
        faces=list(main.faces),
        share_ver=main.share_ver,
        market_ver=main.market_ver,
        budget_fit=budget_fit(total, p.budget_won),
        days=days,
    )


# ---- 업체 실측 견적서: 업체 양식 파일 + 요약 칸. 실측 요청(visit) 확인 · 상태 바꾸기는 visit.service가 한다 ----

MISSING = {
    "files": "견적서 파일을 하나 이상 올려 주세요.",
    "entered_amount": "낼 금액을 넣어 주세요.",
    "vat_mode": "넣은 금액이 부가세 포함인지 골라 주세요.",
}  # 보낼 때 꼭 있어야 하는 칸. 실측한 날 · 공사 기간 · 유효기간은 선택


async def _quote_files(
    s: AsyncSession, quote_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[VendorQuoteFile, File]]]:
    out: dict[uuid.UUID, list[tuple[VendorQuoteFile, File]]] = {i: [] for i in quote_ids}
    if not quote_ids:
        return out
    q = (
        select(VendorQuoteFile, File)
        .join(File, File.id == VendorQuoteFile.file_id)
        .where(VendorQuoteFile.quote_id.in_(quote_ids))
        .order_by(VendorQuoteFile.sort)
    )
    for qf, f in (await s.execute(q)).all():
        out[qf.quote_id].append((qf, f))
    return out


def _quote_out(q: VendorQuote, files: list[tuple[VendorQuoteFile, File]]) -> VendorQuoteOut:
    return VendorQuoteOut(
        id=q.id,
        code=q.code,
        version=q.version,
        sent_at=q.sent_at,
        measured_on=q.measured_on,
        entered_amount=q.entered_amount,
        vat_mode=q.vat_mode,
        supply=q.supply,
        vat=q.vat,
        total=q.total,
        days=q.days,
        valid_until=q.valid_until,
        created_at=q.created_at,
        updated_at=q.updated_at,
        incl_removal=q.incl_removal,
        incl_waste=q.incl_waste,
        paper_spec=q.paper_spec,
        warranty_months=q.warranty_months,
        files=[
            QuoteFileOut(
                file_id=f.id,
                filename=f.filename,
                content_type=f.content_type,
                size=f.size,
                sort=qf.sort,
            )
            for qf, f in files
        ],
    )


async def _versions(s: AsyncSession, visit_id: uuid.UUID) -> list[VendorQuote]:
    q = (
        select(VendorQuote)
        .where(VendorQuote.visit_id == visit_id)
        .order_by(VendorQuote.version.desc())
        .execution_options(populate_existing=True)
    )
    return list((await s.execute(q)).scalars().all())


async def vendor_quotes(
    s: AsyncSession, visit_id: uuid.UUID
) -> tuple[VendorQuoteOut | None, list[VendorQuoteOut]]:
    """(임시 저장본, 보낸 버전들 최신 먼저)"""
    rows = await _versions(s, visit_id)
    files = await _quote_files(s, [r.id for r in rows])
    draft = next((_quote_out(r, files[r.id]) for r in rows if r.sent_at is None), None)
    return draft, [_quote_out(r, files[r.id]) for r in rows if r.sent_at is not None]


async def save_draft(
    s: AsyncSession,
    visit_id: uuid.UUID,
    owner_id: uuid.UUID,
    data: QuoteDraftIn,
    today: date,
    exempt_only: bool,
) -> None:
    """임시 저장본을 통째로 바꾼다(없으면 다음 버전으로 만든다). commit은 부르는 쪽이 한다."""
    if exempt_only and data.vat_mode not in (None, "exempt"):
        raise AppError(422, "vat_mode", "면세 업체는 면세로만 적을 수 있어요.")
    if data.measured_on is not None and data.measured_on > today:
        raise AppError(422, "measured_on", "실측한 날은 오늘까지만 고를 수 있어요.")
    if data.measured_on and data.valid_until and data.valid_until < data.measured_on:
        raise AppError(422, "valid_until", "유효기간은 실측한 날 뒤로 골라 주세요.")
    files = await files_service.owned(s, owner_id, data.file_ids, lock=True)
    if any(i not in files or files[i].kind != "quote_doc" for i in data.file_ids):
        raise AppError(422, "file", "올린 견적서 파일을 다시 확인해 주세요.")
    rows = await _versions(s, visit_id)
    draft = next((r for r in rows if r.sent_at is None), None)
    if data.file_ids:  # 같은 요청의 앞 버전 파일은 다시 붙일 수 있다
        used = (
            select(VendorQuoteFile.file_id)
            .join(VendorQuote, VendorQuote.id == VendorQuoteFile.quote_id)
            .where(VendorQuoteFile.file_id.in_(data.file_ids), VendorQuote.visit_id != visit_id)
        )
        if (await s.execute(used)).first():
            raise AppError(409, "file_used", "다른 견적서에 붙인 파일이에요.")
    if draft is None:
        if rows:  # 다시 올리기: 같은 번호에 버전만 올린다
            code, version = rows[0].code, rows[0].version + 1
        else:
            no = int(await s.scalar(text("select nextval('vendor_quote_code_seq')")))
            code, version = f"Q-{today:%y%m}-{no:04d}", 1
        draft = VendorQuote(id=uuid7(), visit_id=visit_id, code=code, version=version)
        s.add(draft)
    simplified = await _simplified(s, owner_id)
    money = (
        _money(data.entered_amount, data.vat_mode, simplified)
        if data.entered_amount is not None and data.vat_mode is not None
        else None
    )
    draft.measured_on = data.measured_on
    draft.entered_amount = data.entered_amount
    draft.vat_mode = data.vat_mode
    draft.supply, draft.vat, draft.total = (
        (money.supply, money.vat, money.total) if money else (None, None, None)
    )
    draft.days = data.days
    draft.valid_until = data.valid_until
    # v3 '포함됐나요?' 칩 (D21)
    draft.incl_removal = data.incl_removal
    draft.incl_waste = data.incl_waste
    draft.paper_spec = data.paper_spec
    draft.warranty_months = data.warranty_months
    draft.updated_at = now_utc()
    await s.flush()
    await s.execute(delete(VendorQuoteFile).where(VendorQuoteFile.quote_id == draft.id))
    s.add_all(
        [VendorQuoteFile(quote_id=draft.id, file_id=i, sort=n) for n, i in enumerate(data.file_ids)]
    )
    await s.flush()


async def _simplified(s: AsyncSession, vendor_id: uuid.UUID | None) -> bool:
    return vendor_id is not None and await vendor_service.tax_kind_of(s, vendor_id) == "simplified"


def _money(amount: int, mode: str, simplified: bool) -> Money:
    """업체가 적은 금액 → 공급가 · 부가세 · 합계(계산 엔진). 간이과세 업체는 부가세를 따로 붙이지 않아
    낸 금액이 곧 합계다(L02: from_entered(금액, 'included', rate=0))."""
    if simplified:
        return from_entered(amount, "included", rate=Decimal(0))
    return from_entered(amount, mode)


async def _valid_soon_jobs(s: AsyncSession, q: VendorQuote, rows: list[VendorQuote]) -> None:
    """보낸 버전의 유효기간 3일 · 1일 전 18:00 고객 알림 일(D20)을 넣는다(이미 지난 시각은 빼고).
    같은 요청의 앞 버전 일은 거둔다(처리 함수도 최신 버전인지 다시 본다)."""
    now = now_utc()
    for old in rows:
        if old.id != q.id and old.sent_at is not None:
            await jobs_service.cancel(s, now=now, kind=VALID_SOON, ref_id=old.id)
    if q.valid_until is None:
        return
    for at in deadline.valid_soon_at(q.valid_until):
        if at > now:
            await jobs_service.add(s, kind=VALID_SOON, ref_id=q.id, run_at=at)


async def seal_draft(
    s: AsyncSession, visit_id: uuid.UUID, today: date, *, vendor_id: uuid.UUID | None = None
) -> VendorQuote:
    """임시 저장본을 보낸 버전으로 굳힌다. 빠진 칸은 칸별로 422. commit은 부르는 쪽이 한다.
    금액은 보낼 때 계산 엔진으로 한 번 더 센다(간이과세면 부가세 0, L02). 유효기간 알림 일도 같은 트랜잭션에.
    vendor_id를 안 주면 견적서 파일을 올린 업체로 본다(파일은 그 업체 것만 붙는다)."""
    rows = await _versions(s, visit_id)
    draft = next((r for r in rows if r.sent_at is None), None)
    files = (await _quote_files(s, [draft.id]))[draft.id] if draft else []
    missing = [k for k in MISSING if k == "files" and not files]
    if draft is not None:
        missing += [k for k in MISSING if k != "files" and getattr(draft, k) is None]
    else:
        missing = list(MISSING)
    if missing:
        raise AppError(
            422,
            "missing",
            MISSING[missing[0]],
            fields=[{"loc": [k], "msg": MISSING[k]} for k in missing],
        )
    # 0원 견적서는 보내지 않는다(칸 검사를 1원 이상으로 바꾸기 전에 임시 저장한 것 포함, QA P7)
    if draft.entered_amount < 1:
        msg = "낼 금액은 1원 이상으로 넣어 주세요."
        raise AppError(422, "entered_amount", msg, fields=[{"loc": ["entered_amount"], "msg": msg}])
    if draft.valid_until is not None and draft.valid_until < today:
        msg = "견적 유효기간이 지났어요. 날짜를 다시 골라 주세요."
        raise AppError(422, "valid_until", msg, fields=[{"loc": ["valid_until"], "msg": msg}])
    simplified = await _simplified(s, vendor_id or files[0][1].owner_id)
    # 보낼 때 한 번 더 계산 엔진으로
    money = _money(draft.entered_amount, draft.vat_mode, simplified)
    res = await s.execute(
        update(VendorQuote)
        .where(VendorQuote.id == draft.id, VendorQuote.sent_at.is_(None))
        .values(sent_at=now_utc(), supply=money.supply, vat=money.vat, total=money.total)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise AppError(409, "invalid_state", "이미 보낸 견적서예요.")
    await _valid_soon_jobs(s, draft, rows)
    return draft


async def sent_briefs(
    s: AsyncSession, visit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, QuoteBriefOut]:
    """요청마다 보낸 최신 견적서 요약"""
    if not visit_ids:
        return {}
    q = (
        select(VendorQuote)
        .where(VendorQuote.visit_id.in_(visit_ids), VendorQuote.sent_at.is_not(None))
        .order_by(VendorQuote.visit_id, VendorQuote.version.desc())
        .ext(distinct_on(VendorQuote.visit_id))
    )
    return {
        r.visit_id: QuoteBriefOut(
            id=r.id,
            code=r.code,
            version=r.version,
            total=r.total,
            days=r.days,
            valid_until=r.valid_until,
            sent_at=r.sent_at,
        )
        for r in (await s.execute(q)).scalars()
    }


async def sent_versions(
    s: AsyncSession, visit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[VendorQuoteOut]]:
    """요청마다 보낸 버전들 (최신 먼저, 파일 포함). 임시 저장본은 넣지 않는다."""
    out: dict[uuid.UUID, list[VendorQuoteOut]] = {i: [] for i in visit_ids}
    if not visit_ids:
        return out
    q = (
        select(VendorQuote)
        .where(VendorQuote.visit_id.in_(visit_ids), VendorQuote.sent_at.is_not(None))
        .order_by(VendorQuote.visit_id, VendorQuote.version.desc())
    )
    rows = list((await s.execute(q)).scalars().all())
    files = await _quote_files(s, [r.id for r in rows])
    for r in rows:
        out[r.visit_id].append(_quote_out(r, files[r.id]))
    return out


async def quote_file(
    s: AsyncSession, file_id: uuid.UUID, quote_id: uuid.UUID | None = None
) -> tuple[VendorQuote, File] | None:
    """견적서에 붙은 파일과 그 견적서 버전 (내줘도 되는지는 visit.service가 정한다).
    파일은 같은 요청의 여러 버전에 붙을 수 있어서, quote_id를 주면 그 버전으로 찾는다."""
    q = (
        select(VendorQuote, File)
        .join(VendorQuoteFile, VendorQuoteFile.quote_id == VendorQuote.id)
        .join(File, File.id == VendorQuoteFile.file_id)
        .where(VendorQuoteFile.file_id == file_id)
    )
    if quote_id is not None:
        q = q.where(VendorQuote.id == quote_id)
    row = (await s.execute(q.limit(1))).first()
    return (row[0], row[1]) if row else None


async def has_draft(s: AsyncSession, visit_id: uuid.UUID) -> bool:
    q = select(VendorQuote.id).where(
        VendorQuote.visit_id == visit_id, VendorQuote.sent_at.is_(None)
    )
    return (await s.execute(q)).first() is not None


async def sent_by_version(
    s: AsyncSession, visit_id: uuid.UUID, version: int
) -> QuoteBriefOut | None:
    """그 요청의 보낸 버전 하나 (업체 확정이 그 버전을 고정한다)"""
    q = select(VendorQuote).where(
        VendorQuote.visit_id == visit_id,
        VendorQuote.version == version,
        VendorQuote.sent_at.is_not(None),
    )
    r = (await s.execute(q)).scalar_one_or_none()
    return _brief(r) if r else None


async def briefs_by_id(
    s: AsyncSession, quote_ids: list[uuid.UUID]
) -> dict[uuid.UUID, QuoteBriefOut]:
    if not quote_ids:
        return {}
    rows = (await s.execute(select(VendorQuote).where(VendorQuote.id.in_(quote_ids)))).scalars()
    return {r.id: _brief(r) for r in rows}


def _brief(r: VendorQuote) -> QuoteBriefOut:
    return QuoteBriefOut(
        id=r.id,
        code=r.code,
        version=r.version,
        total=r.total,
        days=r.days,
        valid_until=r.valid_until,
        sent_at=r.sent_at,
    )


async def standard_versions(s: AsyncSession, project_id: uuid.UUID) -> list[StandardQuote]:
    """이 집 표준견적서 모든 버전 (공정 · 버전 순). 서류 목록에 쓴다."""
    q = (
        select(StandardQuote)
        .where(StandardQuote.project_id == project_id)
        .order_by(StandardQuote.trade, StandardQuote.version)
    )
    return list((await s.execute(q)).scalars().all())


# ---- 견적서 유효기간 '곧 지나요' 고객 알림 (D20). 처리 함수는 quote/jobs.py ----

# 요청 상태 · 업체 이름만 읽는다(읽기 조인). visit은 위층이라 모듈을 import하지 않는다
_VISITS = table(
    "visits", column("id"), column("status"), column("project_id"), column("vendor_name")
)


async def on_valid_soon(
    s: AsyncSession, quote_id: uuid.UUID, run_at: datetime, now: datetime
) -> uuid.UUID | None:
    """유효기간 3일 · 1일 전 18:00: 고객이 아직 고를 수 있는 견적서(요청이 quoted · 그 요청의 최신 보낸 버전 ·
    유효기간 안)면 고객 알림 한 줄. 돌려주는 값: 알림을 받은 고객 id, 이미 보냈거나 상황이 바뀌었으면 None.
    commit은 부르는 쪽(worker)이 한다."""
    q = await s.get(VendorQuote, quote_id, populate_existing=True)
    if q is None or q.sent_at is None or q.valid_until is None:
        return None
    left = (q.valid_until - now.astimezone(SEOUL).date()).days
    if left < 0:
        return None
    latest = await s.scalar(
        select(VendorQuote.id)
        .where(VendorQuote.visit_id == q.visit_id, VendorQuote.sent_at.is_not(None))
        .order_by(VendorQuote.version.desc())
        .limit(1)
    )
    v = (
        await s.execute(
            select(_VISITS.c.status, _VISITS.c.project_id, _VISITS.c.vendor_name).where(
                _VISITS.c.id == q.visit_id
            )
        )
    ).first()
    if latest != q.id or v is None or v.status != "quoted":
        return None
    owner = (await project_service.briefs(s, [v.project_id]))[v.project_id].owner_id
    key = f"{VALID_SOON}:{q.id}:{run_at.astimezone(SEOUL):%Y%m%d}"
    sent = select(Notification.id).where(
        Notification.user_id == owner, Notification.dedup_key == key
    )
    if (await s.execute(sent)).first() is not None:
        return None
    when = f"{left}일 남았어요" if left > 0 else "오늘까지예요"
    await notify_service.add(
        s,
        user_id=owner,
        kind=VALID_SOON,
        body=f"{v.vendor_name} 견적서 유효기간이 {when}",
        link=catalog.link(VALID_SOON, pid=v.project_id),
        dedup_key=key,
        project_id=v.project_id,
    )
    return owner
