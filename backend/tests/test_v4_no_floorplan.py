"""도면 빼기(11-22 밤, 사용자 '도면은 받는 거에서 빼 줘'): 기본 정보 받기에서 도면을 뺀다.

- 고객 비서 도구 목록에 평면도 찾기(find_floorplan_docs)가 없고, 불러도 '쓸 수 없는 도구'다(코드는 다시 켤 때를 위해 둔다).
- 내 공사 보드는 '대표 평면 · 예시'를 보이지 않는다(plan_example false).
"""

import pytest

from app.assistant import tools
from app.assistant.tools import ToolError
from tests.test_v4_assistant_turns import home


def test_floorplan_tool_is_off_for_the_assistant():
    names = [d["name"] for d in tools.defs("customer")]
    assert "find_floorplan_docs" not in names
    # 다른 도구는 그대로
    assert {"recommend_vendors", "get_home", "propose_home_info"} <= set(names)
    with pytest.raises(ToolError) as e:
        tools.get("find_floorplan_docs", "customer")
    assert e.value.code == "unknown_tool"


def test_board_shows_no_plan_example(api):
    _, pid = home(api, "nofloor@mitjip.test")
    board = api.get("/assistant/board", params={"project_id": pid})
    assert board.status_code == 200, board.text
    assert board.json()["plan_example"] is False
