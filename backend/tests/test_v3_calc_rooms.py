"""v3 집 전체 도배 면적 (whole-house-area.md 방안 4): 공급 × 1.55 + 방 × 20.4㎡, 천장 0.35,
방 개수 기본값(평형), 방 개수별 공간 몫으로 칩 끄기. 기대값은 조사 문서 5장 표와 같다."""

from decimal import Decimal

import pytest

from app.calc import dobae
from app.calc.space_share import (
    OTHER_KINDS,
    SPACE_SHARE_ROOMS_2026_11,
    room_kinds,
    rooms_needed,
)
from app.refprice.book import DOBAE_V3_2026_11 as P
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market

D = Decimal
T = SPACE_SHARE_ROOMS_2026_11


def std(h: dobae.HomeV3) -> dobae.StandardV3:
    return dobae.standard_v3(h, P, paper_market(h.grade), T, HOUSE_2026H2)


def home(m2: str, rooms: int | None = None, basis="supply", **kw) -> dobae.HomeV3:
    return dobae.HomeV3(D(m2), basis, "basic", False, rooms=rooms, **kw)


def paper(v: dobae.StandardV3) -> Decimal:
    return next(ln.qty for ln in v.quote.lines if ln.key == "paper")


def every(rooms: int) -> tuple[str, ...]:
    return ("living", "kitchen", *room_kinds(rooms), "hall", "entry", "dress")


@pytest.mark.parametrize(
    ("m2", "rooms", "area", "wall", "ceiling", "py", "total"),
    [
        ("79.3", 3, "184.1", "119.7", "64.4", "66.8", 2_235_232),  # 24평
        ("112.4", 3, "235.4", "153.0", "82.4", "85.5", 2_859_232),  # 34평
        ("145.5", 4, "307.1", "199.6", "107.5", "111.5", 3_729_628),  # 44평
    ],
)
def test_representative_sizes_with_default_rooms(m2, rooms, area, wall, ceiling, py, total):
    v = std(home(m2))
    q = v.quote
    assert v.rooms == rooms
    assert (q.paper_m2, q.wall_m2, q.ceiling_m2) == (D(area), D(wall), D(ceiling))
    assert paper(v) == D(py) and q.total == total
    assert v.share is None and v.share_ver is None
    assert q.version == "2026H2-rooms"
    assert q.assumptions[0].startswith(f"도배 면적은 공급면적 × 1.55 + 방 {rooms}개 × 20.4㎡")
    assert "천장은 도배 면적의 35%" in q.assumptions[1]


def test_room_count_changes_area_by_20_4_m2():
    """34평: 방 2 → 215.0 · 방 4 → 255.8 (문서 5장 '방 하나 적은 · 많은 집')"""
    two, three, four = (std(home("112.4", n)) for n in (2, 3, 4))
    assert (two.quote.paper_m2, two.quote.total) == (D("215.0"), 2_610_498)
    assert (four.quote.paper_m2, four.quote.total) == (D("255.8"), 3_106_810)
    assert three.quote.paper_m2 - two.quote.paper_m2 == D("20.4")


def test_exclusive_area_converts_to_supply_by_1_315():
    """전용 84㎡ → 공급 110.46㎡ × 1.55 + 3방 × 20.4 = 232.4㎡"""
    v = std(home("84", basis="exclusive"))
    assert (v.rooms, v.quote.paper_m2) == (3, D("232.4"))
    assert "(전용 × 1.315 = 공급 110.5㎡)" in v.quote.assumptions[0]


def test_default_rooms_by_pyeong_and_m2_table_agree():
    assert [dobae.default_rooms(D(m), "supply", P) for m in ("72.7", "72.8", "132.2", "132.3")] == [
        2,
        3,
        3,
        4,
    ]
    assert [dobae.default_rooms(D(m), "exclusive", P) for m in ("55.3", "55.4", "100.6")] == [
        2,
        3,
        4,
    ]
    bands = dobae.room_bands_m2(P)
    assert (("supply", D("72.8"), 3) in bands) and (("exclusive", D("100.6"), 4) in bands)


def test_turning_off_a_chip_subtracts_its_room_count_share():
    """34평 3방에서 작은방 2(0.15)를 끄면 0.85 몫, 2방 집에서 작은방 1(0.22)을 끄면 0.78 몫"""
    full3 = std(home("112.4", 3))
    off = tuple(k for k in every(3) if k != "room2")
    v = std(home("112.4", 3, scope="partial", spaces=off))
    assert (v.share, v.share_ver) == (D("0.85"), "space-rooms-2026.11")
    assert v.quote.wall_m2 == D("130.1")  # 153.0 × 0.85
    assert v.quote.total < full3.quote.total
    off2 = tuple(k for k in every(2) if k != "room1")
    assert std(home("112.4", 2, scope="partial", spaces=off2)).share == D("0.78")


def test_all_chips_on_equals_whole_house():
    for n in range(1, 6):
        v = std(home("112.4", n, scope="partial", spaces=every(n)))
        assert v.share == D(1)
        assert v.quote.total == std(home("112.4", n)).quote.total


def test_room_tables_sum_to_one_and_follow_room_count():
    assert len(T.version) <= 20  # standard_quotes.share_ver varchar(20)
    for n, t in T.tables.items():
        assert sum(t.values()) == D(1), n
        assert set(t) == set(OTHER_KINDS) | set(room_kinds(n))
    assert [T.tables[2][k] for k in ("master", "room1")] == [D("0.25"), D("0.22")]
    assert [T.tables[4][k] for k in room_kinds(4)] == [
        D(x) for x in ("0.17", "0.16", "0.11", "0.05")
    ]


@pytest.mark.parametrize("rooms", [0, 6, -1])
def test_rooms_out_of_range_is_error(rooms):
    with pytest.raises(ValueError):
        std(home("112.4", rooms))


@pytest.mark.parametrize("rooms", [1, 5])
def test_rooms_edges_work(rooms):
    v = std(home("112.4", rooms))
    assert v.rooms == rooms
    assert v.quote.paper_m2 == dobae.m2(D("112.4") * D("1.55") + rooms * D("20.4"))


def test_all_chips_off_is_error_and_extra_room_chip_is_error():
    with pytest.raises(ValueError):
        std(home("112.4", 3, scope="partial", spaces=()))
    with pytest.raises(ValueError, match="방 개수보다"):
        std(home("112.4", 2, scope="partial", spaces=("room2",)))


def test_old_project_without_rooms_uses_default_or_picked_rooms():
    """옛 공사(rooms 없음): 평형 기본값. 고른 방 칩이 더 많으면 그만큼 (24평 2방 표 → room2를 골랐으면 3방)"""
    assert std(home("60")).rooms == 2
    v = std(home("60", scope="partial", spaces=("living", "room2")))
    assert v.rooms == 3 and v.share == D("0.35")  # 3방 표 거실 0.20 + 작은방 2 0.15
    assert rooms_needed(["living", "room4"]) == 5 and rooms_needed(["hall"]) == 0


def test_balcony_flag_adds_nothing_because_regression_is_extended_homes():
    a, b = std(home("112.4", 3)), std(home("112.4", 3, balcony_ext=True))
    assert a.quote.total == b.quote.total
    assert not any("발코니 확장은" in x for x in b.quote.assumptions)
