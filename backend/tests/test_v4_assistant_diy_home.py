"""v4 비서 집 정보 승인 카드로 직접 할 일(반셀프 칩) 바꾸기. 유료 호출 0회(Claude 대본)."""

import pytest

from app.agent import llm
from tests.conftest import query
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_turns import ask, home, ok


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def test_home_info_card_changes_diy_without_rev(api, script):
    _, pid = home(api)
    rev = api.get(f"/projects/{pid}").json()["rev"]
    script(
        [
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_home_info",
                        "input": {"fields": {"diy": ["outlet", "paint"]}},
                    }
                ]
            },
            {"text": "카드를 확인하고 눌러 주세요."},
        ]
    )
    ev = ok(ask(api, pid, "문틀 페인트랑 콘센트 커버는 제가 할게요"))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert a["summary"]["rows"] == [
        {
            "label": "직접 할 일",
            "value": "페인트(문틀 · 몰딩) · 콘센트 · 스위치 커버",
            "sub": "지금 없음",
        }
    ]
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    rows = query("select key, value from project_conditions where key like 'diy.%' order by key")
    assert [(x["key"], x["value"]) for x in rows] == [("diy.outlet", "self"), ("diy.paint", "self")]
    assert api.get(f"/projects/{pid}").json()["rev"] == rev  # 표준견적서 칸이 아니라 판은 그대로

    # 같은 목록이면 바뀐 칸이 없어요(카드를 만들지 않음)
    script(
        [
            {
                "tool_calls": [
                    {
                        "id": "q",
                        "name": "propose_home_info",
                        "input": {"fields": {"diy": ["paint", "outlet"]}},
                    }
                ]
            },
            {"text": "이미 그렇게 저장돼 있어요."},
        ]
    )
    ev = ok(ask(api, pid, "페인트랑 콘센트는 제가 해요"))
    assert not [x for x in acts(ev) if x["status"] == "proposed"]
