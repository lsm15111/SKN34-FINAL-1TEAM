"""v4 고침 갈래 FA1(QA r6 c1 H2): 거절 직후 '아 그냥 그거 다시 해 줘'가 막히던 것. 다시 해 달라는 뜻은 모델이 제안 도구의
asked_again으로 정하고, 코드는 이번 턴 고객 말이 있는지 · 거절한 같은 제안인지만 봐요. 카드는 여전히 고객이 눌러야
실행돼요(고정 선 1). 유료 호출 0회(Claude 대본)."""

import json

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import tools as tools_mod
from tests.test_v3_visit_kit import customer, quiet, vendor
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_turns import ask, ok


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


def tool_result(log, call: int) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


def proposed(ev) -> list[dict]:
    return [x for x in acts(ev) if x["status"] == "proposed"]


def test_every_propose_tool_takes_asked_again_and_read_tools_do_not():
    for t in tools_mod.REGISTRY.values():
        props = t.schema.get("properties", {})
        if t.kind == "propose":
            assert props.get("asked_again", {}).get("type") == "boolean", t.name
            # 꼭 넣는 칸(선택 칸이면 엄격 도구 선택 칸 합이 Claude 한도 24를 넘어 400)
            assert "asked_again" in t.schema.get("required", []), t.name
        else:
            assert "asked_again" not in props, t.name
    # Claude 엄격 꼴로 바꿔도(제안 도구만 strict) 칸이 그대로 남아요
    got = llm.to_claude_tools(tools_mod.defs("customer"))
    req = next(x for x in got if x["name"] == "propose_visit_request")
    assert req["strict"] is True and "asked_again" in req["input_schema"]["properties"]


def request_turn(again: bool | None) -> list[dict]:
    args = {"trade": "dobae", "vendor_refs": ["v1"]}
    if again is not None:
        args["asked_again"] = again
    return [
        {"tool_calls": [{"id": "p", "name": "propose_visit_request", "input": args}]},
        {"text": "결도배 실측 요청 카드를 확인해 주세요."},
    ]


def test_rejected_request_is_made_again_when_the_customer_asks_back(api, script, monkeypatch):
    quiet(monkeypatch)
    vendor(api, "gyeol@mitjip.test", "결도배")
    _, pid = customer(api)
    first = [
        {"tool_calls": [{"id": "r", "name": "recommend_vendors", "input": {"trade": "dobae"}}]},
        *request_turn(None),
    ]
    script(first)
    (a,) = proposed(ok(ask(api, pid, "결도배에 실측 요청해 줘")))
    assert api.post(f"/assistant/actions/{a['action_id']}/reject").json()["status"] == "rejected"
    # 모델이 asked_again을 켜지 않으면(비서가 스스로 다시 권함) 거절한 같은 제안은 다시 밀지 않아요
    log = script(request_turn(None))
    assert proposed(ok(ask(api, pid, "아 그냥 그거 다시 해 줘"))) == []
    note = tool_result(log, 1)
    assert note["state"] == "rejected" and "asked_again=true" in note["note"]
    # 고객 말을 읽은 모델이 켜면 같은 내용으로 새 승인 카드(낱말 규칙에 없는 말이어도)
    script(request_turn(True))
    (b,) = proposed(ok(ask(api, pid, "실수로 거절했어요 다시 해 줘요")))
    assert b["kind"] == "visit_request" and b["action_id"] != a["action_id"]
    r = approve(api, b["action_id"], seen=b["target_ver"])  # 실행은 고객이 눌러야
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text


def test_asked_again_does_not_leak_to_the_next_call_in_the_turn(api, script, monkeypatch):
    """한 턴에 제안 도구를 두 번 부르면 asked_again은 그 부름에만 붙어요(두 번째 부름은 꺼져 있으면 막혀요)."""
    quiet(monkeypatch)
    vendor(api, "gyeol@mitjip.test", "결도배")
    _, pid = customer(api)
    script(
        [
            {"tool_calls": [{"id": "r", "name": "recommend_vendors", "input": {"trade": "dobae"}}]},
            *request_turn(None),
        ]
    )
    (a,) = proposed(ok(ask(api, pid, "결도배에 실측 요청해 줘")))
    assert api.post(f"/assistant/actions/{a['action_id']}/reject").json()["status"] == "rejected"
    on = {"trade": "dobae", "vendor_refs": ["v1"], "asked_again": True}
    off = {"trade": "dobae", "vendor_refs": ["v1"]}
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "p1", "name": "propose_visit_request", "input": off},
                    {"id": "p2", "name": "propose_visit_request", "input": on},
                ]
            },
            {"text": "카드를 확인해 주세요."},
        ]
    )
    (b,) = proposed(ok(ask(api, pid, "그거 다시 해 줘요")))
    results = [json.loads(x["content"]) for x in log[1]["messages"][-1]["content"]]
    assert [x["state"] for x in results] == ["rejected", "new"]
    assert b["action_id"] != a["action_id"]
