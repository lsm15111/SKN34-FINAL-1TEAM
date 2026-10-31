"""상담 흐름: 같이 쓰는 칸은 한 번만 묻고, 겹치는 공정은 알린다. DB · HTTP · LLM 없이 서비스 함수만 본다."""

from decimal import Decimal

import pytest

from app.consult import service
from app.consult.schemas import Answer, ConsultCard
from app.consult.trades import REGISTRY, catalog
from app.consult.trades import overlaps as ov
from app.consult.trades.base import FieldSpec, TradeSpec

MOKGONG = REGISTRY["mokgong"]
# 방문 개수를 목공과 같이 쓰는 가짜 공정 (도장 · 필름 자리)
PAINT = TradeSpec(
    key="fakepaint",
    label="가짜 도장",
    order=99,
    fields=(
        FieldSpec(
            key="doors",
            label="칠할 방문 개수",
            question="칠할 방문은 몇 개예요?",
            kind="count",
            unknown=3,
            share="doors",
        ),
    ),
    agent=MOKGONG.agent,
    build=MOKGONG.build,
    card_lines=MOKGONG.card_lines,
)


@pytest.fixture
def paint(monkeypatch):
    monkeypatch.setitem(REGISTRY, PAINT.key, PAINT)


def card(**values) -> ConsultCard:
    return ConsultCard(
        trades=["mokgong", "fakepaint"],
        area_m2=Decimal("112.4"),
        area_basis="supply",
        occupied=False,
        values={"mokgong": {"items": ["door"]}, **values},
    )


def door_questions(c: ConsultCard) -> list:
    return [q for q in service.questions(c) if q.field.endswith(".doors")]


def test_shared_field_is_asked_once(paint):
    qs = door_questions(card())
    assert [q.field for q in qs] == ["mokgong.doors"]
    assert "목공 · 가짜 도장에 같이 넣고" in qs[0].text
    # 공정마다 다른 칸(문틀 교체)은 그대로 묻는다
    assert "mokgong.door_frame" in [q.field for q in service.questions(card())]


def test_shared_answer_fills_every_trade(paint):
    c = service.normalize(service.apply_answer(card(), Answer(field="mokgong.doors", value="4")))
    assert c.values["fakepaint"]["doors"] == 4 and not door_questions(c)
    # '모르겠어요'면 기본값과 실측 확인 표시를 같이 옮긴다
    c = service.apply_answer(card(), Answer(field="mokgong.doors", value="unknown"))
    c = service.normalize(c)
    assert c.values["fakepaint"]["doors"] == 3
    assert {"mokgong.doors", "fakepaint.doors"} <= set(c.to_check)


def test_values_set_per_trade_are_kept(paint):
    # 다른 공정에 값이 있으면 묻지 않고 그 값을 쓴다
    c = service.normalize(card(fakepaint={"doors": 2}))
    assert c.values["mokgong"]["doors"] == 2 and not door_questions(c)
    # 공정마다 따로 정한 값은 덮어쓰지 않는다
    c = card(fakepaint={"doors": 2})
    c = service.normalize(service.apply_answer(c, Answer(field="mokgong.doors", value="4")))
    assert (c.values["mokgong"]["doors"], c.values["fakepaint"]["doors"]) == (4, 2)


def test_router_catalog_lists_shared_fields(paint):
    text = catalog()
    # 방문 개수는 도장 · 필름도 같이 쓴다 (공정이 늘어도 맞게 줄 안의 칸만 본다)
    row = next(ln for ln in text.splitlines() if ln.startswith("- share=doors: "))
    assert {"mokgong.doors", "fakepaint.doors"} <= set(row.split(": ", 1)[1].split(", "))
    assert "mokgong.doors | 방문 개수 | count" in text


def test_overlap_rules_need_both_trades_and_values(monkeypatch):
    rule = ov.Overlap("dobae", "mokgong", ov.both(ov.always, ov.has("items", "door")), "겹쳐요")
    monkeypatch.setattr(ov, "RULES", (rule, rule))
    door = {"mokgong": {"items": ["base", "door"]}}
    assert ov.overlaps(["dobae", "mokgong"], door) == ["겹쳐요"]  # 같은 말은 한 번
    assert ov.overlaps(["mokgong"], door) == []
    assert ov.overlaps(["dobae", "mokgong"], {"mokgong": {"items": ["base"]}}) == []
    assert ov.overlaps(["dobae", "mokgong"], {}) == []
