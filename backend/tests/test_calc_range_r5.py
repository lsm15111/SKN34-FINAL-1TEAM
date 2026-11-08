"""예상 범위 가정값 r5: 방 여러 칸 도배는 업체처럼 벽지 롤을 방마다 따로 세어 올린다(docs/research/T10 8절).
방 1칸 · 집 전체 · 목공은 r4와 같다. 기대값은 손으로 계산했다."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.calc import dobae, spaces
from app.calc.price_range import JobQty, RangeInput, price_range
from app.quote import ranges
from app.refprice.book import DOBAE
from app.refprice.market import RANGE
from app.refprice.market import RANGE_2026H2_R4 as R4
from app.refprice.market import RANGE_2026H2_R5 as R5
from app.refprice.spaces import SPACES

# 작은방 3칸쯤: 방마다 벽 16㎡ · 천장 7㎡, 표준견적서 공급가 80.8만 원
AMOUNTS = {"wall": 288_000, "ceiling": 180_000, "paper": 300_000, "primer": 40_000}
THREE = RangeInput(
    "dobae",
    AMOUNTS,
    {"area": "area"},
    grade="basic",
    conds={"removal": "open", "waste": "open"},
    cond_qty={"removal": Decimal(69)},
    job_share=Decimal("0.3"),
    fixed_key="dobae.basic",
    job_qty=JobQty(
        Decimal(48),
        Decimal(21),
        base_supply=sum(AMOUNTS.values()),
        rooms=((Decimal(16), Decimal(7)),) * 3,
    ),
)


def qty(**over) -> RangeInput:
    assert THREE.job_qty is not None
    return replace(THREE, job_qty=replace(THREE.job_qty, **over))


def same_as_r4(inp: RangeInput) -> bool:
    return price_range(inp, R5) == replace(price_range(inp, R4), version=R5.version)


def test_r5_is_the_default_and_only_counts_rolls_per_room():
    assert RANGE is R5 and R5.version == "2026H2-r5"
    assert R5.job_rule["dobae"] == replace(R4.job_rule["dobae"], per_room=True)
    assert replace(R5, version=R4.version, job_rule=R4.job_rule, sources=R4.sources) == R4


def test_three_rooms_round_rolls_room_by_room():
    # 방마다 벽 2롤 + 천장 1롤 = 9롤. 9 ÷ 3.3 = 2.7 → 3품. 9 × 4.5만 + 75만 + 부자재 9만 = 124.5만 → 136.95만
    r = price_range(THREE, R5)
    assert r.mid == 1_370_000
    # 면적 비례 시장 금액(80.8만 × 0.85 = 68.68만)보다 더 드는 55.82만 × 부가세
    assert r.fixed_add == 610_000
    assert any("방마다" in n for n in r.notes)
    # r4: 합쳐서 벽 48㎡ → 4롤, 천장 21㎡ → 2롤 = 6롤 → 2품. 27만 + 50만 + 6만 = 83만 → 91.3만
    old = price_range(THREE, R4)
    assert old.mid == 910_000 and old.fixed_add == 160_000
    assert not any("방마다" in n for n in old.notes)


def test_one_room_whole_house_and_carpentry_stay_r4():
    one = qty(wall_m2=Decimal(16), ceiling_m2=Decimal(7), rooms=((Decimal(16), Decimal(7)),))
    assert same_as_r4(one)
    assert same_as_r4(qty(rooms=()))  # 방마다 면적이 없으면 합친 면적으로 센다
    assert same_as_r4(replace(THREE, job_share=Decimal(1)))
    mok = RangeInput(
        "mokgong",
        {"molding": 300_000, "base": 120_000},
        {"edge": "area", "flat": "guess", "door": "guess"},
        job_share=Decimal("0.2"),
        fixed_key="mokgong",
    )
    assert same_as_r4(mok)


def _job_qty(names: list[str]) -> JobQty:
    pk = spaces.pick(names, "30", SPACES)
    q = dobae.quote(
        dobae.DobaeInput(Decimal("112.4"), "supply", "basic", True, False, False, share=pk.paper),
        DOBAE,
    )
    inp = ranges.range_input("dobae", "basic", q.lines, ranges.Known("area", pk))
    assert inp.job_qty is not None
    return inp.job_qty


def test_rooms_split_the_area_by_each_space_share():
    # 거실 0.18 · 작은방 0.145: 벽 · 천장 면적을 이 비율로 나눈다. 욕실은 보통 도배하지 않아 빠진다
    q = _job_qty(["거실", "작은방 1", "욕실"])
    assert len(q.rooms) == 2
    (w1, c1), (w2, c2) = q.rooms
    assert abs(w1 + w2 - q.wall_m2) < Decimal("0.001")
    assert abs(c1 + c2 - q.ceiling_m2) < Decimal("0.001")
    assert abs(w1 / w2 - Decimal("0.18") / Decimal("0.145")) < Decimal("0.001")
    # 욕실만 골라도 작은방 하나로 본다(spaces.pick)
    assert len(_job_qty(["욕실"]).rooms) == 1


def test_negative_room_area_is_rejected():
    with pytest.raises(ValueError):
        price_range(qty(rooms=((Decimal(16), Decimal(-1)),)), R5)
