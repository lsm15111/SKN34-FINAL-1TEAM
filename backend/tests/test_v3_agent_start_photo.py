"""ChatGPT 비교(G1 · G6)에서 나온 고침: 처음 고객의 '뭐부터'는 가이드로, 사진 요청은 안내 한 줄 + 나머지 질문으로."""

import time

from app.agent.v3.gate import gate
from app.agent.v3.turn import PHOTO


def test_first_timer_start_question_goes_to_guide_even_with_a_trade_word():
    assert gate("34평 아파트 도배를 처음 해 보는데 뭐부터 해야 해요?").route == "guide"


def test_trade_method_order_stays_with_the_trade():
    assert gate("도배 작업 순서 알려 주세요").route == "trade"
    assert gate("몰딩 교체하고 도배도 하려는데 순서를 어떻게 해야 해요?").route == "multi"


def test_photo_phrase_is_removed_from_the_question():
    q = "곰팡이 핀 벽은 도배 전에 어떻게 처리하는지 사진으로 보여 줘"
    rest = PHOTO.sub(" ", q).strip()
    assert "사진" not in rest and "곰팡이" in rest
    assert PHOTO.search("몰딩 종류 이미지로 보여줄 수 있어?")
    assert not PHOTO.search("사진 찍어 두면 하자 접수에 도움 돼요?")


def test_photo_pattern_is_linear_on_long_spaces():
    t = time.perf_counter()
    PHOTO.search("사진" + " " * 50_000 + "x")
    assert time.perf_counter() - t < 0.5
