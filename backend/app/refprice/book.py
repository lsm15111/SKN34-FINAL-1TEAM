"""도배 · 목공 기준 단가 한 벌 (2026 하반기). 수집 · DB 표는 다음 단계라 지금은 코드에 둔다.

값마다 출처와 적용 시점을 붙이고, 공공 값이 없는 칸은 '팀 가정값'으로 적는다.
견적에는 version을 고정해서 나중에 값이 바뀌어도 만든 때의 기준을 알 수 있게 한다.
"""

from dataclasses import replace
from decimal import Decimal

from app.calc.common import won
from app.calc.dobae import DobaePrices, ProfilePrices, WorkFacts, pick_profile
from app.calc.mokgong import MokgongPrices
from app.calc.precise_common import SilkPaper

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

# v3 표준견적서 · 손님 계산 · 가견적이 쓰는 판 (docs/v3/research/whole-house-area.md 방안 4).
# 옛 판(2026H2)은 v2 단가표 예시 · 정밀 견적 같은 옛 계산이 그대로 쓴다.
# - 도배 면적 = 공급㎡ × 1.55 + 방 개수 × 20.4㎡ (확장 평면도 20곳 회귀, 오차 11.7㎡)
# - 전용면적은 × 1.315로 공급면적을 잡는다 (공고 평면 20곳 공급 ÷ 전용 가운뎃값)
# - 천장 0.35 (평면도 0.349). 회귀가 확장 집 기준이라 발코니 확장 가산은 1(더하지 않음)
# - area_factor는 고정 배수로 셀 때의 바로잡은 값(공급 2.2 · 전용 2.9, 방안 1). 회귀식이 있어 지금은 안 쓴다
# - 방 개수 기본값: 공급 22평 미만 2개 · 22~39평 3개 · 40평 이상 4개 (평면도 20곳 · 집닥 34평 → 3)
DOBAE_V3_2026_11 = replace(
    DOBAE_2026H2,
    version="2026H2-rooms",
    area_factor={"supply": Decimal("2.2"), "exclusive": Decimal("2.9")},
    ceiling_share=Decimal("0.35"),
    balcony_factor=Decimal(1),
    area_per_supply=Decimal("1.55"),
    area_per_room=Decimal("20.4"),
    supply_per_exclusive=Decimal("1.315"),
    room_bands=((Decimal(0), 2), (Decimal(22), 3), (Decimal(40), 4)),
    room_fallback=3,
    sources={
        **DOBAE_2026H2.sources,
        "area": "팀 가정값 · 공개 평면도 20곳 회귀 (공급 × 1.55 + 방 × 20.4㎡, plans-2026.11-v9)",
    },
)

# ---- v4 조건별 두 기준 (2026-11-21 사용자 결정, ADR docs/v4/adr/0004-금액-조건별-두-기준.md) ----
# 어느 기준인지는 계산 엔진(calc.dobae.pick_profile)이 공사 조건으로 골라요. 새 표준견적서는 이 두 판으로 세고,
# 이미 만든 견적은 저장한 줄 · 판(2026H2-rooms)을 그대로 둬요. 면적 회귀 · 방 개수 · 품은 v3 판과 같다.
# 근거: d10-/data/price-sources/README.md(추천안 R) · d10-/reports/v4 비서 에이전트/quote-accuracy/README.md(P3)
_MARKET = "시장 실견적 가운데(8출처 619건, 2026-11)"
_SEOUL = "서울 업체 실견적 보정(2026-11)"
_HAPJI_MULT = "합지 품은 실크의 0.55배, 시장 실견적 가운데"
_WAGE_REMODEL = 300_000  # 서울 업체 인건비 품당 30만 원(235건 중 216건)

# 도배만 하는 공사: 시장 가운데(추천안 R). 실크 벽지 × 1.04(소요량 1.2 → 1.248), 시공은 공공 단가 그대로,
# 초배지 줄 → 부자재(실크 6,900 · 합지 3,300원/공급 평), 합지 시공비 × 0.55.
# 퍼티(넣은 견적 5곳 가운데 14,264원/평) · 운송 · 경비(5만 원)는 넣는 곳이 5~38%뿐이라 '선택'(합계 밖)
DOBAE_MARKET_2026_11 = replace(
    DOBAE_V3_2026_11,
    version="2026.11-market",
    profile=ProfilePrices(
        key="paper_only",
        name="도배만 하는 공사 기준",
        source=_MARKET,
        labor_basis="public",
        labor_mult={"basic": Decimal(1), "economy": Decimal("0.55")},
        paper_ratio={"basic": Decimal("1.248"), "economy": Decimal("1.2")},
        material_py={"basic": 6_900, "economy": 3_300},
        putty_py=14_264,
        putty_state="optional",
        meal_md=None,
        truck=50_000,
        truck_state="optional",
        sources={
            "material": f"{_MARKET} · 부자재 공급 평당 (가게 견적 가운데)",
            "putty": f"{_MARKET} · 퍼티를 넣은 견적 5곳 공급 평당 가운데",
            "truck": f"{_MARKET} · 운송 · 경비를 받은 견적 5곳 가운데",
            "labor_mult": _HAPJI_MULT,
        },
    ),
)

# 전체 철거 · 목공이 크게 든 리모델링: 서울 업체 실견적 보정(P3). 시공 ㎡ 단가 = 표준품셈 품 × 일당 30만 원
# (벽 0.024 · 천장 0.0351인/㎡), 벽지 소요량 1.58, 부자재 16,000 · 퍼티 20,000원/공급 평, 식대 15,000원/품,
# 운송비 30,000원. 시공 줄은 인건비만이라(풀은 부자재 줄) 짐 할증도 시공 금액 전부에 붙인다(labor_ratio 1)
DOBAE_REMODEL_2026_11 = replace(
    DOBAE_V3_2026_11,
    version="2026.11-remodel",
    labor_wall=won(DOBAE_V3_2026_11.md_wall * _WAGE_REMODEL),
    labor_ceiling=won(DOBAE_V3_2026_11.md_ceiling * _WAGE_REMODEL),
    labor_ratio=Decimal(1),
    paper_ratio=Decimal("1.58"),
    sources={
        **DOBAE_V3_2026_11.sources,
        "wall": f"{_SEOUL} · 표준품셈 벽 0.024인/㎡ × 일당 30만 원",
        "ceiling": f"{_SEOUL} · 표준품셈 천장 0.0351인/㎡ × 일당 30만 원",
    },
    profile=ProfilePrices(
        key="remodel",
        name="리모델링 기준",
        source=_SEOUL,
        labor_basis="market",
        labor_mult={"basic": Decimal(1), "economy": Decimal("0.55")},
        paper_ratio={"basic": Decimal("1.58"), "economy": Decimal("1.58")},
        material_py={"basic": 16_000, "economy": 16_000},
        putty_py=20_000,
        putty_state="included",
        meal_md=15_000,
        truck=30_000,
        truck_state="included",
        sources={
            "material": f"{_SEOUL} · 부자재 공급 평당 16,000원",
            "putty": f"{_SEOUL} · 퍼티 공급 평당 20,000원",
            "meal": f"{_SEOUL} · 식대 품당 15,000원",
            "truck": f"{_SEOUL} · 운송비 1대",
            "labor_mult": _HAPJI_MULT,
        },
    ),
)

# ---- 가견적과 표준견적서가 같은 수량 · 같은 줄 규칙 (2026-11-21, ADR docs/v4/adr/0006-가견적-표준-같은-규칙.md) ----
# 금액 줄 값은 앞 판(2026.11-*)과 같고 두 규칙만 더한 판이에요. 이미 만든 견적은 앞 판 그대로 둬요.
# - 품 = 0.5 올림(표준품셈 품 × 품 배수): 실크 0.91 · 합지 0.91 × 0.55. 두 기준이 같은 값(공정표와 맞춤)
# - 가견적도 표준견적서 '선택' 줄(퍼티 · 운송 · 경비)을 합계 밖에 둬요(same_rules)
# 근거: d10-/data/price-sources/cases.csv 본표 실크 315건 시장 품 ÷ 표준품셈 품 가운데 0.914(dev · held-out 같음),
# 합지 88건 0.492(실크의 0.54배). 서울12호 235건은 1.0이지만 두 기준 품이 같아야 해서 같이 써요
_MD_MULT = {"basic": Decimal("0.91"), "economy": Decimal("0.91") * Decimal("0.55")}
_MD_SRC = "시장 실견적 품 ÷ 표준품셈 품 가운데(실크 315건 0.91, 2026-11) · 합지는 × 0.55"


def _same_rules(p: DobaePrices, version: str) -> DobaePrices:
    return replace(
        p,
        version=version,
        sources={**p.sources, "md_mult": _MD_SRC},
        md_mult=_MD_MULT,
        same_rules=True,
    )


DOBAE_MARKET_2026_11B = _same_rules(DOBAE_MARKET_2026_11, "2026.11b-market")
DOBAE_REMODEL_2026_11B = _same_rules(DOBAE_REMODEL_2026_11, "2026.11b-remodel")

# 기준마다 지금 쓰는 판
DOBAE_PROFILES: dict[str, DobaePrices] = {
    "paper_only": DOBAE_MARKET_2026_11B,
    "remodel": DOBAE_REMODEL_2026_11B,
}
# 공사 조건이 없는 계산(손님 · 평수만 물은 질문 · 업체 단가표 예시)의 판: 조건 없이 계산 엔진이 고른 기준
DOBAE_DEFAULT = DOBAE_PROFILES[pick_profile(WorkFacts()).profile]
# 저장한 표준견적서의 판(price_ver) → 그 판. 가견적 비교를 저장본과 같은 판으로 셀 때 쓴다
DOBAE_BY_VER: dict[str, DobaePrices] = {
    p.version: p
    for p in (
        DOBAE_2026H2,
        DOBAE_V3_2026_11,
        DOBAE_MARKET_2026_11,
        DOBAE_REMODEL_2026_11,
        DOBAE_MARKET_2026_11B,
        DOBAE_REMODEL_2026_11B,
    )
}


def dobae_prices_of(price_ver: str | None) -> DobaePrices:
    """저장한 표준견적서 판 → 도배 단가 판. 모르는 판이면 지금 기본 판(도배만 하는 공사 기준)."""
    return DOBAE_BY_VER.get(price_ver or "", DOBAE_DEFAULT)


# 실크벽지 두 종류 평당 자재값. 지금은 업체 도배 견적서 1건(2026-11, 사용자 제공 이미지) 값이고,
# 실견적 자료가 더 모이면 바꾼다. 화면 자재 id(wall-silk-*)로 고른다 (frontend/public/v2/data.json · v2_materials.json)
_SILK_SRC = "업체 도배 견적서 1건 (2026-11) · 실크벽지 평당 자재값"
SILK_2026 = {
    "wall-silk-best": SilkPaper(
        "best", "실크벽지 (LX 실크벽지 베스트 or 개나리 로하스)", 9_500, _SILK_SRC
    ),
    "wall-silk-diamant": SilkPaper(
        "diamant", "실크벽지 (LX 디아망 or 개나리 프리모)", 15_000, _SILK_SRC
    ),
}
SILK_DEFAULT = "wall-silk-best"

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
