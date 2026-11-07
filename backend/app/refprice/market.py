"""예상 범위 가정값 한 벌 (2026 하반기 r2). 공공 기준 · 시장 관측으로 잡고, 가견적 · 실측 견적이 쌓이면 고친다.

값마다 근거를 sources에 적는다. 범위에는 version을 고정해 나중에 값이 바뀌어도 만든 때의 기준을 알 수 있게 한다.
근거 문서: docs/agent/06-price-range.md, docs/research/T2 · T3 · T4.
"""

from decimal import Decimal

from app.calc.price_range import CondRule, RangeRules

_D = Decimal

RANGE_2026H2 = RangeRules(
    version="2026H2-r2",
    z=_D("1.2816"),
    qty_sigma={
        "dobae": {
            "area": {"band": _D("0.14"), "area": _D("0.08"), "self": _D("0.04"), "visit": _D(0)}
        },
        "mokgong": {
            "edge": {"band": _D("0.18"), "area": _D("0.12"), "self": _D("0.05"), "visit": _D(0)},
            "flat": {"guess": _D("0.45"), "self": _D("0.10"), "visit": _D(0)},
            "door": {"guess": _D("0.20"), "self": _D(0), "visit": _D(0)},
        },
    },
    price_sigma={
        "dobae.basic": _D("0.17"),
        "dobae.economy": _D("0.25"),
        "dobae": _D("0.20"),
        "mokgong": _D("0.24"),
    },
    price_center={
        "dobae.basic": _D("0.85"),
        "dobae.economy": _D("0.65"),
        "dobae": _D("0.80"),
        "mokgong": _D(1),
    },
    visit_sigma={"dobae": _D("0.08"), "mokgong": _D("0.12")},
    min_job={"dobae": 250_000, "mokgong": 300_000},
    conds={
        "dobae": {
            "removal": CondRule("qty", 500, 2_900, _D("0.5"), "시장 500~1,600원/㎡ · 품셈 해체"),
            "waste": CondRule("lump", 30_000, 200_000, _D("0.7"), "숨고 3만~7만 · 10만~20만원"),
            "moving": CondRule("lump", 50_000, 200_000, _D("0.5"), "숨고 5만~10만 · 10만~20만원"),
        },
        "mokgong": {
            "remove_ceiling": CondRule("lump", 100_000, 500_000, _D("0.6"), "팀 가정값"),
            "remove_door": CondRule("qty", 20_000, 60_000, _D("0.8"), "팀 가정값(폐문 처리)"),
            "remove_trim": CondRule("lump", 100_000, 400_000, _D("0.7"), "팀 가정값"),
            "waste": CondRule("lump", 100_000, 300_000, _D("0.7"), "팀 가정값"),
            "moving": CondRule("lump", 50_000, 200_000, _D("0.5"), "숨고 거주 중 추가 인력"),
        },
    },
    vat_rate=_D("0.1"),
    sources={
        "z": "AACE 56R-08(Rev. 2020-08-07) 80% 구간 = 10~90%",
        "qty_sigma": "도배 면적 계수 상충 약 20% · 확장 ±5% · AR 측정 3~5%(T4 5.3), "
        "천장 평탄화는 유형(등박스 · 우물 메우기 · 거실 전체 · 처짐 보강)에 따라 면적 차이가 큼(T3)",
        "price_sigma": "34평 실크 시장 200만~300만 · 합지 110만~210만원(T2 5.5), "
        "도배 일당 20만~30만원(T4), 34평 목공 시장 320만~590만원(T3)",
        "price_center": "34평 실크 공공 기준 약 300만원(철거 빼고, 부가세 별도) vs 시장 보통 약 250만원(T2 5.6) → "
        "부가세 포함 여부가 불명해 0.85, 합지는 공공 노무에 합지 · 실크 구분이 없어 0.65, "
        "목공은 엔진 약 390만원이 시장 범위 안(T3) → 1. 가견적 10건부터 보정",
        "visit_sigma": "가견적 → 실측 보통 10~20% 조정(T3), AACE Class 2~3",
        "min_job": "도배 방 하나 합지 25만~35만 · 1인 1일 20만~30만원(T2 5.3), "
        "품셈 소규모 공사 반나절 · 하루 올림, 목수 1품 25만~35만원(T3)",
        "conds": "숨고 블로그 값은 AI 생성 표기가 있어 신뢰 낮음 → 가견적 때 업체 응답으로 빠르게 보정",
    },
)
