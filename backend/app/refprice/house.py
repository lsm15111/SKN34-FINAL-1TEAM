"""집 크기 가정값 (내 집 평수 · 평형대 면적). 도배 · 목공 단가와 같은 전용 → 공급 환산(1.2)을 쓴다."""

from dataclasses import replace
from decimal import Decimal

from app.calc.standard_quote import HouseRules

HOUSE_2026H2 = HouseRules(
    version="2026H2",
    # 평형대마다 가장 흔한 평형: 전용 59㎡형은 공급 24평, 84㎡형은 34평이라 평형대 + 4평으로 잡는다
    band_pyeong={"10": 14, "20": 24, "30": 34, "40": 44, "50": 54},
    supply_per_exclusive=Decimal("1.2"),
    source="팀 가정값 (평형대는 흔한 평형으로, 전용면적은 × 1.2로 공급면적을 잡아요)",
)

# r2: 공급 ÷ 전용 1.3 (24평형 1.34 · 32평형 1.26 · 34평형 1.34 · 43평형 1.25, docs/research/T2 4.4 · T3)
HOUSE_2026H2_R2 = replace(
    HOUSE_2026H2,
    version="2026H2-r2",
    supply_per_exclusive=Decimal("1.3"),
    source="팀 가정값 (평형대는 흔한 평형으로, 전용면적은 × 1.3으로 공급면적을 잡아요)",
)

# 지금 계산에 쓰는 집 크기 가정값
HOUSE = HOUSE_2026H2_R2
