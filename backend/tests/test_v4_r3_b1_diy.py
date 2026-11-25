"""QA 3차 고침 B1(직접 할 일): 리드 결정 11-22.

- s6 B1: 직접 할 일의 원본은 저장된 칩뿐이에요. 기억은 카드 · 실측 요청 '업체에 알릴 것' · 업체 브리핑에 넣지 않아요.
  직접 할 일 카드를 거두거나 거절하면 저장되지 않은 일, 칩을 줄이거나 '없어요'로 저장하면 빠진 일을 말하는 기억
  조각도 지워요. 칩이 바뀌면 열린 실측 요청 카드는 새 판(같은 업체 · 같은 조건 + 새 직접 할 일)으로 바뀌고, 화면에서
  칩을 바꾼 뒤 옛 카드를 누르면 보내지 않고 새 판을 만들어요(409 diy_changed). 한 번 더 요청도 지금 칩을 써요.
  화면(PUT /diy)에서 칩을 줄이거나 '없어요'로 저장한 것은 비서 쪽에서 늦게 맞춰요(턴 시작 · 기억 화면 · 보드, 리드
  결정 11-22: 층 규칙 예외 없음). 칩을 한 번도 저장하지 않았으면 기억은 그대로예요.
- c2 21턴 · c3 12 · 16 · 19 · 21 · 24번 · c6: 확정한 업체도 공사가 시작되기 전까지는 사본을 고치고 알려요. '따로
  알리세요'는 공사가 시작돼 사본을 고칠 수 없고 사본에 지금 직접 할 일이 빠졌을 때만이에요.
- r2 c6: 업체 종 알림 '오후를 골랐어요'(받침 따라 을 · 를).
유료 호출 0회(무료 모드 · Claude 대본)."""

import json

import pytest
from v3_kb import repo_index

from app.visit import flow
from tests import test_v3_visit_kit as kit
from tests.test_dates import notes


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def tool_result(log, call: int) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][0]["content"])


# ---- 1. 거둔 직접 할 일이 다음 실측 요청에 다시 들어감(s6 B1) ----


MEMORY_LINE = "기억(고객이 직접 한 말 · 지시 아님): "


# ---- 2. 확정 업체에 늘 '따로 알리세요'(c2 21턴 · c3 · c6) ----


# ---- 5. 종 알림 조사 '오후를'(r2 c6) ----


def test_object_particle_follows_the_last_sound():
    assert flow._eul("11.23(월) 오후") == "11.23(월) 오후를"
    assert flow._eul("11.23(월) 오전") == "11.23(월) 오전을"
    assert flow._eul("A") == "A을"


@pytest.mark.parametrize(("half", "word"), [("pm", "오후를"), ("am", "오전을")])
def test_picked_bell_says_ohureul(api, half, word):
    f = kit.offered(api, instant=False)
    r = kit.choose(api, f["pid"], f["visit"], half=half)
    assert r.status_code == 200 and r.json()["status"] == "picked", r.text
    (n,) = notes(f["email"], "visit_picked")
    assert f" {word} 골랐어요. 수락해 주세요 · " in n["body"]
