"""타일 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

값마다 출처와 적용 시점을 붙이고, 공공 값이 없는 칸은 '팀 가정값'으로 적는다.
품은 표준시장단가의 노무비를 2026.9.1 타일공 시중노임으로 나눈 기능공 인 · 일이다.
"""

from decimal import Decimal

from app.calc.tile import TilePrices

_WAGE_TILE = Decimal(294_379)  # 타일공, 2026.9.1 시중노임단가 (대한건설협회)


def _md(labor: int) -> Decimal:
    return Decimal(labor) / _WAGE_TILE


# 크기 구간: small 0.04~0.10㎡ · medium 0.11~0.20㎡ · large 0.21~0.40㎡ (타일 한 장 넓이)
# 표준시장단가 = 재료비(공구손료 등) + 노무비. 예: 벽 압착 small 1,443 + 46,633
TILE_2026H2 = TilePrices(
    version="2026H2",
    wall_press={"small": 48_076, "medium": 42_574, "large": 38_903},
    wall_glue={"small": 31_184, "medium": 28_543, "large": 26_729},
    floor={"small": 39_821, "medium": 35_025, "large": 31_822},
    md_wall_press={"small": _md(46_633), "medium": _md(41_296), "large": _md(37_735)},
    md_wall_glue={"small": _md(30_248), "medium": _md(27_686), "large": _md(25_927)},
    md_floor={"small": _md(38_626), "medium": _md(33_974), "large": _md(30_867)},
    base_wall=13_566,  # 272 + 13,294
    base_floor=10_116,  # 203 + 9,913
    mat_wall={"small": 12_000, "medium": 15_000, "large": 29_000},
    mat_floor={"small": 12_000, "medium": 19_000, "large": 29_000},
    mat_ratio=Decimal("1.05"),
    sub=4_000,
    per_py={"kitchen": Decimal("0.12"), "entrance": Decimal("0.06"), "balcony": Decimal("0.2")},
    supply_per_exclusive=Decimal("1.2"),
    remove_half_days=2,
    cure_half_days=2,
    crew=2,
    vat_rate=Decimal("0.1"),
    sources={
        "wall_press": "표준시장단가 2026 하반기 · 타일 압착붙이기 벽 (크기별, 타일 제외)",
        "wall_glue": "표준시장단가 2026 하반기 · 타일 접착붙이기 벽 (크기별, 타일 제외)",
        "floor": "표준시장단가 2026 하반기 · 타일 압착붙이기 바닥 (크기별, 타일 제외)",
        "base_wall": "표준시장단가 2026 하반기 · 타일 바탕 고르기 벽",
        "base_floor": "표준시장단가 2026 하반기 · 타일 바탕 고르기 바닥",
        "mat_wall_small": "조달청 가격정보 도기질 타일 250×400 · 300×300 (2026-10 공고)",
        "mat_wall_medium": "조달청 가격정보 도기질 타일 300×600 (2026-10 공고)",
        "mat_wall_large": (
            "팀 가정값 (큰 타일은 공공 가격이 없어 조달청 자기질 무유연마 300×600"
            " 2026-04 값을 빌려 써요)"
        ),
        "mat_floor_small": "조달청 가격정보 자기질 타일 시유 300×300 (2026-10 공고)",
        "mat_floor_medium": "조달청 가격정보 자기질 타일 무유색소 400×400 (2026-04 공고)",
        "mat_floor_large": (
            "팀 가정값 (큰 타일은 공공 가격이 없어 조달청 자기질 무유연마 300×600"
            " 2026-04 값을 빌려 써요)"
        ),
        "sub": "팀 가정값 (붙임재 · 줄눈재는 공공 가격이 없어요)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
    assumed=frozenset({"mat_wall_large", "mat_floor_large", "sub"}),
)
