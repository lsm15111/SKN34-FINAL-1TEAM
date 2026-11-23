"""v4 비서 고침 4차 G(문장 검사 다듬기, QA r4 c2 · c5 · s4 · s5).

1. 묶음 안 한 문장이 검사로 빠지면 가리키는 말이 수를 말할 때('세 가지예요')만 묶음째 빼고, 아니면 그 문장만 뺀다(줄
   머리 기호 · 따옴표는 이웃 문장이 이어받고 번호는 다시 매김). 본문이 빠져 남은 글이 없거나 가리키는 말뿐이면 정직한 한 줄.
2. 카드 · 채팅을 가리키는 안내와 '오면 알려 드릴게요' 약속은 숫자가 있어도 되풀이를 보고, 같은 카드(읽히는 종류 · 대상)를
   새 대상 없이 다시 가리키면 뺀다. 금액 · 날짜를 물은 턴의 사실 답 · 카드를 물은 턴의 안내 · 새 소식 · 이 턴 카드는 둔다.
3. 앞날 · 조건에 맞춰 누르라는 말('견적서가 오면 … 눌러 주세요')은 누를 카드가 없어도 정직한 한 줄로 바꾸지 않는다.
4. 어림은 반올림 단위의 반 안(만 원 단위 ±5,000원 · 10만 원 단위 ±50,000원, 백만 자리 이상은 3%만).
DB 없는 문장 검사 + Claude 대본 턴(유료 호출 0회)."""

import asyncio
import json

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy, runtime
from app.assistant.runtime import SentenceGate, recent_said
from app.v2 import guard
from tests.test_v4_assistant_offers import tokens
from tests.test_v4_assistant_turns import ask, home, ok, turn_row

PROMPT = "너는 믿집 비서야."


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


def gate(allowed: str = "", **kw) -> SentenceGate:
    async def emit(name: str, data: dict) -> None:
        assert name == "token"

    return SentenceGate(emit, PROMPT, allowed, **kw)


def run(g: SentenceGate, text: str, opened: set[str] | None = None, cards: bool = False) -> str:
    """턴처럼: 글 → 블록 끝 → 정리(settle) → 본문이 빠졌으면 정직한 한 줄(mend)."""

    async def go():
        g.opened |= opened or set()
        await g.feed(text)
        await g.flush()
        await g.settle()
        await g.mend(cards)

    asyncio.run(go())
    return g.text


def said(*answers: str) -> list[str]:
    """지난 비서 답들(오래된 것부터) → 되풀이 견줄 문장."""
    history = []
    for a in answers:
        history += [{"role": "user", "content": "물음"}, {"role": "assistant", "content": a}]
    return recent_said(history)


# ---- 1. 묶음 안 한 줄만 빼기 · 정직한 한 줄 ----

DRAFT = (
    "실리콘은 직접 하신다고 이렇게 보내 보세요.\n"
    '"사장님, 안녕하세요. 실리콘 작업은 제가 직접 하려고 해요. 실리콘 값 1,234,567원은 제가 따로 내요. '
    '시공 범위에서 실리콘은 빼 주세요. 감사합니다."\n'
    "믿집은 대신 보내지 못해서, 메뉴의 [채팅]에서 직접 보내 주세요."
)


def test_one_failed_line_in_a_draft_drops_only_that_line():
    """QA r4 c2 15턴: 초안 다섯 문장 중 한 문장이 숫자 검사에 걸려 초안이 통째로 사라짐 → 네 문장 남는다."""
    g = gate()
    got = run(g, DRAFT)
    assert got == (
        "실리콘은 직접 하신다고 이렇게 보내 보세요.\n"
        '"사장님, 안녕하세요. 실리콘 작업은 제가 직접 하려고 해요. 시공 범위에서 실리콘은 빼 주세요. 감사합니다."\n'
        "믿집은 대신 보내지 못해서, 메뉴의 [채팅]에서 직접 보내 주세요."
    )
    assert "묶음째 뺌" not in g.dropped and g.cut == 0
    assert runtime.CUT_TEXT not in got  # 본문이 남았다


def test_failed_first_or_last_line_hands_over_the_quote():
    """줄을 연 문장이 빠지면 줄 바꿈 · 여는 따옴표를, 닫는 문장이 빠지면 닫는 따옴표를 이웃 문장이 받는다."""
    first = DRAFT.replace('"사장님, 안녕하세요.', '"사장님, 1,234,567원 안녕하세요.').replace(
        " 실리콘 값 1,234,567원은 제가 따로 내요.", ""
    )
    got = run(gate(), first)
    assert '보내 보세요.\n"실리콘 작업은 제가 직접 하려고 해요.' in got
    assert got.count('"') == 2
    last = DRAFT.replace("감사합니다.", "1,234,567원 감사합니다.").replace(
        " 실리콘 값 1,234,567원은 제가 따로 내요.", ""
    )
    got = run(gate(), last)
    assert '실리콘은 빼 주세요."\n믿집은' in got and got.count('"') == 2


def test_counted_pointer_still_drops_the_whole_group():
    """'세 가지예요'처럼 수를 말하면 한 줄만 빠져도 묶음째 뺀다(수가 틀리지 않게, 고침 3차 A2 그대로)."""
    g = gate()
    got = run(g, "준비물은 세 가지예요.\n- 사포\n- 젯소 1,234,567원\n- 붓\n그다음 칠하면 돼요.")
    assert got == "그다음 칠하면 돼요." and "묶음째 뺌" in g.dropped
    # 머리 없는 목록: 바로 앞 문장이 수를 말하면 묶음째, 아니면 걸린 줄만
    g = gate()
    got = run(g, "준비물이 다섯 개 필요해요.\n- 사포\n- 젯소 1,234,567원\n- 붓\n그다음 칠하세요.")
    assert got == "준비물이 다섯 개 필요해요.\n그다음 칠하세요."
    g = gate()
    got = run(g, "준비물을 챙겨 두세요.\n- 사포\n- 젯소 1,234,567원\n- 붓\n그다음 칠하세요.")
    assert got == "준비물을 챙겨 두세요.\n- 사포\n- 붓\n그다음 칠하세요."


def test_numbers_are_renumbered_after_a_dropped_row():
    got = run(gate(), "순서는 이래요.\n1. 짐을 빼요.\n2. 1,234,567원을 내요.\n3. 말려요.")
    assert got == "순서는 이래요.\n1. 짐을 빼요.\n2. 말려요."


def test_honest_line_when_nothing_or_only_pointers_are_left():
    """다 빠지면 정해 둔 한 줄, 남은 것이 가리키는 말(카드 · 채팅 단추)뿐이면 끝에 붙인다. 카드가 있는 턴은 FAIL_TEXT."""
    g = gate()
    assert run(g, "실리콘 값은 1,234,567원이에요.") == runtime.CUT_TEXT
    g = gate()
    got = run(
        g,
        '이렇게 보내 보세요.\n"실리콘 값 1,234,567원은 제가 내요."\n메뉴의 [채팅]에서 직접 보내 주세요.',
    )
    # 정직한 한 줄은 따로 한 말풍선
    assert got == f"메뉴의 [채팅]에서 직접 보내 주세요.\n\n{runtime.CUT_TEXT}"
    assert "가리킨 말 없음" in g.dropped
    g = gate()
    assert run(g, "실리콘 값은 1,234,567원이에요.", cards=True) == runtime.FAIL_TEXT


def test_no_honest_line_when_a_body_is_left_or_only_noise_was_dropped():
    g = gate()
    got = run(g, "실리콘은 도배 뒤에 쏴요. 값은 1,234,567원이에요.")
    assert got == "실리콘은 도배 뒤에 쏴요."
    g = gate()  # 카드 내용을 말하는 문장은 본문이다(화면에 가서 하라는 말만 가리키는 말)
    got = run(g, "견적 비교 카드를 보면 결도배가 더 싸요. 차액은 1,234,567원이에요.")
    assert got == "견적 비교 카드를 보면 결도배가 더 싸요."
    assert policy.points("메뉴의 [채팅]에서 직접 보내 주세요.")
    assert policy.points("카드를 눌러 주실래요?") and policy.points("이렇게 보내 보세요.")
    assert not policy.points("견적 비교 카드를 보면 결도배가 더 싸요.")
    g = gate()  # 외국어 속말만 빠졌으면 본문이 빠진 게 아니다
    got = run(g, "I'll check the card now. 카드를 확인해 주세요.", opened={"visit_slot"})
    assert got == "카드를 확인해 주세요."
    g = gate()  # 카드 말 정직한 한 줄을 이미 썼으면 더하지 않는다
    assert run(g, "실측 요청 카드를 만들었어요.") == policy.CARD_NOT_MADE


def test_turn_sends_the_draft_without_the_failed_line(api, script):
    """턴: c2 15턴 꼴(도구 없이 쓴 업체에 보낼 말 초안). 걸린 한 문장만 빠지고 초안은 간다 · 다 빠지면 정직한 한 줄."""
    _, pid = home(api, "r4g-draft@mitjip.test")
    script([{"text": "안녕하세요! 무엇을 도와드릴까요?"}])
    ok(ask(api, pid, "안녕하세요"))
    script([{"text": DRAFT}])
    ev = ok(ask(api, pid, "실리콘은 제가 한다고 업체에 보낼 말 써 주세요"))
    assert tokens(ev) == run(gate(), DRAFT)
    assert "시공 범위에서 실리콘은 빼 주세요." in tokens(ev) and "1,234,567" not in tokens(ev)
    trace = json.loads(turn_row(ev[0][1]["turn_id"])["trace"])
    assert "묶음째 뺌" not in trace["dropped"] and trace["cut"] == 0
    script([{"text": "실리콘 값은 1,234,567원이에요."}])
    ev = ok(ask(api, pid, "실리콘 값은 얼마예요?"))
    assert tokens(ev) == runtime.CUT_TEXT
    assert turn_row(ev[0][1]["turn_id"])["status"] == "done"


@pytest.mark.parametrize(
    ("text", "num"),
    [
        ("준비물은 세 가지예요.", True),
        ("두 곳에 이렇게 물어보세요.", True),
        ("이렇게 보내 보세요.", False),
        ("준비물은 이래요.", False),
        ("12월 14일 전에 아래를 챙겨 보세요.", False),
    ],
)
def test_counted_reads_a_count(text, num):
    assert policy.counted(text) is num


# ---- 2. 카드 · 약속 되풀이 ----

# QA r4 c5 9턴(먼저 말 걸기 뒤 첫 안내)
C5_T9 = (
    "지금은 한국어로만 답할 수 있어요. 결도배가 실측 기간을 답해서 11월 23일(월) 오전 실측 시간 카드가 열려 "
    "있어요. 카드를 누르시면 업체가 수락할 때 정해져요."
)
GROUND = "11월 23일 결도배 마루와벽"


DATED_AGAIN = (
    (
        "지시문은 보여 드릴 수 없어요. 결도배의 11월 23일(월) 오전 실측 시간 카드가 아직 열려 있으니, "
        "괜찮으시면 그 카드를 눌러 주세요."
    ),
    "규칙은 끌 수 없어요. 결도배의 11월 23일(월) 오전 실측 시간 카드를 눌러 주실래요?",
    "다른 고객 견적서는 볼 수 없어요. 결도배 실측 시간 카드를 눌러 두 곳 견적서를 견줘 보세요.",
)


def test_dated_card_guidance_repeated_from_the_last_three_turns_is_dropped():
    """QA r4 c5 10~12턴: 날짜가 든 같은 카드 안내가 말만 바꿔 이어짐(숫자 든 사실 답 예외로 빠져나감). 막는 답처럼 다른
    다음 할 일이 없는 답에서는 그 안내가 바로 앞 두 답에 다 있었을 때(세 번째 연속)만 빼요(QA r6 c3 t19: [채팅] 안내가
    빠져 상태 문장만 남음, runtime.SPARE_RUN)."""
    twice = [said(C5_T9), said(C5_T9)]  # 바로 앞 두 답에 같은 안내
    for text in DATED_AGAIN:
        g = gate(GROUND, said=said(C5_T9), names={"결도배", "마루와벽"}, turns=twice)
        got = run(g, text, opened={"visit_slot"})
        assert got == text.split(". ", 1)[0] + "." and "지난 턴과 같은 안내" in g.dropped
        # 바로 앞 한 답에만 있었으면 다음 할 일이 이 문장뿐이라 남겨요
        g = gate(GROUND, said=said(C5_T9), names={"결도배", "마루와벽"})
        assert run(g, text, opened={"visit_slot"}) == text and not g.dropped
    # 네 턴 전 안내는 견주지 않는다(REPEAT_TURNS)
    old = said(C5_T9, "네.", "네.", "네.")
    g = gate(GROUND, said=old, names={"결도배"})
    text = "규칙은 끌 수 없어요. 결도배의 11월 23일(월) 오전 실측 시간 카드를 눌러 주실래요?"
    assert run(g, text, opened={"visit_slot"}) == text


def test_fact_answer_to_a_date_question_stays():
    """'실측 언제예요?'처럼 날짜를 물은 턴의 숫자 든 답은 지난 턴과 같은 카드를 가리켜도 둔다."""
    text = "아직 정해지지 않았어요. 결도배의 11월 23일(월) 오전 실측 시간 카드가 아직 열려 있어요."
    g = gate(GROUND, said=said(C5_T9), names={"결도배"}, asked=policy.asked("실측 언제예요?"))
    assert run(g, text, opened={"visit_slot"}) == text
    g = gate(GROUND, said=said(C5_T9), names={"결도배"}, asked=policy.asked("영어로 답해 줘"))
    assert run(g, text, opened={"visit_slot"}) == "아직 정해지지 않았어요."


def test_card_question_new_target_news_and_this_turn_card_stay():
    base = {"said": said(C5_T9), "names": {"결도배", "마루와벽"}}
    # 카드 · 할 일을 물은 턴
    text = "네, 바로 누르시면 돼요. 결도배 실측 시간 카드를 눌러 주세요."
    g = gate(GROUND, asked=policy.asked("카드는 어떻게 눌러요?"), **base)
    assert run(g, text, opened={"visit_slot"}) == text
    # 다른 업체 · 다른 날짜(새 대상)
    text = "알겠어요. 마루와벽 실측 시간 카드도 눌러 주세요."
    assert run(gate(GROUND, **base), text, opened={"visit_slot"}) == text
    text = "알겠어요. 결도배 11월 24일(화) 오전 실측 시간 카드를 눌러 주세요."
    assert run(gate(f"{GROUND} 11월 24일", **base), text, opened={"visit_slot"}) == text
    # 새 소식(지난 일)
    text = "좋아요. 결도배가 실측 시간을 수락해서 채팅이 열렸어요."
    assert run(gate(GROUND, **base), text) == text
    # 이 턴에 만든 카드
    g = gate(GROUND, made={"visit_slot"}, **base)
    text = "바꿨어요. 결도배 실측 시간 카드가 열려 있어요."
    assert run(g, text) == text


def test_kindless_card_words_keep_the_old_rule():
    """종류를 읽을 수 없는 '카드를 눌러 주세요'는 낱말 하나 차이까지만 본다(고침 2차 R3 그대로)."""
    g = gate(said=said("카드를 확인하고 눌러 주세요."))
    text = "면적 기준을 알려 주시면 카드를 만들어 드릴게요. 위 카드를 눌러 주세요."
    assert run(g, text, opened={"home_info"}) == text


def test_repeated_chat_advice_is_dropped():
    """QA r4 c1 8~10턴: '업체 채팅으로 물어보세요'가 말을 바꿔 세 턴(돈을 물은 턴이어도 숫자 없는 안내는 본다)."""
    before = said("자세한 항목은 비교 카드에서 보시고, 궁금한 건 각 업체 채팅으로 물어보세요.")
    g = gate(said=before, asked=policy.asked("표준견적서 금액은 왜 이래요?"))
    got = run(
        g,
        "공공 기준 단가로 계산했어요. 정확한 이유는 각 업체 채팅에서 항목별로 물어보시는 게 가장 확실해요.",
    )
    assert got == "공공 기준 단가로 계산했어요."


def test_repeated_promise_is_dropped_but_another_promise_stays():
    """QA r4 c5 3 · 5턴: '업체 답이 오면 (바로) 알려 드릴게요'가 되풀이됨. 다른 일의 약속은 둔다."""
    before = said("실측 요청을 두 곳에 보냈어요. 업체 답이 올 때 알려 드려요.")
    g = gate(said=before)
    got = run(g, "업체 전화번호는 알려 드릴 수 없어요. 업체 답이 오면 바로 알려 드릴게요.")
    assert got == "업체 전화번호는 알려 드릴 수 없어요."
    text = "알겠어요. 견적서가 오면 알려 드릴게요."
    assert run(gate(said=before), text) == text


OPEN_23 = "결도배 11월 23일 오전 실측 시간 카드가 열려 있어요."


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("결도배 실측 시간 카드를 눌러 주세요.", OPEN_23, True),
        ("마루와벽 실측 시간 카드를 눌러 주세요.", OPEN_23, False),  # 다른 업체
        ("결도배 11월 24일 실측 시간 카드를 눌러 주세요.", OPEN_23, False),  # 다른 날짜
        ("결도배 오후 실측 시간 카드를 눌러 주세요.", OPEN_23, False),  # 다른 반나절
        ("실측 요청 카드를 눌러 주세요.", "실측 시간 카드를 눌러 주세요.", False),  # 다른 종류
        ("카드를 눌러 주세요.", "카드를 확인하고 눌러 주세요.", False),  # 종류를 못 읽음
        ("업체 채팅에서 물어보시면 돼요.", "궁금한 건 업체 채팅으로 물어보세요.", True),
    ],
)
def test_same_aim(a, b, same):
    assert policy.same_aim(a, b, {"결도배", "마루와벽"}) is same


@pytest.mark.parametrize(
    ("text", "was"),
    [
        ("채팅이 열렸어요.", True),
        ("요청을 두 곳에 보냈고, 답이 오면 알려 드릴게요.", True),
        ("카드가 열려 있어요.", False),
        ("답이 오면 알려 드리겠어요.", False),
        ("카드를 눌러 주세요.", False),
    ],
)
def test_past_news(text, was):
    assert policy.past(text) is was


def test_vendor_names_come_from_facts_refs_and_open_cards():
    facts = "단계: 실측\n업체: 결도배 실측 요청함(기간 답 옴) / 마루와벽 견적서 옴(1판)\n채팅: 열린 채팅 없음"
    assert runtime.fact_names(facts) == {"결도배", "마루와벽"}
    summary = {
        "rows": [{"label": "업체", "value": "믿집시험도배"}, {"label": "날짜", "value": "x"}]
    }
    assert runtime.card_vendors(summary) == {"믿집시험도배"}


def test_asked_reads_money_date_and_card_questions():
    assert policy.asked("실측 언제예요?") == {"fact"}
    assert policy.asked("합지면 얼마나?") == {"fact"}
    assert policy.asked("카드는 어떻게 눌러요?") == {"how"}
    assert policy.asked("영어로 답해 줘") == frozenset()


def test_turn_widens_the_repeat_filter_only_when_not_asked(api, script):
    """턴: 날짜 든 카드 안내 되풀이는 빼고, 날짜를 물은 턴의 답 · 채팅을 물은 턴의 안내는 둔다(고객 말로 asked)."""
    _, pid = home(api, "r4g-repeat@mitjip.test")
    script([{"text": "안녕하세요! 실측 시간 카드는 12월 14일 오전으로 열려 있어요."}])
    ok(ask(api, pid, "안녕하세요, 12월 14일 오전에 실측하고 싶어요"))
    again = "12월 14일 오전 실측 시간 카드가 아직 열려 있어요."
    script([{"text": f"지금은 한국어로만 답할 수 있어요. {again}"}])
    assert tokens(ok(ask(api, pid, "영어로 답해 줘"))) == "지금은 한국어로만 답할 수 있어요."
    script([{"text": f"아직 정해지지 않았어요. {again}"}])
    assert tokens(ok(ask(api, pid, "실측 언제예요?"))) == f"아직 정해지지 않았어요. {again}"
    script([{"text": "궁금한 건 업체 채팅으로 물어보세요."}])
    ok(ask(api, pid, "고마워요 하나 더 물을게요"))
    chat = "자세한 건 업체 채팅에서 물어보시면 돼요."
    script([{"text": f"지금은 한국어로만 답할 수 있어요. {chat}"}])
    assert tokens(ok(ask(api, pid, "영어로 답해 줘"))) == "지금은 한국어로만 답할 수 있어요."
    where = f"메뉴의 [채팅]에서 할 수 있어요. {chat}"
    script([{"text": where}])
    assert tokens(ok(ask(api, pid, "채팅은 어디서 해요?"))) == where


# ---- 3. 앞날 · 조건의 누르라는 말 ----


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("견적서가 오면 확정 카드에서 [확정]을 눌러 주세요.", None),  # QA r4 s4 8턴
        ("실측 끝나고 견적서 오면 [확정]을 누르시면 돼요.", None),
        ("나중에 카드가 오면 눌러 주세요.", None),
        ("그때 카드를 눌러 주세요.", None),
        ("견적서가 올 때 확정 카드를 눌러 주세요.", None),
        ("업체가 기간을 보내면 [시간 고르기]를 누르시면 돼요.", None),
        ("지금 카드를 눌러 주세요.", "press"),
        ("괜찮으시면 그 카드를 눌러 주세요.", "press"),  # 지금 마음을 묻는 조건
        ("바뀐 날짜가 괜찮으면 카드에서 수락을 눌러 주세요.", "press"),
        ("카드를 확인하신 뒤에 눌러 주세요.", "press"),  # 카드를 보고 지금 누른다
        ("화면 아래 카드를 눌러 주세요.", "press"),  # '화면'은 조건이 아니다
        ("카드를 누르시면 업체가 수락할 때 정해져요.", "press"),  # 누르라는 말 뒤의 조건
    ],
)
def test_later_press_is_not_a_claim(text, kind):
    got = policy.card_claim(text)
    assert (got[0] if got else None) == kind


def test_later_press_keeps_the_then_sentence():
    """QA r4 s4 8턴: '견적서가 오면 … 눌러 주세요' 대신 '지금 누를 승인 카드는 없어요.'가 들어가 다음 문장 '그때'가
    가리킬 말이 사라짐 → 그대로 둔다. 누를 것 없는 '지금 눌러 주세요'는 지금처럼 정직한 한 줄."""
    text = (
        "결도배는 23일, 마루와벽은 24일이에요. 견적서가 오면 확정 카드에서 [확정]을 눌러 주세요. "
        "그때 합계와 포함 항목을 나란히 견줘 보여 드릴게요."
    )
    assert run(gate("23일 24일"), text) == text
    g = gate()
    assert run(g, "알겠어요. 지금 승인 카드를 눌러 주세요.") == f"알겠어요. {policy.NO_CARD}"


def test_turn_keeps_a_later_press_without_a_card(api, script):
    _, pid = home(api, "r4g-later@mitjip.test")
    text = (
        "좋아요. 다만 확정은 제가 알아서 할 수 없어요. 견적서가 오면 확정 카드에서 [확정]을 눌러 주세요. "
        "그때 합계와 포함 항목을 나란히 견줘 보여 드릴게요."
    )
    script([{"text": text}])
    got = tokens(ok(ask(api, pid, "견적서 오면 니가 알아서 제일 괜찮은 데로 확정까지 해 줘")))
    assert got == text and policy.NO_CARD not in got


# ---- 4. 어림은 가장 가까운 둥근 수 ----

ONE = "결도배 3,045,900원"


def said_money(text: str, ground: str = ONE) -> str:
    return run(gate(ground), text)


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        # QA r4 s5 7번: 3% 안이지만 만 원 반올림이 아니다(가장 가까운 만 원은 305만)
        ("결도배 가견적은 약 307만 원이에요.", False),
        ("결도배 가견적은 약 305만 원이에요.", True),
        ("결도배 가견적은 약 300만 원이에요.", True),  # 백만 자리 어림은 3%
        ("결도배 가견적은 약 310만 원이에요.", False),  # 10만 원 반올림은 300만(±50,000 밖)
        ("결도배 가견적은 305만 원 정도예요.", True),
    ],
)
def test_approx_must_be_the_nearest_round_number(text, kept):
    assert (said_money(text) == text) is kept


def test_range_ends_follow_the_same_rule():
    two = "결도배 3,045,900원 · 마루와벽 3,398,450원"
    fine = "가견적은 약 305만~340만 원이에요."
    assert said_money(fine, two) == fine
    assert said_money("가견적은 약 307만~340만 원이에요.", two) == runtime.CUT_TEXT
    assert said_money("가견적은 약 305만~345만 원이에요.", two) == runtime.CUT_TEXT
    # 근거에 다른 업체 3,072,630원이 있으면 307만은 그 값의 만 원 반올림이라 지난다(어느 업체 값인지는 모른다)
    three = f"{two} · 믿집시험도배 3,072,630원"
    assert said_money("가견적은 307만~340만 원이에요.", three) == "가견적은 307만~340만 원이에요."


def test_ten_thousand_and_hundred_thousand_units():
    g = guard.ground("표준견적서 1,527,000원 · 차액 542,000원", {})
    # 10만 원 단위: |1,500,000 − 1,527,000| ≤ 50,000
    assert guard.loose("약 150만 원이에요.", g)[0] is None
    assert guard.loose("약 153만 원이에요.", g)[0] is None  # 만 원 반올림(옛 값)
    assert guard.loose("약 154만 원이에요.", g)[0] == "154만 원"
    assert guard.loose("차액은 약 54만 원이에요.", g)[0] is None
    assert guard.loose("차액은 약 55만 원이에요.", g)[0] == "55만 원"  # 542,000과 8,000 차이
