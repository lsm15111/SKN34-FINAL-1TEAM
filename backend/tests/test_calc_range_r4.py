"""예상 범위 가정값 r4: 일부 공간 도배는 업체가 받는 방식(벽지 롤 수 × 롤 단가 + 도배사 하루 품 + 부자재)으로
가운데를 잡는다(docs/research/T10). 집 전체 · 목공은 r3와 같다. 기대값은 손으로 계산했다."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.calc.price_range import JobQty, RangeInput, price_cdf, price_range, price_range_total
from app.refprice.market import RANGE
from app.refprice.market import RANGE_2026H2_R3 as R3
from app.refprice.market import RANGE_2026H2_R4 as R4

# 32평 작은방 하나쯤: 벽 24.7㎡ · 천장 10.6㎡, 표준견적서 공급가 39.8만 원
AMOUNTS = {"wall": 148_000, "ceiling": 90_000, "paper": 140_000, "primer": 20_000}
ROOM = RangeInput(
    "dobae",
    AMOUNTS,
    {"area": "area"},
    grade="basic",
    conds={"removal": "open", "waste": "open"},
    cond_qty={"removal": Decimal("35.3")},
    job_share=Decimal("0.145"),
    fixed_key="dobae.basic",
    job_qty=JobQty(Decimal("24.7"), Decimal("10.6"), base_supply=sum(AMOUNTS.values())),
)
MOK = RangeInput(
    "mokgong",
    {"molding": 300_000, "base": 120_000},
    {"edge": "area", "flat": "guess", "door": "guess"},
    job_share=Decimal("0.2"),
    fixed_key="mokgong",
)


def qty(**over) -> RangeInput:
    assert ROOM.job_qty is not None
    return replace(ROOM, job_qty=replace(ROOM.job_qty, **over))


def same_as_r3(inp: RangeInput) -> bool:
    return price_range(inp, R4) == replace(price_range(inp, R3), version=R4.version)


def test_r4_is_the_default_and_adds_only_the_job_rule():
    assert RANGE is R4 and R4.version == "2026H2-r4"
    assert replace(R4, version=R3.version, job_rule=R3.job_rule, sources=R3.sources) == R3
    assert set(R4.job_rule) == {"dobae"} and "job_rule" in R4.sources


def test_one_room_is_rolls_and_a_day_and_materials():
    # 벽 2롤 + 천장 1롤(면마다 올림) × 4.5만 + 1품 25만 + 부자재 3만 = 41.5만 → 부가세 포함 45.65만 → 46만
    r = price_range(ROOM, R4)
    assert r.mid == 460_000
    assert price_range(ROOM, R3).mid == 570_000  # r3: 공공 단가 몫 + 고정비 + 철거 · 폐기물
    # 철거 · 폐기물은 이 금액에 들어 있어 따로 섞지 않는다
    assert r.extra_max == 0 and not any(p.driver.startswith("cond:") for p in r.parts)
    assert any("롤" in n for n in r.notes)
    # 면적 비례 시장 금액(39.8만 × 0.85 = 33.83만)보다 더 드는 7.67만 × 부가세
    assert r.fixed_add == 80_000


def test_living_room_ceiling_takes_two_days():
    assert price_range(qty(living_ceiling=True), R4).mid == 730_000  # 3롤 + 2품 + 3만 = 66.5만
    # 천장을 안 하면 벽 2롤 + 1품 + 3만 = 37만 → 41만
    assert price_range(qty(ceiling_m2=Decimal(0), living_ceiling=True), R4).mid == 410_000


def test_hapji_room_uses_hapji_rolls():
    r = price_range(replace(ROOM, grade="economy", fixed_key="dobae.economy"), R4)
    assert r.mid == 380_000  # 3롤 × 2.1만 + 1품 25만 + 3만 = 34.3만 → 37.73만


def test_more_rolls_round_up_to_whole_days():
    # 벽 60㎡ → 5롤, 천장 25㎡ → 2롤. 7롤 ÷ 3.3 = 2.1 → 3품. 7 × 4.5만 + 75만 + 7만 = 113.5만 → 124.85만
    assert price_range(qty(wall_m2=Decimal(60), ceiling_m2=Decimal(25)), R4).mid == 1_250_000


def test_vendor_estimate_adds_the_small_job_gap():
    vendor = replace(ROOM, amounts={"wall": 150_000, "paper": 100_000}, vendor_priced=True)
    r = price_range(vendor, R4)
    # 업체 가견적 25만 + (41.5만 − 33.83만) = 32.67만 → 35.94만
    assert r.mid == 360_000 and r.fixed_add == 80_000 and r.extra_max == 0


def test_moving_stays_and_cdf_and_total_use_the_same_center():
    moving = price_range(replace(ROOM, conds={**ROOM.conds, "moving": "open"}), R4)
    assert [p.driver for p in moving.parts if p.driver.startswith("cond:")] == ["cond:moving"]
    assert Decimal("0.45") <= price_cdf(ROOM, R4, 460_000) <= Decimal("0.55")
    tot = price_range_total([ROOM, MOK], R4)
    # 도배 7.67만 + 목공 고정비 30만 × 0.8 = 31.67만 → 34.84만
    assert tot.fixed_add == 350_000 and tot.extra_max == 0


def test_whole_house_carpentry_and_unknown_grade_keep_r3():
    assert same_as_r3(replace(ROOM, job_share=Decimal(1)))
    assert same_as_r3(MOK)
    assert same_as_r3(replace(ROOM, grade=None, fixed_key="dobae"))


@pytest.mark.parametrize(
    "bad",
    [
        {"roll_m2": Decimal(0)},
        {"loss": Decimal("0.9")},
        {"day_rate": 0},
        {"living_ceiling_days": 0},
        {"rolls_per_day": {"basic": Decimal(0)}},
        {"sub_min": -1},
    ],
)
def test_job_rule_rejects_bad_values(bad):
    with pytest.raises(ValueError):
        replace(R4.job_rule["dobae"], **bad)


def test_negative_quantity_is_rejected():
    with pytest.raises(ValueError):
        price_range(qty(wall_m2=Decimal(-1)), R4)
