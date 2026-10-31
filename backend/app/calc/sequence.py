"""공정 여러 개를 한 줄의 예상 공정표로 잇는다. 목공이 끝난 뒤 도배한다."""

from dataclasses import dataclass
from decimal import Decimal

from app.calc.dobae import Step

ORDER = ("mokgong", "dobae")


@dataclass(frozen=True)
class TradeStep:
    trade: str
    key: str
    name: str
    half_days: int


def sequence(steps: dict[str, list[Step]]) -> tuple[list[TradeStep], Decimal]:
    """짐 정리 · 보양은 처음 한 번만 하고, 도배가 뒤에 오면 목공의 정리 · 청소는 도배 마감에 합친다."""
    trades = [t for t in ORDER if steps.get(t)]
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
