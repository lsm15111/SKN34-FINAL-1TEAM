"""v2 받은 견적 맞춰 보기: 업체 금액 + 포함 범위 → 같은 범위의 시장 기준과 비교 (v10 quoteCheck의 숫자 부분).

시장 기준은 market_band가 계산한다. 결과는 범위 · 위치 · 차이(%) · 안내 글과 범위 막대 위치(%).
"""

from dataclasses import dataclass, field, replace
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.calc import market_band
from app.calc.common import PYEONG_M2, with_vat, won
from app.calc.mvp_common import num

REMOVAL_DOBAE = (600, 2400)  # 기존 벽지 철거: 시장 ㎡당
REMOVAL_MOKGONG = (60_000, 200_000)  # 철거 · 폐기물 · 양중
EXTRA_MAX = 9

ETC_WARN = (
    "수납장 · 붙박이 · 천장 전체 같은 목공이 들어 있으면 이 계산으로는 비교가 어려워요. "
    "견적서에서 그 줄 금액을 빼고 다시 넣어 보세요."
)


@dataclass(frozen=True)
class CheckScope:
    ceiling: bool = True
    removal: bool = False
    moving: bool = False
    casing9: bool = False
    etc: bool = False
    extras: dict[str, int] = field(default_factory=dict)  # 체크한 추가 항목: key → 곳 수


def _fmt(x: Decimal) -> str:
    return format(x.normalize(), ",f")


def _int(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def percent_vs(amount: int, std: int) -> Decimal | None:
    """v10 CALC.percentVs: (금액 − 기준) ÷ 기준 × 100, 소수 한 자리 반올림."""
    if std <= 0:
        return None
    x = (Decimal(amount - std) / std * 1000 + Decimal("0.5")).to_integral_value(ROUND_FLOOR)
    return x / 10


def _why(where: str, trade: str) -> list[str]:
    dobae = trade == "dobae"
    if where == "high":
        return [
            "인테리어 회사 · 중개 플랫폼을 거친 견적은 벽지 가게 · 목공 팀 직접 견적보다 8~15% 높은 편이에요.",
            "천장이 높거나 우물천장 · 몰딩이 많으면 품이 더 들어요."
            if dobae
            else "문 · 몰딩 등급(멤브레인 · 도장 · 무몰딩)이 높으면 값이 올라요.",
            "다른 공정(필름 · 바닥 등)이 한 견적에 섞였는지 줄을 확인해 보세요.",
            "부가세 포함 금액인지 물어보세요.",
        ]
    if where == "low":
        return [
            "빠진 범위가 없는지(천장 · 부자재 · 철거 · 마감) 줄을 확인해 보세요.",
            "합지인지 실크인지, 벽지 브랜드 · 등급을 확인해 보세요."
            if dobae
            else "문짝만인지 문틀까지인지 확인해 보세요.",
            "부가세 · 출장비가 따로 붙는지 물어보세요.",
        ]
    return ["범위가 같다면 흔한 금액이에요. 포함 범위와 하자 보수 기간을 계약서에 적어 두세요."]


def _warn(text: str) -> dict:
    return {"warn": text}


def check(
    mi: market_band.MarketDobaeInput | market_band.MarketMokgongInput,
    book: market_band.MarketBook,
    amount: Decimal,
    mode: str,
    scope: CheckScope,
) -> dict:
    """mi = 견적과 같은 시장 기준 입력(v10 mkInputs). mode: unknown · excluded · included."""
    v = _int(amount)
    if not v > 0:
        return _warn("받은 금액을 넣어 주세요.")
    supply = won(Decimal(v) / Decimal("1.1")) if mode == "included" else v
    lo_x = hi_x = 0
    notes: list[str] = []
    if isinstance(mi, market_band.MarketDobaeInput):
        trade = "dobae"
        m = market_band.dobae(replace(mi, include_ceiling=scope.ceiling), book)
        if scope.removal:
            by = {ln.key: ln for ln in m.lines}
            a = (by["wall"].qty or Decimal(0)) + (by["ceiling"].qty or Decimal(0))
            lo_x += _int(a * REMOVAL_DOBAE[0])
            hi_x += _int(a * REMOVAL_DOBAE[1])
            notes.append(f"기존 벽지 철거: 시장 ㎡당 600~2,400원 × {_fmt(a)}㎡")
        if scope.moving:
            notes.append("짐 이동 · 정리는 업체마다 달라 범위에 넣지 않았어요")
    else:
        trade = "mokgong"
        if scope.etc:
            return _warn(ETC_WARN)
        m = market_band.mokgong(mi, book)
        p = book.mokgong
        known = {e.key for e in p.extras}
        picks = {k: max(1, min(EXTRA_MAX, c)) for k, c in scope.extras.items() if k in known}
        door = next((ln for ln in m.lines if ln.key == "door"), None)
        cd, wd = 0, False
        if scope.casing9:
            if door is not None and door.qty is not None:
                cd, wd = int(door.qty), True
            else:
                py = mi.area_m2 / PYEONG_M2
                cd = market_band.doors_for(py, p.doors_by_py, p.doors_count)
        xr = market_band.extras_range(p, picks, cd, wd)
        lo_x, hi_x = lo_x + xr.lo, hi_x + xr.hi
        notes.extend(xr.notes)
        if scope.removal:
            lo_x += REMOVAL_MOKGONG[0]
            hi_x += REMOVAL_MOKGONG[1]
            notes.append("철거 · 폐기물 · 양중: 6만~20만 원(시장 조사)")
    lo, hi = m.lo + lo_x, m.hi + hi_x
    where = "low" if supply < lo else "high" if supply > hi else "in"
    pct = percent_vs(supply, lo if where == "low" else hi) if where != "in" else Decimal(0)
    if where == "in":
        head = "보통 범위 안이에요"
    else:
        word = "높아요" if where == "high" else "낮아요"
        head = f"보통보다 {num(abs(pct or Decimal(0)))}% {word}"
    # 범위 막대(덧씌움): 범위 양쪽에 범위 폭의 15%를 더 둔다
    span = (hi - lo) or 1
    pad = 0.15 * span
    b_lo = min(supply, lo) - pad
    b_w = (max(supply, hi) + pad - b_lo) or 1
    bar = {
        "band_left": (lo - b_lo) / b_w * 100,
        "band_width": span / b_w * 100,
        "me": (supply - b_lo) / b_w * 100,
    }
    return {
        "warn": None,
        "trade": trade,
        "supply": supply,
        "lo": lo,
        "hi": hi,
        "where": where,
        "pct": pct,
        "head": head,
        "notes": notes,
        "why": _why(where, trade),
        "vat_unknown": mode == "unknown",
        "bar": bar,
    }


def estimate_for(
    lines: list[dict], prices: dict[str, Decimal | None], grade: str | None, std_total: int
) -> dict:
    """v10 estimateFor: 업체 단가 × 이 집 표준 수량. 비운 줄이 하나라도 있으면 가견적 없음."""
    supply = 0
    for ln in lines:
        if ln["state"] not in ("included", "separate") or ln["qty"] is None:
            continue
        pk = f"paper_{grade or 'basic'}" if ln["key"] == "paper" else ln["key"]
        price = prices.get(pk)
        if price is None:
            return {"ok": False, "why": f"'{ln['name']}' 단가를 넣어 주세요"}
        supply += won(Decimal(ln["qty"]) * price)
    m = with_vat(supply)
    return {
        "ok": True,
        "supply": m.supply,
        "vat": m.vat,
        "total": m.total,
        "pct": percent_vs(m.total, std_total),
    }
