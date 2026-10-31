"""공정 스펙 · 레지스트리. DB · HTTP · LLM 없이 계약만 본다."""

from decimal import Decimal

import pytest

from app.calc import dobae as dobae_calc
from app.calc import mokgong as mokgong_calc
from app.consult.trades import ORDER, REGISTRY, catalog
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec
from app.refprice.book import DOBAE_2026H2, MOKGONG_2026H2

COMMON = Common(area_m2=Decimal("112.4"), area_basis="supply", occupied=False)
DOBAE, MOKGONG = REGISTRY["dobae"], REGISTRY["mokgong"]


def field(**over) -> FieldSpec:
    base = {"key": "kind", "label": "종류", "question": "?", "kind": "choice"}
    return FieldSpec(**({"choices": (Choice("a", "가"),)} | base | over))


def spec(**over) -> TradeSpec:
    base = {
        "key": "sample",
        "label": "예시",
        "order": 5,
        "fields": (field(),),
        "agent": DOBAE.agent,
        "build": DOBAE.build,
        "card_lines": DOBAE.card_lines,
    }
    return TradeSpec(**(base | over))


def test_registry_is_in_work_order_with_short_keys():
    assert list(REGISTRY) == list(ORDER)
    assert ORDER.index("mokgong") < ORDER.index("dobae")  # 목공이 끝난 뒤 도배
    orders = [s.order for s in REGISTRY.values()]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)
    for key, s in REGISTRY.items():
        assert s.key == key and len(key) <= 10 and key.isascii() and key.islower()
        assert s.agent.label == s.label and s.agent.sources


def test_bad_specs_are_rejected_at_import_time():
    with pytest.raises(ValueError):
        spec(key="Dobae")
    with pytest.raises(ValueError):
        spec(key="toolongkey1")
    with pytest.raises(ValueError):
        spec(order=0)
    with pytest.raises(ValueError):
        spec(fields=(field(), field()))
    with pytest.raises(ValueError):  # 모르겠어요 기본값이 선택지 밖
        field(unknown="b")
    with pytest.raises(ValueError):  # unknown은 선택지 값으로 쓸 수 없다
        field(choices=(Choice("unknown", "?"),))
    with pytest.raises(ValueError):
        field(kind="count", choices=(), min=3, max=1)
    with pytest.raises(ValueError):
        field(key="Kind")


def test_field_reads_form_answers():
    grade = DOBAE.field("grade")
    assert grade.read("economy") == ("economy", False)
    assert grade.read("unknown") == ("basic", True)
    with pytest.raises(ValueError):
        grade.read("gold")
    with pytest.raises(ValueError):
        grade.read(["basic"])

    items = MOKGONG.field("items")
    # 선택지 순서로 맞추고 겹친 것은 하나로
    assert items.read(["door", "molding", "door"]) == (["molding", "door"], False)
    assert items.read("base") == (["base"], False)
    for bad in ([], ["sofa"], "unknown"):
        with pytest.raises(ValueError):
            items.read(bad)

    doors = MOKGONG.field("doors")
    assert doors.read("3") == (3, False) and doors.read(" 2개 ") == (2, False)
    assert doors.read("unknown") == (3, True)
    for bad in ("0", "11", "two", "２"):
        with pytest.raises(ValueError):
            doors.read(bad)
    assert doors.text(3) == "3개" and items.text(["molding", "door"]) == "천장 몰딩 · 방문"


def test_door_fields_are_asked_only_with_doors():
    def asked(v):
        return [f.key for f in MOKGONG.missing(v)]

    assert asked({}) == ["items"]
    assert asked({"items": ["molding"]}) == []
    assert asked({"items": ["door"]}) == ["doors", "door_frame"]
    # 방문을 빼면 방문 칸 값은 지운다
    stale = {"items": ["molding"], "doors": 2, "door_frame": "no", "nope": "x"}
    assert MOKGONG.relevant(stale) == {"items": ["molding"]}


def test_build_calls_the_calc_engine_with_the_spec_values():
    q = DOBAE.build(COMMON, {"grade": "basic", "include_ceiling": "no"})
    want = dobae_calc.quote(
        dobae_calc.DobaeInput(Decimal("112.4"), "supply", "basic", False, False), DOBAE_2026H2
    )
    assert q == want
    m = MOKGONG.build(COMMON, {"items": ["door"], "doors": 2, "door_frame": "no"})
    want_m = mokgong_calc.quote(
        mokgong_calc.MokgongInput(Decimal("112.4"), "supply", ("door",), False, 2, False),
        MOKGONG_2026H2,
    )
    assert m == want_m


def test_card_lines_and_router_catalog():
    assert DOBAE.card_lines(COMMON, {"grade": "economy", "include_ceiling": "yes"}) == [
        "도배 등급: 저가형(합지)",
        "천장: 포함",
    ]
    assert MOKGONG.card_lines(COMMON, {"items": ["molding", "door"], "door_frame": "no"}) == [
        "목공 항목: 천장 몰딩, 방문",
        "방문: 문짝만 바꿔요",
    ]
    text = catalog()
    assert "- dobae.grade | 도배 유형 | choice | economy=저가형 · 합지, basic=기본형 · 실크" in text
    assert "- mokgong.doors | 방문 개수 | count | 숫자 1~10, unknown=모르겠어요" in text
    # 목공이 먼저 (작업 순서)
    assert text.index("## mokgong") < text.index("## dobae")
