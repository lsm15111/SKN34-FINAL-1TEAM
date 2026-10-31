"""주방 가정값 한 벌 (2026 하반기). 주방 가구 · 상판 · 후드 · 수전은 공공 기준 단가가 없다.

표준시장단가 · 시장시공가격 · 조달청 시설공통자재에 싱크대 · 주방 상판 항목이 없어 모든 값이 팀 가정값이다.
조달청 '인조대리석'은 400×400 바닥 · 벽 판재라 주방 상판에 쓰지 않았다. 근거가 생기면 이 파일만 바꾼다.
"""

from decimal import Decimal

from app.calc.kitchen import KitchenPrices

KITCHEN_2026H2 = KitchenPrices(
    version="2026H2",
    cabinet=450_000,
    top={"acrylic": 200_000, "quartz": 400_000},
    hood=250_000,
    sink=250_000,
    len_per_py=Decimal("0.1"),
    len_min=Decimal("2.4"),
    len_max=Decimal("4.2"),
    layout_factor={
        "straight": Decimal("1.0"),
        "l_shape": Decimal("1.4"),
        "parallel": Decimal("1.7"),
    },
    supply_per_exclusive=Decimal("1.2"),
    md_cabinet=Decimal("0.4"),
    crew=2,
    vat_rate=Decimal("0.1"),
    sources={
        "cabinet": "팀 가정값 (싱크대는 공공 단가가 없어요 · PET 도어 보급형 기준)",
        "top_acrylic": "팀 가정값 (주방 상판은 공공 단가가 없어요 · 인조대리석 기준)",
        "top_quartz": "팀 가정값 (주방 상판은 공공 단가가 없어요 · 엔지니어드스톤 기준)",
        "hood": "팀 가정값 (레인지후드는 공공 가격이 없어요 · 보급형 기준)",
        "sink": "팀 가정값 (싱크볼 · 수전은 공공 가격이 없어요 · 보급형 기준)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
)
