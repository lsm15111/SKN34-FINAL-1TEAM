"""v4 비서 턴 사실 정직(QA r1 '고칠 것' c1-3 · c3-1): '최근 처리한 카드'에 실행 못 한 카드(실패 · 실행 없이 닫힘)와
서버가 알린 까닭을 넣어 비서가 까닭을 지어내지 않게 한다('카드가 오래돼서' · '저장됐을 가능성이 커요'). 새 카드로 바뀐
카드는 넣지 않는다. 유료 호출 0회(Claude 대본)."""

import uuid
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import service
from tests.conftest import query
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_turns import ask, home, ok


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


def facts_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


def card(status: str, result: dict | None = None, error_code: str | None = None):
    return SimpleNamespace(
        status=status,
        result=result,
        error_code=error_code,
        summary={"title": "집 정보 저장"},
        kind="home_info",
    )


def test_decided_line_tells_why_a_card_did_not_run():
    line = service.decided_line(
        [
            card("expired", {"reason": "handled_elsewhere"}),
            card("failed", {"reason": "stalled"}, "stalled"),
            card("failed", {"reason": "quote_changed"}, "quote_changed"),
            card("expired", {"reason": "replaced"}),  # 새 카드로 바뀜: 넣지 않는다
            card("executed", {"text": "저장했어요."}),
        ]
    )
    assert line == (
        "최근 처리한 카드: "
        "집 정보 저장(실행 안 됨 · 닫힘 · 서버가 알린 까닭: 화면에서 이미 처리했거나 상태가 바뀐 제안이에요.)"
        " · 집 정보 저장(승인했지만 실행 못 함 · 서버가 알린 까닭: 실행하지 못한 제안이에요.)"
        " · 집 정보 저장(승인했지만 실행 못 함 · 서버가 알린 까닭: 업체가 견적서를 다시 올렸어요.)"
        " · 집 정보 저장(승인해 실행됨)"
    )


def test_closed_card_and_its_reason_reach_the_turn_facts(api, script):
    _, pid = home(api)
    script(
        [
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_home_info", "input": {"fields": {"rooms": 3}}}
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    (a,) = [x for x in acts(ok(ask(api, pid, "방은 세 개예요"))) if x["status"] == "proposed"]
    query(  # 정리(sweep)가 화면에서 처리된 것으로 닫았다
        "update assistant_actions set status = 'expired', result = '{\"reason\": \"handled_elsewhere\"}'"
        " where id = $1",
        uuid.UUID(a["action_id"]),
    )
    r = approve(api, a["action_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "action_closed"
    log = script([{"text": "카드가 닫혀서 저장되지 않았어요."}])
    ok(ask(api, pid, "눌렀는데 이미 처리했대요"))
    assert (
        "최근 처리한 카드: 집 정보 저장(실행 안 됨 · 닫힘 · 서버가 알린 까닭: "
        f"{r.json()['error']['message']})"
    ) in facts_of(log[0])
