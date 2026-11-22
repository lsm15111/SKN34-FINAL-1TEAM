"""말풍선 나누기(11-22 밤, 사용자 '응 말풍선 나누기 넣어줘'): 피클처럼 생각 덩어리마다 말풍선을 나눈다.

- 문장 검사: 모델이 쓴 빈 줄(말풍선 나눔)을 빈 줄로 지킨다(글 조각 경계에서 나뉘어도). 줄 바꿈 · 문장 끝 빈칸은 그대로.
  도구 뒤 글은 새 말풍선(빈 줄)으로 연다. 정직한 한 줄(CUT_TEXT · FAIL_TEXT)도 따로 한 말풍선이다.
- 지시문 쪽 시험은 test_v4_bubbles_prompt.py.
DB · LLM 없음."""

import asyncio

from app.assistant import runtime
from tests.test_v4_r4_g_gate import gate, run

FIRST = "세 곳을 골라 왔어요!"
MID = "값을 먼저 보시려면 결도배가 잘 맞아요."
LAST = "어느 곳에 실측을 요청할까요?"


def feed_all(g, *blocks: list[str]) -> str:
    """턴처럼: 블록마다 글 조각을 차례로 넣고, 블록 사이(도구 부르는 자리)와 끝에서 flush."""

    async def go():
        for chunks in blocks:
            for c in chunks:
                await g.feed(c)
            await g.flush()
        await g.settle()

    asyncio.run(go())
    return g.text


def test_spacing_kinds():
    assert runtime.spacing(" ") == " "
    assert runtime.spacing("  ") == " "
    assert runtime.spacing("\n") == "\n"
    assert runtime.spacing("\n\n") == "\n\n"
    assert runtime.spacing("\n\n\n\n") == "\n\n"


def test_blank_lines_are_kept_as_bubble_breaks():
    text = f"{FIRST}\n\n{MID}\n\n{LAST}"
    assert run(gate(), text) == text


def test_line_breaks_and_spaces_stay_as_they_were():
    text = f"{FIRST} {MID}\n{LAST}"
    assert run(gate(), text) == text


def test_many_newlines_become_one_blank_line():
    assert run(gate(), f"{FIRST}\n\n\n\n{MID}") == f"{FIRST}\n\n{MID}"


def test_blank_line_split_across_stream_chunks():
    assert feed_all(gate(), [f"{FIRST}\n", f"\n{MID}"]) == f"{FIRST}\n\n{MID}"
    assert feed_all(gate(), [f"{FIRST}\n", "\n", f"{MID}"]) == f"{FIRST}\n\n{MID}"
    assert feed_all(gate(), [f"{FIRST}\n", f"{MID}"]) == f"{FIRST}\n{MID}"


def test_text_after_a_tool_opens_a_new_bubble():
    assert (
        feed_all(gate(), ["좋아요, 바로 볼게요."], [f"{FIRST} {LAST}"])
        == f"좋아요, 바로 볼게요.\n\n{FIRST} {LAST}"
    )
    # 도구 뒤 글이 줄 바꿈으로 시작해도 빈 줄 하나
    assert (
        feed_all(gate(), ["좋아요, 바로 볼게요."], [f"\n\n{FIRST}"])
        == f"좋아요, 바로 볼게요.\n\n{FIRST}"
    )
    # 도구 앞에 보낸 글이 없으면 빈 줄 없이 시작
    assert feed_all(gate(), [""], [FIRST]) == FIRST


def test_honest_line_is_its_own_bubble():
    got = run(gate(), "실리콘 값은 1,234,567원이에요. 메뉴의 [채팅]에서 직접 보내 주세요.")
    assert got == f"메뉴의 [채팅]에서 직접 보내 주세요.\n\n{runtime.CUT_TEXT}"
