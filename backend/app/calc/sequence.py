"""공정 여러 개를 한 줄의 예상 공정표로 잇고, 공정 견적을 하나로 합친다.

공정 순서는 부르는 쪽이 넘긴다 (상담은 공정 레지스트리의 order · late_order). 계산 엔진이라 레지스트리를 모른다.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import Quote, Step

Phase = Literal["prep", "remove", "main", "late", "finish"]
_EDGE = ("prep", "remove", "finish")


@dataclass(frozen=True)
class TradeStep:
    trade: str
    key: str
    name: str
    half_days: int
    phase: Phase = "main"


@dataclass(frozen=True)
class Totals:
    """공정 견적 합계. 금액은 공정마다 이미 반올림한 값을 더하기만 한다 (VAT도 공정별 VAT의 합)."""

    subtotal: int
    vat: int
    total: int
    basis_counts: dict[str, int]  # 줄 근거별 개수 (public · assumed · none, '안 함' 줄은 빼고)


def sequence(
    steps: dict[str, list[Step]],
    order: Sequence[str] = ("mokgong", "dobae"),
    late_order: Sequence[str] = (),
) -> tuple[list[TradeStep], Decimal]:
    """현장 순서로 잇는다: 짐 정리 · 보양 한 번 → 철거(공정마다 모아서 먼저) → 본 작업(order) →
    늦게 하는 작업(Step.late, late_order 다음 order) → 정리 · 청소 한 번(마지막에 일한 공정의 것).

    order를 넘기지 않으면 예전 순서(목공 → 도배)다. order에 없는 공정이 들어오면 ValueError.
    """
    if set(steps) - set(order):
        raise ValueError("공정 순서에 없는 공정이 있어요")
    trades = [t for t in order if steps.get(t)]
    late_trades = [t for t in late_order if t in trades] + [
        t for t in trades if t not in late_order
    ]

    def pick(ts: list[str], phase: Phase, ok) -> list[TradeStep]:
        return [
            TradeStep(t, s.key, s.name, s.half_days, phase) for t in ts for s in steps[t] if ok(s)
        ]

    prep = pick(trades, "prep", lambda s: s.key == "prep")[:1]
    remove = pick(trades, "remove", lambda s: s.key == "remove")
    main = pick(trades, "main", lambda s: s.key not in _EDGE and not s.late)
    late = pick(late_trades, "late", lambda s: s.key not in _EDGE and s.late)
    finishes = {t: s for t in trades for s in steps[t] if s.key == "finish"}
    worked = [s.trade for s in main + late if s.trade in finishes]
    last = worked[-1] if worked else next((t for t in reversed(trades) if t in finishes), None)
    finish = []
    if last is not None:
        f = finishes[last]
        finish = [TradeStep(last, f.key, f.name, f.half_days, "finish")]
    out = prep + remove + main + late + finish
    return out, Decimal(sum(s.half_days for s in out)) / 2


def totals(quotes: Iterable[Quote]) -> Totals:
    subtotal = vat = total = 0
    counts = {"public": 0, "assumed": 0, "none": 0}
    for q in quotes:
        subtotal += q.subtotal
        vat += q.vat
        total += q.total
        for ln in q.lines:
            if ln.state != "excluded":
                counts[ln.basis] += 1
    return Totals(subtotal, vat, total, counts)
