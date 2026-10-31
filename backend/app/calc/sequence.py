"""공정 여러 개를 한 줄의 예상 공정표로 잇고, 공정 견적을 하나로 합친다.

공정 순서는 부르는 쪽이 넘긴다 (상담은 공정 레지스트리의 order 순서). 계산 엔진이라 레지스트리를 모른다.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.calc.common import Quote, Step


@dataclass(frozen=True)
class TradeStep:
    trade: str
    key: str
    name: str
    half_days: int


@dataclass(frozen=True)
class Totals:
    """공정 견적 합계. 금액은 공정마다 이미 반올림한 값을 더하기만 한다 (VAT도 공정별 VAT의 합)."""

    subtotal: int
    vat: int
    total: int
    basis_counts: dict[str, int]  # 줄 근거별 개수 (public · assumed · none, '안 함' 줄은 빼고)


def sequence(
    steps: dict[str, list[Step]], order: Sequence[str] = ("mokgong", "dobae")
) -> tuple[list[TradeStep], Decimal]:
    """order 순서로 공정을 잇는다. 짐 정리 · 보양은 처음 한 번만 하고, 정리 · 청소 마감은 마지막 공정에만 둔다.

    order를 넘기지 않으면 예전 순서(목공 → 도배)다. order에 없는 공정이 들어오면 ValueError.
    """
    if set(steps) - set(order):
        raise ValueError("공정 순서에 없는 공정이 있어요")
    trades = [t for t in order if steps.get(t)]
    out: list[TradeStep] = []
    prepped = False
    for t in trades:
        for st in steps[t]:
            if st.key == "prep":
                if prepped:
                    continue
                prepped = True
            if st.key == "finish" and t != trades[-1]:
                continue
            out.append(TradeStep(t, st.key, st.name, st.half_days))
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
