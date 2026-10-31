"""인테리어 필름 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

값마다 출처와 적용 시점을 붙이고, 공공 값이 없는 칸은 '팀 가정값'으로 적는다.
필름은 시중노임에 직종이 없어 내장공 노임으로 품을 잡는다 (시장시공가격 노무비 ÷ 노임).
"""

from decimal import Decimal

from app.calc.film import FilmPrices

_WAGE_INTERIOR = Decimal(258_904)  # 내장공, 2026.9.1 시중노임단가 (대한건설협회). 필름공 직종 없음

# 시장시공가격 = 재료비(공구손료 3%) + 노무비. 폭 300mm 이상 667 + 22,266 · 미만 1,242 + 41,426
FILM_2026H2 = FilmPrices(
    version="2026H2",
    wide=22_933,
    narrow=42_668,
    md_wide=Decimal(22_266) / _WAGE_INTERIOR,
    md_narrow=Decimal(41_426) / _WAGE_INTERIOR,
    film={"basic": 8_000, "premium": 15_000},
    film_ratio=Decimal("1.3"),
    leaf_m2=Decimal("3.8"),
    frame_m2=Decimal("1.5"),
    entrance_leaf_m2=Decimal("2.1"),
    entrance_frame_m2=Decimal("0.8"),
    molding_per_py=Decimal("2.4"),
    molding_width=Decimal("0.1"),
    closet_per_py=Decimal("0.25"),
    kitchen_per_py=Decimal("0.15"),
    supply_per_exclusive=Decimal("1.2"),
    crew=2,
    vat_rate=Decimal("0.1"),
    sources={
        "wide": "조달청 시장시공가격 2026-10 · 인테리어필름 붙임 폭 300mm 이상 (필름 제외)",
        "narrow": (
            "조달청 시장시공가격 2026-10 · 인테리어필름 붙임 폭 300mm 미만, 몰딩 · 틀 (필름 제외)"
        ),
        "film_basic": "팀 가정값 (인테리어 필름 자재는 공공 가격이 없어요, 프라이머 포함)",
        "film_premium": "팀 가정값 (인테리어 필름 자재는 공공 가격이 없어요, 프라이머 포함)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
    assumed=frozenset({"film_basic", "film_premium"}),
)
