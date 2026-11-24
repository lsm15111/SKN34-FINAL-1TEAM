"""QA r7 고침 B 2(c1 28 · 29턴): 공사 전 할 일 카드가 '벽 앞 가구 옮기기'를 고객 몫으로 적어 표준견적서 짐 할증 · '실측 때
업체와 가구 이동을 정해요'와 어긋났고, 두 번 말한 강아지 줄도 없었어요. 가구 · 짐은 누가 옮길지 업체와 정하는 일로,
기억에 반려동물이 있으면 맡길 곳 · 냄새 · 문 열림 줄을 더해요. 유료 호출 0회."""

import uuid

import pytest
from v3_kb import repo_index

from app.agent.v3.trades import BY_CODE
from app.assistant.tools import aftercare, cards
from tests.helpers import signup
from tests.test_v3_project_home import HOME
from tests.test_v4_assistant_diy import TODAY, as_owner, remember

FURNITURE_DEAL = "벽 앞 가구 · 짐을 누가 옮길지 업체와 채팅으로 정하기"
SMALL_STUFF = "공사할 방의 작은 짐 · 귀중품은 미리 치워 두기"
OLD = ("벽 앞 가구 옮기기", "공사할 방의 짐 · 가구 정리하기")


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def labels(card) -> list[str]:
    return [x["label"] for x in card.data["checklist"]]


def test_furniture_moving_is_settled_with_the_vendor_not_put_on_the_customer():
    assert FURNITURE_DEAL in BY_CODE["dobae"].prep and SMALL_STUFF in BY_CODE["common"].check_before
    lived = labels(aftercare.check_card("b", "before", ["dobae"], [], home=cards.HomeCtx()))
    assert FURNITURE_DEAL in lived and SMALL_STUFF in lived
    assert not set(OLD) & set(lived)
    # 가구를 말하는 줄은 모두 업체와 정하는 줄이에요(고객이 옮기라는 줄 없음)
    assert all("업체" in x for x in lived if "가구" in x)
    # 전날 준비물도 같은 줄, 빈 집이면 짐 · 가구 줄이 모두 빠져요
    eve = labels(cards.prep_card("p", ["dobae"], cards.HomeCtx()))
    assert FURNITURE_DEAL in eve and not set(OLD) & set(eve)
    empty = labels(
        aftercare.check_card("b", "before", ["dobae"], [], home=cards.HomeCtx(occupied=False))
    )
    assert not any("가구" in x or "짐" in x for x in empty)


def test_pet_memory_adds_leave_smell_and_open_door_lines():
    home = cards.HomeCtx(occupied=True, pet=True)
    card = aftercare.check_card("b", "before", ["dobae"], [], home=home)
    assert cards.PET_ITEM in labels(card) and cards.PET_DOOR_ITEM in labels(card)
    assert cards.PET_LINE in card.data["lines"]
    said = f"{cards.PET_LINE} {cards.PET_ITEM} {cards.PET_DOOR_ITEM}"
    assert all(w in said for w in ("맡길", "냄새", "현관 · 방문이 열려도"))
    eve = cards.prep_card("p", ["dobae"], home)
    assert {cards.PET_ITEM, cards.PET_DOOR_ITEM} <= set(labels(eve))
    # 기억에 반려동물이 없거나 빈 집이면 반려동물 줄은 없어요
    for h in (cards.HomeCtx(), cards.HomeCtx(occupied=False, pet=True)):
        got = aftercare.check_card("b", "before", ["dobae"], [], home=h)
        assert not [x for x in labels(got) if "반려동물" in x]
        assert cards.PET_LINE not in got.data["lines"]


def test_week_before_card_of_a_lived_in_home_whose_dog_is_remembered(api):
    """c1: 사는 집 · 강아지 기억 → 공사 전 할 일 카드에 가구는 업체와 정하기 · 반려동물 줄."""
    signup(api, "dog@mitjip.test")
    r = api.post("/projects", json={**HOME, "occupied": True})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    remember(api, pid, "pet", "강아지")
    card = as_owner(api, pid, lambda s, u: aftercare.prep_card(s, u, uuid.UUID(pid), TODAY))
    got = labels(card)
    assert FURNITURE_DEAL in got and not set(OLD) & set(got)
    assert cards.PET_ITEM in got and cards.PET_DOOR_ITEM in got
    assert cards.PET_LINE in card.data["lines"]
