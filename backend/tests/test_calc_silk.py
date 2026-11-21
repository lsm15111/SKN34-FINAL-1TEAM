"""실크벽지 두 종류(베스띠 · 로하스 / 디아망 · 프리모): 벽지 줄을 평당 자재값으로 센다. 기대값은 손으로 검산했다."""

from datetime import date
from decimal import Decimal

from app.calc import market_band, precise_dobae, precise_mokgong
from app.calc.common import pyeong_to_m2
from app.calc.precise_common import silk_qty
from app.calc.quick_budget import QuickIn, quick
from app.calc.v2_quote import V2QuoteInput, build
from app.refprice.book import DOBAE_2026H2, SILK_2026
from app.refprice.market import MARKET_2026_11
from app.v2.service import books
from tests.helpers import signup

D = Decimal
BEST, DIA = SILK_2026["wall-silk-best"], SILK_2026["wall-silk-diamant"]
PY21 = pyeong_to_m2(D(21))  # 69.4㎡


def paper(lines):
    return next(ln for ln in lines if ln.key == "paper")


def test_silk_prices_come_from_the_quote_image():
    assert (BEST.key, BEST.per_py) == ("best", 9_500)
    assert (DIA.key, DIA.per_py) == ("diamant", 15_000)
    assert "견적서" in BEST.source and BEST.source == DIA.source


def test_silk_qty_is_pyeong_of_paper_area():
    assert silk_qty(D("208.2")) == D("63.0")  # 208.2 ÷ 3.3058 = 62.98
    assert silk_qty(D("3.3058")) == D("1.0")


def test_precise_paper_line_uses_chosen_silk():
    base = precise_dobae.V2DobaeInput(area_m2=PY21, grade="basic")
    # 21평: 도배 면적 69.4 × 2.5 = 173.5㎡, 소요량 × 1.2 = 208.2㎡ = 63.0평
    best = precise_dobae.quote(base.__class__(**{**base.__dict__, "silk": BEST}), DOBAE_2026H2)
    dia = precise_dobae.quote(base.__class__(**{**base.__dict__, "silk": DIA}), DOBAE_2026H2)
    pb, pd = paper(best.lines), paper(dia.lines)
    assert (pb.name, pb.qty, pb.unit, pb.unit_price, pb.amount) == (
        "실크벽지 (LX 실크벽지 베스트 or 개나리 로하스)",
        D("63.0"),
        "평",
        9_500,
        598_500,
    )
    assert (pd.qty, pd.unit_price, pd.amount) == (D("63.0"), 15_000, 945_000)
    assert pb.price_basis == "pick" and "÷ 3.3058" in pb.calc
    # 벽지 줄만 다르다
    assert dia.subtotal - best.subtotal == 945_000 - 598_500


def test_economy_grade_ignores_silk():
    inp = precise_dobae.V2DobaeInput(area_m2=PY21, grade="economy", silk=DIA)
    p = paper(precise_dobae.quote(inp, DOBAE_2026H2).lines)
    assert p.unit == "㎡" and "합지" in p.name


def test_market_paper_line_uses_chosen_silk():
    base = market_band.MarketDobaeInput(area_m2=PY21, grade="basic")
    plain = market_band.dobae(base, MARKET_2026_11)
    best = market_band.dobae(base.__class__(**{**base.__dict__, "silk": BEST}), MARKET_2026_11)
    dia = market_band.dobae(base.__class__(**{**base.__dict__, "silk": DIA}), MARKET_2026_11)
    pb = next(ln for ln in best.lines if ln.key == "paper")
    assert (pb.unit, pb.unit_price) == ("평", 9_500)
    assert best.supply < dia.supply and dia.lo > best.lo
    # 시장 실크 평균(2,909원/㎡ ≈ 9,617원/평)과 베스띠 값이 가까워 범위가 거의 같다
    assert abs(best.supply - plain.supply) < plain.supply * D("0.02")


def test_quick_budget_asks_silk_instead_of_grade():
    papers = (BEST, DIA)
    r = quick(QuickIn(area_m2=pyeong_to_m2(D(32)), papers=papers), MARKET_2026_11)
    assert "벽지는 실크벽지 (LX 실크벽지 베스트 or 개나리 로하스)로 계산" in r.assumed
    assert r.alt is not None and r.alt.value == "diamant" and r.alt.lo > r.lo
    keys = [a.key for a in r.asks]
    assert "paper" in keys and "grade" not in keys
    ask = next(a for a in r.asks if a.key == "paper")
    assert [c.value for c in ask.choices] == ["best", "diamant"]
    picked = quick(QuickIn(area_m2=pyeong_to_m2(D(32)), papers=papers, paper=DIA), MARKET_2026_11)
    assert (picked.lo, picked.hi) == (r.alt.lo, r.alt.hi) and picked.alt is None
    assert "paper" not in [a.key for a in picked.asks]


def test_quote_reads_silk_from_wallpaper_pick():
    def total(picks):
        q = V2QuoteInput(
            pyeong=D(32), occupied=False, cats=("wallpaper",), picks=picks, plan=None,
            balcony=False, mok=precise_mokgong.MokSel(), door_count_set=False,
        )  # fmt: skip
        (t,) = build(q, books(), date(2026, 11, 16))["precise"]
        return t["total"], next(ln for ln in t["lines"] if ln["key"] == "paper")

    best, pb = total({"wallpaper": "wall-silk-best"})
    dia, pd = total({"wallpaper": "wall-silk-diamant"})
    assert pb["name"] == BEST.name and pd["name"] == DIA.name and dia > best
    assert total({})[0] == best  # 안 고르면 베스띠 · 로하스


def test_quick_budget_api_paper(api):
    signup(api)
    r = api.post("/v2/quick-budget", json={"pyeong": 32}).json()
    assert r["alt"]["value"] == "diamant" and "paper" in [a["key"] for a in r["asks"]]
    dia = api.post("/v2/quick-budget", json={"pyeong": 32, "paper": "diamant"}).json()
    assert (dia["lo"], dia["hi"]) == (r["alt"]["lo"], r["alt"]["hi"])
    assert api.post("/v2/quick-budget", json={"pyeong": 32, "paper": "gold"}).status_code == 422
    q = {"pyeong": 32, "cats": ["wallpaper"], "tier": "basic"}
    one = api.post("/v2/quote", json=q | {"picks": {"wallpaper": "wall-silk-diamant"}}).json()
    line = next(ln for ln in one["precise"][0]["lines"] if ln["key"] == "paper")
    assert (line["unit"], line["unit_price"]) == ("평", 15_000)
