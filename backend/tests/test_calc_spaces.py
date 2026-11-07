"""고른 공간 몫: 이름 → 종류, 평형대, 몫 더하기, 거의 다 고르면 집 전체, 욕실만 · 모르는 이름, 계산 엔진 반영."""

from decimal import Decimal

import pytest

from app.calc import dobae, mokgong
from app.calc.common import pyeong_to_m2
from app.calc.spaces import SpaceShares, band_of, kinds_of, pick
from app.refprice.book import DOBAE, MOKGONG
from app.refprice.spaces import SPACES

_D = Decimal
T = SpaceShares(
    version="t",
    paper={"30": {"living": _D("0.3"), "room": _D("0.2"), "master": _D("0.25"), "hall": _D("0.1")}},
    molding={
        "30": {"living": _D("0.3"), "room": _D("0.2"), "master": _D("0.2"), "hall": _D("0.1")}
    },
    base={"30": {"living": _D("0.2"), "room": _D("0.2"), "master": _D("0.2"), "hall": _D("0.2")}},
    ceiling={"30": {"living": _D("0.25"), "room": _D("0.1"), "master": _D("0.15")}},
    cv={"living": _D("0.1"), "room": _D("0.1"), "master": _D("0.1"), "hall": _D("0.3")},
    cv_guess=_D("0.3"),
    base_ratio=_D(1),
    doors={"master": 1, "room": 1},
    doors_whole={"30": 3},
    whole_at=_D("0.9"),
    fallback="room",
    sources={},
)


@pytest.mark.parametrize(
    ("name", "kinds"),
    [
        ("거실", ("living",)),
        ("주방", ("kitchen",)),  # '방'이 들어 있어도 주방
        ("거실 · 주방", ("living", "kitchen")),
        ("안방", ("master",)),
        ("침실 1", ("master",)),
        ("침실 2", ("room",)),
        ("작은방 1", ("room",)),
        ("방 2", ("room",)),
        ("아이방", ("room",)),
        ("드레스룸", ("dress",)),
        ("옷방", ("dress",)),
        ("안방 화장실", ("bath",)),
        ("공용 욕실", ("bath",)),
        ("다용도실", ("utility",)),
        ("복도", ("hall",)),
        ("현관", ("entry",)),
        ("서재", ("room",)),
        ("알파룸", ("room",)),
        ("우리 집 거기", ("other",)),
    ],
)
def test_kind_from_name(name, kinds):
    assert kinds_of(name) == kinds


def test_band_from_pyeong():
    assert [band_of(_D(x)) for x in ("8", "19.9", "24", "34", "43.5", "61")] == [
        "10",
        "10",
        "20",
        "30",
        "40",
        "50",
    ]
    with pytest.raises(ValueError):
        band_of(_D(0))


def test_shares_add_up_and_doors_follow_rooms():
    got = pick(["거실", "작은방 1"], "30", T)
    assert not got.whole and (got.paper, got.molding, got.base) == (_D("0.5"), _D("0.5"), _D("0.4"))
    assert got.edge == _D("0.450")  # 몰딩 · 걸레받이를 길이 비율(1:1)로 묶은 몫
    assert got.doors == 1 and got.flat_m2_share == _D("0.250")  # 평탄화는 거실 천장
    assert got.door_share == _D("0.333")
    two = pick(["작은방 1", "작은방 2"], "30", T)
    assert two.paper == _D("0.400") and two.doors == 2 and two.door_share == _D("0.667")
    assert two.flat_m2_share == _D("0.200")  # 거실이 없으면 고른 방 천장


def test_almost_everything_is_whole_house():
    got = pick(["거실", "안방", "작은방 1", "작은방 2", "복도"], "30", T)
    assert got.whole and got.paper == got.edge == got.base == 1 and got.paper_sigma == 0


def test_bath_only_and_unknown_names_are_guessed_not_zero():
    bath = pick(["안방 화장실"], "30", T)
    assert bath.zero == ("안방 화장실",) and bath.paper == _D("0.200")  # 작은방 하나로 본다
    mixed = pick(["거실", "공용 욕실"], "30", T)
    assert mixed.paper == _D("0.300") and mixed.zero == ("공용 욕실",)
    odd = pick(["우리 집 거기"], "30", T)
    assert odd.guessed == ("우리 집 거기",) and odd.paper == _D("0.200")
    assert odd.paper_sigma == _D("0.300")  # 어떤 공간인지 모르면 크기 차이를 크게 본다
    with pytest.raises(ValueError):
        pick([], "30", T)
    with pytest.raises(ValueError):
        pick(["거실"], "70", T)


def test_real_table_typical_layout_is_whole_and_one_room_is_small():
    six = ["거실", "주방", "안방", "작은방 1", "작은방 2", "복도"]
    for band in ("10", "20", "30"):
        assert pick(six, band, SPACES).whole
    big = pick(six, "40", SPACES)  # 40평대는 작은방이 셋이라 기본 6곳이면 집 전체가 아니다
    assert not big.whole and _D("0.7") < big.paper < _D("0.85")
    assert pick([*six, "작은방 3", "드레스룸"], "40", SPACES).whole
    for band in ("20", "30", "40"):
        one = pick(["작은방"], band, SPACES)
        assert _D("0.05") < one.paper < _D("0.2") and _D("0.05") < one.edge < _D("0.2")
    for band, table in SPACES.paper.items():
        assert all(0 <= v < 1 for v in table.values()), band


def test_dobae_share_scales_area_and_days():
    area = pyeong_to_m2(_D(32))
    whole = dobae.quote(dobae.DobaeInput(area, "supply", "basic", True, False), DOBAE)
    room = dobae.quote(
        dobae.DobaeInput(area, "supply", "basic", True, False, share=_D("0.12")), DOBAE
    )
    assert room.paper_m2 < whole.paper_m2 * _D("0.13")
    assert room.subtotal < whole.subtotal and room.days < whole.days
    assert any("12%" in a for a in room.assumptions)
    with pytest.raises(ValueError):
        dobae.quote(dobae.DobaeInput(area, "supply", "basic", True, False, share=_D(0)), DOBAE)


def test_mokgong_share_scales_trim_and_flatten_follows_spaces():
    area = pyeong_to_m2(_D(34))
    items = ("molding", "base", "flatten")
    whole = mokgong.quote(mokgong.MokgongInput(area, "supply", items, False), MOKGONG)
    part = mokgong.quote(
        mokgong.MokgongInput(
            area, "supply", items, False, share=_D("0.3"), flat_share=_D("0.1"), flat_living=False
        ),
        MOKGONG,
    )
    assert part.molding_m == (whole.molding_m * _D("0.3")).quantize(_D("0.1"))
    assert part.flatten_m2 < whole.flatten_m2
    assert any("고른 공간 몫 30%" in a for a in part.assumptions)
    assert any("고른 공간 천장" in a for a in part.assumptions)


def test_share_sigma_follows_space_kinds_and_shrinks_with_more_spaces():
    one = pick(["작은방 1"], "30", T)
    assert one.paper_sigma == _D("0.100")
    two = pick(["작은방 1", "작은방 2"], "30", T)
    assert two.paper_sigma < one.paper_sigma  # 방 크기 차이가 서로 상쇄된다(÷√2)
    hall = pick(["복도"], "30", T)
    assert hall.paper_sigma == _D("0.300")  # 복도 · 현관 · 드레스룸은 집마다 크기 차이가 크다


def test_real_table_matches_research_checks():
    six = ["거실", "주방", "안방", "작은방 1", "작은방 2", "복도"]
    full = [*six, "드레스룸", "현관"]
    for band in ("20", "30", "40"):
        rooms = {"20": 2, "30": 2, "40": 3}[band]
        names = [*full, *(f"방 {i}" for i in range(rooms - 2))]
        for name, table in (("paper", SPACES.paper), ("molding", SPACES.molding)):
            got = pick(names, band, SPACES)
            total = sum(table[band][k] for k in got.kinds)
            assert abs(total - 1) <= _D("0.05"), (
                band,
                name,
                total,
            )  # 흔한 평면을 다 고르면 합이 약 1
    entry = pick(["현관"], "30", SPACES)
    assert entry.base == 0 and entry.molding > 0  # 현관은 타일 바닥이라 걸레받이가 없다
    living = pick(["거실"], "30", SPACES)
    assert _D("0.17") <= living.paper <= _D("0.20")  # 거실 단독(확장 후 20~23㎡)
