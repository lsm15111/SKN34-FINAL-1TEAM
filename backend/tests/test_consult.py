"""공정 상담 API. LLM은 부르지 않는다 (스텁 또는 가짜 응답)."""

from decimal import Decimal

import pytest

from app.agent import llm
from app.agent.schemas import (
    Caution,
    Change,
    ExpertAnswer,
    PlanStep,
    RouterOut,
    TradePlan,
    TradeQuestion,
)
from app.config import settings
from app.consult.service import (
    CHANGED_REPLY,
    EXPERT_FAILED,
    FALLBACK_REPLY,
    OUT_OF_SCOPE,
    PLAN_FAILED,
)
from app.consult.trades import REGISTRY
from tests.helpers import make_admin, signup
from tests.test_project import body

URL = "/consult"
USAGE = llm.Usage("fake", 1, 1, 0, 0, 1)
FORM = [
    ("area", "34"),
    ("area_basis", "supply"),
    ("occupied", "no"),
    ("dobae.grade", "basic"),
    ("dobae.include_ceiling", "yes"),
]
DONE = {
    "trades": ["dobae"],
    "area_m2": "112.4",
    "area_basis": "supply",
    "occupied": False,
    "values": {"dobae": {"grade": "basic", "include_ceiling": "yes"}},
}


def route(**kw) -> RouterOut:
    base = {
        "pyeong": None,
        "area_m2": None,
        "area_basis": None,
        "occupied": None,
        "balcony_ext": None,
        "built_year": None,
        "changes": [],
        "questions": [],
        "out_of_scope": False,
        "reply": "알겠어요.",
    }
    return RouterOut(**(base | kw))


def change(field: str, value: str, op: str = "set") -> Change:
    return Change(field=field, op=op, value=value)


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
ANSWER = ExpertAnswer(
    answer="합지는 종이 벽지라 값이 싸고, 실크는 닦을 수 있고 오래 가요.", sources=["field"]
)


@pytest.fixture
def fake_llm(monkeypatch):
    """schema에 맞는 가짜 응답을 돌려주고, 불린 (스키마 이름, 역할)을 남긴다."""
    state = {"route": route(), "plan": PLAN, "answer": ANSWER, "calls": []}

    async def parse(system, user, schema, *, role="default", **_):
        state["calls"].append((schema.__name__, role))
        out = {RouterOut: state["route"], TradePlan: state["plan"], ExpertAnswer: state["answer"]}
        return out[schema], USAGE

    monkeypatch.setattr(llm, "parse", parse)
    return state


def names(state) -> list[str]:
    return [name for name, _ in state["calls"]]


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
    assert out["summary"] is None
    assert [q["kind"] for q in out["questions"]] == ["text", "choice", "choice", "choice", "choice"]
    grade = out["questions"][3]
    assert grade["trade"] == "dobae"
    assert [c["value"] for c in grade["choices"]] == ["economy", "basic", "unknown"]

    out = turn(api, out["card"], answers=answers(FORM))
    assert out["questions"] == [] and out["card"]["to_check"] == []
    assert out["card"]["values"] == {"dobae": {"grade": "basic", "include_ceiling": "yes"}}
    (res,) = out["results"]
    q = res["quote"]
    assert (res["trade"], res["label"], q["version"]) == ("dobae", "도배", "2026H2")
    assert (q["subtotal"], q["vat"], q["total"]) == (3_058_446, 305_845, 3_364_291)
    assert {ln["key"]: ln["basis"] for ln in q["lines"]}["waste"] == "none"
    s = out["summary"]
    assert (s["subtotal"], s["vat"], s["total"], s["days"]) == (
        3_058_446,
        305_845,
        3_364_291,
        "2.5",
    )
    assert [st["key"] for st in out["schedule"]] == ["paper", "finish"]
    facts = {(f["label"], f["text"]) for f in out["facts"]}
    assert facts >= {("면적", "공급면적 112.4㎡"), ("도배 유형", "기본형 · 실크")}
    # LLM_LIVE=false: 설명 없이 계산 결과만, 그리고 그 사실을 알린다
    assert res["plan"] is None and res["plan_status"] == "failed" and out["notice"] == PLAN_FAILED


def test_unknown_answer_uses_default_and_marks_check(api):
    signup(api)
    pairs = [("area", "112.4㎡"), ("area_basis", "unknown"), ("dobae.grade", "unknown")]
    out = turn(api, answers=answers(pairs))
    c = out["card"]
    assert c["area_basis"] == "supply" and c["values"]["dobae"]["grade"] == "basic"
    assert c["to_check"] == ["area_basis", "dobae.grade"]
    assert fields(out) == ["occupied", "dobae.include_ceiling"]
    assert {f["label"] for f in out["facts"] if f["check"]} == {"면적", "도배 유형"}


def test_bad_answers_and_cards_are_rejected(api):
    signup(api)
    for a in [
        ("dobae.grade", "gold"),
        ("dobae.grade", ["basic"]),
        ("area", "아주 큼"),
        ("occupied", "unknown"),  # 모르겠어요가 없는 칸
        ("dobae.color", "red"),
        ("mokgong.doors", "2"),  # 고르지 않은 공정
    ]:
        assert api.post(URL, json={"answers": answers([a])}).status_code == 422, a
    too_many = answers([("mokgong.items", ["door"]), ("mokgong.doors", "11")])
    assert api.post(URL, json={"trades": ["mokgong"], "answers": too_many}).status_code == 422
    for card in [
        {"trades": ["sauna"]},  # 없는 공정
        {"trades": ["dobae", "dobae"]},
        {"trades": ["dobae"], "values": {"dobae": {"grade": "gold"}}},
        {"trades": ["dobae"], "values": {"dobae": {"color": "red"}}},
        {"trades": ["dobae"], "values": {"mokgong": {"items": ["door"]}}},
        {"trades": ["mokgong"], "values": {"mokgong": {"doors": 11}}},
        {"trades": ["mokgong"], "values": {"mokgong": {"doors": "3"}}},
        {"trades": ["dobae"], "to_check": ["occupied"]},
    ]:
        assert api.post(URL, json={"card": card}).status_code == 422, card
    assert api.post(URL, json={"trades": ["sauna"]}).status_code == 422


def test_free_text_without_llm_keeps_the_form(api):
    signup(api)
    out = turn(api, message="합지랑 실크는 뭐가 달라요?")
    assert out["reply"] == FALLBACK_REPLY and fields(out)[0] == "area"


def test_router_changes_are_checked_by_the_spec(api, fake_llm):
    signup(api)
    fake_llm["route"] = route(
        area_basis="unknown",
        changes=[
            change("dobae.include_ceiling", "no"),
            change("dobae.include_ceiling", "maybe"),  # 선택지 밖
            change("dobae.grade", "gold"),
            change("dobae.color", "red"),  # 없는 칸
            change("mokgong.doors", "2"),  # 고르지 않은 공정
        ],
    )
    out = turn(api, DONE, message="천장은 빼 주세요. 평수 기준은 잘 몰라요")
    c = out["card"]
    assert c["values"] == {"dobae": {"grade": "basic", "include_ceiling": "no"}}
    assert (c["area_basis"], c["to_check"]) == ("supply", ["area_basis"])

    mok = {
        "trades": ["mokgong"],
        "area_m2": "84.9",
        "area_basis": "exclusive",
        "occupied": True,
        "values": {"mokgong": {"items": ["molding"]}},
    }
    fake_llm["route"] = route(
        changes=[
            change("mokgong.items", "door", "add"),
            change("mokgong.items", "sofa", "add"),
            change("mokgong.items", "unknown"),  # 모르겠어요가 없는 칸
            change("mokgong.doors", "11"),  # 범위 밖
        ]
    )
    out = turn(api, mok, message="방문도 바꿀래요")
    assert out["card"]["values"] == {"mokgong": {"items": ["molding", "door"]}}
    # 방문을 고르면 방문 칸을 묻는다
    assert fields(out) == ["mokgong.doors", "mokgong.door_frame"]
    q = out["questions"][0]
    assert (q["kind"], q["min"], q["max"]) == ("count", 1, 10)
    assert [c["value"] for c in q["choices"]] == ["unknown"]

    # 마지막 항목은 뺄 수 없고, 방문을 빼면 방문 칸 값은 지운다
    full = {"items": ["molding", "door"], "doors": 2, "door_frame": "no"}
    fake_llm["route"] = route(
        changes=[
            change("mokgong.items", "door", "remove"),
            change("mokgong.items", "molding", "remove"),
        ]
    )
    out = turn(api, mok | {"values": {"mokgong": full}}, message="방문이랑 몰딩은 빼요")
    assert out["card"]["values"] == {"mokgong": {"items": ["molding"]}}
    fake_llm["route"] = route(changes=[change("mokgong.items", "base, molding")])
    out = turn(api, mok, message="걸레받이랑 몰딩만 해요")
    assert out["card"]["values"]["mokgong"]["items"] == ["molding", "base"]


def test_chat_changes_the_card_and_plan_is_checked(api, fake_llm):
    signup(api)
    fake_llm["route"] = route(changes=[change("dobae.include_ceiling", "no")])
    out = turn(api, DONE, message="천장은 빼 주세요")
    assert out["reply"] == "알겠어요."
    assert out["card"]["values"]["dobae"]["include_ceiling"] == "no"
    (res,) = out["results"]
    assert res["plan_status"] == "new"
    plan = res["plan"]
    # 없는 단계 키, 숫자가 든 항목, 목록 밖 출처는 버린다
    assert [s["key"] for s in plan["steps"]] == ["paper", "finish"]
    assert plan["visit_checks"] == ["기존 벽지가 몇 겹인지 봐 주세요."]
    assert len(plan["cautions"]) == 1 and plan["cautions"][0]["source"].startswith("현장 후기")
    assert plan["prompt_version"] == "wallpaper-v1"
    assert fake_llm["calls"] == [("RouterOut", "router"), ("TradePlan", "plan")]

    # 칸이 그대로면 공정 에이전트를 다시 부르지 않는다
    fake_llm["route"] = route()
    again = turn(api, out["card"], message="고마워요")
    assert again["results"][0]["plan_status"] == "same" and again["results"][0]["plan"] is None
    assert names(fake_llm) == ["RouterOut", "TradePlan", "RouterOut"]


def test_bad_summary_drops_the_whole_plan(api, fake_llm):
    signup(api)
    fake_llm["plan"] = PLAN.model_copy(update={"summary": "총 336만 원이에요."})
    out = turn(api, answers=answers(FORM))
    assert out["results"][0]["plan"] is None and out["notice"] == PLAN_FAILED


def test_invented_numbers_and_out_of_scope_replies(api, fake_llm):
    signup(api)
    fake_llm["route"] = route(reply="보통 300만 원쯤 들어요.")
    assert turn(api, message="얼마 정도 들어요?")["reply"] is None
    fake_llm["route"] = route(reply="", out_of_scope=True)
    assert turn(api, message="욕실 방수도 해 주세요")["reply"] == OUT_OF_SCOPE
    # 답을 버려도 칸이 바뀌었으면 다시 계산했다고만 알린다
    fake_llm["route"] = route(
        reply="합지면 30만 원 싸요.", changes=[change("dobae.grade", "economy")]
    )
    assert turn(api, DONE, message="합지로 할게요")["reply"] == CHANGED_REPLY


def test_questions_go_to_the_trade_experts(api, fake_llm):
    signup(api)
    fake_llm["route"] = route(
        reply="",
        questions=[
            TradeQuestion(trade="dobae", question="합지랑 실크는 뭐가 달라요?"),
            TradeQuestion(trade="dobae", question="공정마다 하나만 물어요"),
            TradeQuestion(trade="mokgong", question="몰딩은 뭐예요?"),
            TradeQuestion(trade="sauna", question="없는 공정은 버려요"),
        ],
    )
    out = turn(api, message="합지랑 실크 차이랑 몰딩이 뭔지 알려 주세요")
    assert out["reply"] == f"도배: {ANSWER.answer}\n목공: {ANSWER.answer}"
    assert fake_llm["calls"] == [
        ("RouterOut", "router"),
        ("ExpertAnswer", "expert"),
        ("ExpertAnswer", "expert"),
    ]
    assert fields(out)[0] == "area"  # 폼은 그대로

    # 지어낸 금액이 든 답은 버리고 그렇다고 알린다
    fake_llm["answer"] = ExpertAnswer(answer="실크는 3,325원/㎡이에요.", sources=["pps"])
    fake_llm["route"] = route(reply="", questions=[TradeQuestion(trade="dobae", question="얼마?")])
    assert turn(api, message="실크는 얼마예요?")["reply"] == f"도배: {EXPERT_FAILED}"

    # 값 변경과 질문이 같이 오면 의견과 답을 함께 만든다
    fake_llm["answer"] = ANSWER
    fake_llm["route"] = route(
        reply="",
        changes=[change("dobae.grade", "economy")],
        questions=[TradeQuestion(trade="dobae", question="합지는 오래 가요?")],
    )
    out = turn(api, DONE, message="합지로 하면 오래 가요?")
    assert out["reply"] == f"{CHANGED_REPLY}\n도배: {ANSWER.answer}"
    assert out["results"][0]["plan_status"] == "new"
    assert out["results"][0]["plan"]["summary"] == PLAN.summary


def test_expert_answers_keep_only_known_sources():
    agent = REGISTRY["dobae"].agent
    a = agent.check_answer(
        ExpertAnswer(answer=" 닦을 수 있어요. ", sources=["field", "x", "field"])
    )
    assert a == ExpertAnswer(answer="닦을 수 있어요.", sources=["field"])
    for bad in ("", "  ", "가" * 301, "보통 2일 걸려요.", "평당 5만 원이에요.", "30㎡예요."):
        with pytest.raises(llm.LlmError):
            agent.check_answer(ExpertAnswer(answer=bad, sources=[]))


def test_prefill_from_my_project_only(api):
    signup(api)
    pid = project(api)
    out = turn(api, project_id=pid)
    c = out["card"]
    assert c["trades"] == ["mokgong", "dobae"]
    assert c["values"] == {"mokgong": {"items": ["molding", "base"]}, "dobae": {"grade": "basic"}}
    assert (c["area_m2"], c["area_basis"], c["occupied"]) == ("112.4", "supply", True)
    assert c["spaces"] == {"mokgong": ["거실"], "dobae": ["거실", "방", "방 2"]}
    assert list(out["trade_labels"].items()) == [("mokgong", "목공"), ("dobae", "도배")]
    assert ("목공 공간", "거실") in {(f["label"], f["text"]) for f in out["facts"]}
    # 견적 받기에 없는 칸만 폼으로 묻는다
    assert fields(out) == ["dobae.include_ceiling"]

    out = turn(api, c, answers=answers([("dobae.include_ceiling", "yes")]))
    res = out["results"]
    assert [(r["trade"], r["label"]) for r in res] == [("mokgong", "목공"), ("dobae", "도배")]
    mok = res[0]["quote"]
    assert {ln["key"] for ln in mok["lines"]} >= {"molding", "base", "remove_trim", "moving"}
    # 짐 정리는 처음 한 번, 목공이 끝난 뒤 도배
    sched = [(s["trade"], s["key"]) for s in out["schedule"]]
    assert sched[0] == ("mokgong", "prep")
    assert sched[-2:] == [("dobae", "paper"), ("dobae", "finish")]
    assert sum(s["key"] == "prep" for s in out["schedule"]) == 1
    # 요약은 계산 엔진이 공정 금액을 더한 값과 이은 공정표 기간
    s = out["summary"]
    for k in ("subtotal", "vat", "total"):
        assert s[k] == sum(r["quote"][k] for r in res)
    assert Decimal(s["days"]) == Decimal(sum(st["half_days"] for st in out["schedule"])) / 2
    lines = [ln for r in res for ln in r["quote"]["lines"] if ln["state"] != "excluded"]
    assert sum(s["basis_counts"].values()) == len(lines) and s["basis_counts"]["assumed"] >= 2

    signup(api, email="other@mitjip.test")
    assert api.post(URL, json={"project_id": pid}).status_code == 404


def test_door_questions_only_when_doors_are_picked(api):
    signup(api)
    pid = project(api, mokgong={"spaces": ["a", "b"], "items": ["door", "molding"]})
    out = turn(api, project_id=pid)
    assert out["card"]["trades"] == ["mokgong"]
    assert fields(out) == ["mokgong.doors", "mokgong.door_frame"]
    pairs = [("mokgong.doors", "unknown"), ("mokgong.door_frame", "no")]
    out = turn(api, out["card"], answers=answers(pairs))
    v = out["card"]["values"]["mokgong"]
    assert (v["items"], v["doors"], v["door_frame"]) == (["molding", "door"], 3, "no")
    assert out["card"]["to_check"] == ["mokgong.doors"]
    door = next(ln for ln in out["results"][0]["quote"]["lines"] if ln["key"] == "door")
    assert door["qty"] == "3" and door["name"] == "방문 교체 (문짝만)"


def test_start_without_a_project_asks_the_trade_fields(api):
    signup(api)
    common = answers([("area", "24평"), ("area_basis", "supply"), ("occupied", "yes")])
    out = turn(api, trades=["mokgong"], answers=common)
    assert out["card"]["trades"] == ["mokgong"] and fields(out) == ["mokgong.items"]
    q = out["questions"][0]
    assert (q["kind"], q["min"], q["max"]) == ("multi", 1, 4)
    assert [c["value"] for c in q["choices"]] == ["molding", "base", "door", "flatten"]
    out = turn(api, out["card"], answers=answers([("mokgong.items", ["door", "base"])]))
    assert out["card"]["values"]["mokgong"]["items"] == ["base", "door"]
    assert fields(out) == ["mokgong.doors", "mokgong.door_frame"]


def test_only_the_changed_trade_is_planned_again(api, fake_llm):
    signup(api)
    pid = project(api)
    first = turn(api, project_id=pid, answers=answers([("dobae.include_ceiling", "yes")]))
    assert [r["plan_status"] for r in first["results"]] == ["new", "new"]
    assert names(fake_llm) == ["TradePlan", "TradePlan"]
    versions = {r["trade"]: r["plan"]["prompt_version"] for r in first["results"]}
    assert versions == {"mokgong": "carpentry-v1", "dobae": "wallpaper-v1"}

    fake_llm["route"] = route(changes=[change("dobae.grade", "economy")])
    out = turn(api, first["card"], message="합지로 바꿔 주세요")
    assert {r["trade"]: r["plan_status"] for r in out["results"]} == {
        "mokgong": "same",
        "dobae": "new",
    }
    assert names(fake_llm)[2:] == ["RouterOut", "TradePlan"]


def test_plan_cache_hit_skips_the_llm(api, fake_llm, monkeypatch):
    signup(api)
    first = turn(api, answers=answers(FORM))
    assert first["results"][0]["plan_status"] == "new" and names(fake_llm) == ["TradePlan"]
    # 새 대화라도 같은 집 · 같은 칸이면 저장해 둔 의견을 쓴다 (LLM을 부르지 않는다)
    again = turn(api, answers=answers(FORM))
    assert again["results"][0]["plan_status"] == "new"
    assert again["results"][0]["plan"] == first["results"][0]["plan"]
    assert names(fake_llm) == ["TradePlan"]
    # 캐시를 끄면 다시 부른다
    monkeypatch.setattr(settings, "llm_plan_cache_s", 0)
    turn(api, answers=answers(FORM))
    assert names(fake_llm) == ["TradePlan", "TradePlan"]
