"""v4 비서 턴 (/assistant/turns · /vendor/assistant/turns): SSE 순서 · seq · 저장 · 가림 · 같은 키 되돌림 ·
대화 잠금(409 turn_running) · 멈춘 턴 · 권한(404 · 403) · 무료 모드 · Claude 대본(도구 루프 · 상한 6 ·
같은 오류 두 번 · pause_turn · refusal · 두 번 실패 → 차단기 · 상한 넘음 → 무료). 유료 호출 0회."""

import json
import uuid
from datetime import timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy, runtime
from app.config import settings
from tests.conftest import query
from tests.helpers import make_admin, signup, use, vendor_signup
from tests.test_v3_project_home import HOME
from tests.test_vendor_profile import approved_vendor

PHONE_TEXT = "제 번호 010-1234-5678이고 101동 1203호예요. 오늘 뭐 하면 돼요?"


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    """시험 DB에는 지식 자료가 없어 운영과 같은 CSV 색인을 넘긴다(무료 답 파이프라인용)."""
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def events(body: str) -> list[tuple[str, dict, str | None]]:
    out = []
    for block in body.strip().split("\n\n"):
        f = {}
        for line in block.splitlines():
            k, _, v = line.partition(": ")
            f[k] = v
        if "event" in f:
            out.append((f["event"], json.loads(f["data"]), f.get("id")))
    return out


def home(api, email: str = "home@mitjip.test") -> tuple[str, str]:
    token = signup(api, email)
    r = api.post("/projects", json=HOME)
    assert r.status_code == 201, r.text
    return token, r.json()["id"]


def ask(api, pid: str, text: str = "오늘 뭐 하면 돼요?", key: str | None = None, **body):
    return api.post(
        "/assistant/turns",
        json={"project_id": pid, "client_key": key or uuid.uuid4().hex, "text": text, **body},
    )


def ok(r) -> list[tuple[str, dict, str | None]]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    ev = events(r.text)
    assert ev[0][0] == "ack" and ev[-1][0] in ("done", "error")
    seqs = [d["seq"] for _, d, _ in ev]
    assert seqs == list(range(1, len(ev) + 1))  # seq는 턴 안에서 1씩 는다
    turn = ev[0][1]["turn_id"]
    assert all(i == f"{turn}:{d['seq']}" for _, d, i in ev)
    return ev


def names(ev) -> list[str]:
    return [e for e, _, _ in ev]


def turn_row(turn_id: str) -> dict:
    return dict(query("select * from assistant_turns where id = $1", uuid.UUID(turn_id))[0])


def test_login_role_and_vendor_approval(api):
    assert ask(api, str(uuid.uuid4())).status_code == 401
    use(api, make_admin(api))
    assert ask(api, str(uuid.uuid4())).status_code == 403
    vendor_signup(api, email="wait@mitjip.test")  # 승인 전 업체
    assert api.get("/vendor/assistant/today").status_code == 403
    assert api.get("/vendor/assistant/today").json()["error"]["code"] == "vendor_not_approved"
    approved_vendor(api, "ok@mitjip.test")
    assert api.get("/vendor/assistant/today").status_code == 200
    assert ask(api, str(uuid.uuid4())).status_code == 403  # 업체가 고객 API
    _, pid = home(api)
    assert api.get("/vendor/assistant/today").status_code == 403  # 고객이 업체 API
    assert api.get("/assistant/feed", params={"project_id": pid}).status_code == 200


def test_free_turn_streams_cards_saves_masked_and_lists_only_in_assistant(api):
    _, pid = home(api)
    ev = ok(ask(api, pid, PHONE_TEXT))
    done = ev[-1][1]
    assert done["mode"] == "free" and done["rev"] == 2 and not done["stopped"]
    cards = [d for e, d, _ in ev if e == "card"]
    assert cards and cards[-1]["kind"] == "answer" and cards[-1]["data"]["src"] == "guide"
    assert set(done["cards"]) == {c["card_id"] for c in cards}
    t = turn_row(ev[0][1]["turn_id"])
    assert (t["status"], t["mode"], t["surface"], t["error_code"]) == (
        "done",
        "free",
        "customer",
        None,
    )
    assert t["ended_at"] is not None and json.loads(t["trace"])["rev"] == 1
    msgs = query("select role, text from chat_messages order by role desc")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert "010-1234-5678" not in msgs[0]["text"] and "1203" not in msgs[0]["text"]
    (c,) = query("select kind, project_id from chats")
    assert c["kind"] == "assistant" and str(c["project_id"]) == pid
    assert api.get("/ai/threads").json() == []  # v3 목록에는 ai 대화만
    # 대화 기록: 고객 말 + 비서 답(카드)
    feed = api.get("/assistant/feed", params={"project_id": pid}).json()
    assert [x["role"] for x in feed["items"]] == ["user", "assistant"]
    assert feed["items"][1]["parts"][-1]["card"]["kind"] == "answer" and feed["rev"] == 2
    assert feed["items"][0]["text"] == msgs[0]["text"]
    got = api.get(f"/assistant/turns/{ev[0][1]['turn_id']}").json()
    assert got["status"] == "done" and got["mode"] == "free" and got["cards"]
    latest = api.get("/assistant/threads/latest", params={"project_id": pid}).json()
    assert latest["chat_id"] == ev[0][1]["chat_id"] and latest["rev"] == 2


def test_same_client_key_replays_without_a_new_turn(api):
    _, pid = home(api)
    first = ok(ask(api, pid, key="same-key-1234"))
    again = ok(ask(api, pid, key="same-key-1234"))
    assert again[0][1]["turn_id"] == first[0][1]["turn_id"]
    assert names(again)[-1] == "done" and again[-1][1]["rev"] == first[-1][1]["rev"]
    assert len(query("select id from assistant_turns")) == 1
    assert len(query("select id from chat_messages")) == 2


def test_running_turn_locks_the_chat_until_it_stalls(api):
    _, pid = home(api)
    ev = ok(ask(api, pid))
    chat = uuid.UUID(ev[0][1]["chat_id"])
    uid = query("select user_id from assistant_turns")[0]["user_id"]
    query(
        "insert into assistant_turns (id, user_id, chat_id, surface, client_key, status, mode)"
        " values ($1, $2, $3, 'customer', 'running-key-1', 'running', 'llm')",
        uuid.uuid4(),
        uid,
        chat,
    )
    r = ask(api, pid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "turn_running"
    r = ask(api, pid, key="running-key-1")  # 같은 키가 도는 중이어도 409
    assert r.status_code == 409
    query(
        "update assistant_turns set heartbeat_at = now() - interval '3 minutes' where status = 'running'"
    )
    ok(ask(api, pid))  # 2분 넘게 멈춘 턴은 failed 'stalled'로 닫고 새 턴이 돈다
    stalled = query(
        "select status, error_code from assistant_turns where client_key = 'running-key-1'"
    )
    assert (stalled[0]["status"], stalled[0]["error_code"]) == ("failed", "stalled")


def test_others_project_and_turn_are_404(api):
    _, pid = home(api, "a@mitjip.test")
    ev = ok(ask(api, pid))
    _, mine = home(api, "b@mitjip.test")
    assert ask(api, pid).status_code == 404
    assert api.get("/assistant/feed", params={"project_id": pid}).status_code == 404
    assert api.get("/assistant/board", params={"project_id": pid}).status_code == 404
    assert api.get(f"/assistant/turns/{ev[0][1]['turn_id']}").status_code == 404
    assert api.get("/assistant/feed", params={"project_id": mine}).json()["items"] == []


def test_board_and_today_and_health(api):
    _, pid = home(api)
    b = api.get("/assistant/board", params={"project_id": pid})
    assert b.status_code == 200, b.text
    board = b.json()
    assert board["step"] in range(7) and board["confirmed"] is True
    assert board["project_name"] == "노원구 아파트 도배"
    assert any("노원구" in x for x in board["facts"]) and board["money"]["won"] > 0
    t = api.get("/assistant/today", params={"project_id": pid})
    assert t.status_code == 200, t.text and "todo" in t.json()
    h = api.get("/assistant/health").json()
    assert h == {"mode": "free", "reason": "off"}  # LLM_LIVE=false


# ---- Claude 대본(유료 호출 0회) ----


def test_llm_turn_runs_tools_checks_numbers_and_caches(api, script):
    _, pid = home(api)
    log = script(
        [
            {"tool_calls": [{"id": "t1", "name": "get_home", "input": {}}]},
            {
                "text": "노원구 집이에요. 공급 69.4㎡ 기준이에요. 2,000,000원이면 돼요. 제가 저장했어요."
            },
        ]
    )
    ev = ok(ask(api, pid, PHONE_TEXT))
    assert names(ev)[:4] == ["ack", "status", "card", "token"]
    assert ev[2][1]["kind"] == "home_info"
    text = "".join(d["text"] for e, d, _ in ev if e == "token")
    assert "69.4㎡" in text and "2,000,000" not in text and "저장했어요" not in text
    done = ev[-1][1]
    assert done["mode"] == "llm" and done["cards"] == ["home"]
    first, second = log
    assert first["model"] == "claude-sonnet-5-5"
    tools = [t["name"] for t in first["tools"]]
    assert tools == sorted(tools) and "cache_control" in first["tools"][-1]
    strict = {t["name"] for t in first["tools"] if t.get("strict")}  # 제안 도구만 엄격(20개 한도)
    assert strict and all(n.startswith("propose_") for n in strict)
    assert "propose_window_answer" not in tools  # 업체 도구는 고객 턴에 없다
    assert first["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert first["tool_choice"] == {"type": "auto"}
    user, facts = first["messages"][-2:]
    assert user["role"] == "user" and facts["role"] == "system" and "지금:" in facts["content"]
    assert "010-1234-5678" not in json.dumps(first, ensure_ascii=False)  # LLM 전에 가림
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "region" in result["content"]
    assert "owner" not in result["content"] and pid not in result["content"]  # id 없음
    t = turn_row(ev[0][1]["turn_id"])
    assert (t["mode"], t["tool_calls"]) == ("llm", 1)
    trace = json.loads(t["trace"])
    assert trace["llm"] == 2 and trace["tools"][0]["name"] == "get_home" and trace["tools"][0]["ok"]
    usage = query("select purpose, turn_id, ok from llm_usage order by created_at")
    assert [u["purpose"] for u in usage] == ["assistant", "assistant"]
    assert all(str(u["turn_id"]) == ev[0][1]["turn_id"] for u in usage)
    (saved,) = query("select text from chat_messages where role = 'assistant'")
    assert "2,000,000" not in saved["text"] and "69.4㎡" in saved["text"]


def test_tool_cap_six_then_wrap_up_once(api, script):
    _, pid = home(api)
    calls = [{"id": f"t{i}", "name": "get_home", "input": {}} for i in range(8)]
    log = script([{"tool_calls": calls}, {"text": "지금까지로 정리했어요."}])
    ev = ok(ask(api, pid))
    t = turn_row(ev[0][1]["turn_id"])
    assert t["tool_calls"] == policy.TOOL_MAX
    assert len(log) == 2 and len(log) <= policy.LLM_MAX
    results = log[1]["messages"][-1]["content"]
    errors = [r for r in results if r.get("is_error")]
    assert len(errors) == 2 and "tool_limit" in errors[0]["content"]
    assert results[-1] == {"type": "text", "text": runtime.WRAP}  # 마무리 한 번
    assert log[1]["tool_choice"] == {"type": "none"}
    assert ev[-1][1]["mode"] == "llm" and json.loads(t["trace"])["stop"] == "tools"


def test_llm_call_cap_eight_last_one_wraps_up(api, script):
    _, pid = home(api)
    pause = {"stop": "pause_turn", "text": ""}
    tool = {"tool_calls": [{"id": "t", "name": "show_card", "input": {"kind": "home_info"}}]}
    log = script([pause, pause, tool, tool, tool, tool, tool, {"text": "정리했어요."}, tool])
    ev = ok(ask(api, pid))
    assert len(log) == policy.LLM_MAX  # 8번째가 마지막(마무리) 호출
    assert log[-1]["tool_choice"] == {"type": "none"}
    assert log[-1]["messages"][-1]["content"][-1] == {"type": "text", "text": runtime.WRAP}
    t = turn_row(ev[0][1]["turn_id"])
    assert t["tool_calls"] == 5 and json.loads(t["trace"])["stop"] == "llm"
    assert names(ev)[-1] == "done"


def test_same_tool_error_twice_stops_with_a_fail_card(api, script):
    _, pid = home(api)
    bad = {"name": "propose_visit_slot", "input": {"slot_ref": "s9"}}
    log = script(
        [
            {"tool_calls": [{"id": "a", **bad}]},
            {"tool_calls": [{"id": "b", **bad}]},
            {"text": "다시 해 볼게요."},
        ]
    )
    ev = ok(ask(api, pid))
    assert len(log) == 2  # 두 번째 같은 오류 뒤 멈춤
    first_err = log[1]["messages"][-1]["content"][0]
    assert first_err["is_error"] and "unknown_ref" in first_err["content"]
    done = ev[-1][1]
    assert done["stopped"] is True
    fail = [d for e, d, _ in ev if e == "card" and d["card_id"].startswith("fail-")]
    assert fail and fail[0]["kind"] == "answer"
    assert fail[0]["data"]["text"].startswith("같은 문제가 두 번 나서 멈췄어요")
    assert turn_row(ev[0][1]["turn_id"])["status"] == "stopped"


def test_pause_turn_is_sent_again_without_a_new_user_message(api, script):
    _, pid = home(api)
    log = script([{"stop": "pause_turn", "text": "찾는 중이에요."}, {"text": "다 찾았어요."}])
    ev = ok(ask(api, pid))
    assert len(log) == 2
    assert log[1]["messages"][-1]["role"] == "assistant"  # 이어 보내기: 새 user 말 없음
    assert ev[-1][1]["mode"] == "llm"


def test_refusal_goes_free(api, script):
    _, pid = home(api)
    script([{"stop": "refusal", "text": "그건"}])
    ev = ok(ask(api, pid))
    assert ev[-1][1]["mode"] == "free"
    assert any(e == "card" and d["kind"] == "answer" for e, d, _ in ev)
    assert json.loads(turn_row(ev[0][1]["turn_id"])["trace"])["reason"] == "refusal"


def test_two_claude_failures_trip_the_breaker(api, script):
    _, pid = home(api)
    log = script([RuntimeError("down"), RuntimeError("down")])
    ev = ok(ask(api, pid))
    assert ev[-1][1]["mode"] == "free" and len(log) == 2
    log = script([])  # 차단기가 켜져 있으면 Claude를 부르지 않는다
    ev = ok(ask(api, pid))
    assert ev[-1][1]["mode"] == "free" and log == []
    # health는 차단기를 따로 알리지 않고 off로 묶어요(보안 I3, 화면에 필요한 값만)
    assert api.get("/assistant/health").json() == {"mode": "free", "reason": "off"}


def test_over_budget_answers_free_without_calling(api, script, monkeypatch):
    _, pid = home(api)
    monkeypatch.setattr(settings, "llm_cap_user_day_usd", 0.0)
    log = script([{"text": "부르면 안 돼요."}])
    ev = ok(ask(api, pid))
    assert ev[-1][1]["mode"] == "free" and log == []
    assert json.loads(turn_row(ev[0][1]["turn_id"])["trace"])["reason"] == "budget"


def test_card_choice_passes_only_known_refs(api, script):
    _, pid = home(api)
    log = script(
        [
            {"tool_calls": [{"id": "t", "name": "get_home", "input": {}}]},
            {"text": "확인했어요."},
        ]
    )
    ok(ask(api, pid))
    log = script([{"text": "골랐어요."}])
    ok(ask(api, pid, "이걸로 할게요", context={"card_id": "picks", "choice": ["v1", "s3"]}))
    sent = log[0]["messages"][-2]["content"][0]["text"]
    assert "카드에서 고름" not in sent  # 이번 대화에서 만든 적 없는 이름표는 버린다
    # 지난 턴 글(검사한 답)은 다음 턴 앞에 붙는다
    assert any(m["role"] == "assistant" for m in log[0]["messages"][:-2])


def test_vendor_turn_needs_own_visit(api, script):
    approved_vendor(api, "ok@mitjip.test")
    r = api.post(
        "/vendor/assistant/turns",
        json={"visit_id": str(uuid.uuid4()), "client_key": uuid.uuid4().hex, "text": "브리핑해 줘"},
    )
    assert r.status_code == 404
    script([{"text": "새 요청이 없어요."}])
    r = api.post(
        "/vendor/assistant/turns",
        json={"client_key": uuid.uuid4().hex, "text": "오늘 할 일 알려 줘"},
    )
    ev = ok(r)
    assert ev[-1][1]["mode"] == "llm"
    feed = api.get("/vendor/assistant/feed").json()
    assert [x["role"] for x in feed["items"]] == ["user", "assistant"]
    assert query("select surface from assistant_turns")[0]["surface"] == "vendor"


def test_stalled_sweep_closes_old_turns(api):
    import asyncio

    from app.assistant import service
    from app.shared.clock import now_utc

    _, pid = home(api)
    ev = ok(ask(api, pid))
    uid = query("select user_id from assistant_turns")[0]["user_id"]
    query(
        "insert into assistant_turns (id, user_id, chat_id, surface, client_key, status, mode,"
        " heartbeat_at) values ($1, $2, $3, 'customer', 'old-running-1', 'running', 'llm',"
        " now() - interval '10 minutes')",
        uuid.uuid4(),
        uid,
        uuid.UUID(ev[0][1]["chat_id"]),
    )
    got = asyncio.run(service.sweep(now_utc() + timedelta(seconds=1)))
    assert got["stalled"] == 1
