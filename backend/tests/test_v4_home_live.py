"""보드가 지금 집 정보 카드 값(home)을 같이 보낸다: 대화의 집 정보 카드가 보낸 때 값이 아니라 이 값으로 그려서, 저장 ·
고치기(보드 · 카드의 모달) 뒤 바로 바뀐다(2026-11-23 사용자 '화면에 바로 반영되지 않아'). 유료 호출 0회."""

from tests.test_v3_project_home import HOME
from tests.test_v4_assistant_turns import home


def board(api, pid: str) -> dict:
    r = api.get("/assistant/board", params={"project_id": pid})
    assert r.status_code == 200, r.text
    return r.json()


def test_board_carries_the_live_home_card_and_follows_edits(api):
    _, pid = home(api)
    b = board(api, pid)
    h = b["home"]
    assert h["facts"] == b["facts"]  # 보드 '우리 집' 줄과 카드 줄은 같은 값
    assert h["area"] == {"m2": "69.4", "basis": "supply", "pyeong": h["area"]["pyeong"]}
    assert (h["locked"], h["changes"], h["action_id"], h["saved"]) == (False, [], None, False)

    # 기본 정보를 고치면(보드 · 카드의 '우리 집 정보' 모달이 같은 PATCH를 써요) 다음 보드 읽기에 바로 새 값
    r = api.patch(f"/projects/{pid}", json={**HOME, "area_m2": "84.9", "occupied": True})
    assert r.status_code == 200, r.text
    after = board(api, pid)["home"]
    assert after["area"]["m2"] == "84.9"
    assert "살면서 공사" in after["facts"] and "빈 집" not in after["facts"]
    assert after["facts"] != h["facts"]
