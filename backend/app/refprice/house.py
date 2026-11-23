"""집 크기 가정값 (내 집 평수 · 평형대 면적). 전용 → 공급 환산은 도배 · 목공과 같은 한 값(calc.common, ADR 0007)이다.

판마다 남겨 둬요. 옛 판(2026H2, 전용 × 1.2)은 기록이고, 새 계산은 HOUSE_DEFAULT를 써요.
"""

from decimal import Decimal

from app.calc.common import SUPPLY_PER_EXCLUSIVE
from app.calc.standard_quote import HouseRules

# 평형대마다 가장 흔한 평형: 전용 59㎡형은 공급 24평, 84㎡형은 34평이라 평형대 + 4평으로 잡는다
_BAND_PYEONG = {"10": 14, "20": 24, "30": 34, "40": 44, "50": 54}

HOUSE_2026H2 = HouseRules(
    version="2026H2",
    band_pyeong=_BAND_PYEONG,
    supply_per_exclusive=Decimal("1.2"),
    source="팀 가정값 (평형대는 흔한 평형으로, 전용면적은 × 1.2로 공급면적을 잡아요)",
)
# QA r6 c2(2026-11-24): 전용 84㎡가 30.5평으로 보였어요. 도배 면적과 같은 환산(× 1.315)으로 맞춘 판
HOUSE_2026_11 = HouseRules(
    version="2026.11",
    band_pyeong=_BAND_PYEONG,
    supply_per_exclusive=SUPPLY_PER_EXCLUSIVE,
    source="팀 가정값 (평형대는 흔한 평형으로, 전용면적은 × 1.315로 공급면적을 잡아요: 공개 공고 평면 20곳 가운데)",
)
HOUSE_DEFAULT = HOUSE_2026_11  # 지금 쓰는 판
