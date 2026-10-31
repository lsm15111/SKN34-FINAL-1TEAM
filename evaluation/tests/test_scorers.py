"""코드 채점: 규칙을 지킨 가짜 응답은 통과하고, 어긴 응답은 그 검사만 실패한다."""

import copy

import pytest

from evaluation.scorers import trade_plan as tp
from evaluation.scorers import witness
from evaluation.tests.conftest import cp_input, make_case, wp_input

WP_SRC = tp.skill_sources("wallpaper")
CP_SRC = tp.skill_sources("carpentry")


def failed(agent: str, plan: dict, case: dict) -> set[str]:
    s = tp.score(agent, plan, case["expect"], WP_SRC if agent == "wallpaper" else CP_SRC)
    return {k for k, ok in s["checks"].items() if not ok}


def failed_rules(agent: str, plan: dict, case: dict) -> set[str]:
    s = tp.score(agent, plan, case["expect"], WP_SRC if agent == "wallpaper" else CP_SRC)
    return {k for k, ok in s["rules"].items() if not ok}


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
    assert failed("wallpaper", GOOD_WP, wp_case) == set()
    for agent, case in (("wallpaper", wp_case), ("carpentry", cp_case)):
        assert failed(agent, witness.ideal_plan(agent, case), case) == set()


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
    got = failed("wallpaper", plan, wp_case)
    assert check in got
    assert got <= {check, "no_number_words", "summary_sent", "must"}


def test_terms_need_gloss_in_first_sentence(wp_case):
    plan = copy.deepcopy(GOOD_WP)
    plan["cautions"][0]["text"] = "합지는 기존 벽지에 덧방하는 경우가 많아요."
    assert tp.unexplained_terms(plan, "wallpaper") == ["덧방"]
    plan["cautions"][0]["text"] = "합지는 기존 벽지를 떼지 않고 그 위에 바르는(덧방) 경우가 많아요."
    assert tp.unexplained_terms(plan, "wallpaper") == []
    plan["steps"][0]["note"] = "짐 정리 · 보양을 해요."
    assert tp.unexplained_terms(plan, "wallpaper") == ["보양"]


def test_everyday_words_are_not_terms():
    plan = copy.deepcopy(GOOD_WP)
    plan["cautions"][0]["text"] = (
        "천장 도배는 벽보다 품이 더 들어요. 그래서 짐 있는 집 할증이 붙어요."
    )
    assert tp.unexplained_terms(plan, "wallpaper") == []
    # 목공 지식의 할증은 '버리는 몫'이라 풀어야 한다
    assert tp.unexplained_terms(plan, "carpentry") == ["할증"]
    plan["cautions"][0]["text"] = "자재에는 버리는 몫(할증)이 이미 들어 있어요."
    assert tp.unexplained_terms(plan, "carpentry") == []


def test_empty_house_must_not_talk_about_belongings():
    case = make_case("wallpaper", wp_input(occupied=False))
    plan = witness.ideal_plan("wallpaper", case)
    assert failed("wallpaper", plan, case) == set()
    plan["summary"] += " 빈집이라 짐 정리 없이 바로 시작해요."
    assert "empty.moving" in failed_rules("wallpaper", plan, case)
    # '벌어짐 · 갈라짐'의 '짐'은 짐 이야기가 아니다
    plan = witness.ideal_plan("wallpaper", case)
    plan["steps"][-1]["note"] = "이음매 벌어짐과 벽 갈라짐을 보고 청소해요."
    assert "empty.moving" not in failed_rules("wallpaper", plan, case)


def test_not_chosen_ceiling_allows_negated_mention():
    case = make_case("wallpaper", wp_input(include_ceiling=False))
    plan = witness.ideal_plan("wallpaper", case)
    assert "천장은 하지 않는" in plan["summary"]
    assert failed("wallpaper", plan, case) == set()
    plan["visit_checks"].append("천장도 같이 바르면 깔끔해요.")
    assert "not_chosen.ceiling" in failed_rules("wallpaper", plan, case)
    plan["visit_checks"][-1] = "천장 높이를 재 달라고 해요."  # 벽 높이 이야기라 괜찮다
    assert "not_chosen.ceiling" not in failed_rules("wallpaper", plan, case)


def test_carpentry_unchosen_items_and_other_trade(cp_case):
    plan = witness.ideal_plan("carpentry", cp_case)
    assert failed("carpentry", plan, cp_case) == set()
    bad = copy.deepcopy(plan)
    bad["visit_checks"].append("문틀이 뒤틀렸는지도 봐 달라고 해요.")
    bad["cautions"][-1] = {"text": "목공이 끝난 뒤 도배를 해요.", "source": "field"}
    assert failed_rules("carpentry", bad, cp_case) == {"not_chosen.door", "other.trade"}
    ok = copy.deepcopy(plan)
    ok["visit_checks"].append("방문 교체는 이번에 하지 않아요.")
    assert "not_chosen.door" not in failed_rules("carpentry", ok, cp_case)


def test_conditions_from_case_input():
    case = make_case(
        "carpentry",
        cp_input(
            items=["door"],
            doors=3,
            door_frame=True,
            occupied=True,
            other_trades=["dobae"],
            to_check=["doors"],
        ),
    )
    must = set(case["expect"]["must"])
    assert {"sum.item.door", "sum.door_frame.yes", "prep.mention", "after.moving"} <= must
    assert {"order.other", "check.doors"} <= must
    assert {"not_chosen.molding", "not_chosen.base", "not_chosen.flatten"} <= set(
        case["expect"]["must_not"]
    )
    plan = witness.ideal_plan("carpentry", case)
    assert failed("carpentry", plan, case) == set()
    plan["cautions"] = [c for c in plan["cautions"] if "도배" not in c["text"]]
    plan["visit_checks"] = [v for v in plan["visit_checks"] if "개수" not in v]
    assert failed_rules("carpentry", plan, case) == {"order.other", "check.doors"}


def test_order_rule_needs_same_sentence():
    case = make_case("wallpaper", wp_input(other_trades=["mokgong"]))
    plan = witness.ideal_plan("wallpaper", case)
    assert failed("wallpaper", plan, case) == set()
    for c in plan["cautions"]:
        if "목공" in c["text"]:
            c["text"] = "목공도 해요. 그다음 이야기는 실측 때 해요."
    assert "order.other" in failed_rules("wallpaper", plan, case)


def test_skill_sources_match_agent_module():
    from evaluation.common import trades

    assert WP_SRC == set(trades.module("wallpaper").SOURCES)
    assert CP_SRC == set(trades.module("carpentry").SOURCES)
