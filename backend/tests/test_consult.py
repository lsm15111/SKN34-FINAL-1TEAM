"""도배 · 목공 상담 API. LLM은 부르지 않는다 (스텁 또는 가짜 응답)."""

import pytest

from app.agent import llm
from app.agent.schemas import CardUpdate, Caution, PlanStep, TradePlan
from app.consult.service import CHANGED_REPLY, FALLBACK_REPLY, OUT_OF_SCOPE, PLAN_FAILED
from tests.helpers import make_admin, signup
from tests.test_project import body

URL = "/consult"
USAGE = llm.Usage("fake", 1, 1, 0, 0, 1)
FORM = [
    ("area", "34"),
    ("area_basis", "supply"),
    ("occupied", "no"),
    ("grade", "basic"),
    ("include_ceiling", "yes"),
]
DONE = {
    "area_m2": "112.4",
    "area_basis": "supply",
    "occupied": False,
    "grade": "basic",
    "include_ceiling": True,
}


def upd(**kw) -> CardUpdate:
    base = {
        "pyeong": None,
        "area_m2": None,
        "area_basis": None,
        "grade": None,
        "include_ceiling": None,
        "occupied": None,
        "balcony_ext": None,
        "built_year": None,
        "doors": None,
        "door_frame": None,
        "out_of_scope": False,
        "reply": "알겠어요.",
    }
    return CardUpdate(**(base | kw))


PLAN = TradePlan(
    summary="실크로 벽과 천장을 바르는 빈집 도배예요. 철거 여부는 실측 때 정해요.",
    steps=[
        PlanStep(key="paper", note="기존 벽지 상태를 보고 초배와 정배를 해요."),
        PlanStep(key="nope", note="없는 단계예요."),
        PlanStep(key="finish", note="이음매와 들뜸을 같이 봐요."),
    ],
    visit_checks=["기존 벽지가 몇 겹인지 봐 주세요.", "천장 높이가 2.4m인지 재 주세요."],
    cautions=[
        Caution(text="철거와 폐기물이 가견적에 들어 있는지 물어봐요.", source="field"),
        Caution(text="출처가 목록에 없어요.", source="blog123"),
    ],
)


@pytest.fixture
def fake_llm(monkeypatch):
    """schema에 맞는 가짜 응답을 돌려주고, 불린 스키마 이름을 남긴다."""
    state = {"update": upd(), "plan": PLAN, "calls": []}

    async def parse(system, user, schema, **_):
        state["calls"].append(schema.__name__)
        return (state["update"] if schema is CardUpdate else state["plan"]), USAGE

    monkeypatch.setattr(llm, "parse", parse)
    return state


def turn(api, card=None, **kw):
    r = api.post(URL, json={"card": card, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def answers(pairs):
    return [{"field": f, "value": v} for f, v in pairs]


def fields(out) -> list[str]:
    return [q["field"] for q in out["questions"]]


def project(api, **trades) -> str:
    b = body(size={"basis": "supply", "m2": "112.4"})
    if trades:
        b["trades"] = trades
    r = api.post("/projects", json=b)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_needs_customer_login(api):
    assert api.post(URL, json={}).status_code == 401
    make_admin(api)
    assert api.post(URL, json={}).status_code == 403


def test_form_answers_reach_a_standard_quote_without_llm(api):
    signup(api)
    out = turn(api)
    assert fields(out) == [f for f, _ in FORM] and out["results"] == []
    out = turn(api, out["card"], answers=answers(FORM))
    assert out["questions"] == [] and out["card"]["to_check"] == []
    (res,) = out["results"]
    q = res["quote"]
    assert res["trade"] == "dobae" and q["version"] == "2026H2"
    assert (q["subtotal"], q["vat"], q["total"]) == (3_058_446, 305_845, 3_364_291)
    assert out["days"] == "2.5" and [s["key"] for s in out["schedule"]] == ["paper", "finish"]
    # LLM_LIVE=false: 설명 없이 계산 결과만, 그리고 그 사실을 알린다
    assert res["plan"] is None and res["plan_status"] == "failed" and out["notice"] == PLAN_FAILED


def test_unknown_answer_uses_default_and_marks_check(api):
    signup(api)
    out = turn(api, answers=answers([("area", "112.4㎡"), ("area_basis", "unknown")]))
    assert out["card"]["area_basis"] == "supply" and out["card"]["to_check"] == ["area_basis"]
    assert fields(out) == ["occupied", "grade", "include_ceiling"]


def test_bad_answer_is_rejected(api):
    signup(api)
    for a in [("grade", "gold"), ("area", "아주 큼"), ("doors", "11")]:
        r = api.post(URL, json={"answers": answers([a])})
        assert r.status_code == 422


def test_free_text_without_llm_keeps_the_form(api):
    signup(api)
    out = turn(api, message="합지랑 실크는 뭐가 달라요?")
    assert out["reply"] == FALLBACK_REPLY and fields(out)[0] == "area"


def test_chat_changes_the_card_and_plan_is_checked(api, fake_llm):
    signup(api)
    fake_llm["update"] = upd(include_ceiling="no")
    out = turn(api, DONE, message="천장은 빼 주세요")
    assert out["reply"] == "알겠어요." and out["card"]["include_ceiling"] is False
    (res,) = out["results"]
    assert res["plan_status"] == "new"
    plan = res["plan"]
    # 없는 단계 키, 숫자가 든 항목, 목록 밖 출처는 버린다
    assert [s["key"] for s in plan["steps"]] == ["paper", "finish"]
    assert plan["visit_checks"] == ["기존 벽지가 몇 겹인지 봐 주세요."]
    assert len(plan["cautions"]) == 1 and plan["cautions"][0]["source"].startswith("현장 후기")
    assert plan["prompt_version"] == "wallpaper-v1"
    assert fake_llm["calls"] == ["CardUpdate", "TradePlan"]

    # 칸이 그대로면 공정 에이전트를 다시 부르지 않는다
    fake_llm["update"] = upd()
    again = turn(api, out["card"], message="고마워요")
    assert again["results"][0]["plan_status"] == "same" and again["results"][0]["plan"] is None
    assert fake_llm["calls"] == ["CardUpdate", "TradePlan", "CardUpdate"]


def test_bad_summary_drops_the_whole_plan(api, fake_llm):
    signup(api)
    fake_llm["plan"] = PLAN.model_copy(update={"summary": "총 336만 원이에요."})
    out = turn(api, answers=answers(FORM))
    assert out["results"][0]["plan"] is None and out["notice"] == PLAN_FAILED


def test_invented_numbers_and_out_of_scope_replies(api, fake_llm):
    signup(api)
    fake_llm["update"] = upd(reply="보통 300만 원쯤 들어요.")
    assert turn(api, message="얼마 정도 들어요?")["reply"] is None
    fake_llm["update"] = upd(reply="", out_of_scope=True)
    assert turn(api, message="욕실도 해 주세요")["reply"] == OUT_OF_SCOPE
    # 답을 버려도 칸이 바뀌었으면 다시 계산했다고만 알린다
    fake_llm["update"] = upd(doors=2, reply="방문 2개면 86만 원이에요.")
    assert turn(api, DONE, message="방문은 2개예요")["reply"] == CHANGED_REPLY


def test_prefill_both_trades_from_my_project_only(api):
    signup(api)
    pid = project(api)
    out = turn(api, project_id=pid)
    c = out["card"]
    assert c["trades"] == ["dobae", "mokgong"] and c["mok_items"] == ["molding", "base"]
    assert (c["area_m2"], c["area_basis"], c["grade"]) == ("112.4", "supply", "basic")
    assert c["occupied"] is True and c["mok_spaces"] == ["거실"]
    # 견적 받기에 없는 칸만 폼으로 묻는다
    assert fields(out) == ["include_ceiling"]

    out = turn(api, c, answers=answers([("include_ceiling", "yes")]))
    assert [r["trade"] for r in out["results"]] == ["mokgong", "dobae"]
    mok = out["results"][0]["quote"]
    assert {ln["key"] for ln in mok["lines"]} >= {"molding", "base", "remove_trim", "moving"}
    # 짐 정리는 처음 한 번, 목공이 끝난 뒤 도배
    sched = [(s["trade"], s["key"]) for s in out["schedule"]]
    assert sched[0] == ("mokgong", "prep") and sched[-2:] == [
        ("dobae", "paper"),
        ("dobae", "finish"),
    ]
    assert sum(s["key"] == "prep" for s in out["schedule"]) == 1

    signup(api, email="other@mitjip.test")
    assert api.post(URL, json={"project_id": pid}).status_code == 404


def test_door_questions_only_when_doors_are_picked(api):
    signup(api)
    pid = project(api, mokgong={"spaces": ["a", "b"], "items": ["door", "molding"]})
    out = turn(api, project_id=pid)
    assert out["card"]["trades"] == ["mokgong"] and fields(out) == ["doors", "door_frame"]
    out = turn(api, out["card"], answers=answers([("doors", "unknown"), ("door_frame", "no")]))
    c = out["card"]
    assert (c["doors"], c["door_frame"], c["to_check"]) == (3, False, ["doors"])
    door = next(ln for ln in out["results"][0]["quote"]["lines"] if ln["key"] == "door")
    assert door["qty"] == "3" and door["name"] == "방문 교체 (문짝만)"


def test_only_the_changed_trade_is_planned_again(api, fake_llm):
    signup(api)
    pid = project(api)
    first = turn(api, project_id=pid, answers=answers([("include_ceiling", "yes")]))
    assert [r["plan_status"] for r in first["results"]] == ["new", "new"]
    assert fake_llm["calls"] == ["TradePlan", "TradePlan"]
    versions = {r["trade"]: r["plan"]["prompt_version"] for r in first["results"]}
    assert versions == {"mokgong": "carpentry-v1", "dobae": "wallpaper-v1"}

    fake_llm["update"] = upd(grade="economy")
    out = turn(api, first["card"], message="합지로 바꿔 주세요")
    assert {r["trade"]: r["plan_status"] for r in out["results"]} == {
        "mokgong": "same",
        "dobae": "new",
    }
    assert fake_llm["calls"][2:] == ["CardUpdate", "TradePlan"]
