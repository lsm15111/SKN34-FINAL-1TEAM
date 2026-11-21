"""v4 비서 말 길이 · 되풀이(QA r1 '고칠 것' c1-5 · c2-6 · c3-5 · c5-1, 08-rules '줄일 것'): 아주 긴 답만 줄인다 · 앞
여섯 문장(500자)까지 바로 보내고 넘친 문장은 묻는 말 · 다음 할 일만 턴 끝에 보낸다 · 끝 안내가 지난 두 비서 턴의 끝
문장과 완전히 같으면 뺀다(그 문장뿐이면 둔다, 이 턴에 만든 · 보인 카드를 가리키면 새 안내) · 한 턴 안 같은 문장은
한 번 · 숫자 검사 · 카드 말 검사는 그대로. DB 없는 문장 검사 + Claude 대본 턴(유료 호출 0회)."""

import asyncio
import json
import uuid

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy
from app.assistant.runtime import SentenceGate, recent_ends
from tests.conftest import query
from tests.test_v4_assistant_offers import tokens
from tests.test_v4_assistant_turns import ask, home, ok

PROMPT = "너는 믿집 비서야."
NAG = "지금은 카드에 있는 결도배 실측 승인 카드를 확인하고 눌러 주세요."


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


def gate(allowed: str = "", **kw) -> tuple[SentenceGate, list[str]]:
    sent: list[str] = []

    async def emit(name: str, data: dict) -> None:
        assert name == "token"
        sent.append(data["text"])

    return SentenceGate(emit, PROMPT, allowed, **kw), sent


def run(g: SentenceGate, *chunks: str, opened: set[str] | None = None) -> None:
    async def go():
        g.opened |= opened or set()
        for c in chunks:
            await g.feed(c)
        await g.flush()
        await g.settle()

    asyncio.run(go())


# ---- 길이 (DB 없음) ----


SIX = ["하나예요.", " 둘이에요.", " 셋이에요.", " 넷이에요.", " 다섯이에요.", " 여섯이에요."]


def test_very_long_answer_keeps_the_lead_then_next_steps():
    g, sent = gate("3,300,000 2026-12-14")
    run(
        g,
        "결도배가 3,300,000원으로 더 싸요. 철거 포함 여부가 달라요. 보증 기간도 달라요. ",
        "부가세 방식도 견줘 보세요. 폐기물 처리도 달라요. 공사 기간도 달라요. ",
        "견적 비교 카드에서 포함 항목을 볼 수 있어요. 유효기간도 짧아요.",
    )
    assert sent == [
        "결도배가 3,300,000원으로 더 싸요.",
        " 철거 포함 여부가 달라요.",
        " 보증 기간도 달라요.",
        " 부가세 방식도 견줘 보세요.",
        " 폐기물 처리도 달라요.",
        " 공사 기간도 달라요.",
        " 견적 비교 카드에서 포함 항목을 볼 수 있어요.",  # 넘친 둘 중 '다음 할 일'
    ]
    assert g.text == "".join(sent) and g.cut == 1 and "길이 상한" in g.dropped


def test_answers_up_to_six_sentences_are_not_cut():
    g, sent = gate()
    run(g, "".join(SIX))
    assert sent == SIX and g.cut == 0 and "길이 상한" not in g.dropped


def test_overflow_without_a_next_step_sends_nothing_more():
    g, sent = gate()
    run(g, "".join(SIX) + " 일곱이에요. 여덟이에요.")
    assert sent == SIX and g.cut == 2


def test_long_sentences_stop_at_the_char_cap():
    long1 = "가" * 300 + "예요."
    long2 = "나" * 250 + "예요."
    g, sent = gate()
    run(g, f"{long1} {long2} 셋째 문장이에요. 카드에서 볼 수 있어요.")
    assert sent == [
        long1,
        f" {long2}",
        " 카드에서 볼 수 있어요.",
    ]  # 500자를 넘으면 뒤는 묻는 말 · '다음 할 일'만


def test_checks_run_before_the_cap():
    """숫자 검사 · 한 일처럼 말함으로 빠진 문장은 바로 보낼 몫을 쓰지 않는다."""
    g, sent = gate("3,388,000")
    run(
        g,
        "견적은 3,388,000원이에요. 사실 2,000,000원이면 돼요. 마루와벽으로 제가 확정했어요. "
        "포함 항목이 달라요. 기간도 달라요. 보증도 달라요. 부가세도 달라요. 폐기물도 달라요. "
        "카드에서 볼 수 있어요.",
    )
    assert sent == [
        "견적은 3,388,000원이에요.",
        " 포함 항목이 달라요.",
        " 기간도 달라요.",
        " 보증도 달라요.",
        " 부가세도 달라요.",
        " 폐기물도 달라요.",
        " 카드에서 볼 수 있어요.",
    ]


def test_tail_card_words_must_be_true():
    """넘친 문장의 '눌러 주세요'는 누를 것이 있을 때만 끝 문장이 된다(아니면 정직한 한 줄도 내지 않는다)."""
    g, sent = gate()
    run(g, "".join(SIX) + " 승인 카드를 확인하고 눌러 주세요.")
    assert sent == SIX
    g, sent = gate()
    run(g, "".join(SIX) + " 승인 카드를 확인하고 눌러 주세요.", opened={"visit_slot"})
    assert sent[-1] == " 승인 카드를 확인하고 눌러 주세요."


def test_same_sentence_twice_in_one_turn_goes_once():
    g, sent = gate()
    run(g, "카드에서 볼 수 있어요. 카드에서 볼 수 있어요! 다른 말이에요.")
    assert sent == ["카드에서 볼 수 있어요.", " 다른 말이에요."] and "같은 문장" in g.dropped


# ---- 되풀이 (DB 없음) ----


def test_end_sentence_same_as_last_turns_is_dropped():
    g, sent = gate(ends=[NAG])
    run(g, f"콘센트 위치는 전기 공사업체가 옮겨요. {NAG}", opened={"visit_slot"})
    assert sent == ["콘센트 위치는 전기 공사업체가 옮겨요."]
    assert "지난 턴과 같은 끝 문장" in g.dropped and g.cut == 1


def test_repeat_in_the_middle_stays_and_alone_stays():
    g, sent = gate(ends=[NAG])
    run(g, f"{NAG} 콘센트는 전기 공사업체 일이에요.", opened={"visit_slot"})
    assert sent == [NAG, " 콘센트는 전기 공사업체 일이에요."]  # 끝 문장이 아니면 순서대로 보낸다
    g, sent = gate(ends=[NAG])
    run(g, NAG, opened={"visit_slot"})
    assert sent == [NAG]  # 그 문장뿐이면 둔다


def test_card_made_or_shown_this_turn_is_new_guidance():
    g, sent = gate(ends=["카드를 확인하고 눌러 주세요."], made={"visit_request"})
    run(g, "실측 요청 카드를 만들었어요. 카드를 확인하고 눌러 주세요.")
    assert sent == ["실측 요청 카드를 만들었어요.", " 카드를 확인하고 눌러 주세요."]


def test_near_same_and_numbers():
    # 되풀이 빼기는 완전히 같은 문장만(띄움 · 문장부호만 다름, 08-rules): 낱말이 하나라도 다르면 다른 말이다
    assert not policy.same_line(NAG, NAG.replace("지금은 ", "")) and policy.same_line("네.", "네!")
    assert not policy.same_line(
        "결도배 실측 승인 카드를 확인하고 눌러 주세요.",
        "마루와벽 실측 승인 카드를 확인하고 눌러 주세요.",
    )
    assert not policy.same_line("합계는 3,300,000원이에요.", "합계는 3,465,000원이에요.")
    assert policy.next_step("공사 날짜 카드에서 수락을 눌러 주세요.")
    assert not policy.next_step("도배는 보통 이틀 걸려요.")


def test_recent_ends_reads_the_last_two_answers():
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "옛 답이에요. 옛 끝이에요."},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "첫 문장이에요.\n둘째 끝이에요."},
        {"role": "user", "content": "c"},
        {"role": "assistant", "content": "(카드를 보여 줬어요: 업체 추천)"},
    ]
    assert recent_ends(history) == ["둘째 끝이에요."]  # 카드만 보낸 턴은 끝 문장이 없다
    assert recent_ends(history[:4]) == ["옛 끝이에요.", "둘째 끝이에요."]


# ---- 턴 (Claude 대본) ----


def test_turn_trims_a_long_answer_and_a_repeated_ending(api, script):
    _, pid = home(api)
    long = (
        "도배 전에 짐을 옮겨요. 콘센트 커버는 떼어 둬요. 바닥 보양은 업체가 해요. "
        "강아지는 다른 방에 둬요. 창문은 닫아 둬요. 엘리베이터 보양도 업체가 해요. "
        "공사 전 할 일 카드에서 하나씩 확인해 보세요. 고마워요."
    )
    script([{"text": long}])
    # 대화 첫 답(소개 · 첫인사)은 줄이지 않는다
    assert tokens(ok(ask(api, pid, "안녕하세요"))) == long
    script([{"text": long}])
    ev = ok(ask(api, pid, "공사 전에 뭐 해요?"))
    first = tokens(ev)
    assert first == (
        "도배 전에 짐을 옮겨요. 콘센트 커버는 떼어 둬요. 바닥 보양은 업체가 해요. "
        "강아지는 다른 방에 둬요. 창문은 닫아 둬요. 엘리베이터 보양도 업체가 해요. "
        "공사 전 할 일 카드에서 하나씩 확인해 보세요."
    )
    (saved,) = query(
        "select text from chat_messages where role = 'assistant' order by created_at desc limit 1"
    )
    assert saved["text"] == first  # 저장한 답 = 보낸 글(다음 턴 LLM이 읽는다)
    t = query("select trace from assistant_turns where id = $1", uuid.UUID(ev[0][1]["turn_id"]))
    assert json.loads(t[0]["trace"])["cut"] == 1
    script(
        [{"text": "관리사무소에 공사 신고를 해요. 공사 전 할 일 카드에서 하나씩 확인해 보세요."}]
    )
    again = tokens(ok(ask(api, pid, "또 뭐가 있어요?")))
    assert again == "관리사무소에 공사 신고를 해요."  # 앞 턴과 같은 끝 문장은 뺀다
