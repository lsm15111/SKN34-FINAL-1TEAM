"""에이전트 허브: 총괄(관문 + 오케스트레이터) · 바닥 전문가 · LLM ↔ 도구 루프. DB 없이, 유료 호출 0회(스텁)."""

import asyncio
import json
import re
import uuid
from datetime import date

import pytest
from v3_kb import repo_index, repo_kb

from app.agent import llm
from app.agent.hub import concierge, experts
from app.agent.hub.core import AgentSpec, Budget, BudgetExceeded, Run, Tool, ToolOut, call_tool
from app.agent.hub.experts.base import ExpertTask, run_expert, split_cites
from app.agent.hub.reply import Reply
from app.agent.v3 import policy
from app.agent.v3 import turn as v3_turn
from app.agent.v3.schemas import Button, TurnContext
from app.config import settings


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setattr(settings, "llm_live", False)
    llm.clear_stubs()
    yield
    llm.clear_stubs()


def ctx(mode: str = "free") -> TurnContext:
    return TurnContext(user_id=uuid.uuid4(), today=date(2026, 11, 27), mode=mode)  # type: ignore[arg-type]


def turn(text: str, *, mode: str = "free", memory=None, waiting=None, button=None):
    return asyncio.run(
        concierge.run_turn(
            text, ctx(mode), kb=repo_kb(), memory=memory, waiting=waiting, button=button
        )
    )


def expert(text: str, *, mode: str = "free", **kw):
    t = ExpertTask(text=text, ctx=ctx(mode), policy=policy.policy_of(text), **kw)
    return asyncio.run(run_expert(experts.get("floor"), t, repo_kb(), budget=Budget(), mode=mode))


def sentences(ans) -> list[str]:
    return [x.text for s in ans.sections for x in s.sentences]


def call(name: str, i: int = 1, **args) -> dict:
    return {"tool_calls": [{"id": f"c{i}", "name": name, "arguments": args}]}


# ---- 바닥 전문가 등록 · 지식 묶음 ----
def test_floor_expert_is_registered_from_folder():
    x = experts.registered()["floor"]
    assert x.code == "floor" and x.ko == "바닥" and x.prompt_version == "floor_v1"
    names = {t.name for t in x.tools}
    assert {"search_knowledge", "compare_materials", "fit_materials", "add_checklist"} <= names
    assert {"draft_vendor_questions", "remember_condition", "ask_condition"} <= names


def test_floor_pack_cites_real_chunks_and_has_no_numbers():
    pack = experts.get("floor").pack
    ix = repo_index()
    missing = sorted(r for r in pack.refs() if r not in ix.by_ref)
    assert missing == []  # 모든 문장의 근거 번호가 실제 지식 조각
    texts = re.findall(r'"text":"([^"]*)"', pack.model_dump_json())
    assert texts and not [t for t in texts if re.search(r"\d", t)]  # 금액 · 기간 숫자를 쓰지 않음


# ---- 바닥 전문가 무료 모드 ----
def test_compare_gives_material_lines_and_table_without_asking():
    rep = expert("강마루랑 강화마루 차이가 뭐예요?")
    table = next(c for c in rep.cards if c.kind == "compare")
    assert [r.cells[0] for r in table.table.rows] == ["강마루", "강화마루"]
    assert rep.ask is None  # 견주기만 물으면 조건을 되묻지 않고 칩으로 권해요
    assert "우리 집에 맞는 바닥재 골라 줘" in rep.suggest
    assert all(x.cites for x in rep.sections[0].sentences)


def test_checklists_are_semi_self_tasks_with_owner():
    before = expert("바닥 공사 전에 뭘 준비해야 해요?")
    lines = [x.text for x in before.sections[0].sentences]
    assert before.sections[0].title == "[바닥] 바닥 공사 전에 할 일"
    assert any(t.startswith("직접 · ") for t in lines) and any(
        t.startswith("업체에 확인 · ") for t in lines
    )
    after = expert("마루 깔고 끝나고 뭘 확인해요?")
    assert after.sections[0].title == "[바닥] 바닥 공사 끝나고 확인할 것"


def test_vendor_questions_are_copyable_lines():
    rep = expert("바닥 업체에 뭘 물어봐야 해요?")
    assert 1 <= len(rep.vendor) <= 3 and all(v.endswith("요.") for v in rep.vendor)


def test_price_question_uses_rules_not_numbers():
    rep = expert("장판 견적 얼마예요?")
    said = [x.text for s in rep.sections for x in s.sentences]
    assert said[0].startswith("지금 믿집은 도배 · 목공만 금액을 계산해요")
    assert not [t for t in said if re.search(r"\d", t)] and rep.vendor


def test_general_floor_question_uses_verified_card():
    rep = expert("마루가 왜 들뜨는 거예요?")
    assert (
        rep.sections[0].source == "card" and "card:floor.defect.lifting-cause@1" in rep.used_cards
    )


def test_customer_told_family_is_remembered_and_used_for_fit():
    rep = expert("강아지 키우는데 마루 괜찮을까요?")
    assert rep.memory == {"floor.family": "반려동물"}
    said = " ".join(x.text for s in rep.sections for x in s.sentences)
    assert "말씀하신 조건(반려동물)" in said and rep.ask.slot == "floor.priority"


def test_defect_question_explains_without_judging_and_drafts_repair_request():
    rep = expert("마루가 들떴어요 하자인가요?")
    said = [x.text for s in rep.sections for x in s.sentences]
    assert any("단정하기는 어려워요" in t for t in said)
    assert any("보수" in v for v in rep.vendor)


def test_vendor_question_wording_and_after_work_wording():
    assert expert("바닥 업체 실측 올 때 뭘 물어보면 좋아요?").vendor
    rep = expert(
        "미장 끝나고 바로 마루 시공해도 되나요?"
    )  # 공사 전 이야기: 공사 뒤 체크리스트가 아니에요
    assert not any("끝나고 확인할 것" in s.title for s in rep.sections)


def test_new_floor_words_and_pet_question_reach_floor_expert():
    for q in (
        "LVT가 뭐예요?",
        "아이가 뛰는 소리 매트로 줄일 수 있어요?",
        "강아지가 마루에서 미끄러져요",
    ):
        assert "trade:floor" in turn(q).answer.trace.parts, q
    assert turn("오늘 점심 뭐 먹지").answer.trace.route == "out_of_scope"
    assert "trade:floor" not in turn("강아지 산책 몇 번 해요?").answer.trace.parts


# ---- 총괄: 넘겨주기 · 되묻기 · 대화 기억 ----
def test_fit_asks_one_condition_at_a_time_and_remembers():
    first = turn("우리 집에 맞는 바닥재 골라 줘")
    assert first.answer.trace.route == "trade" and first.answer.trace.parts == ["trade:floor"]
    assert first.answer.ask.slot == "floor.family"
    assert first.waiting == {
        "route": "trade", "trade": "floor", "slot": "floor.family", "q": "우리 집에 맞는 바닥재 골라 줘",
    }  # fmt: skip

    b = Button(route="trade", trade="floor", slot="floor.family", value="어린 아이")
    second = turn("어린 아이", memory=first.memory, waiting=first.waiting, button=b)
    assert second.memory["brief"] == {"floor.family": "어린 아이"}
    assert "장판(PVC 시트) 쪽이 잘 맞는 편이에요" in " ".join(sentences(second.answer))
    assert second.answer.ask.slot == "floor.priority"
    assert second.waiting["q"] == "우리 집에 맞는 바닥재 골라 줘"  # 원래 질문으로 이어 가요

    third = turn(
        "소음 줄이기", memory=second.memory, waiting=second.waiting
    )  # 버튼 없이 글로 답해도
    assert third.memory["brief"] == {"floor.family": "어린 아이", "floor.priority": "소음 줄이기"}
    assert third.answer.ask is None and third.waiting is None


def test_non_expert_trade_is_same_as_v3_turn():
    q = "실크 벽지랑 합지 벽지 차이가 뭐예요?"
    hub = turn(q)
    old = asyncio.run(v3_turn.run_turn(q, ctx(), kb=repo_kb()))
    assert hub.answer.model_dump() == old.answer.model_dump()
    assert hub.waiting == old.waiting


def test_multi_trade_splits_to_expert_and_v3_in_trade_order():
    res = turn("도배랑 마루 중에 뭘 먼저 해요?")
    tr = res.answer.trace
    assert tr.route == "multi" and "trade:floor" in tr.parts and "trade:dobae" in tr.parts
    titles = [s.title for s in res.answer.sections]
    assert any(t.startswith("[도배]") for t in titles) and any(
        t.startswith("[바닥]") for t in titles
    )
    first_dobae = next(i for i, t in enumerate(titles) if t.startswith("[도배]"))
    first_floor = next(i for i, t in enumerate(titles) if t.startswith("[바닥]"))
    assert first_dobae < first_floor  # 공정 순서: 도배 → 바닥


# ---- LLM 모드(스텁 대본) ----
def test_expert_llm_loop_checks_numbers_and_cites():
    llm.set_chat_script(
        [
            call("search_knowledge", query="강마루 들뜸"),
            call(
                "answer",
                2,
                sentences=[
                    {
                        "text": "강마루는 바닥에 붙여 소음 · 들뜸이 적은 편이에요.",
                        "cites": ["K218", "K99999"],
                    },
                    {"text": "시공비는 평당 7만 원이에요.", "cites": []},
                ],
                ask_slot="floor.family",
            ),
        ]
    )
    rep = expert("강마루 괜찮아요?", mode="llm")
    assert rep.how == "llm" and rep.prompts == ["floor_v1"]
    assert rep.tools == ["search_knowledge", "answer"]
    sec = rep.sections[0]
    assert sec.source == "llm" and [x.text for x in sec.sentences] == [
        "강마루는 바닥에 붙여 소음 · 들뜸이 적은 편이에요."
    ]  # 자료에 없는 숫자 문장은 빠져요
    assert "K99999" not in sec.sentences[0].cites  # 보이지 않은 근거 번호는 떼요
    assert rep.ask.slot == "floor.family"
    seen = llm.chat_seen()
    assert "바닥 전문가" in seen[0]["system"] and "answer" in seen[0]["tools"]


def test_inline_cite_marks_move_out_of_answer_text():
    llm.set_chat_script(
        [
            call("search_knowledge", query="마루 시공 뒤 확인"),
            call(
                "answer",
                2,
                sentences=[{"text": "계약한 제품이 맞는지 먼저 봐요. [K779]", "cites": []}],
            ),
        ]
    )
    rep = expert("마루 시공 끝나면 뭐 확인해야 해요?", mode="llm")
    assert rep.sections[0].sentences[0].text == "계약한 제품이 맞는지 먼저 봐요."
    s = split_cites("들떠요 [K12·K13] 그래서 (K1, K22)", ["K9"])
    assert s.text == "들떠요 그래서" and s.cites == ["K9", "K12", "K13", "K1", "K22"]
    assert split_cites("숫자 [1] 그대로", []).text == "숫자 [1] 그대로"


def test_expert_llm_failure_falls_back_to_offline():
    llm.set_chat_script([{"error": True}])
    rep = expert("강마루랑 강화마루 차이가 뭐예요?", mode="llm")
    assert rep.how == "offline" and any(c.kind == "compare" for c in rep.cards)


def test_expert_llm_tools_put_screen_pieces_without_rewrite():
    llm.set_chat_script(
        [
            call("remember_condition", key="floor.family", value="강아지를 키워요 반려동물"),
            call("add_checklist", 2, phase="before"),
            call("answer", 3, sentences=[{"text": "공사 전에 할 일을 정리했어요."}]),
        ]
    )
    rep = expert("강아지 키우는데 바닥 공사 전에 뭘 챙겨요?", mode="llm")
    assert rep.memory == {"floor.family": "반려동물"}
    assert [s.title for s in rep.sections] == ["[바닥]", "[바닥] 바닥 공사 전에 할 일"]


def test_concierge_llm_delegates_to_expert_and_writes_lead():
    llm.set_chat_script(
        [
            call("ask_expert", trade="floor", question="장판이랑 데코타일 뭐가 나아요?"),
            call(
                "answer", 2, sentences=[{"text": "데코타일은 긁힘에 강한 편이에요.", "cites": []}]
            ),  # 바닥 전문가 차례
            call("ask_expert", 3, trade="dobae", question="도배 먼저 해요?"),
            call(
                "finish",
                4,
                lead="도배를 먼저 하고 바닥을 깔면 돼요.",
                suggest=["바닥 공사 전에 할 일 알려 줘"],
            ),
        ]
    )
    res = turn("도배랑 바닥 둘 다 하는데 어떻게 진행해요?", mode="llm")
    ans = res.answer
    assert ans.trace.route == "multi" and ans.trace.parts == ["trade:floor", "trade:dobae"]
    assert ans.lead == "도배를 먼저 하고 바닥을 깔면 돼요."
    assert "concierge_v1" in ans.trace.prompts and "floor_v1" in ans.trace.prompts
    assert "데코타일은 긁힘에 강한 편이에요." in sentences(ans)


def test_concierge_llm_without_delegation_falls_back_to_v3():
    llm.set_chat_script([call("finish", lead="안녕하세요")])
    q = "처음인데 뭐부터 해요?"
    res = turn(q, mode="llm")
    old = asyncio.run(v3_turn.run_turn(q, ctx("llm"), kb=repo_kb()))
    assert res.answer.trace.route == old.answer.trace.route
    assert sentences(res.answer) == sentences(old.answer)


def test_concierge_lead_with_made_up_number_is_dropped():
    llm.set_chat_script(
        [
            call("ask_expert", trade="floor", question="장판 어때요?"),
            {"error": True},  # 바닥 전문가 LLM 실패 → 무료 모드 답
            call("finish", 3, lead="장판은 3일이면 끝나요."),
        ]
    )
    res = turn("처음인데 장판 깔려면 뭐부터 해요?", mode="llm")
    assert res.answer.lead == "" and res.answer.sections


def test_llm_request_is_built_through_real_sdk_path(monkeypatch):
    """네트워크 없이 실제 langchain_openai 경로로 요청을 만든다: 도구 스키마 · 메시지 순서 · 총괄 → 전문가 흐름."""
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "llm_live", True)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test-offline"))
    payloads: list[dict] = []
    replies = [
        ("ask_expert", {"trade": "floor", "question": "장판이랑 데코타일 뭐가 나아요?"}),
        ("compare_materials", {"materials": ["jangpan", "decotile"]}),
        ("answer", {"sentences": [{"text": "긁힘에 강한지부터 봐요.", "cites": []}]}),
        ("finish", {"lead": "바닥재는 비교표를 보고 고르면 돼요."}),
    ]

    async def fake(self, messages, stop=None, run_manager=None, **kwargs):
        payloads.append(self._get_request_payload(messages, stop=stop, **kwargs))
        name, args = replies.pop(0)
        msg = AIMessage(
            content="", tool_calls=[{"id": f"c{len(payloads)}", "name": name, "args": args}]
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    monkeypatch.setattr(ChatOpenAI, "_agenerate", fake)
    ans = turn("처음인데 바닥이랑 도배 다 하려면 바닥재는 뭐가 나아요?", mode="llm").answer
    assert replies == [] and len(payloads) == 4
    assert ans.lead == "바닥재는 비교표를 보고 고르면 돼요." and "trade:floor" in ans.trace.parts
    assert any(c.kind == "compare" for c in ans.cards)
    tools = {(t.get("function") or t)["name"] for t in payloads[1]["tools"]}
    assert {
        "search_knowledge",
        "compare_materials",
        "answer",
    } <= tools  # 전문가 차례에는 전문가 도구
    for p in payloads:
        for t in p["tools"]:
            schema = (t.get("function") or t)["parameters"]
            assert schema["type"] == "object" and "$ref" not in json.dumps(schema)


# ---- 런타임 ----
def test_budget_and_tool_guard():
    b = Budget(llm_calls=1, delegations=0)
    b.take_llm()
    with pytest.raises(BudgetExceeded):
        b.take_llm()
    with pytest.raises(BudgetExceeded):
        b.take_delegation()

    from pydantic import BaseModel, Field

    class Args(BaseModel):
        n: int = Field(ge=1)

    tool = Tool("count", "센다", Args, lambda r, a: ToolOut(text=f"ok {a.n}", refs=("K1",)))
    spec = AgentSpec(name="t", system="", tools=(tool,), finish=Tool("end", "끝", Args, tool.run))
    state = Run(reply=Reply(), budget=Budget())
    c = {"id": "1", "name": "count", "arguments": json.dumps({"n": 2})}
    assert asyncio.run(call_tool(spec, state, c)) == "ok 2" and state.shown == {"K1"}
    assert "이미 불렀어요" in asyncio.run(
        call_tool(spec, state, c)
    )  # 같은 도구 · 같은 인자는 한 번만
    bad = {"id": "2", "name": "count", "arguments": {"n": 0}}
    assert asyncio.run(call_tool(spec, state, bad)) == "인자가 맞지 않아요: n"
    assert "없는 도구" in asyncio.run(call_tool(spec, state, {"id": "3", "name": "nope"}))
    assert state.reply.tools == ["count"]
