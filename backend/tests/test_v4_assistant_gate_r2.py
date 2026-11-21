"""v4 비서 문장 검사 고침 2차(QA r2 갈래 E1, 08-rules '덜 지우기'): 되풀이 빼기는 완전히 같은 끝 안내만(R3: 다시 물은
답 · 반대 뜻 문장은 둠) · 길이 상한은 아주 긴 답만, 묻는 말 · 다음 할 일 · 소개 · 비교 답은 남김(R4) · 정직한 한 줄은
확실히 틀릴 때만(R5: 이 턴에 보인 단추 카드 · 다른 종류 카드를 만든 턴은 그대로) · 업체가 한 일('결도배에서 견적서를
보냈어요')은 사실 전달로 둠(R9) · 모델에만 줄 도구 hint · 이름표 · 안쪽 이름이 고객 답에 나오지 않음(M3).
DB 없는 문장 검사."""

import asyncio

import pytest

from app.assistant import policy
from app.assistant.runtime import claims_done, recent_ends
from app.assistant.schemas import CardOut
from tests.test_v4_assistant_talk import gate
from tests.test_v4_assistant_talk import run as run_gate

# ---- R3: 되풀이 빼기 ----


def test_answer_asked_again_is_not_dropped_as_a_repeat():
    ends = recent_ends(
        [
            {"role": "user", "content": "공사 언제 시작해요?"},
            {"role": "assistant", "content": "확정 공정표를 봤어요. 공사는 12월 14일에 시작해요."},
        ]
    )
    g, sent = gate("12월 14일 2026-12-14", ends=ends)
    run_gate(g, "다시 알려 드릴게요. 공사는 12월 14일에 시작해요.")  # 고객: '언제 시작한다고요?'
    assert sent == ["다시 알려 드릴게요.", " 공사는 12월 14일에 시작해요."]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("폐기물 처리는 포함이에요.", "폐기물 처리는 불포함이에요."),
        ("이번 주 토요일 오전 실측은 가능해요.", "이번 주 토요일 오전 실측은 불가능해요."),
        ("철거 비용이 들어 있어요.", "철거 비용이 안 들어 있어요."),
        ("토요일 오전으로 잡았어요.", "토요일 오후로 잡았어요."),
        ("이번 주 토요일에 와요.", "이번 주 일요일에 와요."),
        ("실측 요청 카드를 확인하고 눌러 주세요.", "실측 시간 카드를 확인하고 눌러 주세요."),
    ],
)
def test_opposite_or_other_kind_words_are_not_the_same_line(a, b):
    assert not policy.same_line(a, b)


def test_changed_fact_at_the_end_is_sent():
    g, sent = gate(ends=["이번 주 토요일 오전 실측은 가능해요."])
    run_gate(g, "업체 답을 다시 봤어요. 이번 주 토요일 오전 실측은 불가능해요.")
    assert sent == ["업체 답을 다시 봤어요.", " 이번 주 토요일 오전 실측은 불가능해요."]


def test_same_nag_at_the_end_is_still_dropped():
    nag = "결도배 실측 승인 카드를 확인하고 눌러 주세요."
    g, sent = gate(ends=[nag])
    run_gate(g, f"콘센트는 전기 공사업체가 옮겨요. {nag}", opened={"visit_slot"})
    assert sent == ["콘센트는 전기 공사업체가 옮겨요."]


# ---- R4: 길이 상한 ----


def test_review_examples_are_not_cut_any_more():
    """리뷰 R4의 네 문장 답(끝이 묻는 말 · 부탁)은 상한 안이라 그대로 간다."""
    g, sent = gate("34")
    run_gate(
        g,
        "34평이면 표준견적서를 바로 볼 수 있어요. 실크벽지 기준이에요. "
        "업체 추천도 이어서 볼 수 있어요. 실측은 무슨 요일이 편하세요?",
    )
    assert sent[-1] == " 실측은 무슨 요일이 편하세요?" and len(sent) == 4
    g, sent = gate()
    run_gate(g, "좋아요. 도배 범위를 정할게요. 방 수가 맞는지 볼게요. 편한 요일을 알려 주세요.")
    assert sent == [
        "좋아요.",
        " 도배 범위를 정할게요.",
        " 방 수가 맞는지 볼게요.",
        " 편한 요일을 알려 주세요.",
    ]


def test_very_long_answer_keeps_questions_and_next_steps():
    g, sent = gate()
    run_gate(
        g,
        "하나예요. 둘이에요. 셋이에요. 넷이에요. 다섯이에요. 여섯이에요. "
        "업체 카드에서 골라 주세요. 덧붙이는 말이에요. 실측은 무슨 요일이 편하세요? 편한 시간도 알려 주세요.",
    )
    assert sent[6:] == [
        " 업체 카드에서 골라 주세요.",
        " 실측은 무슨 요일이 편하세요?",
        " 편한 시간도 알려 주세요.",
    ]
    assert g.cut == 1 and "길이 상한" in g.dropped


def test_vendor_or_compare_card_answer_is_not_cut():
    """업체 소개 · 견적 비교 카드를 보인 턴의 답은 카드를 풀어 말해 길어도 줄이지 않는다."""
    g, sent = gate()
    eight = (
        "하나예요. 둘이에요. 셋이에요. 넷이에요. 다섯이에요. 여섯이에요. 일곱이에요. 여덟이에요."
    )

    async def go():
        await g.feed("하나예요. 둘이에요. 셋이에요. 넷이에요. 다섯이에요. 여섯이에요. 일곱이에요.")
        await g.shown(CardOut(card_id="compare-dobae", kind="quote_compare", data={"cols": []}))
        await g.feed(" 여덟이에요.")
        await g.flush()
        await g.settle()

    asyncio.run(go())
    assert "".join(sent) == eight and g.cut == 0


# ---- R5: 정직한 한 줄 ----


def test_press_words_for_a_pick_card_shown_this_turn_stay():
    g, sent = gate()

    async def go():
        await g.shown(CardOut(card_id="picks-dobae", kind="vendor_picks", data={"picks": []}))
        await g.feed("마음에 드는 업체를 골라 카드에서 눌러 주세요.")
        await g.flush()
        await g.settle()

    asyncio.run(go())
    assert sent == ["마음에 드는 업체를 골라 카드에서 눌러 주세요."]


def test_made_words_of_another_kind_stay_when_a_card_was_made():
    """이 턴에 승인 카드를 만들었으면 종류 낱말이 어긋나도 확실히 틀린 말이 아니라 그대로 둔다."""
    g, sent = gate()

    async def go():
        await g.feed("토요일 오전으로 실측 요청 카드를 만들었어요. 카드를 확인해 주세요.")
        await g.flush()
        await g.cards({"visit_slot"}, fresh=True)
        await g.settle()

    asyncio.run(go())
    assert sent == ["토요일 오전으로 실측 요청 카드를 만들었어요.", " 카드를 확인해 주세요."]


def test_card_words_are_replaced_only_when_surely_wrong():
    g, sent = gate()
    run_gate(g, "실측 요청 카드를 만들었어요. 카드를 확인하고 눌러 주세요. 기다릴게요.")
    assert sent == [policy.CARD_NOT_MADE, " 기다릴게요."]  # 만든 카드도 누를 것도 없다
    g, sent = gate()
    run_gate(g, "카드에서 수락을 눌러 주세요.", opened={"visit_slot"})
    assert sent == [
        "카드에서 수락을 눌러 주세요."
    ]  # 누를 승인 카드가 있다(단추 이름은 따지지 않는다)


# ---- R9: 업체가 한 일 ----


@pytest.mark.parametrize(
    ("text", "claimed"),
    [
        ("결도배에서 견적서를 보냈어요.", False),
        ("업체에서 공사 날짜를 보냈어요.", False),
        ("제가 화면에서 저장했어요.", True),
        ("카드에서 저장했어요.", True),
        ("믿집에서 요청을 보냈어요.", True),
    ],
)
def test_vendor_did_it_is_a_fact(text, claimed):
    assert claims_done(text) is claimed


# ---- M3: 도구 hint · 이름표 · 안쪽 이름 ----


def test_tool_hint_and_inside_names_are_not_shown():
    g, sent = gate("7")
    g.hint("고객이 이번에 한 말 그대로 note에 넣어요.")  # 도구 오류 hint(모델에만)
    run_gate(
        g,
        "업체를 찾지 못했어요. 고칠 방법은 도구 결과에 나온 이름표만 넘기는 거예요. "
        "v7 업체는 이 대화에 없어요. 고객이 이번에 한 말 그대로 넣어야 해요. "
        "vendor_ref 칸이 필요해요. 다시 골라 주세요.",
    )
    assert sent == ["업체를 찾지 못했어요.", " 다시 골라 주세요."]
    assert {"이름표", "안쪽 이름", "도구 안내 글"} <= set(g.dropped)


@pytest.mark.parametrize(
    "text",
    ["공급 84 m2 기준이에요.", "84㎡ 기준이에요.", "LED 조명이에요.", "2층 2호선 근처예요."],
)
def test_plain_words_are_not_inside_names(text):
    assert policy.inside(text) is None
