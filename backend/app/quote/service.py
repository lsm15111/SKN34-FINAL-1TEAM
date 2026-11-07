"""표준견적서(믿집 계산)와 업체 실측 견적서.

표준견적서는 처음 볼 때 계산해 저장하고, 집 정보(rev) · 산식 · 단가 버전이 그대로면 저장본을 쓴다.
하나라도 바뀌면 새 버전을 쌓는다(예전 버전은 남는다). 숫자는 모두 계산 엔진이 만든다.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.calc import dobae, mokgong
from app.calc import spaces as space_calc
from app.calc.common import FORMULA_VERSION, Step, from_entered
from app.calc.quote_diff import budget_gap
from app.calc.standard_quote import house_area, house_pyeong
from app.files import service as files_service
from app.files.models import File
from app.project import service as project_service
from app.project.schemas import ProjectOut
from app.quote import ranges
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
from app.refprice.book import DOBAE, MOKGONG
from app.refprice.house import HOUSE
from app.refprice.spaces import SPACES
from app.shared.clock import now_utc
from app.shared.errors import AppError
from app.shared.ids import uuid7

# 저장한 표준견적서가 쓴 기준 한 벌: 단가 버전 + 공간 몫 버전 (둘 중 하나가 바뀌면 다시 계산)
PRICE_VER = f"{DOBAE.version}+{SPACES.version}"


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


def _area(p: ProjectOut) -> tuple[Decimal, str]:
    return house_area(p.size.band, p.size.m2, p.size.basis, HOUSE)


def _pyeong(p: ProjectOut) -> Decimal:
    return house_pyeong(p.size.band, p.size.m2, p.size.basis, HOUSE)


def space_pick(p: ProjectOut, trade: str) -> tuple[space_calc.SpacePick, list[str]]:
    """그 공정에 고른 공간 → 수량 몫(calc.spaces)과 고른 공간 이름"""
    t = p.trades.dobae if trade == "dobae" else p.trades.mokgong
    if t is None:
        raise ValueError("고른 공정이 아니에요")
    names = {sp.id: sp.name for sp in p.spaces}
    picked = [names[sid] for sid in t.spaces if sid in names]
    band = p.size.band or space_calc.band_of(_pyeong(p))
    return space_calc.pick(picked, band, SPACES), picked


def known(p: ProjectOut, trade: str) -> ranges.Known:
    """범위 계산에 넣을 '이 집을 얼마나 아는지'"""
    pk, _ = space_pick(p, trade)
    return ranges.Known(ranges.size_precision(p), pk)


def _space_note(pk: space_calc.SpacePick, picked: list[str]) -> list[str]:
    """고른 공간 몫(%)은 계산 엔진 가정 문구에 있고, 여기서는 어떤 공간을 셌는지만 남긴다"""
    if pk.whole:
        return []
    notes = [f"고른 공간: {' · '.join(picked)}"]
    if pk.guessed:
        notes.append(f"{' · '.join(pk.guessed)}은(는) 어떤 공간인지 몰라 작은방 크기로 잡았어요.")
    if pk.zero:
        notes.append(f"{' · '.join(pk.zero)}은(는) 보통 이 공정을 하지 않아 수량에 넣지 않았어요.")
    return notes


def calc_trades(p: ProjectOut, crews: Mapping[str, int] | None = None) -> list[TradeCalc]:
    """이 집 정보로 고른 공정을 계산한다(목공 → 도배 순서). 공정표도 이 결과를 쓴다.
    crews를 주면 그 공정의 하루 인원을 바꿔 기간을 센다(업체가 적은 인원)."""
    crews = crews or {}
    mp = replace(MOKGONG, crew=crews["mokgong"]) if "mokgong" in crews else MOKGONG
    dp = replace(DOBAE, crew=crews["dobae"]) if "dobae" in crews else DOBAE
    area, basis = _area(p)
    out: list[TradeCalc] = []
    if p.trades.mokgong:
        pk, picked = space_pick(p, "mokgong")
        rooms = max(pk.doors, 1)
        items = tuple(p.trades.mokgong.items)
        m = mokgong.quote(
            mokgong.MokgongInput(
                area,
                basis,
                items,
                p.occupied,
                doors=rooms if "door" in items else 0,
                share=pk.molding,
                base_share=pk.base,
                flat_share=pk.flat_m2_share or None,
                flat_living="living" in pk.kinds,
            ),
            mp,
        )
        notes = list(m.assumptions) + _space_note(pk, picked)
        if "door" in items:
            notes.append(f"방문은 목공을 고른 방 수({rooms}개)로 잡았어요.")
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
            )
        )
    if p.trades.dobae:
        pk, picked = space_pick(p, "dobae")
        d = dobae.quote(
            dobae.DobaeInput(
                area, basis, p.trades.dobae.grade, True, p.occupied, p.balcony_ext, share=pk.paper
            ),
            dp,
        )
        out.append(
            TradeCalc(
                "dobae",
                p.trades.dobae.grade,
                d.lines,
                d.subtotal,
                d.vat,
                d.total,
                d.man_days,
                dp.crew,
                d.steps,
                list(d.assumptions) + _space_note(pk, picked),
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


def _fresh(row: StandardQuote, p: ProjectOut) -> bool:
    """집 정보가 그대로면 저장본을 쓴다. 산식 · 단가 버전이 바뀌어도 실측을 요청해 잠긴 집은 그대로 둔다
    (업체에 보낸 가견적 · 견적 비교가 같은 표준견적서를 보게)."""
    if row.project_rev != p.rev:
        return False
    return p.locked or (row.formula_ver == FORMULA_VERSION and row.price_ver == PRICE_VER)


async def ensure_standard(s: AsyncSession, p: ProjectOut) -> dict[str, StandardQuote]:
    """이 집의 최신 표준견적서(공정별). 없거나 바뀌었으면 새 버전을 저장하고 commit한다."""
    latest = await _latest(s, p.id)
    wanted = {t.trade: t for t in calc_trades(p)}
    stale = [t for t in wanted if t not in latest or not _fresh(latest[t], p)]
    if not stale:
        return {t: latest[t] for t in wanted}
    area, basis = _area(p)
    pyeong = _pyeong(p)
    try:
        for trade in stale:
            c = wanted[trade]
            row = StandardQuote(
                project_id=p.id,
                trade=trade,
                version=(latest[trade].version + 1) if trade in latest else 1,
                project_rev=p.rev,
                formula_ver=FORMULA_VERSION,
                price_ver=PRICE_VER,
                grade=c.grade,
                area_m2=area,
                area_basis=basis,
                pyeong=pyeong,
                supply=c.supply,
                vat=c.vat,
                total=c.total,
                # 다시 읽은 저장본(Numeric 소수 한 자리)과 같은 모양: 6 → 6.0
                man_day=c.man_day.quantize(Decimal("0.1")),
                crew=c.crew,
                notes=c.notes,
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


async def standard_for(s: AsyncSession, user: User, project_id: uuid.UUID) -> StandardOut:
    """GET /projects/{id}/standard: 만든 사람 · 관리자만(남의 것은 404)."""
    p = await project_service.get_for(s, user, project_id)
    rows = await ensure_standard(s, p)
    order = [t for t in ("mokgong", "dobae") if t in rows]
    lines = await _lines(s, [rows[t].id for t in order])
    ks = {t: known(p, t) for t in order}
    inps = {t: ranges.range_input(t, rows[t].grade, lines[rows[t].id], ks[t]) for t in order}
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
                )
                for ln in lines[rows[t].id]
            ],
            supply=rows[t].supply,
            vat=rows[t].vat,
            total=rows[t].total,
            man_day=rows[t].man_day,
            crew=rows[t].crew,
            notes=list(rows[t].notes),
            space_share=ks[t].pick.paper if t == "dobae" else ks[t].pick.edge,
            range=ranges.trade_range(inps[t], ks[t]),
        )
        for t in order
    ]
    supply = sum(x.supply for x in trades)
    vat = sum(x.vat for x in trades)
    total = sum(x.total for x in trades)
    budget = None
    if p.budget:
        status, over = budget_gap(total, p.budget)
        budget = BudgetOut(band=p.budget, status=status, over_by=over)
    first = rows[order[0]]
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
        range=ranges.total_range([inps[t] for t in order], [ks[t] for t in order]),
        budget=budget,
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
    money = (
        from_entered(data.entered_amount, data.vat_mode)
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
    draft.updated_at = now_utc()
    await s.flush()
    await s.execute(delete(VendorQuoteFile).where(VendorQuoteFile.quote_id == draft.id))
    s.add_all(
        [VendorQuoteFile(quote_id=draft.id, file_id=i, sort=n) for n, i in enumerate(data.file_ids)]
    )
    await s.flush()


async def seal_draft(s: AsyncSession, visit_id: uuid.UUID, today: date) -> VendorQuote:
    """임시 저장본을 보낸 버전으로 굳힌다. 빠진 칸은 칸별로 422. commit은 부르는 쪽이 한다."""
    draft = next((r for r in await _versions(s, visit_id) if r.sent_at is None), None)
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
    if draft.valid_until is not None and draft.valid_until < today:
        msg = "견적 유효기간이 지났어요. 날짜를 다시 골라 주세요."
        raise AppError(422, "valid_until", msg, fields=[{"loc": ["valid_until"], "msg": msg}])
    money = from_entered(draft.entered_amount, draft.vat_mode)  # 보낼 때 한 번 더 계산 엔진으로
    res = await s.execute(
        update(VendorQuote)
        .where(VendorQuote.id == draft.id, VendorQuote.sent_at.is_(None))
        .values(sent_at=now_utc(), supply=money.supply, vat=money.vat, total=money.total)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        raise AppError(409, "invalid_state", "이미 보낸 견적서예요.")
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
