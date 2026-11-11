"""도면 수량 계산. DB · HTTP 없이 순수 함수만 본다. 기대값은 손으로 검산한 값이다."""

from decimal import Decimal

import pytest

from app.calc.plan_qty import Plan, PlanOptions, PlanSpace, Window, from_plan

D = Decimal

# 안벽 180mm라 치수선에서 0.18m를 빼면 안쪽 길이가 딱 떨어지게 잡았다
ROOM = PlanSpace(
    id="room",
    ko="침실",
    kind="room",
    w_mm=3180,
    d_mm=3180,
    paper="full",
    door_open=1,
    own_door=True,
    windows=(Window(1500, "half"),),
    sure="high",
)
LIVING = PlanSpace(
    id="living",
    ko="거실",
    kind="living",
    w_mm=4180,
    d_mm=5180,
    paper="full",
    ext_mm=1200,
    open_mm=2000,
    door_open=1,
    windows=(Window(2400, "full"),),
)
KITCHEN = PlanSpace(
    id="kitchen", ko="주방", kind="kitchen", w_mm=2180, d_mm=3180, paper="kitchen", open_mm=2000
)
BATH = PlanSpace(
    id="bath",
    ko="욕실",
    kind="bath",
    w_mm=2180,
    d_mm=1880,
    paper="none",
    door_open=1,
    own_door=True,
)
# 전부 확장분인 칸: 확장하지 않으면 없어진다
NOOK = PlanSpace(
    id="nook",
    ko="확장 칸",
    kind="dress",
    w_mm=1680,
    d_mm=1380,
    paper="full",
    ext_mm=1200,
    open_mm=1500,
    sure="low",
)
PLAN = Plan(spaces=(ROOM, LIVING, KITCHEN, BATH, NOOK))


def by_id(r):
    return {s.id: s for s in r.spaces}


def test_spaces_expanded():
    s = by_id(from_plan(PLAN))
    room = s["room"]
    # 둘레 12 × 2.3 − 문 0.9 × 2.1 − 창 1.5 × 1.2 = 23.91
    assert (room.w_m, room.d_m, room.perim_m) == (D("3.0"), D("3.0"), D("12.0"))
    assert (room.wall_m2, room.ceiling_m2, room.molding_m, room.base_m) == (
        D("23.9"),
        D("9.0"),
        D("12.0"),
        D("11.1"),
    )
    living = s["living"]
    # 둘레 18 − 트인 2 = 16, 벽 36.8 − 문 1.89 − 큰 창 2.4 × 2.1 = 29.87, 걸레받이 16 − 0.9 − 2.4
    assert (living.perim_m, living.wall_m2, living.ceiling_m2, living.base_m) == (
        D("16.0"),
        D("29.9"),
        D("20.0"),
        D("12.7"),
    )
    assert living.ext
    # 주방은 벽 · 몰딩 · 걸레받이 절반, 천장은 그대로
    k = s["kitchen"]
    assert (k.wall_m2, k.ceiling_m2, k.molding_m, k.base_m) == (
        D("9.2"),
        D("6.0"),
        D("4.0"),
        D("4.0"),
    )
    assert k.kitchen and k.papered
    assert not s["bath"].papered and s["bath"].wall_m2 == 0


def test_totals_expanded():
    r = from_plan(PLAN)
    # 벽 23.91 + 29.87 + 9.2 + 8.97 = 71.95 → 72.0, 천장 9 + 20 + 6 + 1.8
    assert (r.wall_m2, r.ceiling_m2, r.paper_m2) == (D("72.0"), D("36.8"), D("108.8"))
    assert r.primer_m2 == D("115.8")  # 71.95 × 1.2 + 36.8 × 0.8 = 115.78
    # 몰딩 35.9m × 1.1 ÷ 2.4 = 16.45 → 17개, 걸레받이 31.7m → 14.53 → 15개
    assert (r.molding_m, r.molding_pcs, r.base_m, r.base_pcs) == (D("35.9"), 17, D("31.7"), 15)
    # 방문은 침실 · 욕실 두 곳, 문선 10.2m씩
    assert (r.doors, r.casing_m) == (2, D("20.4"))
    # 창 폭은 벽지 바르는 공간만: 침실 1.5 + 거실 2.4
    assert r.windows_m == D("3.9")
    # 실크: 한 롤 6띠. 벽 띠 31 ÷ 6 + 천장 3/5 + 4/3 + 2/5 + 2/9 = 7.72 × 1.1 → 9롤
    assert (r.rolls["silk"].per_roll, r.rolls["silk"].rolls) == (6, 9)
    # 합지: 한 롤 5띠. 벽 4 + 5 + 1.6 + 1.6, 천장 1.5 + 4 + 1 + 3/7 = 19.13 × 1.1 → 22롤
    assert (r.rolls["hapji"].per_roll, r.rolls["hapji"].rolls) == (5, 22)
    assert r.rolls["silk"].size == "1.06m × 15.6m"
    assert r.low == ["확장 칸"]


def test_not_expanded_cuts_extension_and_drops_gone_space():
    r = from_plan(PLAN, PlanOptions(expanded=False))
    s = by_id(r)
    living = s["living"]
    # 세로 5.0 − 확장 1.2 = 3.8, 벽 13.6 × 2.3 − 1.89 − 5.04 = 24.35 → 24.4 (반올림은 올림)
    assert (living.d_m, living.perim_m, living.wall_m2, living.ceiling_m2) == (
        D("3.8"),
        D("13.6"),
        D("24.4"),
        D("15.2"),
    )
    assert not living.ext
    nook = s["nook"]
    assert (nook.d_m, nook.papered, nook.wall_m2, nook.molding_m) == (D("0.0"), False, 0, 0)
    assert r.doors == 2


def test_ceiling_off():
    r = from_plan(PLAN, PlanOptions(ceiling=False))
    assert r.ceiling_m2 == 0 and r.paper_m2 == r.wall_m2 == D("72.0")
    # 벽 띠만 31 ÷ 6 × 1.1 = 5.68 → 6롤
    assert r.rolls["silk"].rolls == 6


def test_kinds_filter_counts_only_chosen_spaces():
    r = from_plan(PLAN, PlanOptions(kinds=("kitchen",)))
    assert [s.id for s in r.spaces if s.papered] == ["kitchen"]
    assert (r.wall_m2, r.ceiling_m2, r.molding_m) == (D("9.2"), D("6.0"), D("4.0"))
    # 고르지 않은 공간의 방문은 세지 않는다
    assert r.doors == 0


def test_higher_ceiling_adds_wall_only():
    lo, hi = from_plan(PLAN), from_plan(PLAN, PlanOptions(ceiling_h=D("2.4")))
    assert hi.wall_m2 > lo.wall_m2 and hi.ceiling_m2 == lo.ceiling_m2
    assert hi.rolls["silk"].per_roll == 6  # 15.6 ÷ 2.5 = 6.24
    assert "천장 높이 2.4m" in hi.assumptions[0]


def test_wall_thickness_from_plan():
    r = from_plan(Plan(spaces=(ROOM,), wall_int_mm=150, wall_given=True))
    assert by_id(r)["room"].w_m == D("3.0")  # 3.18 − 0.15 = 3.03
    assert "벽 두께 150mm" in r.assumptions[1] and "(도면 표기)" in r.assumptions[1]


def test_empty_plan_is_zero():
    r = from_plan(Plan(spaces=()))
    assert (r.paper_m2, r.molding_pcs, r.doors, r.rolls["silk"].rolls) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("plan", "opts"),
    [
        (PLAN, PlanOptions(ceiling_h=D(0))),
        (
            Plan(spaces=(PlanSpace(id="x", ko="x", kind="room", w_mm=-1, d_mm=10, paper="full"),)),
            None,
        ),
    ],
)
def test_rejects_bad_input(plan, opts):
    with pytest.raises(ValueError):
        from_plan(plan, opts)
