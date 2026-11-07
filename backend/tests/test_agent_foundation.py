"""에이전트 바탕(LLM · DB 없이): 출력 검사기 · 출력 모양 · 공정 슬롯 · 다음 질문 · 선제 안내 트리거."""

from datetime import date
from decimal import Decimal

import pytest

from app.agent import guards
from app.agent.schemas import (
    ROUTES,
    CoachReply,
    GateResult,
    PhotoFindings,
    QuoteExplain,
    ScheduleReply,
    TradeReply,
)
from app.agent.trades import pick_questions
from app.agent.trades.dobae import DOBAE
from app.agent.trades.mokgong import MOKGONG
from app.knowledge import triggers as tg

SLOTS = {"range.low": guards.money(2_640_000), "range.high": guards.money(4_650_000)}


def test_slots_are_rendered_and_checked():
    r = guards.check("예상 범위는 ⟦range.low⟧~⟦range.high⟧예요. 업체마다 단가가 달라서예요.", SLOTS)
    assert r.ok and r.text == "예상 범위는 264만 원~465만 원예요. 업체마다 단가가 달라서예요."


def test_unknown_slot_and_made_up_numbers_are_dropped():
    r = guards.check("합계는 ⟦std.total⟧예요. 보통 300만 원이면 돼요. 업체에 물어보세요.", SLOTS)
    assert r.dropped == ("합계는 ⟦std.total⟧예요.", "보통 300만 원이면 돼요.")
    assert r.unknown_slots == ("std.total",) and r.text == "업체에 물어보세요."
    assert "계산 엔진 · 인용에 없는 숫자" in r.reasons


def test_numbers_in_cited_knowledge_are_allowed():
    cited = ["퍼티를 하면 도배까지 2일을 말려요."]
    ok = guards.check("퍼티를 하면 2일 말려야 해요.", {}, cited)
    bad = guards.check("퍼티를 하면 5일 말려야 해요.", {}, cited)
    assert ok.ok and not bad.ok


def test_hangul_money_counts_and_list_numbers():
    assert not guards.check("삼백만 원 정도예요.", {}).ok
    assert not guards.check("이십평 기준이에요.", {}).ok
    assert guards.check("2가지만 알려 주세요. 3번 확인해요.", {}).ok
    assert guards.check("1. 철거부터 해요.", {}).ok
    assert not guards.check("방문 5개를 바꿔요.", {}).ok  # 개수는 계산 엔진 값만


def test_banned_phrases_and_pii():
    assert not guards.check("그 업체는 사기꾼이에요.", {}).ok
    assert not guards.check("법적으로 문제없어요.", {}).ok
    masked = guards.mask("010-1234-5678로 연락하고 101동 1203호로 오세요")
    assert "1234" not in masked and "1203" not in masked


def test_numbers_and_money_format():
    assert guards.numbers("264만~465만 원, 2,944원/㎡, 30%") == {
        Decimal(2_640_000),
        Decimal(4_650_000),
        Decimal(2_944),
        Decimal(30),
    }
    assert guards.money(3_166_556) == "3,166,556원" and guards.money(50_000) == "5만 원"


@pytest.mark.parametrize(
    "model", [GateResult, CoachReply, TradeReply, QuoteExplain, ScheduleReply, PhotoFindings]
)
def test_output_models_have_json_schema(model):
    schema = model.model_json_schema()
    assert schema["type"] == "object" and schema["properties"]


def test_gate_routes_and_coach_limits():
    assert len(ROUTES) == 12 and "oos_trade" in ROUTES
    with pytest.raises(ValueError):
        CoachReply(lead="x", concepts_introduced=["a", "b", "c", "d"])  # 새 용어 3개까지


def test_trade_slots_are_well_formed():
    for cfg in (DOBAE, MOKGONG):
        keys = [s.key for s in cfg.slots]
        assert len(keys) == len(set(keys)) and keys[0] == "spaces"
        for s in cfg.slots:
            assert s.choices and 1 <= s.effort <= 3 and s.ask and s.why
            assert all(a.split(":")[0] in ("qty", "cond", "scenario") for a in s.affects)


def test_next_question_follows_range_parts_and_effort():
    shares = {"qty:area": 0.4, "price": 0.5, "cond:removal": 0.1}
    first = pick_questions(DOBAE, shares, answered=[])
    assert [s.key for s in first] == ["spaces", "ceiling"]  # 면적 폭 + 먼저 물을 것
    later = pick_questions(DOBAE, shares, answered=["spaces", "ceiling"])
    assert later[0].key == "pattern" or later[0].key == "grade"
    by_removal = pick_questions(DOBAE, {"cond:removal": 0.9}, answered=["spaces", "ceiling"])
    assert by_removal[0].key == "existing"  # 철거 여부가 폭을 가장 많이 만들면 기존 벽지부터
    assert pick_questions(MOKGONG, {"qty:edge": 0.9}, answered=["spaces"])[0].key in (
        "molding_style",
        "molding_len",
    )


def ctx(**over) -> tg.CardContext:
    base = {"today": date(2026, 11, 8), "step": "standard", "trades": frozenset({"dobae"})}
    return tg.CardContext(**(base | over))


def test_triggers_from_project_state():
    on = tg.triggers(ctx(built_year=2005, grade="basic", occupied=True))
    assert {"stage_quote", "stage_consult", "trade_dobae", "old_building", "occupied"} <= on
    assert {"silk_selected", "ceiling_unknown"} <= on and "asbestos_era" not in on
    both = tg.triggers(ctx(trades=frozenset({"dobae", "mokgong"}), built_year=2005, flatten=True))
    assert {"has_both_trades", "asbestos_era"} <= both
    soon = tg.triggers(ctx(step="dates", work_start=date(2026, 12, 2)))
    assert "d_minus_14" not in soon and "winter_work" in soon
    near = tg.triggers(ctx(step="dates", work_start=date(2026, 11, 10)))
    assert {"d_minus_3", "d_minus_7", "d_minus_14"} <= near  # 기간이라 겹친다(D-2)
    assert tg.triggers(ctx(working=True, events=frozenset({"mokgong_done"}))) >= {
        "stage_work",
        "mokgong_done",
    }
    mok = tg.triggers(
        ctx(trades=frozenset({"mokgong"}), flatten=True, door=True, molding_style="none")
    )
    assert {"flatten_selected", "door_selected", "moldless_selected"} <= mok
    assert "door_selected" not in tg.triggers(ctx(door=True))  # 목공을 안 골랐으면 꺼짐
    assert set(tg.triggers(ctx())) <= set(tg.TRIGGERS) and set(mok) <= set(tg.TRIGGERS)


def test_pick_one_unseen_card_by_priority():
    cards = [
        {
            "key": "dobae.a",
            "trade": "dobae",
            "trigger": "silk_selected",
            "priority": 50,
            "level": 2,
        },
        {
            "key": "dobae.b",
            "trade": "dobae",
            "trigger": "silk_selected",
            "priority": 90,
            "level": 1,
        },
        {"key": "dobae.c", "trade": "dobae", "trigger": "on_question", "priority": 99, "level": 1},
        {"key": "mokgong.d", "trade": "mokgong", "trigger": "trade_mokgong", "priority": 95},
    ]
    on = {"silk_selected", "trade_mokgong", "on_question"}
    both = {"dobae", "mokgong"}
    assert [c["key"] for c in tg.pick(cards, on, both)] == ["mokgong.d"]
    assert [c["key"] for c in tg.pick(cards, on, both, muted=["mokgong"])] == ["dobae.b"]
    assert [c["key"] for c in tg.pick(cards, on, {"dobae"})] == ["dobae.b"]  # 고른 공정만
    seen = ["mokgong.d", "dobae.b"]
    assert [c["key"] for c in tg.pick(cards, on, both, seen=seen)] == ["dobae.a"]
