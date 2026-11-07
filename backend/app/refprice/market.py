"""예상 범위 가정값 한 벌 (2026 하반기). 시장 관측 · 공공 기준으로 잡고, 실측 견적이 쌓이면 고친다.

값마다 근거를 sources에 적는다. 범위에는 version을 고정해 나중에 값이 바뀌어도 만든 때의 기준을 알 수 있게 한다.
"""

from decimal import Decimal

from app.calc.price_range import CondRule, RangeRules

_D = Decimal

RANGE_2026H2 = RangeRules(
    version="2026H2-r1",
    z=_D("1.2816"),
    qty_sigma={
        "dobae": {
            "area": {"band": _D("0.14"), "area": _D("0.08"), "self": _D("0.04"), "visit": _D(0)}
        },
        "mokgong": {
            "edge": {"band": _D("0.18"), "area": _D("0.12"), "self": _D("0.05"), "visit": _D(0)},
            "flat": {"guess": _D("0.35"), "self": _D("0.08"), "visit": _D(0)},
            "door": {"guess": _D("0.20"), "self": _D(0), "visit": _D(0)},
        },
    },
    price_sigma={"dobae": _D("0.20"), "mokgong": _D("0.25")},
    price_center={"dobae": _D(1), "mokgong": _D(1)},
    visit_sigma={"dobae": _D("0.08"), "mokgong": _D("0.12")},
    min_job={"dobae": 500_000, "mokgong": 600_000},
    conds={
        "dobae": {
            "removal": CondRule("qty", 500, 2_000, "팀 가정값"),
            "waste": CondRule("lump", 50_000, 200_000, "팀 가정값"),
            "moving": CondRule("lump", 100_000, 400_000, "팀 가정값"),
        },
        "mokgong": {
            "remove_ceiling": CondRule("lump", 200_000, 800_000, "팀 가정값"),
            "remove_door": CondRule("qty", 20_000, 60_000, "팀 가정값"),
            "remove_trim": CondRule("lump", 100_000, 300_000, "팀 가정값"),
            "waste": CondRule("lump", 100_000, 300_000, "팀 가정값"),
            "moving": CondRule("lump", 100_000, 300_000, "팀 가정값"),
        },
    },
    vat_rate=_D("0.1"),
    sources={
        "qty_sigma": "팀 가정값",
        "price_sigma": "팀 가정값",
        "price_center": "팀 가정값 (공공 기준 = 시장 중심으로 둠)",
        "visit_sigma": "팀 가정값",
        "min_job": "팀 가정값",
    },
)
