"""v2 참고 공정(도배 · 목공 밖): 평형별 수량을 선형으로 잇고, 고른 자재 단위가 맞으면 그 가격대, 아니면 시장 범위.

v10 qtyByPy · dataRange · refTrade를 옮긴 것. 결과는 v10 객체와 같은 키의 dict.
금액은 원 정수(won), 수량은 소수 한 자리(m2), 셀 수 있는 단위는 반올림해 1 이상.
"""

import itertools
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.calc.common import m2, won
from app.calc.mvp_common import num

COUNT_UNITS = ("개", "세트", "짝", "식", "곳", "자")
PUBLIC_SRC = re.compile(r"표준시장단가|조달청|품셈")


@dataclass(frozen=True)
class RefMaterial:
    id: str
    cat: str
    tier: str
    brand: str
    name: str
    price_min: int | None
    price_max: int | None
    unit: str


def unit_norm(u: str | None) -> str:
    s = re.sub(r"\(.*\)", "", str(u or ""), count=1)
    return re.sub(r"\s", "", s).replace("m2", "㎡", 1)


def _round(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def qty_by_py(by: dict[str, Decimal], py: Decimal) -> Decimal:
    ks = sorted(Decimal(k) for k in by)
    val = {Decimal(k): Decimal(v) for k, v in by.items()}
    if py <= ks[0]:
        return val[ks[0]] * py / ks[0]
    for a, b in itertools.pairwise(ks):
        if py <= b:
            return val[a] + (val[b] - val[a]) * (py - a) / (b - a)
    return val[ks[-1]] * py / ks[-1]


def data_range(
    cat: str, unit: str, mats: dict[str, RefMaterial], cat_ko: str
) -> tuple[int, int, str] | None:
    """믿집 자재 자료에서 같은 단위 가격대(고른 자재가 없을 때)."""
    ms = [
        m
        for m in mats.values()
        if m.cat == cat and unit_norm(m.unit) == unit_norm(unit) and m.price_min is not None
    ]
    if not ms:
        return None
    low = min(m.price_min for m in ms if m.price_min is not None)
    high = max(m.price_max if m.price_max is not None else m.price_min or 0 for m in ms)
    return low, high, f"믿집 자재 자료 {cat_ko} {len(ms)}개 가격대"


def ref_trade(
    cat: str,
    py: Decimal,
    pick: RefMaterial | None,
    wallpaper_too: bool,
    trade: dict,
    mats: dict[str, RefMaterial],
    cat_ko: str,
) -> dict:
    """trade = estimate_ref.json의 trades[cat]."""
    lines = []
    for it in trade["items"]:
        state = it.get("state") or "included"
        if cat == "paint" and not wallpaper_too:
            if it["key"] == "paint_full":
                state = "included"
            elif it["key"] == "paint_accent":
                state = "optional"
        fixed = it["qty"].get("fixed")
        raw = Decimal(fixed) if fixed is not None else qty_by_py(it["qty"]["by_py"], py)
        qty = max(1, _round(raw)) if it["unit"] in COUNT_UNITS else m2(raw)
        lo = hi = None
        basis = "market"
        src: list[str] = []

        def add(low, high, qty=qty):
            nonlocal lo, hi
            lo = (lo or 0) + won(qty * Decimal(low))
            hi = (hi or 0) + won(qty * Decimal(high))

        if it.get("mat") == "pick":
            if (
                pick is not None
                and unit_norm(pick.unit) == unit_norm(it["unit"])
                and pick.price_min is not None
            ):
                high = pick.price_max if pick.price_max is not None else pick.price_min
                add(pick.price_min, high)
                src.append(f"고른 자재 {pick.brand} {pick.name}")
                basis = "pick"
            else:
                fb = it.get("mat_fallback")
                f = data_range(cat, it["unit"], mats, cat_ko) if fb == "data_range" else fb
                if f:
                    low, high, s = (f["low"], f["high"], f["source"]) if isinstance(f, dict) else f
                    add(low, high)
                    tail = f" (고른 자재는 단위가 '{pick.unit}'라 바로 못 넣었어요)" if pick else ""
                    src.append(s + tail)
        labor = it.get("labor")
        if labor:
            add(labor["low"], labor["high"])
            src.append(labor["source"])
            if PUBLIC_SRC.search(labor["source"]):
                basis = "pick" if basis == "pick" else "public"
        if it.get("calc"):
            calc = it["calc"]
        elif fixed is not None:
            calc = f"{num(Decimal(fixed))}{it['unit']}"
        else:
            calc = f"{num(py)}평 기준"
        pub = it.get("public")
        lines.append(
            {
                "key": it["key"],
                "name": it["name"],
                "qty": qty,
                "unit": it["unit"],
                "lo": lo,
                "hi": hi,
                "state": state,
                "basis": basis,
                "source": " · ".join(s for s in src if s),
                "calc": calc,
                "pub": {
                    "unit_price": pub["unit_price"],
                    "amount": won(qty * Decimal(pub["unit_price"])),
                    "source": pub["source"],
                }
                if pub
                else None,
                "note": it.get("note") or None,
            }
        )
    counted = [ln for ln in lines if ln["state"] == "included" and ln["lo"] is not None]
    lo = sum(ln["lo"] for ln in counted)
    hi = sum(ln["hi"] for ln in counted)
    days = max(Decimal(1), Decimal(_round(qty_by_py(trade["days_by_py"], py) * 2)) / 2)
    notes = list(dict.fromkeys(ln["note"] for ln in lines if ln["note"]))
    return {
        "cat": cat,
        "ko": cat_ko,
        "level": trade.get("level") or "참고",
        "lines": lines,
        "lo": lo,
        "hi": hi,
        "vlo": won(Decimal(lo) * Decimal("0.1")),
        "vhi": won(Decimal(hi) * Decimal("0.1")),
        "days": days,
        "crew": trade.get("crew") or 2,
        "steps": [{"key": "work", "name": f"{cat_ko} 시공", "half_days": max(1, int(days * 2))}],
        "notes": notes,
    }
