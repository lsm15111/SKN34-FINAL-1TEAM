"""욕실 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

방수 · 타일 · 실리콘은 공공 단가가 있고, 도기 · 수전 · 욕조 · 천장재는 공공 단가가 없어 팀 가정값이다.
조달청 '불연천장재 SMC 4412'는 사무실용 텍스(두께 15mm)라 욕실 SMC 천장재로 쓰지 않았다.
"""

from decimal import Decimal

from app.calc.bath import BathPrices

# 타일 한 조(타일공 + 보통인부)의 하루 노임 (2026.9.1 시중노임단가, 대한건설협회)
_TILE_TEAM = Decimal(294_379 + 172_698)

BATH_2026H2 = BathPrices(
    version="2026H2",
    wp_liquid=18_961,  # 재료 569 + 노무 18,392
    wp_coat=28_234,  # 재료 12,053 + 노무 16,181
    base_wall=13_566,  # 재료 272 + 노무 13,294
    tile_wall=42_574,  # 재료 1,278 + 노무 41,296
    tile_wall_overlay=28_543,  # 재료 857 + 노무 27,686
    tile_floor=39_821,  # 재료 1,195 + 노무 38,626
    wall_tile_mat=15_000,
    floor_tile_mat=12_000,
    tile_ratio=Decimal("1.03"),
    drain=40_250,
    caulk=3_713,
    ceiling={"smc": 45_000, "pvc": 35_000},
    toilet_basin=400_000,
    faucets=200_000,
    accessories=120_000,
    tub_new=450_000,
    partition=500_000,
    floor_m2=Decimal("4.0"),
    wall_m2=Decimal("17.0"),
    wp_up_m2=Decimal("2.5"),
    caulk_full_m=Decimal(12),
    caulk_fixture_m=Decimal(4),
    md_tile_wall=Decimal(41_296) / _TILE_TEAM,
    md_tile_wall_overlay=Decimal(27_686) / _TILE_TEAM,
    md_tile_floor=Decimal(38_626) / _TILE_TEAM,
    md_fit=Decimal("0.75"),
    md_fixture_only=Decimal("0.5"),
    md_tub=Decimal("0.5"),
    tile_crew=2,
    fit_crew=2,
    wp_half_days=3,
    cure_half_days=2,
    vat_rate=Decimal("0.1"),
    sources={
        "wp_liquid": "표준시장단가 2026 하반기 · 시멘트 액체방수 바닥",
        "wp_coat": "조달청 시장시공가격 2026-10 · 우레탄 도막방수 바닥 비노출 2mm (재료 포함)",
        "base_wall": "표준시장단가 2026 하반기 · 타일 바탕 고르기 벽",
        "tile_wall": "표준시장단가 2026 하반기 · 타일 압착붙이기 벽 0.11~0.20㎡ (타일 제외)",
        "tile_wall_overlay": "표준시장단가 2026 하반기 · 타일 접착붙이기 벽 0.11~0.20㎡ (타일 제외)",
        "tile_floor": "표준시장단가 2026 하반기 · 타일 압착붙이기 바닥 0.04~0.10㎡ (타일 제외)",
        "wall_tile_mat": "조달청 가격정보 2026-10 · 도기질 타일 300×600 · 할증 표준품셈",
        "floor_tile_mat": "조달청 가격정보 2026-10 · 자기질 타일 300×300 · 할증 표준품셈",
        "drain": "조달청 가격정보 2026-10 · 바닥 배수구 50mm",
        "caulk": "표준시장단가 2026 하반기 · 수밀코킹 삼각 폭 15mm 이하 (재료 제외)",
        "ceiling_smc": "팀 가정값 (욕실 SMC 천장재는 공공 가격이 없어요)",
        "ceiling_pvc": "팀 가정값 (욕실 PVC 천장재는 공공 가격이 없어요)",
        "toilet_basin": "팀 가정값 (양변기 · 세면기는 공공 가격이 없어요 · 보급형 기준)",
        "faucets": "팀 가정값 (수전은 공공 가격이 없어요 · 보급형 기준)",
        "accessories": "팀 가정값 (욕실 액세서리 묶음은 공공 가격이 없어요)",
        "tub_new": "팀 가정값 (욕조는 공공 가격이 없어요 · 아크릴 욕조 기준)",
        "partition": "팀 가정값 (샤워 파티션은 공공 가격이 없어요 · 고정형 유리 기준)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
)
