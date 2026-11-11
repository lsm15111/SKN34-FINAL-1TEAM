"""시장 기준 값 한 벌 (market-2026.11-v5.1). 2025~2026 실견적(3 · 4차 806건)으로 맞춘 값이다.

범위 띠는 '실제 견적 ÷ 시장 기준'의 중간 50% · 80%. 출처마다 같은 무게로 잡았다(한 출처 쏠림 막기).
출처 하나씩 빼고 시험: 중간 50% 띠 안 51%, 80% 띠 안 78%.
PUBLIC_EQ는 시장 계산을 공공 기준과 같은 값으로 맞춘 것으로, 공공 → 시장 차이를 한 단계씩 볼 때 출발점이다.
"""

from dataclasses import replace
from decimal import Decimal

from app.calc.market_band import Band, MarketBook, MarketDobae, MarketExtra, MarketMokgong

D = Decimal

_DOBAE = MarketDobae(
    area_factor={"silk": D("2.24"), "hapji": D("2.16")},  # 실견적 롤 수 관행(롤/평 0.53 · 0.50)
    ceiling_share=D("0.37"),  # 벽 · 천장 롤이 나뉜 견적
    labor_wall=5_993,
    labor_ceiling=8_531,
    labor_mult={"silk": D("0.94"), "hapji": D("0.55")},  # 합지는 실크의 약 절반 품
    paper={"silk": 2_909, "hapji": 1_273},  # 롤 16.5㎡ 기준 자재만
    paper_ratio=D("1.2"),
    sub_per_py={"silk": 6_700, "hapji": 3_000},
    occupied_mult=D("0.02"),
    balcony_factor=D("1.08"),
    min_job=300_000,
    fixed=0,
    band={
        "silk": Band(D("0.89"), D("1.27"), D("0.80"), D("1.53")),
        "hapji": Band(D("0.90"), D("1.19"), D("0.82"), D("1.44")),
    },
    band_plan={
        "silk": Band(D("0.95"), D("1.35"), D("0.83"), D("1.63"), 604),
        "hapji": Band(D("0.85"), D("1.15"), D("0.78"), D("1.32"), 110),
    },
    checked={"silk": 679, "hapji": 127},
)

_MOKGONG = MarketMokgong(
    molding_per_py=D("2.4"),
    base_per_py=D("1.8"),
    molding_m=13_000,
    base_m=5_837,  # 공공 시공 3,757 + 자재 2,080
    base_only_min=400_000,
    door_set=400_000,
    door_leaf=195_000,
    doors_by_py=(28, 38),
    doors_count=(4, 5, 6),  # 방 + 욕실
    flatten_per_m2=31_991,  # 공공과 같음(실견적 2건뿐)
    removal_lump=0,  # 철거 · 폐기물은 견적마다 달라 넣지 않을 때가 더 맞음
    overhead=D(0),
    band=Band(D("0.80"), D("1.25"), D("0.6"), D("1.5")),  # 계산 항목만 있는 목공 견적 36건
    checked=36,
    extras=(
        MarketExtra("jungmun", "현관 중문(3연동)", "식", 900_000, 1_100_000, 4),
        MarketExtra("aircon", "에어컨 단내림", "곳", 400_000, 550_000, 4),
        MarketExtra("wall", "가벽(문 포함)", "곳", 1_300_000, 1_700_000, 2),
        MarketExtra("insul", "단열(방 · 확장부)", "곳", 500_000, 1_500_000, 7),
        MarketExtra("artwall", "아트월 · TV 매립", "식", 550_000, 1_000_000, 4),
        MarketExtra("lightbox", "간접등 박스", "식", 300_000, 800_000, 3),
    ),
    casing9_with_door=(50_000, 150_000),
    casing9_alone=(150_000, 220_000),
)

MARKET_2026_11 = MarketBook(version="market-2026.11-v5.1", dobae=_DOBAE, mokgong=_MOKGONG)

PUBLIC_EQ_DOBAE = replace(
    _DOBAE,
    area_factor={"silk": D("2.5"), "hapji": D("2.5")},
    ceiling_share=D("0.25"),
    labor_mult={"silk": D(1), "hapji": D(1)},
    paper={"silk": 3_325, "hapji": 1_300},
    sub_per_py={"silk": 2_200, "hapji": 2_200},
    occupied_mult=D("0.169"),
    min_job=0,
)
PUBLIC_EQ_MOKGONG = replace(
    _MOKGONG,
    molding_m=11_468,
    base_m=5_837,
    door_set=365_942,
    door_leaf=191_170,
    doors_count=(2, 3, 4),  # 표준견적서는 방 문만 센다
    base_only_min=0,
    removal_lump=0,
    overhead=D(0),
)

GAP_DOBAE = (
    (
        "area_factor",
        "도배 면적",
        "공공은 공급면적 × 2.5로 잡고, 시장은 실제 롤 수 관행(평당 0.5롤 정도)으로 잡아요.",
    ),
    (
        "ceiling_share",
        "천장 비중",
        "벽 · 천장 롤이 나뉜 견적을 보면 천장이 37% 정도예요(공공 25%). 천장은 시공비가 비싸요.",
    ),
    (
        "labor_mult",
        "시공 품",
        "합지는 실크보다 빨리 붙여서 시장 품이 절반 정도예요. 공공 기준은 벽지 종류를 나누지 않아요.",
    ),
    ("paper", "벽지 값", "실크는 시장 도매가가 조달청 가격보다 낮고, 합지는 비슷해요."),
    ("sub_per_py", "초배 · 풀 · 부자재", "시장 견적의 부자재가 공공 초배지 계산보다 많아요."),
    (
        "occupied_mult",
        "짐 있는 집",
        "공공 기준은 노무비를 16.9% 올리지만, 실견적에서는 짐 있다고 크게 더 받지 않았어요.",
    ),
    ("min_job", "최소 금액", "작은 집은 업체마다 최소 금액이 있어요."),
)
GAP_MOKGONG = (
    ("molding_m", "몰딩 m당 값", "시장 평몰딩은 시공 + 자재 m당 1만~1.6만 원이에요."),
    ("door_set", "방문 한 짝 값", "문틀 포함 시장가는 30만~46만 원(가운데 40만 원)이에요."),
    ("door_leaf", "문짝만 값", "문짝만은 17만~25만 원이에요."),
    ("doors_count", "방문 개수", "표준견적서는 방 문만 세고, 시장 견적은 욕실 문까지 세요."),
    (
        "base_only_min",
        "걸레받이만 할 때 최소 금액",
        "걸레받이만 하면 35만~50만 원을 최소로 받아요.",
    ),
)
