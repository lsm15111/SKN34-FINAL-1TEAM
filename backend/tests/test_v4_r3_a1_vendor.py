"""고침 3차 A1(QA r3 c6 업체): 업체 턴 사실에 요청 건수와 요청마다 지금 상태, 카드가 어느 요청 것인지, 새 카드로 바뀌어
닫힌 카드. 유료 호출 0회(Claude 대본).

- T3: '고객이 고른 반나절은 세 건'이라 하고 한 건만 말함 · 다른 요청(c6c)의 못 받아요를 이 요청(c6a)에 붙임.
- T12 · T13: 새 카드로 바뀌어 닫힌 카드를 '아직 남아 있을 수 있어요' · '따로 누르지 않으셔도 돼요'.
- T16 · T17 · T20: 턴 사실의 '서버가 알린 까닭'을 그대로 옮겨 '서버가'라고 말함.
"""

import pytest
from v3_kb import repo_index

from app.agent import llm
from tests.test_v3_visit_kit import add, customer, requested, visit_of
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_free import vendor_turn
from tests.test_v4_assistant_turns import ok
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


def facts_of(req: dict) -> str:
    return next(m["content"] for m in req["messages"] if m["role"] == "system")


def test_vendor_facts_count_requests_and_tie_cards_to_their_request(api, script):
    f = requested(api)  # 노원구 고객 → 마루와벽
    _, pid2 = customer(api, "home2@mitjip.test", sgg="도봉구")
    assert add(api, pid2, f["vendor"]).status_code == 201
    assert ask_visits(api, pid2, [f["vendor"]]).status_code == 201
    other = visit_of(pid2, f["vendor"])
    login(api, f["email"])
    # 화면 브리핑 카드가 도봉구 요청에 기간 답하기 제안을 연다
    assert api.post(f"/vendor/assistant/briefs/{other}").status_code == 200
    log = script(
        [
            {
                "tool_calls": [
                    {
                        "id": "d",
                        "name": "propose_decline",
                        "input": {"visit_ref": "m1", "code": "other"},
                    }
                ]
            },
            {"text": "못 받아요 카드를 만들었어요."},
        ]
    )
    ev = ok(vendor_turn(api, other, "이건 못 받겠어요"))
    facts = facts_of(log[0])
    assert "지금 보는 요청: m1(도봉구 32평 도배)" in facts
    assert "요청: 2건 · 노원구 32평 도배 새 실측 요청(기간 답하기 · " in facts
    assert " / 도봉구 32평 도배 새 실측 요청(기간 답하기 · " in facts
    assert "승인 기다리는 카드: 이 기간으로 답하기 · 도봉구 32평 도배" in facts
    (no,) = [a for a in acts(ev) if a["kind"] == "decline" and a["status"] == "proposed"]
    assert approve(api, no["action_id"], prefix="/vendor/assistant").status_code == 200
    log = script([{"text": "네, 노원구 요청만 남았어요."}])
    ok(vendor_turn(api, f["visit"], "남은 요청 뭐예요?"))
    facts = facts_of(log[0])
    assert "지금 보는 요청: m2(노원구 32평 도배)" in facts
    assert "요청: 1건 · 노원구 32평 도배 새 실측 요청" in facts
    # 다른 요청(도봉구)의 못 받아요 · 새 카드로 바뀌어 닫힌 기간 답하기 카드가 어느 요청 것인지 보인다
    assert "이번 요청 못 받아요 · 도봉구 32평 도배(승인해 실행됨)" in facts
    assert (
        "이 기간으로 답하기 · 도봉구 32평 도배(실행 안 됨 · 닫힘 · 까닭: 새 카드로 바뀐 제안이에요.)"
        in facts
    )
    assert "서버가" not in facts
