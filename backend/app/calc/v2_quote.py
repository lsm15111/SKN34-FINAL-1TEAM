"""v2 표준견적서: v10 v3Inputs · buildQuote를 옮긴 것. 정밀 공정마다 시장 범위(band)와 공공 → 시장 차이(gap)를 붙인다.

정밀 공정(목공 · 도배)은 mvp_mokgong · mvp_dobae, 시장 기준은 market_band, 참고 공정은 v2_ref_trade가 계산한다.
결과는 v10 객체와 같은 키의 dict. 오늘 날짜는 인자로 받는다(견적 번호 · 날짜).
"""

import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from app.calc import market_band, mvp_dobae, mvp_mokgong
from app.calc.common import Line, m2, pyeong_to_m2
from app.calc.dobae import DobaePrices
from app.calc.mokgong import MokgongPrices
from app.calc.mvp_common import MvpLine, num
from app.calc.plan_qty import PlanQty
from app.calc.v2_ref_trade import RefMaterial, ref_trade

TRADE_OF = {"wallpaper": "dobae", "carpentry": "mokgong"}
DEFAULT_PY = Decimal(32)
AUTO_PY_M2 = Decimal("3.305785")  # v10 mok10Auto: 도면이 없을 때 천장 넓이 = 평 × 3.305785 ÷ 1.32
# 공공 → 시장 차이 칸 이름: v10은 doors_default
GAP_KEY = {"doors_count": "doors_default"}


@dataclass(frozen=True)
class V2Plan:
    """고른 예시 평면도와 그 수량."""

    name: str  # 도면 이름 (범위가 일부면 '(거실 · 방만)'까지)
    supply_m2: Decimal
    supply_py: int
    expanded: bool
    qty: PlanQty


@dataclass(frozen=True)
class V2Books:
    dobae: DobaePrices
    mok: mvp_mokgong.MokBook
    mokgong: MokgongPrices
    market: market_band.MarketBook
    public_eq_dobae: market_band.MarketDobae
    public_eq_mokgong: market_band.MarketMokgong
    gap_dobae: tuple[tuple[str, str, str], ...]
    gap_mokgong: tuple[tuple[str, str, str], ...]
    estimate_ref: dict
    materials: dict[str, RefMaterial]
    cat_ko: dict[str, str]
    dobae_removal_calc: str


@dataclass(frozen=True)
class V2QuoteInput:
    pyeong: Decimal | None
    occupied: bool
    cats: tuple[str, ...]
    picks: dict[str, str]
    plan: V2Plan | None
    balcony: bool
    mok: mvp_mokgong.MokSel
    door_count_set: bool  # 고객이 방문 개수를 넣었는지 (S.mok10.door.count != null)
    door_removal: bool = (
        False  # v10: 문틀까지 교체 · 덧방을 고르면 문 수 · 자재와 상관없이 철거 줄을 둔다
    )


@dataclass(frozen=True)
class V2Inputs:
    """v10 v3Inputs 결과."""

    py: Decimal
    area_m2: Decimal
    measured: dict | None
    occupied: bool
    balcony: bool
    grade: str
    mok: tuple[str, ...]
    doors: int
    doors_auto: dict
    assumed: list[str]


def rooms_for(py: Decimal) -> int:
    return 2 if py < 28 else 3 if py < 38 else 4


def baths_for(py: Decimal) -> int:
    return 1 if py < 28 else 2


def mok_items(sel: mvp_mokgong.MokSel) -> tuple[str, ...]:
    """v10 mok10Items: 시장 기준 · 화면에 쓰는 목공 항목."""
    it = []
    if sel.molding_type != "none" and sel.molding:
        it.append("molding")
    if sel.base:
        it.append("base")
    if sel.door.mode != "none" and sel.door.pick:
        it.append("door")
    return tuple(it)


def inputs(q: V2QuoteInput, books: V2Books) -> V2Inputs:
    assumed = []
    plan = q.plan
    py = Decimal(plan.supply_py) if plan else q.pyeong
    if not py:
        py = DEFAULT_PY
        assumed.append("평형을 몰라서 32평으로 잡았어요")
    measured = None
    if plan:
        t = plan.qty
        measured = {
            "name": plan.name,
            "wall_m2": t.wall_m2,
            "ceiling_m2": t.ceiling_m2,
            "molding_m": t.molding_m,
            "base_m": t.base_m,
            "doors": t.doors,
        }
    if plan and plan.qty.doors:
        auto = {"n": plan.qty.doors, "how": f"도면 {plan.name}에서 센 방문"}
    else:
        r, b = rooms_for(py), baths_for(py)
        auto = {"n": r + b, "how": f"{num(py)}평 기준 방 {r} + 욕실 {b}"}
    doors = q.mok.door.count if q.mok.door.count is not None else auto["n"]
    pick = books.materials.get(q.picks.get("wallpaper", ""))
    grade = "economy" if pick and pick.tier == "economy" else "basic"
    items = mok_items(q.mok)
    if not q.door_count_set and "door" in items:
        assumed.append(f"방문은 {auto['how']} {doors}개로 잡았어요")
    return V2Inputs(
        py=py,
        area_m2=plan.supply_m2 if plan else pyeong_to_m2(py),
        measured=measured,
        occupied=q.occupied,
        balcony=plan.expanded if plan else q.balcony,
        grade=grade,
        mok=items,
        doors=doors,
        doors_auto=auto,
        assumed=assumed,
    )


def _line(ln: Line, calc: str | None = None) -> dict:
    basis = ln.price_basis if isinstance(ln, MvpLine) else ln.basis
    return {
        "key": ln.key,
        "name": ln.name,
        "qty": ln.qty,
        "unit": ln.unit,
        "unit_price": ln.unit_price,
        "amount": ln.amount,
        "state": ln.state,
        "source": ln.source,
        "basis": basis,
        "calc": calc if calc is not None else (ln.calc if isinstance(ln, MvpLine) else ""),
    }


def _steps(steps) -> list[dict]:
    return [{"key": s.key, "name": s.name, "half_days": s.half_days} for s in steps]


def _mok_md_raw(lines: list[dict], sel: mvp_mokgong.MokSel, books: V2Books) -> float:
    """v10 md.door + md.trim + md.ceil (JS 소수 계산 그대로, 화면 표시에 쓰지 않음)."""
    mg, f = books.mokgong, books.mok.fixed
    by = {ln["key"]: ln for ln in lines}
    door = trim = ceil = 0.0
    md_door = float(mg.md_door)
    if "door" in by:
        n = float(by["door"]["qty"])
        door += n * md_door / 2 if sel.door.mode == "leaf" else n * md_door
        if "casing" in by:
            door += float(by["casing"]["qty"]) * float(mg.md_casing)
    for k in ("slide", "hidden"):
        if k in by:
            door += float(by[k]["qty"]) * md_door * 1.5
    if "molding" in by:
        mult = float(f.minus_mult) if sel.molding_type == "minus" else 1
        trim += float(by["molding"]["qty"]) * float(mg.md_molding) * mult
    if "base" in by:
        bp = books.mok.products.get(sel.base or "")
        mult = float(f.hidden_mult) if bp and bp.type == "hidden" else 1
        trim += float(by["base"]["qty"]) * float(mg.md_base) * mult
    if "flatten_overlay" in by:
        ceil += float(by["flatten_overlay"]["qty"]) * float(mg.md_board)
    if "ceiling_redo" in by:
        ceil += float(by["ceiling_redo"]["qty"]) * (float(mg.md_frame) + float(mg.md_board))
    return door + trim + ceil


def _mokgong(q: V2QuoteInput, inp: V2Inputs, books: V2Books) -> dict | None:
    sel, plan = q.mok, q.plan
    # v10: 도면이 없을 때 자동 천장 넓이는 입력 평에서 바로 잰다(평 × 3.305785 ÷ 1.32)
    auto_fix: set[str] = set()
    if plan is None:
        ceil = m2(inp.py * AUTO_PY_M2 / books.mok.fixed.supply_per_floor)
        extras = dict(sel.extras)
        for x in books.mok.extras:
            if x.auto == "ceiling" and extras.get(x.key) is True:
                extras[x.key] = ceil
                auto_fix.add(x.key)
        sel = replace(sel, extras=extras)
    r = mvp_mokgong.quote(
        mvp_mokgong.MvpMokgongInput(
            area_m2=inp.area_m2,
            sel=sel,
            occupied=inp.occupied,
            doors=inp.doors,
            plan=plan.qty if plan else None,
            plan_name=plan.name if plan else "",
        ),
        books.mok,
        books.mokgong,
    )
    if r is None:
        return None
    lines = [_line(ln, "전용면적(바닥 × 1.0)" if ln.key in auto_fix else None) for ln in r.lines]
    if q.door_removal and all(ln["key"] != "remove_door" for ln in lines):
        at = next(i for i, ln in enumerate(lines) if ln["state"] == "after_visit")
        lines.insert(
            at,
            {
                "key": "remove_door",
                "name": "기존 방문 · 문틀 철거",
                "qty": None,
                "unit": "식",
                "unit_price": None,
                "amount": None,
                "state": "after_visit",
                "source": "공공 단가가 없어 업체 견적에서 확인해요",
                "basis": "none",
                "calc": "",
            },
        )
    return {
        "trade": "mokgong",
        "ko": "목공",
        "lines": lines,
        "supply": r.subtotal,
        "vat": r.vat,
        "total": r.total,
        "man_days": r.man_days,
        "md_raw": _mok_md_raw(lines, sel, books),
        "crew": books.mokgong.crew,
        "steps": _steps(r.steps),
        "days": r.days,
        "notes": r.assumptions,
        "grade": None,
        "extra_amount": r.extra_amount,
        "ver": r.version,
    }


def _dobae(q: V2QuoteInput, inp: V2Inputs, books: V2Books) -> dict:
    plan, p = q.plan, books.dobae
    r = mvp_dobae.quote(
        mvp_dobae.MvpDobaeInput(
            area_m2=inp.area_m2,
            grade=inp.grade,  # type: ignore[arg-type]
            occupied=inp.occupied,
            balcony_ext=inp.balcony,
            plan=plan.qty if plan else None,
            plan_name=plan.name if plan else "",
        ),
        p,
    )
    wall = float(r.wall_m2)
    ceil = float(r.ceiling_m2)  # 천장은 늘 포함
    md = wall * float(p.md_wall) + ceil * (0.027 * 1.3)  # v10 md_ceiling = 0.027 × 1.3
    if inp.occupied:
        md /= float(p.occupied_output)
    lines = [_line(ln, books.dobae_removal_calc if ln.key == "removal" else None) for ln in r.lines]
    return {
        "trade": "dobae",
        "ko": "도배",
        "lines": lines,
        "supply": r.subtotal,
        "vat": r.vat,
        "total": r.total,
        "man_days": r.man_days,
        "md_raw": md,
        "crew": p.crew,
        "steps": _steps(r.steps),
        "days": r.days,
        "notes": r.assumptions,
        "grade": inp.grade,
        "extra_amount": None,
        "ver": None,
    }


def market_input(
    t: dict, q: V2QuoteInput, inp: V2Inputs, include_ceiling: bool = True
) -> market_band.MarketDobaeInput | market_band.MarketMokgongInput:
    """v10 mkInputs(t)."""
    plan = q.plan.qty if q.plan else None
    name = q.plan.name if q.plan else ""
    if t["trade"] == "dobae":
        return market_band.MarketDobaeInput(
            area_m2=inp.area_m2,
            grade=inp.grade,  # type: ignore[arg-type]
            include_ceiling=include_ceiling,
            occupied=inp.occupied,
            balcony_ext=inp.balcony,
            plan=plan,
            plan_name=name,
        )
    return market_band.MarketMokgongInput(
        area_m2=inp.area_m2,
        items=inp.mok,  # type: ignore[arg-type]
        doors=inp.doors,
        door_frame=q.mok.door.mode == "replace",
        plan=plan,
        plan_name=name,
        extra_amount=t["extra_amount"] or 0,
    )


def run_market(mi, books: V2Books) -> market_band.MarketResult:
    if isinstance(mi, market_band.MarketDobaeInput):
        return market_band.dobae(mi, books.market)
    return market_band.mokgong(mi, books.market)


def market_out(m: market_band.MarketResult) -> dict:
    return {
        "trade": m.trade,
        "grade": m.paper,
        "lines": [ln.__dict__ for ln in m.lines],
        "supply": m.supply,
        "lo": m.lo,
        "hi": m.hi,
        "band": {
            "lo": m.band.lo,
            "hi": m.band.hi,
            "lo80": m.band.lo80,
            "hi80": m.band.hi80,
            "n": m.band.n,
        },
        "version": m.version,
    }


def band(t: dict, mi, books: V2Books) -> dict:
    """v10 marketBand(t) 최종판(시장 기준)."""
    m = run_market(mi, books)
    return {"lo": m.lo, "hi": m.hi, "n": m.n, "p": [m.band.lo, m.band.hi], "mk": market_out(m)}


def gap(t: dict, mi, books: V2Books) -> dict:
    """v10 gapSteps(t): 공공 기준(부가세 포함) → 시장 기준(부가세 별도)을 한 단계씩."""
    dob = t["trade"] == "dobae"
    g = market_band.gap_steps(
        mi,
        books.market,
        books.public_eq_dobae if dob else books.public_eq_mokgong,
        books.gap_dobae if dob else books.gap_mokgong,
        t["supply"],
        t["vat"],
    )
    steps = [{**s.__dict__, "key": GAP_KEY.get(s.key, s.key)} for s in g.steps]
    return {"from": g.start, "steps": steps, "to": g.end}


def _hash(text: str) -> int:
    """v10: [...s].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) | 0, 7)"""
    a = 7
    for ch in text:
        c = ord(ch)
        if c > 0xFFFF:  # charCodeAt(0)은 앞 대리 문자
            c = 0xD800 + ((c - 0x10000) >> 10)
        a = (a * 31 + c) & 0xFFFFFFFF
        if a >= 0x80000000:
            a -= 0x100000000
    return a


def quote_code(py: Decimal, cats: tuple[str, ...], picks: dict[str, str], today: date) -> str:
    raw = (
        "["
        + num(py)
        + ","
        + json.dumps(list(cats), ensure_ascii=False, separators=(",", ":"))
        + ","
        + json.dumps(picks, ensure_ascii=False, separators=(",", ":"))
        + "]"
    )
    return f"MJ-{today:%y%m}-{abs(_hash(raw)) % 10000:04d}"


def build(q: V2QuoteInput, books: V2Books, today: date) -> dict:
    """v10 buildQuote() + 정밀 공정마다 band · gap."""
    inp = inputs(q, books)
    precise: list[dict] = []
    if "carpentry" in q.cats:
        r = _mokgong(q, inp, books)
        if r:
            precise.append(r)
    if "wallpaper" in q.cats:
        precise.append(_dobae(q, inp, books))
    for t in precise:
        mi = market_input(t, q, inp)
        t["band"] = band(t, mi, books)
        t["gap"] = gap(t, mi, books)
    ref, missing = [], []
    trades = books.estimate_ref.get("trades", {})
    for c in q.cats:
        if c in TRADE_OF:
            continue
        if c not in trades:
            missing.append(c)
            continue
        pick = books.materials.get(q.picks.get(c, ""))
        ko = books.cat_ko.get(c, c)
        ref.append(
            ref_trade(c, inp.py, pick, "wallpaper" in q.cats, trades[c], books.materials, ko)
        )
    supply = sum(t["supply"] for t in precise)
    vat = sum(t["vat"] for t in precise)
    rlo = sum(t["lo"] + t["vlo"] for t in ref)
    rhi = sum(t["hi"] + t["vhi"] for t in ref)
    bands = [t["band"] for t in precise]
    return {
        "inp": {
            "py": inp.py,
            "area_m2": inp.area_m2,
            "measured": inp.measured,
            "occupied": inp.occupied,
            "balcony": inp.balcony,
            "grade": inp.grade,
            "mok": list(inp.mok),
            "doors": inp.doors,
            "doors_auto": inp.doors_auto,
            "assumed": inp.assumed,
        },
        "precise": precise,
        "ref": ref,
        "missing": missing,
        "supply": supply,
        "vat": vat,
        "total": supply + vat,
        "rlo": rlo,
        "rhi": rhi,
        "all_lo": supply + vat + rlo,
        "all_hi": supply + vat + rhi,
        "code": quote_code(inp.py, q.cats, q.picks, today),
        "at": today.isoformat(),
        "band": {"lo": sum(b["lo"] for b in bands), "hi": sum(b["hi"] for b in bands)}
        if bands
        else None,
    }


def doors_default(py: Decimal, books: V2Books) -> int:
    """v10 MARKET.P.mokgong.doors_default(py)."""
    p = books.market.mokgong
    return market_band.doors_for(py, p.doors_by_py, p.doors_count)
