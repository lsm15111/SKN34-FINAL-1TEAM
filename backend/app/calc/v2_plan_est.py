"""도면 수량과 비교할 '평형으로 어림한 값' (v10 CALC9 fromPlan의 est).

도배 면적 = 공급 × 2.5(천장 25%), 몰딩 = 공급 평 × 2.4m, 걸레받이 = 공급 평 × 1.8m. 소수 한 자리.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.calc.common import m2

PY_M2 = Decimal("3.305785")  # v10 CALC9 평 환산
FACTOR = Decimal("2.5")
CEILING_SHARE = Decimal("0.25")
MOLDING_PER_PY = Decimal("2.4")
BASE_PER_PY = Decimal("1.8")


@dataclass(frozen=True)
class PlanEst:
    py: Decimal
    wall_m2: Decimal
    ceiling_m2: Decimal
    molding_m: Decimal
    base_m: Decimal


def plan_est(supply_m2: Decimal) -> PlanEst:
    py = supply_m2 / PY_M2
    gross = supply_m2 * FACTOR
    return PlanEst(
        py=m2(py),
        wall_m2=m2(gross * (1 - CEILING_SHARE)),
        ceiling_m2=m2(gross * CEILING_SHARE),
        molding_m=m2(py * MOLDING_PER_PY),
        base_m=m2(py * BASE_PER_PY),
    )
