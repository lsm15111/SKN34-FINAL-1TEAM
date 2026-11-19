"""관문 낱말 고침(agent-coverage 5장 2 · 6 · 8 · 10): 작업 대상 문 · 오타 · 영어 · 실측 일정 · 모델명 · 후기 좋은 곳."""

import time

import pytest

from app.agent.v3.gate import gate
from app.agent.v3.policy import calc_request, policy_of
from app.agent.v3.trades import trades_in


def test_door_of_a_room_is_carpentry_not_bath():
    assert trades_in("화장실 문 교체하려면 어떻게 해요?")[0] == "mokgong"
    assert "mokgong" not in trades_in("화장실 문제 생기면 어떻게 해요?")


@pytest.mark.parametrize(
    ("q", "code"),
    [("wallpaper 바꾸고 싶어요", "dobae"), ("도베 비용", "dobae"), ("걸래받이 높이", "mokgong")],
)
def test_typo_and_english_words(q, code):
    assert trades_in(q)[:1] == [code]


def test_visit_when_goes_to_schedule_with_a_project():
    assert gate("실측은 언제 와요?", has_project=True).route == "schedule"
    assert gate("실측은 언제 와요?").route == "guide"  # 내 공사가 없으면 시작 순서 안내


def test_model_name_and_review_rank_are_policy_flags():
    assert "brand_reco" in policy_of("실크벽지 모델명 하나만 알려 주세요")
    assert "vendor_reco" in policy_of("후기 좋은 업체 이름 알려줘")
    assert calc_request("타일 얼마 나올지 계산해 줘")


def test_new_rules_are_linear_on_long_spaces():
    for head in ("실측", "후기", "얼마", "화장실"):
        t = time.perf_counter()
        gate(head + " " * 40_000 + "x")
        assert time.perf_counter() - t < 1.0
