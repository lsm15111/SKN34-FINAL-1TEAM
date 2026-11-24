"""업체 금액과 표준견적서 금액의 차이 · 표준견적서 두 계산의 바뀌는 줄."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.calc.common import COUNTED, Line


def percent_vs(amount: int, standard: int) -> Decimal:
    """표준 대비 몇 % 많은지(음수면 적음). 소수 한 자리에서 반올림한다."""
    if standard <= 0 or amount < 0:
        raise ValueError("금액은 0보다 커야 해요")
    pct = (Decimal(amount) - Decimal(standard)) / Decimal(standard) * 100
    return pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# 예산 구간(원, 부가세 포함 합계와 견준다)의 위 한도. 위 한도가 없거나 아직 몰라요면 None
BUDGET_TOP: dict[str, int | None] = {
    "u300": 3_000_000,
    "300-500": 5_000_000,
    "500-700": 7_000_000,
    "700-1000": 10_000_000,
    "o1000": None,
    "undecided": None,
}


def budget_gap(total: int, band: str) -> tuple[str, int | None]:
    """('within' · 'over' · 'open', 넘은 금액). 위 한도가 없으면 open."""
    if band not in BUDGET_TOP or total < 0:
        raise ValueError("예산 구간을 다시 확인해 주세요")
    top = BUDGET_TOP[band]
    if top is None:
        return "open", None
    return ("over", total - top) if total > top else ("within", None)


def budget_fit(total: int, budget_won: int | None) -> Literal["within", "over"] | None:
    """v3 예산(원)과 부가세 포함 합계를 견준다: 안(같으면 안) · 밖. 예산을 안 넣었으면 None."""
    if budget_won is None:
        return None
    if total < 0 or budget_won <= 0:
        raise ValueError("금액은 0보다 커야 해요")
    return "over" if total > budget_won else "within"


# ---- 표준견적서 두 계산(지금 · 바꾼 뒤)의 바뀌는 줄: 집 정보 승인 카드 차액의 까닭(QA r7 c2 T10 · T11) ----

LINE_CHANGES_TOP = 5  # 까닭으로 넘기는 줄 수(합계 몫 차가 큰 순)


@dataclass(frozen=True)
class LineChange:
    """한 줄이 어떻게 바뀌는지: 지금 · 바꾼 뒤 줄(한쪽에 없으면 None)과 합계에 드는 몫(포함 · 따로 계산 줄의 공급가,
    아니면 0)의 차(바꾼 뒤 − 지금)."""

    key: str
    before: Line | None
    after: Line | None
    gap: int

    @property
    def state_moved(self) -> bool:
        """포함 상태가 바뀌었는지(줄이 새로 생기거나 없어진 것도)."""
        was = self.before.state if self.before is not None else None
        now = self.after.state if self.after is not None else None
        return was != now


def _counted(ln: Line | None) -> int:
    """합계에 드는 몫(공급가): 포함 · 따로 계산 줄의 금액, 아니면 0."""
    return ln.amount if ln is not None and ln.state in COUNTED and ln.amount is not None else 0


def line_changes(
    before: Mapping[str, Line], after: Mapping[str, Line], top: int = LINE_CHANGES_TOP
) -> list[LineChange]:
    """두 계산의 줄(키 → 줄, 키는 부르는 쪽이 정한다 '공정:줄 키') → 포함 상태가 바뀌었거나 합계에 드는 금액이 달라진
    줄 top개. 합계 몫 차가 큰 순이고, 같으면 상태가 바뀐 줄 · 줄 차례 순이에요. 금액은 줄 값 그대로(공급가)라 합계
    (부가세 포함) 차액과 더하거나 빼지 않아요."""
    if top < 1:
        raise ValueError("줄 수는 1 이상이에요")
    keys = list(dict.fromkeys([*before, *after]))
    got = [
        LineChange(k, before.get(k), after.get(k), _counted(after.get(k)) - _counted(before.get(k)))
        for k in keys
    ]
    moved = [c for c in got if c.gap or c.state_moved]
    order = {k: i for i, k in enumerate(keys)}
    moved.sort(key=lambda c: (-abs(c.gap), not c.state_moved, order[c.key]))
    return moved[:top]
