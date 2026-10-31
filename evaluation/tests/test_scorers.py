"""공정 의견 코드 채점: 규칙을 지킨 가짜 응답은 통과하고, 어긴 응답은 그 검사만 실패한다."""

import copy

import pytest

from evaluation.common import trades
from evaluation.run_agent import ideal
from evaluation.scorers import trade_plan as tp
from evaluation.scorers.rules import label_words, line_pattern, plan_sents
from evaluation.scorers.terms import unexplained
from evaluation.tests.conftest import cp_input, make_case, wp_input


def failed(trade: str, plan: dict, case: dict) -> set[str]:
    s = tp.score(trade, plan, case["expect"], set(trades.sources(trade)))
    return {k for k, ok in s["checks"].items() if not ok}


def failed_rules(trade: str, plan: dict, case: dict) -> set[str]:
    s = tp.score(trade, plan, case["expect"], set(trades.sources(trade)))
    return {k for k, ok in s["rules"].items() if not ok}


def terms(plan: dict, trade: str) -> list[str]:
    return unexplained(plan_sents(plan), trade)


GOOD_WP = {
    "summary": "실크(기본형) 벽지로 벽과 천장을 모두 바르는 사는 집 도배예요. "
    "짐을 옮기며 하니 일정을 넉넉히 잡아요.",
    "steps": [
        {"key": "prep", "note": "가구를 한쪽으로 옮기고 바닥과 가구를 비닐로 덮어요."},
        {
            "key": "paper",
            "note": "갈라진 곳을 메워 바탕을 고르고, 밑종이를 먼저 바른 뒤(초배) 새 벽지를 발라요(정배).",
        },
        {"key": "finish", "note": "이음매가 벌어진 곳이 없는지 보고 청소해요."},
    ],
    "visit_checks": [
        "기존 벽지가 몇 겹인지 봐 달라고 해요. 그걸 봐야 철거할지 정해요.",
        "떼어 낸 벽지 같은 폐기물을 누가 치우는지 물어봐요.",
        "짐을 누가 옮기는지 물어봐요.",
    ],
    "cautions": [
        {"text": "철거와 폐기물 처리는 실측 뒤에 따로 붙는 경우가 많아요.", "source": "field"},
        {"text": "견적서는 항목과 포함 범위를 글로 받아 두세요.", "source": "dispute"},
    ],
}


def test_rule_following_plans_pass(wp_case, cp_case):
    assert failed("dobae", GOOD_WP, wp_case) == set()
    for trade, case in (("dobae", wp_case), ("mokgong", cp_case)):
        assert failed(trade, ideal(trade)(case), case) == set()


@pytest.mark.parametrize(
    ("change", "check"),
    [
        (lambda p: p.update(summary=p["summary"] + " 하루 정도 걸려요."), "summary_sent"),
        (lambda p: p["visit_checks"].append("천장 높이가 2.4m인지 재요."), "no_digits"),
        (
            lambda p: p["cautions"].append(
                {"text": "두 명이 하루 정도 걸려요.", "source": "field"}
            ),
            "no_number_words",
        ),
        (lambda p: p["steps"].append({"key": "nope", "note": "없는 단계예요."}), "step_keys"),
        (lambda p: p["steps"].append(dict(p["steps"][0])), "step_keys"),
        (lambda p: p["steps"].pop(0), "step_cover"),
        (lambda p: p.update(summary="도배예요."), "summary_len"),
        (lambda p: p["visit_checks"].append("가" * 130 + "요."), "item_len"),
        (lambda p: p.update(visit_checks=p["visit_checks"][:2]), "visit_count"),
        (lambda p: p.update(cautions=p["cautions"] * 3), "caution_count"),
        (
            lambda p: p["cautions"].append({"text": "블로그에서 봤어요.", "source": "blog"}),
            "caution_source",
        ),
        (lambda p: p["visit_checks"].append("관리사무소에 신고합니다."), "style"),
        (lambda p: p["steps"][1].update(note="기존 벽지를 보고 초배와 정배를 해요."), "terms"),
    ],
)
def test_each_rule_break_fails_only_its_check(wp_case, change, check):
    plan = copy.deepcopy(GOOD_WP)
    change(plan)
    got = failed("dobae", plan, wp_case)
    assert check in got
    assert got <= {check, "no_number_words", "summary_sent", "must"}


def test_terms_need_gloss_in_first_sentence():
    plan = copy.deepcopy(GOOD_WP)
    plan["cautions"][0]["text"] = "합지는 기존 벽지에 덧방하는 경우가 많아요."
    assert terms(plan, "dobae") == ["덧방"]
    plan["cautions"][0]["text"] = "합지는 기존 벽지를 떼지 않고 그 위에 바르는(덧방) 경우가 많아요."
    assert terms(plan, "dobae") == []
    plan["steps"][0]["note"] = "짐 정리 · 보양을 해요."
    assert terms(plan, "dobae") == ["보양"]


def test_term_easy_words_count_as_gloss():
    from evaluation.scorers.terms import TERMS

    assert [k for k, t in TERMS.items() if not t.gloss.search(t.easy)] == []


def test_rules_fit_new_trade_labels(monkeypatch):
    """새 공정 화면 말: 숫자뿐인 선택지 · 한 글자 선택지 · 괄호로 푼 업계 말 · 꼭 언급과 겹치는 낱말"""
    from types import SimpleNamespace as NS

    from app.agent.trade import TradeAgent
    from app.consult.schemas import ConsultCard
    from app.consult.trades import REGISTRY
    from app.consult.trades.base import Choice, FieldSpec, TradeSpec
    from evaluation.plan import config
    from evaluation.scorers import witness
    from evaluation.scorers.expect import expect

    two = (Choice("wall", "벽"), Choice("ceil", "천장"))
    method = (Choice("remove", "다 뜯고 새로"), Choice("over", "덧방 (위에 덧붙이기)"))
    spec = TradeSpec(
        key="probex",
        label="시험",
        order=56,
        fields=(
            FieldSpec(
                "length", "길이", "?", "choice", (Choice("s", "2.4m"), Choice("fit", "보통"))
            ),
            FieldSpec("parts", "칠할 곳", "?", "multi", two, max=2),
            FieldSpec("walls", "칠할 벽 수", "?", "count", min=1, max=9, unknown=2),
            FieldSpec("method", "지금 타일", "?", "choice", method),
        ),
        agent=TradeAgent("probex", "시험", "probex-v1", "시스템", "답", {"field": "현장"}),
        build=lambda c, v: NS(lines=[], steps=[]),
        card_lines=lambda c, v: [],
    )
    monkeypatch.setitem(REGISTRY, "probex", spec)
    monkeypatch.setattr(trades, "ORDER", ("mokgong", "probex", "dobae"))
    monkeypatch.setitem(config.CONFIGS, "probex", config.PlanConfig(scope_exempt=()))
    caches = (tp.rules, tp.auto_exempt, trades.after_lines)
    for c in caches:
        c.cache_clear()
    try:
        rules = tp.rules("probex")
        assert (
            "sum.length.s" not in rules and "sum.length.fit" in rules
        )  # '2.4m'은 숫자 없이 못 쓴다
        wall = rules["not_chosen.parts.wall"].any
        assert wall.search("벽을 칠해요") and wall.search("벽 전체")
        assert not wall.search("벽지를 발라요") and not wall.search("벽면")
        glossed = witness.gloss("덧방으로 해요.", "probex")
        assert glossed == "덧방(기존 것을 떼지 않고 위에 덧붙이기)으로 해요."
        assert witness._pack(["가", "나", "다라", "마"], 3) == ["가 나", "다라", "마"]
        values = {"length": "s", "parts": ["ceil"], "walls": 2, "method": "over"}
        card = ConsultCard(
            trades=["probex"],
            area_m2="84.0",
            area_basis="supply",
            occupied=False,
            values={"probex": values},
            to_check=["probex.walls"],
        )
        e = expect("probex", card, {"step_keys": [], "after_visit": []})
        # '칠할 벽 수'를 실측 때 확인해야 하니 고르지 않은 '벽'을 언급 금지로 두지 않는다
        assert "check.walls" in e["must"] and "not_chosen.parts.wall" not in e["must_not"]
    finally:
        for c in caches:
            c.cache_clear()


def test_everyday_words_are_not_terms():
    plan = copy.deepcopy(GOOD_WP)
    plan["cautions"][0]["text"] = (
        "천장 도배는 벽보다 품이 더 들어요. 그래서 짐 있는 집 할증이 붙어요."
    )
    assert terms(plan, "dobae") == []
    # 목공 지식의 할증은 '버리는 몫'이라 풀어야 한다
    assert terms(plan, "mokgong") == ["할증"]
    plan["cautions"][0]["text"] = "자재에는 버리는 몫(할증)이 이미 들어 있어요."
    assert terms(plan, "mokgong") == []


def test_empty_house_must_not_talk_about_belongings():
    case = make_case("dobae", wp_input(occupied=False))
    plan = ideal("dobae")(case)
    assert failed("dobae", plan, case) == set()
    plan["summary"] += " 빈집이라 짐 정리 없이 바로 시작해요."
    assert "empty.moving" in failed_rules("dobae", plan, case)
    # '벌어짐 · 갈라짐'의 '짐'은 짐 이야기가 아니다
    plan = ideal("dobae")(case)
    plan["steps"][-1]["note"] = "이음매 벌어짐과 벽 갈라짐을 보고 청소해요."
    assert "empty.moving" not in failed_rules("dobae", plan, case)


def test_not_chosen_ceiling_allows_negated_mention():
    case = make_case("dobae", wp_input(include_ceiling="no"))
    plan = ideal("dobae")(case)
    assert "천장은 하지 않는" in plan["summary"]
    assert failed("dobae", plan, case) == set()
    plan["visit_checks"].append("천장도 같이 바르면 깔끔해요.")
    assert "not_chosen.include_ceiling" in failed_rules("dobae", plan, case)
    plan["visit_checks"][-1] = "천장 높이를 재 달라고 해요."  # 벽 높이 이야기라 괜찮다
    assert "not_chosen.include_ceiling" not in failed_rules("dobae", plan, case)


def test_carpentry_unchosen_items_and_trades_not_picked(cp_case):
    plan = ideal("mokgong")(cp_case)
    assert failed("mokgong", plan, cp_case) == set()
    bad = copy.deepcopy(plan)
    bad["visit_checks"].append("문틀이 뒤틀렸는지도 봐 달라고 해요.")
    bad["cautions"][-1] = {"text": "목공이 끝난 뒤 도배를 해요.", "source": "field"}
    bad["cautions"][-2] = {"text": "욕실 타일도 같이 보면 좋아요.", "source": "field"}
    got = failed_rules("mokgong", bad, cp_case)
    assert got == {"not_chosen.items.door", "scope.dobae", "scope.bath", "scope.tile"}
    ok = copy.deepcopy(plan)
    ok["visit_checks"].append("방문 교체는 이번에 하지 않아요.")
    ok["cautions"][-1] = {"text": "욕실 공사는 목공과 따로 하는 공사예요.", "source": "field"}
    assert failed_rules("mokgong", ok, cp_case) == set()


def test_conditions_from_case_input():
    inp = cp_input(
        items=["door"],
        doors=3,  # 모르겠어요 → 기본값 3을 넣고 to_check에 남긴다 (상담과 같게)
        occupied=True,
        others=["dobae"],
        to_check=["mokgong.doors"],
    )
    case = make_case("mokgong", inp)
    must = set(case["expect"]["must"])
    assert {"sum.items.door", "sum.door_frame.yes", "prep.mention", "after.moving"} <= must
    assert {"after.remove_door", "order.dobae", "check.doors"} <= must
    assert {"not_chosen.items.molding", "not_chosen.items.base", "not_chosen.items.flatten"} <= set(
        case["expect"]["must_not"]
    )
    assert "scope.dobae" not in case["expect"]["must_not"]
    plan = ideal("mokgong")(case)
    assert failed("mokgong", plan, case) == set()
    plan["cautions"] = [c for c in plan["cautions"] if "도배" not in c["text"]]
    plan["visit_checks"] = [v for v in plan["visit_checks"] if "개수" not in v]
    assert failed_rules("mokgong", plan, case) == {"order.dobae", "check.doors"}


def test_order_rule_needs_same_sentence():
    case = make_case("dobae", wp_input(others=["mokgong"]))
    plan = ideal("dobae")(case)
    assert failed("dobae", plan, case) == set()
    for c in plan["cautions"]:
        if "목공" in c["text"]:
            c["text"] = "목공도 해요. 그다음 이야기는 실측 때 해요."
    assert "order.mokgong" in failed_rules("dobae", plan, case)


def test_rules_cover_every_after_visit_line_and_use_spec_sources():
    for trade in trades.registered():
        rules = tp.rules(trade)
        assert {f"after.{k}" for k in trades.after_lines(trade)} <= set(rules)
        assert trades.sources(trade) == trades.spec(trade).agent.sources
    assert set(trades.after_lines("mokgong")) == {
        "remove_ceiling",
        "remove_door",
        "remove_trim",
        "waste",
        "moving",
    }


def test_words_from_screen_labels():
    assert label_words("저가형 · 합지") == ["저가형", "합지"]
    assert label_words("천장도 해요") == ["천장"]
    assert label_words("천장 몰딩") == ["몰딩"]
    assert label_words("문틀까지 바꿔요") == ["문틀"]
    assert label_words("걸레받이") == ["걸레받이"]
    assert label_words("천장 도배", drop=("도배",)) == []
    assert line_pattern("기존 방문 · 문틀 철거").startswith("철거|")
    assert "폐기물" in line_pattern("폐기물 처리")
