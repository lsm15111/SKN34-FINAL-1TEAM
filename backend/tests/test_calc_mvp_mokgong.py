"""MVP 목공 계산. DB · HTTP 없이 순수 함수만 본다. 기대값은 손으로 검산한 값이다."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.calc.mvp_mokgong import (
    CountSel,
    DoorSel,
    MokSel,
    MvpMokgongInput,
    default_door_pick,
    default_sel,
    quote,
)
from app.calc.plan_qty import Plan, from_plan
from app.refprice.book import MOKGONG_2026H2 as MG
from app.refprice.mvp_materials import MOK_2026_11 as BOOK

D = Decimal
AREA = D("109.1")  # 공급 33평
PLAN = replace(
    from_plan(Plan(spaces=())),
    molding_m=D("40.0"),
    base_m=D("30.0"),
    ceiling_m2=D("30.0"),
    windows_m=D("3.9"),
    doors=2,
)


def run(sel, **kw):
    return quote(MvpMokgongInput(area_m2=AREA, sel=sel, doors=4, **kw), BOOK, MG)


def amounts(r):
    return {ln.key: ln.amount for ln in r.lines}


def test_standard_grade_without_plan():
    r = run(default_sel(BOOK, "basic"))
    a = amounts(r)
    # 33평 × 2.4 = 79.2m × 8,168 = 646,905.6, 자재 79.2 × 1.1 ÷ 2.4 = 36.3 → 37개 × 5,400
    assert (r.molding_m, a["molding"], a["molding_mat"]) == (D("79.2"), 646_906, 199_800)
    # 33평 × 1.8 = 59.4m × 3,757 = 223,165.8, 자재 59.4 × 1.04 ÷ 2.4 = 25.74 → 26개 × 4,500
    assert (r.base_m, a["base"], a["base_mat"]) == (D("59.4"), 223_166, 117_000)
    assert (r.subtotal, r.vat, r.total) == (1_186_872, 118_687, 1_305_559)
    assert [ln.key for ln in r.lines if ln.state == "after_visit"] == ["remove_trim", "waste"]
    # 품 79.2 × 0.035 + 59.4 × 2/165 = 3.492 → 3.5, 목수 2명이면 반나절 4번
    assert r.man_days == D("3.5")
    assert [(s.key, s.half_days) for s in r.steps] == [("remove", 1), ("trim", 4), ("finish", 1)]
    assert r.days == D("3.0")


def test_door_replace_adds_handle_and_casing():
    sel = MokSel(door=DoorSel("replace", "door-yerim-abs-foam-set", 3))
    r = run(sel)
    a = amounts(r)
    assert (a["door"], a["door_mat"], a["handle"]) == (247_017, 549_000, 48_000)
    # 문선 10.2 × 3 = 30.6m × 2,314 = 70,808.4, 문선 자재 3 × 23,000
    assert (a["casing"], a["casing_mat"]) == (70_808, 69_000)
    assert r.subtotal == 983_825
    assert [ln.key for ln in r.lines if ln.state == "after_visit"] == ["remove_door", "waste"]
    # 품 3 × 0.313 + 30.6 × 0.010 = 1.245 → 반나절 2번
    assert [(s.key, s.half_days) for s in r.steps] == [("door", 2), ("finish", 1)]
    assert r.lines[1].price_basis == "pick" and r.lines[1].basis == "assumed"


def test_plan_lengths_premium_trim_and_extras():
    sel = MokSel(
        door=DoorSel("leaf", "door-ace-abs-ad001-plain"),  # 개수는 도면에서 센 2개
        molding_type="minus",
        molding="molding-youngrim-minus",
        base="molding-dc-hidden-baseboard",
        extras={"flatten_overlay": True, "curtain_box": True, "coffer": D(1)},
    )
    r = run(sel, plan=PLAN, plan_name="시험")
    a = amounts(r)
    assert (r.doors, a["door"], a["door_mat"], "casing" not in a) == (2, 110_000, 180_000, True)
    # 무몰딩: 시공 8,168 × 2 = 16,336원/m × 도면 40m, 자재 40 × 1.1 ÷ 2.4 = 18.3 → 19개
    assert (a["molding"], a["molding_mat"]) == (653_440, 64_600)
    # 히든 걸레받이: 3,757 × 2 = 7,514원/m × 30m, 자재 30 × 1.04 ÷ 3 = 10.4 → 11개
    assert (a["base"], a["base_mat"]) == (225_420, 139_150)
    # 덧방은 도면 천장 30㎡, 커튼박스는 도면 창 폭 3.9m
    assert (a["flatten_overlay"], a["curtain_box"], a["coffer"]) == (484_200, 117_000, 700_000)
    assert r.extra_amount == 1_301_200
    lines = {ln.key: ln for ln in r.lines}
    assert lines["molding"].calc == "도면 시험에서 잰 천장 둘레"
    assert lines["molding"].price_basis == "assumed"
    # 천장 30 × 2/45 = 1.33 → 2, 문 2 × 0.313 ÷ 2 → 1, 몰딩 40 × 0.035 × 2 + 30 × 2/165 × 2 = 3.53 → 4
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("remove", 1),
        ("ceiling", 2),
        ("door", 1),
        ("trim", 4),
        ("finish", 1),
    ]
    assert any("기간 계산에 넣지 않았어요" in n for n in r.assumptions)


def test_nothing_chosen_is_none():
    assert run(MokSel()) is None
    # 방문 작업을 골라도 개수가 0이면 줄이 없다
    assert run(MokSel(door=DoorSel("replace", "door-yerim-abs-foam-set", 0))) is None


def test_grade_defaults():
    assert default_sel(BOOK, "economy").molding == "molding-youngrim-flat"
    assert default_sel(BOOK, "premium").molding_type == "minus"
    assert default_door_pick(BOOK, "basic", "replace") == "door-yerim-abs-foam-set"
    assert default_door_pick(BOOK, "premium", "leaf") == "door-woodin-membrane-brick"
    assert default_door_pick(BOOK, "basic", "none") is None


@pytest.mark.parametrize(
    "sel",
    [
        MokSel(door=DoorSel("replace", "door-ace-abs-ad001-plain", 1)),  # 문틀 교체에 문짝 자재
        MokSel(molding_type="flat", molding="molding-youngrim-minus"),  # 종류와 자재가 다름
        MokSel(slide=CountSel(1, "door-yerim-hidden-set")),
        MokSel(extras={"nope": True}),
        MokSel(extras={"coffer": True}),  # 자동 수량이 없는 항목
    ],
)
def test_rejects_bad_selection(sel):
    with pytest.raises(ValueError):
        run(sel)


def test_rejects_zero_area():
    with pytest.raises(ValueError):
        quote(MvpMokgongInput(area_m2=D(0), sel=default_sel(BOOK, "basic")), BOOK, MG)


def test_doors_by_pyeong_and_exclusive_area():
    from app.calc.mvp_mokgong import doors_by_pyeong

    # 방 + 욕실: 28평 아래 3, 38평 아래 5, 그 위 6
    assert [doors_by_pyeong(BOOK, D(p)) for p in (24, 28, 37, 38)] == [3, 5, 5, 6]
    sel = MokSel(door=DoorSel("leaf", "door-ace-abs-ad001-plain"))
    # 입력 doors가 0이면 평형으로 어림: 전용 84.9 × 1.2 = 101.9㎡ = 30.8평 → 5개
    r = quote(MvpMokgongInput(area_m2=D("84.9"), area_basis="exclusive", sel=sel), BOOK, MG)
    assert r.doors == 5
