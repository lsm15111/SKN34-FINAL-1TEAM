"""v2 표준견적서 (v10 refTrade · v3Inputs · buildQuote). 순수 함수만 본다. 기대값은 손으로 검산한 값이다."""

from datetime import date
from decimal import Decimal

from app.calc import mvp_dobae, mvp_mokgong
from app.calc.v2_quote import V2QuoteInput, build, inputs, quote_code
from app.calc.v2_ref_trade import RefMaterial, qty_by_py, ref_trade, unit_norm
from app.mvp.v2_service import books
from app.refprice.book import DOBAE_2026H2

D = Decimal
TODAY = date(2026, 11, 11)
TRADE = {
    "level": "참고",
    "crew": 2,
    "days_by_py": {"24": 1, "40": 2},
    "items": [
        {
            "key": "a",
            "name": "자재",
            "unit": "㎡",
            "qty": {"by_py": {"24": 10, "40": 20}},
            "mat": "pick",
            "mat_fallback": {"low": 1000, "high": 2000, "source": "시장"},
            "labor": {"low": 500, "high": 700, "source": "표준시장단가 시공"},
            "public": {"unit_price": 900, "source": "공공"},
            "note": "가정",
        },
        {
            "key": "b",
            "name": "철거",
            "unit": "식",
            "state": "after_visit",
            "qty": {"fixed": 1},
            "labor": {"low": 100_000, "high": 200_000, "source": "업체"},
        },
    ],
}


def mat(unit: str) -> RefMaterial:
    return RefMaterial("m1", "floor", "basic", "브랜드", "마루", 3000, 4000, unit)


def test_qty_by_py_and_unit():
    by = {"24": D(20), "32": D(25), "34": D(25), "40": D(30)}
    assert qty_by_py(by, D(28)) == D("22.5")  # 20 + 5 × 4 ÷ 8
    assert qty_by_py(by, D(50)) == D("37.5")  # 30 × 50 ÷ 40
    assert unit_norm("m2 (폭 122cm)") == "㎡" and unit_norm("통(4L)") == "통"


def test_ref_trade_fallback_and_pick():
    r = ref_trade("floor", D(32), None, True, TRADE, {}, "바닥재")
    a, b = r["lines"]
    # 32평: 10 + 10 × 8 ÷ 16 = 15㎡ → 시장 1,000~2,000 + 시공 500~700
    assert (a["qty"], a["lo"], a["hi"], a["basis"]) == (D("15.0"), 22_500, 40_500, "public")
    assert a["pub"] == {"unit_price": 900, "amount": 13_500, "source": "공공"}
    assert (a["calc"], a["source"]) == ("32평 기준", "시장 · 표준시장단가 시공")
    assert (b["qty"], b["calc"], b["state"]) == (1, "1식", "after_visit")
    assert (r["lo"], r["hi"], r["vlo"], r["vhi"]) == (22_500, 40_500, 2_250, 4_050)  # 철거는 빼고
    assert r["days"] == D("1.5") and r["steps"][0]["half_days"] == 3 and r["notes"] == ["가정"]
    p = ref_trade("floor", D(32), mat("㎡"), True, TRADE, {}, "바닥재")["lines"][0]
    assert (p["lo"], p["hi"], p["basis"]) == (52_500, 70_500, "pick")  # 15 × 3,000~4,000 + 시공
    w = ref_trade("floor", D(32), mat("롤"), True, TRADE, {}, "바닥재")["lines"][0]
    assert w["source"].startswith("시장 (고른 자재는 단위가 '롤'라 바로 못 넣었어요)")


def q_input(**over) -> V2QuoteInput:
    base = {
        "pyeong": None,
        "occupied": False,
        "cats": ("wallpaper", "floor", "carpentry"),
        "picks": {},
        "plan": None,
        "balcony": False,
        "mok": mvp_mokgong.MokSel(),
        "door_count_set": False,
    }
    return V2QuoteInput(**(base | over))


def test_inputs_defaults_and_doors():
    i = inputs(q_input(), books())
    assert (i.py, i.area_m2, i.grade) == (D(32), D("105.8"), "basic")  # 32 × 3.3058
    assert i.assumed == ["평형을 몰라서 32평으로 잡았어요"]
    assert i.doors_auto == {"n": 5, "how": "32평 기준 방 3 + 욕실 2"}
    door = mvp_mokgong.MokSel(door=mvp_mokgong.DoorSel("replace", "door-yerim-sound-set"))
    i = inputs(q_input(pyeong=D(24), mok=door), books())
    assert i.doors == 3 and i.assumed == ["방문은 24평 기준 방 2 + 욕실 1 3개로 잡았어요"]


def test_quote_code_like_v10():
    # v10 buildQuote 결과(32평 · 도배 · 바닥재 · 목공 · 고른 자재 없음, 2026-11-11)와 같음
    assert quote_code(D(32), ("wallpaper", "floor", "carpentry"), {}, TODAY) == "MJ-2611-2770"


def test_build_dobae_only():
    q = build(q_input(pyeong=D(32), cats=("wallpaper",)), books(), TODAY)
    d = mvp_dobae.quote(mvp_dobae.MvpDobaeInput(area_m2=D("105.8"), grade="basic"), DOBAE_2026H2)
    (t,) = q["precise"]
    assert (t["trade"], t["total"], q["total"]) == ("dobae", d.total, d.total)
    assert next(ln for ln in t["lines"] if ln["key"] == "removal")["calc"] == (
        "보통인부 노임 172,698원 × 0.01"
    )
    assert q["band"] == {"lo": t["band"]["lo"], "hi": t["band"]["hi"]}
    assert t["gap"]["from"] == t["total"] and t["gap"]["steps"][0]["key"] == "vat"
    assert q["ref"] == [] and q["at"] == "2026-11-11" and q["code"].startswith("MJ-2611-")
