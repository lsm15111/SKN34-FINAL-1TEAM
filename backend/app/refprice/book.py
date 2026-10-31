"""기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

값마다 출처와 적용 시점을 붙이고, 공공 값이 없는 칸은 '팀 가정값'으로 적는다.
견적에는 version을 고정해서 나중에 값이 바뀌어도 만든 때의 기준을 알 수 있게 한다.
"""

from decimal import Decimal

from app.calc.dobae import DobaePrices, won

_WAGE_HELPER = 172_698  # 보통인부 2026.9.1 시중노임단가 (대한건설협회)

DOBAE_2026H2 = DobaePrices(
    version="2026H2",
    labor_wall=5_993,
    labor_ceiling=8_531,
    labor_ratio=Decimal("0.96"),
    paper={"basic": 3_325, "economy": 1_300},
    primer=242,
    removal=won(Decimal("0.01") * _WAGE_HELPER),
    paper_ratio=Decimal("1.2"),
    primer_wall_ratio=Decimal("1.2"),
    primer_ceiling_ratio=Decimal("0.8"),
    md_wall=Decimal("0.024"),
    md_ceiling=Decimal("0.027") * Decimal("1.3"),
    occupied_output=Decimal("0.85"),
    area_factor={"supply": Decimal("2.5"), "exclusive": Decimal("3.0")},
    ceiling_share=Decimal("0.25"),
    balcony_factor=Decimal("1.08"),
    crew=4,
    vat_rate=Decimal("0.1"),
    sources={
        "wall": "표준시장단가 2026 하반기 · 도배지바름 콘크리트 · 모르타르 벽",
        "ceiling": "표준시장단가 2026 하반기 · 도배지바름 석고 · 합판 천장",
        "paper_basic": "조달청 가격정보 비닐벽지 (2026-10 조회, 실크 대용)",
        "paper_economy": "팀 가정값 (합지는 공공 가격이 없어요)",
        "primer": "조달청 가격정보 초배지 (2026-10 조회) · 소요량 표준품셈",
        "occupied": "표준품셈 · 짐 있는 집 시공량 15% 감산, 노무비에만",
        "removal": "표준품셈 벽지 떼내기 × 2026.9.1 보통인부 노임",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
)
