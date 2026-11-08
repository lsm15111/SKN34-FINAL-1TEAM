"""예상 범위 가정값 r3: 실견적 백테스트(docs/research/T10)로 고친 값만 r2와 다르고, 고친 방향대로 범위가 움직이는지 본다.
r2는 버전 기록 · 백테스트 비교용으로 그대로 남는다."""

from decimal import Decimal

from app.calc import dobae, mokgong
from app.calc.common import COUNTED, pyeong_to_m2
from app.calc.price_range import RangeInput, price_range
from app.refprice.book import DOBAE, MOKGONG
from app.refprice.market import RANGE
from app.refprice.market import RANGE_2026H2 as R2
from app.refprice.market import RANGE_2026H2_R3 as R3

AREA = {"area": "area"}
MOK = {"edge": "area", "flat": "guess", "door": "self"}


def dobae_amounts(grade: str) -> dict[str, int]:
    inp = dobae.DobaeInput(pyeong_to_m2(Decimal(32)), "supply", grade, True, False)
    q = dobae.quote(inp, DOBAE)
    return {ln.key: ln.amount for ln in q.lines if ln.state in COUNTED}


def door_amounts(frame: bool = True) -> dict[str, int]:
    inp = mokgong.MokgongInput(
        pyeong_to_m2(Decimal(32)), "supply", ("door",), False, doors=1, door_frame=frame
    )
    q = mokgong.quote(inp, MOKGONG)
    return {ln.key: ln.amount for ln in q.lines if ln.state in COUNTED}


def width(r) -> float:
    return (r.high - r.low) / r.mid


def test_r3_is_the_default_and_r2_is_kept():
    assert RANGE is R3 and R3.version == "2026H2-r3"
    assert R2.version == "2026H2-r2" and R2.price_center["dobae.economy"] == Decimal("0.65")


def test_r3_changes_only_the_backtested_values():
    assert R3.price_center == {**R2.price_center, "dobae.economy": Decimal("0.47")}
    assert R3.price_sigma == {
        **R2.price_sigma,
        "dobae.basic": Decimal("0.21"),
        "dobae.economy": Decimal("0.15"),
        "mokgong": Decimal("0.30"),
    }
    assert R3.min_job == {"dobae": 200_000, "mokgong": 250_000, "mokgong.door": 200_000}
    for name in ("z", "qty_sigma", "visit_sigma", "vat_rate", "trade_corr", "fixed_cost"):
        assert getattr(R3, name) == getattr(R2, name)
    assert R3.small_sigma == R2.small_sigma and R3.conds["dobae"] == R2.conds["dobae"]
    changed = {k for k, v in R3.conds["mokgong"].items() if v != R2.conds["mokgong"][k]}
    assert changed == {"remove_ceiling"}
    assert R3.conds["mokgong"]["remove_ceiling"].min_scale == Decimal("0.2")
    assert set(R3.sources) == set(R2.sources)  # 값마다 근거가 있다


def test_hapji_center_follows_market_and_silk_center_stays():
    # 합지 집 전체 실견적 ÷ 가운데 0.69 → 중심 0.65 → 0.47. 실크는 2026년 실견적과 맞아(1.02) 그대로
    eco = RangeInput("dobae", dobae_amounts("economy"), AREA, grade="economy")
    silk = RangeInput("dobae", dobae_amounts("basic"), AREA, grade="basic")
    e2, e3 = price_range(eco, R2), price_range(eco, R3)
    assert abs(e3.mid / e2.mid - 0.47 / 0.65) < 0.02
    assert price_range(silk, R3).mid == price_range(silk, R2).mid


def test_spread_follows_observed_vendor_spread():
    # 실견적 흩어짐: 실크 0.21~0.22(r2 0.17보다 넓음), 합지 0.14~0.17(r2 0.25보다 좁음)
    eco = RangeInput("dobae", dobae_amounts("economy"), AREA, grade="economy")
    silk = RangeInput("dobae", dobae_amounts("basic"), AREA, grade="basic")
    assert width(price_range(silk, R3)) > width(price_range(silk, R2))
    assert width(price_range(eco, R3)) < width(price_range(eco, R2))


def floor_vat(won: int) -> int:
    return int(won * 1.1)


def test_small_jobs_floor_at_market_low():
    # 문짝 한 짝만: 최소 금액 30만 → 20만(문짝 1짝 시장 17만~23만)
    inp = RangeInput(
        "mokgong",
        door_amounts(frame=False),
        MOK,
        job_share=Decimal("0.2"),
        fixed_key="mokgong.door",
    )
    r2, r3 = price_range(inp, R2), price_range(inp, R3)
    assert abs(r2.low - floor_vat(300_000)) <= 10_000
    assert abs(r3.low - floor_vat(200_000)) <= 10_000
    assert any("최소 금액" in n for n in r3.notes)
    # 벽 한 면 도배: 최소 금액 25만 → 20만
    wall = RangeInput("dobae", {"wall": 50_000}, {"area": "self"}, grade="basic")
    assert abs(price_range(wall, R2).low - floor_vat(250_000)) <= 10_000
    assert abs(price_range(wall, R3).low - floor_vat(200_000)) <= 10_000


def test_small_ceiling_job_scales_ceiling_removal():
    # 현관 우물천장처럼 작은 공사: 천장 철거 최대 50만도 공사 크기만큼(최소 20%) 줄인다
    inp = RangeInput(
        "mokgong",
        door_amounts(),
        MOK,
        conds={"remove_ceiling": "open"},
        job_share=Decimal("0.1"),
        fixed_key="mokgong.door",
    )
    assert price_range(inp, R2).extra_max == 550_000  # 50만 × 부가세
    assert price_range(inp, R3).extra_max == 110_000  # 50만 × 0.2 × 부가세
    whole = RangeInput("mokgong", door_amounts(), MOK, conds={"remove_ceiling": "open"})
    assert price_range(whole, R3).extra_max == 550_000  # 집 전체면 그대로
