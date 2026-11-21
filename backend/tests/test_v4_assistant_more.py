"""v4 비서 남은 칸: 철거 범위(demolition → 리모델링 기준) · done.suggest · status.task · 보드 금액 범위 ·
업체 브리핑 AI 한 문장(Haiku, 실패하면 틀) · 답 엔진 고르기(ASSISTANT_ANSWER_ROUTE, v2.ask.answer_only ·
v2+v3 넘기기). 유료 호출 0회(Claude 대본)."""

import asyncio
import json
import uuid

import asyncpg
import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy
from app.assistant.tools import answer
from app.config import settings
from tests.conftest import query
from tests.test_v3_visit_kit import add, customer, vendor, visit_of
from tests.test_v3_visit_kit import ask as request_visits
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_visit_inbox import login


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def dobae(pid: str, api) -> dict:
    st = api.get(f"/projects/{pid}/standard").json()
    return next(t for t in st["trades"] if t["trade"] == "dobae") | {"price_ver": st["price_ver"]}


# ---- 철거 범위 ----


def test_full_demolition_via_home_info_switches_to_remodel(api, script):
    _, pid = home(api)
    before = dobae(pid, api)
    assert before["profile"] == "paper_only"
    script(
        [
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_home_info",
                        "input": {"fields": {"demolition": "full"}},
                    }
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "전체 철거하고 할 거예요"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert a["summary"]["rows"] == [
        {"label": "철거 범위", "value": "전체 철거", "sub": "지금 없음"}
    ]
    assert "리모델링 기준" in a["summary"]["note"]
    card = next(d for e, d, _ in ev if e == "card" and d["kind"] == "home_info")
    assert card["data"]["changes"] == [
        {"label": "철거 범위", "before": "없음", "after": "전체 철거"}
    ]
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    (c,) = query("select key, value from project_conditions")
    assert (c["key"], c["value"]) == ("demolition", "full")
    assert api.get(f"/projects/{pid}").json()["rev"] == 1  # 집 정보 칸은 그대로(rev 안 오름)
    after = dobae(pid, api)
    assert (after["profile"], after["version"]) == ("remodel", before["version"] + 1)
    assert after["notes"][0].startswith("리모델링 기준으로 셌어요(근거: 전체 철거)")
    # 집 정보 카드 · 모은 조건 칩(화면 말)
    script([{"tool_calls": [{"id": "h", "name": "get_home", "input": {}}]}, {"text": "네."}])
    ev = ok(ask(api, pid, "집 정보 보여 줘"))
    card = next(d for e, d, _ in ev if e == "card" and d["kind"] == "home_info")
    assert card["data"]["demolition"] == "full" and "전체 철거" in card["data"]["facts"]
    conds = api.get(f"/projects/{pid}/conditions").json()
    assert conds == [
        {"trade": "dobae", "key": "demolition", "label": "철거 범위", "value": "전체 철거"}
    ]
    assert api.delete(f"/projects/{pid}/conditions/demolition").status_code == 200
    assert dobae(pid, api)["profile"] == "paper_only"


def test_demolition_value_is_checked_by_db(api):
    _, pid = home(api)
    with pytest.raises(asyncpg.CheckViolationError):
        query(
            "insert into project_conditions (id, project_id, trade, key, value)"
            " values (gen_random_uuid(), $1::uuid, 'dobae', 'demolition', '전체')",
            pid,
        )
    for v in ("full", "partial", "none"):
        query(
            "insert into project_conditions (id, project_id, trade, key, value)"
            " values (gen_random_uuid(), $1::uuid, 'dobae', 'demolition', $2)"
            " on conflict (project_id, key) do update set value = excluded.value",
            pid,
            v,
        )
    assert dobae(pid, api)["profile"] == "paper_only"  # 부분 · 안 함은 신호가 아니다


# ---- done.suggest · status.task · 보드 금액 범위 ----


def two_requested(api) -> tuple[str, list[str]]:
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    _, pid = customer(api)
    for v in (a, b):
        assert add(api, pid, v).status_code == 201
    r = request_visits(api, pid, [a, b])
    assert r.status_code == 201, r.text
    return pid, [visit_of(pid, a), visit_of(pid, b)]


def test_done_suggest_task_and_board_range(api, script):
    pid, visits = two_requested(api)
    script(
        [
            {"tool_calls": [{"id": "t", "name": "today_tasks", "input": {}}]},
            {"text": "업체 답을 기다리고 있어요."},
        ]
    )
    ev = ok(ask(api, pid, "오늘 뭐 하면 돼요?"))
    task = next(d["task"] for e, d, _ in ev if e == "status" and d.get("task"))
    assert task["task_id"] == "visits" and task["title"] == "실측 요청 2곳"
    assert {r["label"] for r in task["rows"]} == {"마루와벽", "결도배"}
    assert {r["state"] for r in task["rows"]} == {"waiting"} and task["state"] == "waiting"
    done = ev[-1][1]
    assert 1 <= len(done["suggest"]) <= 3
    assert all({"id", "text", "why", "say"} <= set(x) for x in done["suggest"])
    assert len({x["say"] for x in done["suggest"]}) == len(done["suggest"])
    assert not {x["say"] for x in done["suggest"]} & set(done["chips"])
    # 보드: 확정 전 업체 금액 범위(요청 때 고정한 가견적)
    totals = sorted(
        r["estimate_total"]
        for r in query(
            "select estimate_total from visits where id = any($1::uuid[])",
            [uuid.UUID(v) for v in visits],
        )
    )
    board = api.get("/assistant/board", params={"project_id": pid}).json()
    assert board["money"]["range"] == [totals[0], totals[-1]]


# ---- 업체 브리핑 한 문장 ----


def test_vendor_brief_sentence_ai_then_cache_and_template(api, script):
    from app import queue

    _, visits = two_requested(api)
    login(api, "maru@mitjip.test")
    url = f"/vendor/assistant/briefs/{visits[0]}"
    plain = api.get(url).json()["sentence"]  # 꺼짐: 틀(코드 값만)
    assert plain.endswith("요.") and ("빈 반나절" in plain or "맞지 않아요" in plain)
    log = script([{"json": {"text": "노원구 도배 요청이에요. 답하기 좋은 기간이 있어요."}}])
    got = api.get(url).json()["sentence"]
    assert got == "노원구 도배 요청이에요. 답하기 좋은 기간이 있어요."
    sent = json.dumps(log, ensure_ascii=False)
    assert log[0]["model"] == "claude-haiku-5-5" and "김믿집" not in sent  # 고객 이름 없음
    log = script([])  # 같은 사실이면 하루 캐시(부르지 않음)
    assert api.get(url).json()["sentence"] == got and log == []
    api.portal.call(queue.redis.flushdb)
    script([{"json": {"text": "이 요청은 99칸이 비어 있어 바로 수락돼요."}}])  # 사실에 없는 숫자
    assert api.get(url).json()["sentence"] == plain  # 검사에 걸리면 틀


# ---- 답 엔진 고르기 ----


def test_engine_for_route_setting():
    assert answer.engine_for("price", "v3") == "v3"
    assert answer.engine_for("general", "v2") == "v2"
    assert answer.engine_for("price", "price=v2,material=v2") == "v2"
    assert answer.engine_for("process", "price=v2,material=v2") == "v3"
    assert answer.engine_for("process", "*=v2,price=v3") == "v2"
    assert answer.engine_for("price", "price=v9") == "v3"
    assert answer.engine_for("price", "") == "v3"
    assert answer.engine_for("general", "v2+v3") == "v2+v3"
    assert answer.engine_for("price", "price=v2+v3") == "v2+v3"
    assert answer.engine_for("material", "price=v2+v3") == "v3"


def test_answer_question_goes_to_v2_when_routed(api, script, monkeypatch):
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", "price=v2")
    call = {
        "id": "q",
        "name": "answer_question",
        "input": {"question": "도배 기간은요?", "kind": "price"},
    }
    log = script(
        [
            {"tool_calls": [call]},
            {"text": "도배는 보통 하루이틀 걸려요."},  # v2 답(서버 도구만)
            {"text": "도배는 보통 하루이틀 걸려요."},
        ]
    )
    ev = ok(ask(api, pid, "도배 기간은요?"))
    assert ev[-1][1]["mode"] == "llm" and len(log) == 3
    v2_req = log[1]
    assert {t["name"] for t in v2_req.get("tools", [])} <= {"price_reference", "search_knowledge"}
    result = log[2]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and '"route": "v2"' in result["content"]
    # v3(기본)이면 v2를 부르지 않는다(LLM 호출 두 번)
    monkeypatch.setattr(settings, "assistant_answer_route", "v3")
    log = script([{"tool_calls": [call]}, {"text": "확인했어요."}])
    ok(ask(api, pid, "도배 기간은요?"))
    assert len(log) == 2


def _intent(label: str):
    from app.agent.schemas import Intent

    return Intent(label=label, confidence=0.9, source="model")


def test_hybrid_picks_engine(monkeypatch):
    """v2+v3 길 고르기(LLM · DB 없음): 범위 안이면 v2, 범위 밖이고 v3가 답하면 v3, v3도 못 하면 v2 안내."""
    from app.agent import gate as agent_gate
    from app.assistant.tools import ToolOut
    from app.v2 import ask as v2_ask

    calls: list[str] = []
    got = {"label": "trade", "answered": True}

    async def classify(message, waiting=None):
        return None if got["label"] is None else _intent(got["label"])

    async def v2(tc, q):
        calls.append("v2")
        return ToolOut(data={"route": "v2", "answer": policy.data("v2 답"), "found": True})

    async def v3(tc, q):
        calls.append("v3")
        out = ToolOut(data={"route": "trade", "answer": policy.data("v3 답"), "found": True})
        return out, got["answered"]

    monkeypatch.setattr(agent_gate, "classify", classify)
    monkeypatch.setattr(answer, "_v2_answer", v2)
    monkeypatch.setattr(answer, "_v3_answer", v3)

    def run() -> tuple:
        calls.clear()
        d = asyncio.run(answer._hybrid(None, "질문")).data
        return (*calls, d["engine"], d["v2_out"], d["route"])

    assert run() == ("v2", "v2", False, "v2")
    got["label"] = None  # 관문이 못 정하면 범위 밖이 아니에요(v2)
    assert run() == ("v2", "v2", False, "v2")
    got["label"] = "out_of_scope"  # v2 LLM은 부르지 않아요
    assert run() == ("v3", "v3", True, "trade")
    got["answered"] = False
    assert run() == ("v3", "v2", True, "out_of_scope")
    d = asyncio.run(answer._hybrid(None, "질문")).data
    assert d["answer"] == policy.data(v2_ask.OUT_TEXT) and d["found"] is True


def test_answer_question_hybrid_route(api, script, monkeypatch):
    """v2+v3 길(실제 v3 무료 답 · Claude 대본): 기록 칸(engine · v2_out)은 모델에 가지 않아요."""
    from app.agent import gate as agent_gate
    from app.v2 import ask as v2_ask

    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", "v2+v3")
    got = {"label": "out_of_scope"}

    async def classify(message, waiting=None):
        return _intent(got["label"])

    monkeypatch.setattr(agent_gate, "classify", classify)

    def turn(q: str) -> tuple[int, str]:
        call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": "general"}}
        log = script([{"tool_calls": [call]}, {"text": "확인했어요."}, {"text": "확인했어요."}])
        ok(ask(api, pid, q))
        last = log[-1]["messages"][-1]["content"][0]
        assert last["type"] == "tool_result"
        return len(log), last["content"]

    n, res = turn("베란다 탄성코트 꼭 해야 해요?")  # 범위 밖 · v3 알아 두기 → v3 근거(LLM 2번)
    assert n == 2 and "탄성코트" in res and '"route": "trade"' in res
    assert "engine" not in res and "v2_out" not in res
    n, res = turn("오늘 점심 뭐 먹지?")  # 범위 밖 · v3도 범위 밖 안내 → v2 안내 그대로
    assert n == 2 and v2_ask.OUT_TEXT in res and '"route": "out_of_scope"' in res
    got["label"] = "trade"
    n, res = turn("도배 기간은요?")  # 범위 안 → v2 답(LLM 3번)
    assert n == 3 and '"route": "v2"' in res
