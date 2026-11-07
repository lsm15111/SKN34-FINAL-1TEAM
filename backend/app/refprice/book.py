"""도배 · 목공 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

값마다 출처와 적용 시점을 붙이고, 공공 값이 없는 칸은 '팀 가정값'으로 적는다.
견적에는 version을 고정해서 나중에 값이 바뀌어도 만든 때의 기준을 알 수 있게 한다.
"""

from dataclasses import replace
from decimal import Decimal

from app.calc.common import won
from app.calc.dobae import DobaePrices
from app.calc.mokgong import MokgongPrices

_WAGE_HELPER = 172_698  # 보통인부 2026.9.1 시중노임단가 (대한건설협회)
# 목재창호 설치 여닫이 1.0~3.0㎡ 원/개소: 단가표 재료비 3,294 + 노무비 79,045 (문 자재는 따로)
_DOOR_INSTALL = 82_339

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

MOKGONG_2026H2 = MokgongPrices(
    version="2026H2",
    molding=8_168,
    molding_mat=3_000,
    molding_ratio=Decimal("1.1"),
    base=3_757,
    base_mat=2_000,
    base_ratio=Decimal("1.04"),
    door_install=_DOOR_INSTALL,
    door_leaf_install=won(Decimal(_DOOR_INSTALL) / 2),
    door_set_mat=260_000,
    door_leaf_mat=150_000,
    casing=2_314,
    casing_per_door=Decimal("10.2"),
    frame=11_054,
    board=12_937,
    ceiling_mat=8_000,
    md_molding=Decimal("0.035"),
    md_base=Decimal(2) / Decimal(165),
    md_door=Decimal("0.313"),
    md_casing=Decimal("0.010"),
    md_frame=Decimal("0.0323"),
    md_board=Decimal(2) / Decimal(45),
    molding_per_py=Decimal("2.4"),
    base_per_py=Decimal("1.8"),
    supply_per_exclusive=Decimal("1.2"),
    flatten_share=Decimal("0.3"),
    crew=2,
    vat_rate=Decimal("0.1"),
    sources={
        "molding": "표준시장단가 2026 하반기 · 몰딩 설치 (재료 제외)",
        "molding_mat": "팀 가정값 (몰딩 자재는 공공 가격이 없어요) · 소요량 표준품셈",
        "base": "표준시장단가 2026 하반기 · 걸레받이 MDF (재료 제외)",
        "base_mat": "팀 가정값 (걸레받이 자재는 공공 가격이 없어요) · 소요량 표준품셈",
        "door_install": "표준시장단가 2026 하반기 · 목재창호 설치 여닫이 1.0~3.0㎡ (재료 제외)",
        "door_leaf_install": "팀 가정값 (문짝만 다는 공공 단가가 없어 목재창호 설치 여닫이의 절반)",
        "casing": "표준시장단가 2026 하반기 · 목재창호 설치 문선 (재료 제외)",
        "door_set_mat": "팀 가정값 (조달청에 목재 · ABS 방문 가격이 없어요) · 문틀 · 문짝 · 문선 · 철물",
        "door_leaf_mat": "팀 가정값 (조달청에 목재 · ABS 방문 가격이 없어요) · 문짝 · 철물",
        "frame": "표준시장단가 2026 하반기 · 경량천장틀 BAR 간격 450 (재료 제외)",
        "board": "표준시장단가 2026 하반기 · 천장 석고판 1겹 (석고판 제외)",
        "ceiling_mat": "팀 가정값 (천장틀 · 석고보드 자재는 공공 가격이 없어요)",
        "none": "공공 단가가 없어 업체 견적에서 확인해요",
    },
)


# ── 2026 하반기 r2: 표준품셈 · 표준시장단가 원문과 대조해 고친 값 (docs/research/T2 · T3) ──
# 지금 계산에 쓰는 한 벌은 맨 아래 DOBAE · MOKGONG이다. 버전을 바꿀 때는 그 두 줄과 FORMULA_VERSION을 함께 바꾼다.
_WAGE_PAPERER = 229_833  # 도배공 2026.9.1 시중노임단가 (대한건설협회)
_REMOVE_WALL = won(Decimal("0.008") * _WAGE_PAPERER + Decimal("0.005") * _WAGE_HELPER)  # 2,702원/㎡
_REMOVE_CEILING = won(Decimal("0.010") * _WAGE_PAPERER + Decimal("0.007") * _WAGE_HELPER)  # 3,507
_CEILING_SHARE_R2 = Decimal("0.30")

DOBAE_2026H2_R2 = replace(
    DOBAE_2026H2,
    version="2026H2-r2",
    # 업계 배수(공급 × 2.5 · 전용 × 3.0)는 벽 + 천장 합계다. 공급 × 2.5에 확장 1.08을 같이 쓰면 24 · 34평형에서
    # 10~18% 많아서 공급은 2.3으로 둔다. AI Hub 도면 벽 면적(전용 × 2.15)과 맞는다(T2 4.4)
    area_factor={"supply": Decimal("2.3"), "exclusive": Decimal("3.0")},
    ceiling_share=_CEILING_SHARE_R2,  # 합계 중 천장 28~33%(T2 4.4)
    # 표준품셈 건축 5-3-7 도배바름: 도배공 2 + 보통인부 1이 콘크리트 벽 95㎡ · 석고보드면 85㎡/일, 천장은 23% 감.
    # 단가 짝(벽 = 콘크리트 5,993원, 천장 = 석고보드 8,531원)에 맞춰 품도 같은 바탕으로 잡고, 천장 감은 한 번만(÷0.77)
    md_wall=Decimal(2) / Decimal(95),
    md_ceiling=Decimal(2) / (Decimal(85) * Decimal("0.77")),
    # 표준품셈 유지관리 3-2-7 도배 해체(벽 2,702 · 천장 3,507원/㎡)를 천장 30%로 섞은 값
    removal=won((1 - _CEILING_SHARE_R2) * _REMOVE_WALL + _CEILING_SHARE_R2 * _REMOVE_CEILING),
    sources={
        **DOBAE_2026H2.sources,
        "removal": "표준품셈 도배 해체(벽 도배공 0.008 + 보통인부 0.005, 천장 0.010 + 0.007인/㎡) × "
        "2026.9.1 노임, 천장 30%로 섞음",
    },
)

MOKGONG_2026H2_R2 = replace(
    MOKGONG_2026H2,
    version="2026H2-r2",
    # 공급 ÷ 전용: 24평형 1.34 · 32평형 1.26 · 34평형 1.34 · 43평형 1.25(T2 4.4), 시장 통칭 1.31~1.40(T3)
    supply_per_exclusive=Decimal("1.3"),
    casing_per_door=Decimal("11.0"),  # 문 하나 문선 양면(T3 권장, 가정값)
)

# 지금 계산에 쓰는 기준 단가 (2026-11-08 r2로 바꿈. r1은 버전 기록 · 비교용으로 남긴다)
DOBAE = DOBAE_2026H2_R2
MOKGONG = MOKGONG_2026H2_R2
