"""도장 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

값마다 출처와 적용 시점을 붙이고, 공공 값이 없는 칸은 '팀 가정값'으로 적는다.
품은 표준시장단가의 노무비를 2026.9.1 도장공 시중노임으로 나눈 기능공 인 · 일이다.
"""

from decimal import Decimal

from app.calc.common import won
from app.calc.paint import PaintPrices

# 2026.9.1 시중노임단가 (대한건설협회)
_WAGE_PAINTER = Decimal(268_225)  # 도장공
_WAGE_HELPER = 172_698  # 보통인부


def _md(labor: int) -> Decimal:
    return Decimal(labor) / _WAGE_PAINTER


# 표준시장단가 = 재료비(공구손료 등) + 노무비. 예: 롤러칠 벽 68 + 3,312 · 올퍼티 벽 385 + 18,853
PAINT_2026H2 = PaintPrices(
    version="2026H2",
    roll={"wall": 3_380, "ceiling": 4_045},
    brush=6_254,
    wood_prep=2_443,
    putty={
        "wall": {"joint": 10_398, "full": 19_238},
        "ceiling": {"joint": 12_410, "full": 23_319},
    },
    removal=won(Decimal("0.01") * _WAGE_HELPER),
    paint_l={"standard": 3_729, "eco": 9_000},
    paint_ratio=Decimal("0.11"),
    coats=2,
    elastic_coats=3,
    elastic_mat=5_000,
    md_roll={"wall": _md(3_312), "ceiling": _md(3_964)},
    md_brush=_md(6_128),
    md_wood_prep=_md(2_394),
    md_putty={
        "wall": {"joint": _md(10_190), "full": _md(18_853)},
        "ceiling": {"joint": _md(12_161), "full": _md(22_852)},
    },
    area_factor={"supply": Decimal("2.5"), "exclusive": Decimal("3.0")},
    ceiling_share=Decimal("0.25"),
    balcony_factor=Decimal("1.08"),
    door_m2=Decimal("4.8"),
    balcony_per_py=Decimal("0.8"),
    supply_per_exclusive=Decimal("1.2"),
    mask_half_days=1,
    spot_half_days=1,
    crew=3,
    vat_rate=Decimal("0.1"),
    sources={
        "roll_wall": "표준시장단가 2026 하반기 · 수성페인트 롤러칠 1회 벽체 (페인트 제외)",
        "roll_ceiling": "표준시장단가 2026 하반기 · 수성페인트 롤러칠 1회 천정 (페인트 제외)",
        "brush": (
            "표준시장단가 2026 하반기 · 수성페인트 붓칠 1회 벽체 (문 · 문틀에 대용, 페인트 제외)"
        ),
        "wood_prep": "표준시장단가 2026 하반기 · 목재면 바탕만들기 퍼티 및 연마 벽체",
        "putty_wall_joint": "표준시장단가 2026 하반기 · 석고보드면 바탕만들기 줄퍼티 벽체",
        "putty_wall_full": "표준시장단가 2026 하반기 · 석고보드면 바탕만들기 올퍼티 벽체",
        "putty_ceiling_joint": "표준시장단가 2026 하반기 · 석고보드면 바탕만들기 줄퍼티 천장",
        "putty_ceiling_full": "표준시장단가 2026 하반기 · 석고보드면 바탕만들기 올퍼티 천장",
        "removal": "표준품셈 벽지 떼내기 × 2026.9.1 보통인부 노임",
        "paint_standard": "조달청 가격정보 수성페인트 KS M 6010 2종 1급 (내부용, 2026-10 공고)",
        "paint_eco": "팀 가정값 (친환경 인증 페인트는 공공 가격이 없어요)",
        "elastic": (
            "표준시장단가 2026 하반기 · 수성페인트 롤러칠 1회 벽체 × 횟수 (탄성코트 칠에 대용)"
        ),
        "elastic_mat": "팀 가정값 (탄성코트 자재는 공공 가격이 없어요)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
    assumed=frozenset({"paint_eco", "elastic_mat"}),
)
