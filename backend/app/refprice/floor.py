"""바닥재 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

값마다 출처와 적용 시점을 붙이고, 공공 값이 없는 칸은 '팀 가정값'으로 적는다.
품은 공공 단가의 노무비를 같은 직종의 2026.9.1 시중노임으로 나눈 기능공 인 · 일이다.
"""

from decimal import Decimal

from app.calc.floor import FloorPrices

# 2026.9.1 시중노임단가 (대한건설협회). 장판은 도배공 직종에 들어간다
_WAGE_PAPER = Decimal(229_833)  # 도배공
_WAGE_FLOORING = Decimal(257_926)  # 플로어링마루시공공
_WAGE_TILE = Decimal(294_379)  # 타일공

FLOOR_2026H2 = FloorPrices(
    version="2026H2",
    # 표준시장단가 = 재료비(부자재) + 노무비. 장판 1,093 + 6,188 · 마루 745 + 11,663 · 타일 955 + 30,867
    lay={"vinyl": 7_281, "wood": 12_408, "tile": 31_822},
    mat={
        "vinyl_18": 10_530,
        "vinyl_22": 14_580,
        "engineered": 22_000,
        "laminate": 14_000,
        "porcelain": 29_000,
    },
    mat_ratio={"vinyl": Decimal("1.1"), "wood": Decimal("1.05"), "tile": Decimal("1.05")},
    tile_sub=4_000,
    level=13_391,  # 262 + 13,129
    md={
        "vinyl": Decimal(6_188) / _WAGE_PAPER,
        "wood": Decimal(11_663) / _WAGE_FLOORING,
        "tile": Decimal(30_867) / _WAGE_TILE,
    },
    supply_per_exclusive=Decimal("1.2"),
    floor_share=Decimal("0.8"),
    balcony_factor=Decimal("1.15"),
    remove_half_days=2,
    cure_half_days=2,
    crew=2,
    vat_rate=Decimal("0.1"),
    sources={
        "lay_vinyl": "표준시장단가 2026 하반기 · 합성고분자계 바닥재 시트 전면접합 (장판 제외)",
        "lay_wood": "표준시장단가 2026 하반기 · 플로어링 마루 설치 (마루 제외)",
        "lay_tile": "표준시장단가 2026 하반기 · 타일 압착붙이기 바닥 0.21~0.40㎡ (타일 제외)",
        "mat_vinyl_18": "조달청 가격정보 PVC 바닥재 1.8mm (2026-10 공고)",
        "mat_vinyl_22": "조달청 가격정보 PVC 바닥재 2.2mm (2026-10 공고)",
        "mat_engineered": "팀 가정값 (강마루 자재는 공공 가격이 없어요, 본드 포함)",
        "mat_laminate": "팀 가정값 (강화마루 자재는 공공 가격이 없어요, 밑깔개 포함)",
        "mat_porcelain": (
            "팀 가정값 (대형 포세린은 공공 가격이 없어 조달청 자기질 무유연마 300×600"
            " 2026-04 값을 빌려 써요)"
        ),
        "sub": "팀 가정값 (붙임재 · 줄눈재는 공공 가격이 없어요)",
        "level": "조달청 시장시공가격 2026-10 · 셀프레벨링 10mm 이하 (자재 제외)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
    assumed=frozenset({"mat_engineered", "mat_laminate", "mat_porcelain", "sub"}),
)
