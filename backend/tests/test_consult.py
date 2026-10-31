"""도배 상담 API. LLM은 부르지 않는다 (스텁 또는 가짜 응답)."""

import pytest

from app.agent import llm
from app.agent.schemas import CardUpdate, Caution, DobaePlan, PlanStep
from app.consult.service import FALLBACK_REPLY, OUT_OF_SCOPE, PLAN_FAILED
from tests.helpers import make_admin, signup
from tests.test_project import body

URL = "/consult/dobae"
USAGE = llm.Usage("fake", 1, 1, 0, 0, 1)
FULL = [("area", "34"), ("area_basis", "supply"), ("grade", "basic"), ("include_ceiling", "yes")]


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
        "out_of_scope": False,
        "reply": "알겠어요.",
    }
    return CardUpdate(**(base | kw))


PLAN = DobaePlan(
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
    r = api.post(URL, json={"card": card or {}, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_needs_customer_login(api):
    assert api.post(URL, json={}).status_code == 401
    make_admin(api)
    assert api.post(URL, json={}).status_code == 403


def test_choices_only_reach_a_standard_quote_without_llm(api):
    signup(api)
    out = turn(api)
    assert out["question"]["field"] == "area" and out["quote"] is None
    card = out["card"]
    for field, value in [*FULL, ("occupied", "no")]:
        out = turn(api, card, answer={"field": field, "value": value})
        card = out["card"]
    assert card["area_m2"] == "112.4" and card["to_check"] == []
    q = out["quote"]
    assert (q["subtotal"], q["vat"], q["total"]) == (3_058_446, 305_845, 3_364_291)
    assert q["version"] == "2026H2" and q["days"] == "2.5"
    # LLM_LIVE=false: 설명 없이 계산 결과만, 그리고 그 사실을 알린다
    assert out["plan"] is None and out["plan_status"] == "failed" and out["notice"] == PLAN_FAILED


def test_number_only_is_read_without_llm(api, monkeypatch):
    signup(api)

    async def boom(*a, **k):
        raise AssertionError("LLM을 부르면 안 돼요")

    monkeypatch.setattr(llm, "parse", boom)
    out = turn(api, message="34평")
    assert out["card"]["area_m2"] == "112.4" and out["question"]["field"] == "area_basis"


def test_free_text_without_llm_asks_again(api):
    signup(api)
    out = turn(api, message="도배 좀 하려고요")
    assert out["reply"] == FALLBACK_REPLY and out["question"]["field"] == "area"


def test_unknown_answer_uses_default_and_marks_check(api):
    signup(api)
    out = turn(api, {"area_m2": "112.4"}, answer={"field": "area_basis", "value": "unknown"})
    assert out["card"]["area_basis"] == "supply" and out["card"]["to_check"] == ["area_basis"]


def test_bad_answer_is_rejected(api):
    signup(api)
    r = api.post(URL, json={"answer": {"field": "grade", "value": "gold"}})
    assert r.status_code == 422
    r = api.post(URL, json={"answer": {"field": "area", "value": "아주 큼"}})
    assert r.status_code == 422


def test_llm_fills_the_card_and_plan_is_checked(api, fake_llm):
    signup(api)
    fake_llm["update"] = upd(
        pyeong=34, area_basis="supply", grade="basic", include_ceiling="yes", occupied=False
    )
    out = turn(api, message="34평형 아파트 빈집이고 실크로 천장까지 하려고요")
    assert out["reply"] == "알겠어요." and out["question"] is None
    assert out["quote"]["total"] == 3_364_291 and out["plan_status"] == "new"
    plan = out["plan"]
    # 없는 단계 키, 숫자가 든 항목, 목록 밖 출처는 버린다
    assert [s["key"] for s in plan["steps"]] == ["paper", "finish"]
    assert plan["visit_checks"] == ["기존 벽지가 몇 겹인지 봐 주세요."]
    assert len(plan["cautions"]) == 1 and plan["cautions"][0]["source"].startswith("현장 후기")
    assert fake_llm["calls"] == ["CardUpdate", "DobaePlan"]

    # 카드가 그대로면 공정 에이전트를 다시 부르지 않는다
    fake_llm["update"] = upd()
    again = turn(api, out["card"], message="고마워요")
    assert again["plan_status"] == "same" and again["plan"] is None
    assert fake_llm["calls"] == ["CardUpdate", "DobaePlan", "CardUpdate"]


def test_bad_summary_drops_the_whole_plan(api, fake_llm):
    signup(api)
    fake_llm["plan"] = PLAN.model_copy(update={"summary": "총 336만 원이에요."})
    card = {"area_m2": "112.4", "area_basis": "supply", "grade": "basic", "include_ceiling": True}
    out = turn(api, card, answer={"field": "occupied", "value": "no"})
    assert out["plan"] is None and out["notice"] == PLAN_FAILED and out["quote"] is not None


def test_invented_numbers_and_out_of_scope_replies(api, fake_llm):
    signup(api)
    fake_llm["update"] = upd(reply="보통 300만 원쯤 들어요.")
    assert turn(api, message="얼마 정도 들어요?")["reply"] is None
    fake_llm["update"] = upd(reply="", out_of_scope=True)
    assert turn(api, message="욕실도 해 주세요")["reply"] == OUT_OF_SCOPE


def test_prefill_from_my_project_only(api):
    signup(api)
    pid = api.post("/projects", json=body(size={"basis": "supply", "m2": "112.4"})).json()["id"]
    out = turn(api, project_id=pid)
    c = out["card"]
    assert (c["area_m2"], c["area_basis"], c["grade"]) == ("112.4", "supply", "basic")
    assert c["occupied"] is True and c["balcony_ext"] is True
    assert out["question"]["field"] == "include_ceiling"

    signup(api, email="other@mitjip.test")
    assert api.post(URL, json={"project_id": pid}).status_code == 404
