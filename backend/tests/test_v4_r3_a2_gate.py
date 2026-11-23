"""v4 비서 고침 3차 A2(문장 검사 · 자르기, QA r3): 길이 상한이 남긴 글이 맞는 말이게.

- 상한: 보통 6문장 · 500자, 대화 첫 답 · 업체 소개 · 견적 비교 카드 턴은 8문장 · 700자(무제한 없앰)
- 목록 번호('1.')는 문장으로 세지 않는다 · 가리키는 문장('네 가지예요' · '이래요' · '이렇게 물어보세요')과 뒤 목록은
  묶음째 보내거나 뺀다(답 자체가 목록이면 목록 줄 여덟까지) · 넘친 문장은 마지막 묻는 말 하나만 끝에
- 앞 문장이 빠져 첫 문장이 되면 첫머리 접속 말을 뗀다 · 카드 말은 이 턴에 한 일 · 눌러 달라는 말만(앞으로 하겠다는 말 ·
  소개는 걸지 않음) · 외국어 속말은 로마자 비율로 · 한자 한 글자는 지우고 낱말이면 뺀다 · 지난 세 턴 안내 되풀이는 뺀다
- 숫자: 이 턴에 만든 승인 카드 요약 · 보인 카드 값은 근거 · 합 · 차는 같은 금액 기준끼리만 · '도구가 실패해서'는 안쪽 말
DB 없는 문장 검사 + Claude 대본 턴(유료 호출 0회)."""

import asyncio
import json
import uuid
from datetime import date, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import policy, runtime
from app.assistant.runtime import SentenceGate, foreign, han_fix, recent_said
from app.assistant.schemas import CardOut
from app.v2 import guard
from tests.conftest import query
from tests.test_v3_project_home import START
from tests.test_v4_assistant_offers import proposed, tokens
from tests.test_v4_assistant_turns import ask, home, ok, turn_row
from tests.test_vendor_profile import approved_vendor

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


def gate(allowed: str = "", **kw) -> tuple[SentenceGate, list[str]]:
    sent: list[str] = []

    async def emit(name: str, data: dict) -> None:
        assert name == "token"
        sent.append(data["text"])

    return SentenceGate(emit, PROMPT, allowed, **kw), sent


def run(g: SentenceGate, *chunks: str, opened: set[str] | None = None, shown=()) -> str:
    async def go():
        g.opened |= opened or set()
        for c in shown:
            await g.shown(c)
        for c in chunks:
            await g.feed(c)
        await g.flush()
        await g.settle()

    asyncio.run(go())
    return g.text


STD = "표준견적서 2,952,491원 · 벽 877,375원 · 천장 672,243원 · 벽지 913,665원 · 부자재 220,800원"


# ---- 결정 2 · 3: 목록 번호 · 가리키는 문장 묶음 ----


def test_numbered_list_marker_is_not_a_sentence():
    """'1. ' · '2. '는 문장 끝이 아니다(QA r3 c5 19턴: 글이 '2.'에서 끝남)."""
    assert runtime.SENT_END.split("순서예요.\n1. 배관을 손봐요. 2. 물을 돌려요.") == [
        "순서예요.",
        "1. 배관을 손봐요.",
        "2. 물을 돌려요.",
    ]
    g, _ = gate()
    said = run(
        g,
        "배관이 먼저고 장판이 나중이에요.\n1. 보일러 배관을 먼저 손봐요.\n2. 물을 돌려서 새는 곳을 봐요.\n"
        "3. 장판은 그다음에 깔아요.\n일정이 겹치면 업체와 채팅으로 맞춰 보세요.",
    )
    assert said.endswith("3. 장판은 그다음에 깔아요.\n일정이 겹치면 업체와 채팅으로 맞춰 보세요.")
    assert g.cut == 0  # 다섯 문장(번호는 세지 않음)이라 상한 안


def test_pointer_and_list_go_whole_or_not_at_all():
    """'들어간 줄은 네 가지예요.' 뒤 목록이 상한에 걸리면 묶음째 빼고, 넘친 뒤 문장은 마지막 묻는 말 하나만
    (QA r3 c1 13턴: '네 가지예요.' 뒤 두 줄만 남고 '그 까닭이 …'가 목록 줄에 붙음)."""
    answer = (
        "표준견적서는 부가세 포함 2,952,491원이에요. 공공 기준 단가로 믿집이 계산한 값이에요. "
        "업체가 와서 본 값은 아니에요.\n들어간 줄은 네 가지예요.\n- 벽지: 913,665원\n"
        "- 벽 도배 시공: 877,375원\n- 천장 도배 시공: 672,243원\n- 부자재: 220,800원\n"
        "업체 견적과 다른 까닭은 철거일 수 있어요. 그 까닭이 철거인지는 카드만으로는 알 수 없어요. "
        "먼저 어느 업체에 물어보실래요?"
    )
    g, _ = gate(STD)
    said = run(g, answer)
    assert said == (
        "표준견적서는 부가세 포함 2,952,491원이에요. 공공 기준 단가로 믿집이 계산한 값이에요. "
        "업체가 와서 본 값은 아니에요. 먼저 어느 업체에 물어보실래요?"
    )
    assert "네 가지" not in said and g.cut == 7  # 묶음 다섯 + 넘친 두 문장
    # 묶음이 상한 안이면 같이 간다
    g, _ = gate(STD)
    said = run(g, answer.split("\n", 1)[1].replace("업체 견적과", "\n업체 견적과", 1))
    assert said.startswith("들어간 줄은 네 가지예요.\n- 벽지: 913,665원\n- 벽 도배 시공")
    assert said.count("\n- ") == 4 and "- 부자재: 220,800원" in said


def test_list_item_dropped_by_a_check_drops_the_group():
    """묶음 안 한 줄이 숫자 검사로 빠지면 묶음째 뺀다('네 가지예요' 뒤 셋만 남지 않게, s5 · c1)."""
    g, _ = gate(STD)
    said = run(
        g,
        "줄은 네 가지예요.\n- 벽지: 1,005,031원\n- 벽: 877,375원\n- 천장: 672,243원\n- 부자재: 220,800원\n"
        "업체 견적과 견줘 보세요.",
    )
    assert said == "업체 견적과 견줘 보세요." and "묶음째 뺌" in g.dropped


def test_pointer_left_without_its_list_is_dropped():
    """'이렇게 물어보세요.' 뒤 물을 말이 없으면 가리키는 문장도 남기지 않는다(QA r3 c4 #20 · #21 · #35)."""
    six = "".join(f"{w} 문장이에요. " for w in ("첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째"))
    g, _ = gate()
    said = run(
        g,
        six + '카드의 [채팅 열기]에서 이렇게 물어보세요.\n- "바탕 보수가 필요한 곳이 어디인가요? '
        '사진으로 보여 주실 수 있나요?"\n답을 보고 승인할지 정하시면 돼요. '
        "먼저 채팅으로 묻기를 고르실래요?",
    )
    assert said == six + "먼저 채팅으로 묻기를 고르실래요?"
    g, _ = gate()
    said = run(g, "추가금이 붙을 수 있어요. 확정하기 전에 아래를 챙겨 보세요.")
    assert said == "추가금이 붙을 수 있어요." and "가리킨 말 없음" in g.dropped


def test_answer_that_is_a_list_sends_up_to_eight_rows():
    """묶음이 첫 문장이면(답 자체가 목록) 상한을 넘어도 목록 줄 여덟까지 보낸다."""
    rows = "".join(f"\n- 준비물 {n}번이에요." for n in range(1, 11))
    g, _ = gate()
    said = run(g, "준비물은 이래요." + rows + "\n더 필요한 게 있으면 알려 주세요.")
    assert said.count("\n- ") == 8 and "준비물 9번" not in said
    assert said.endswith("\n더 필요한 게 있으면 알려 주세요.")  # 넘친 뒤 마지막 묻는 말


def test_count_sentence_at_the_end_stays():
    """'…세 가지예요.'로 끝나는 답은 앞 말을 줄인 끝 문장일 수 있어 둔다(뒤에 가리킨 것이 없을 때만)."""
    g, _ = gate()
    said = run(g, "직접 하실 일은 조명 교체와 실리콘, 콘센트 커버 세 가지예요.")
    assert said == "직접 하실 일은 조명 교체와 실리콘, 콘센트 커버 세 가지예요."
    assert policy.pointer("이유는 두 가지예요.") and policy.pointer("준비물은 이래요.")
    assert not policy.pointer("실측은 그다음이에요.") and not policy.pointer("아래 카드를 보세요.")


def test_tail_question_is_one_and_never_glued_to_a_list_row():
    """넘친 문장 중 마지막 묻는 말 하나만, 목록 줄 끝에 붙이지 않는다(QA r3 c1 14 · 20턴)."""
    g, _ = gate(STD)
    said = run(
        g,
        "실크와 합지는 벽지 값과 시공비가 달라요.\n달라지는 줄은 이래요.\n- 벽지 값: 913,665원\n"
        "- 벽 도배 시공: 877,375원\n- 천장 도배 시공: 672,243원\n- 부자재: 220,800원\n"
        "나머지 줄은 같아요. 업체 [채팅 열기]로 합지 견적을 물어보세요. 견적을 받으면 알려 주실래요? "
        "두 업체에 같이 물어보실래요?",
    )
    assert said.endswith("- 부자재: 220,800원\n두 업체에 같이 물어보실래요?")
    assert said.count("?") == 1 and "[채팅 열기]" not in said


def test_no_tail_question_when_one_was_already_asked():
    g, _ = gate()
    said = run(
        g,
        "어느 쪽이 편하세요? " + "".join(f"{n}번째 말이에요. " for n in range(2, 9)) + "더 볼까요?",
    )
    assert said.count("?") == 1 and said.startswith("어느 쪽이 편하세요?")


# ---- 결정 1: 첫 답 · 업체 소개 · 견적 비교 카드 턴도 끝이 있다 ----


TEN = "".join(f"{n}번째 문장이에요. " for n in range(1, 11)) + "어느 쪽으로 할까요?"


def test_first_answer_is_capped_at_eight_sentences():
    g, _ = gate(long_ok=True)
    said = run(g, TEN)
    assert said.count("문장이에요.") == 8 and said.endswith("어느 쪽으로 할까요?")


def test_long_card_turn_is_capped_at_eight_sentences_and_700_chars():
    card = CardOut(card_id="compare-dobae", kind="quote_compare", data={"cols": []})
    g, _ = gate()
    said = run(g, TEN, shown=[card])
    assert said.count("문장이에요.") == 8
    g, _ = gate()
    long = "".join(ch * 98 + "예요. " for ch in "가나다라마바사아자")
    said = run(g, long, shown=[card])
    assert len(said) <= policy.LONG_CHARS + 101 and said.count("예요.") == 7


# ---- 결정 5: 첫머리 접속 말 ----


def test_lead_link_is_dropped_when_the_first_sentence_was_dropped():
    """앞 문장이 '쓰면 안 되는 표현'으로 빠져 '다만 …'이 첫 문장이 되면 접속 말을 뗀다(QA r3 c4 #33)."""
    g, _ = gate()
    said = run(
        g,
        "어느 쪽이 바가지인지는 아직 몰라요. 다만, 결도배는 폐기물 항목이 없어요. 그래서 물어보세요.",
    )
    assert said == "결도배는 폐기물 항목이 없어요. 그래서 물어보세요."
    g, _ = gate()  # 앞 문장이 남아 있으면 그대로
    said = run(g, "폐기물은 따로예요. 다만 결도배는 항목이 없어요.")
    assert said == "폐기물은 따로예요. 다만 결도배는 항목이 없어요."


# ---- 할 일 2: 카드 말 검사 줄이기 ----


@pytest.mark.parametrize(
    "text",
    [
        "정할 것은 승인 카드로 준비해 둘게요.",  # 할 수 있는 일 소개(QA r3 s2x 1턴)
        "그때 집 정보 카드를 만들어 드릴게요.",  # 앞으로의 제안(s2 3턴)
        "고르신 곳으로 실측 요청 카드를 만들어 드릴게요.",  # s2 6턴
        "원하시면 카드를 만들어 드릴게요.",
        "카드를 준비해 둘까요?",
    ],
)
def test_offers_and_intros_get_no_honest_line(text):
    g, _ = gate()
    said = run(g, f"궁금한 건 편하게 물어봐 주세요. {text}")
    assert policy.CARD_NOT_MADE not in said and text in said


def test_past_card_words_still_get_the_honest_line():
    g, _ = gate()
    said = run(g, "실측 요청 카드를 만들어 뒀어요. 확인해 보세요.")
    assert said == f"{policy.CARD_NOT_MADE} 확인해 보세요."
    g, _ = gate()  # '이미 눌러 주셨어요'는 지난 일이라 누를 것이 없어도 그대로(QA r3 s1 14턴)
    assert run(g, "요청 카드는 아까 눌러 주셨어요.") == "요청 카드는 아까 눌러 주셨어요."


# ---- 할 일 3: 외국어 속말 · 한자 ----


@pytest.mark.parametrize(
    ("text", "out"),
    [
        ("I'll go with 마루와벽.", True),  # QA r3 s4y
        ("Right now we're waiting for 결도배 and 마루와벽 to reply.", True),  # c5 16턴
        ("LX하우시스 베스띠 실크로 하면 무난해요.", False),
        ("LX Z:IN 디아망 포티스는 PVC 실크예요.", False),
        ("공급 84㎡ 기준이에요.", False),
        ("3,300,000원이에요.", False),
        ("OK, 결도배로 할게요.", False),
    ],
)
def test_foreign_reads_the_latin_share(text, out):
    assert foreign(text) is out


def test_han_letters_are_removed_or_the_sentence_dropped():
    """한국어 답의 한자: 한 글자는 지우고(QA r3 c6 T18 '一이 결과엔 …'), 낱말이면 문장을 뺀다."""
    assert (
        han_fix("一이 결과엔 고객이 직접 할 일 칸이 없어요.")
        == "이 결과엔 고객이 직접 할 일 칸이 없어요."
    )
    assert han_fix("공사(工事) 기간은 이틀이에요.") is None
    g, _ = gate()
    said = run(g, "一이 결과엔 직접 할 일 칸이 없어요. 工事 기간은 짧아요. I'll check 결도배 now.")
    assert said == "이 결과엔 직접 할 일 칸이 없어요."
    assert {"한자 지움", "한자 섞인 글", "외국어 속말"} <= set(g.dropped)


# ---- 할 일 4: 지난 세 턴 안내 되풀이 ----


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        (
            "이어서 실측 요청할 업체를 보여 드릴까요?",
            "이어서 실측 요청할 도배 업체를 보여 드릴까요?",
            True,
        ),
        (
            "이어서 실측 요청할 도배 업체를 보여 드릴까요?",
            "실측 요청할 도배 업체를 보여 드릴까요?",
            True,
        ),
        ("철거 비용이 들어 있어요.", "철거 비용이 안 들어 있어요.", False),  # 뜻을 뒤집는 낱말
        ("결도배 카드를 눌러 주세요.", "마루와벽 카드를 눌러 주세요.", False),  # 바꾼 낱말
        ("카드는 25일까지 열려 있어요.", "카드는 24일까지 열려 있어요.", False),
        ("카드는 열려 있어요.", "카드는 12월 열려 있어요.", False),  # 숫자 낱말
    ],
)
def test_near_same(a, b, same):
    assert policy.near_same(a, b) is same


def test_repeated_question_from_the_last_three_turns_is_dropped():
    """QA r3 c3 2~5번: 같은 끝 질문이 '이어서' · '도배' 한 낱말 차이로 네 번."""
    history = [
        {
            "role": "assistant",
            "content": "짐은 방 가운데로 모아요. 이어서 실측 요청할 업체를 보여 드릴까요?",
        },
        {"role": "user", "content": "강아지는요?"},
        {"role": "assistant", "content": "다른 방에 두세요."},
        {"role": "user", "content": "조명은요?"},
        {"role": "assistant", "content": "도배 뒤에 달아요."},
    ]
    g, _ = gate(said=recent_said(history))
    said = run(g, "실리콘은 도배 뒤에 쏴요. 이어서 실측 요청할 도배 업체를 보여 드릴까요?")
    assert said == "실리콘은 도배 뒤에 쏴요." and "지난 턴과 같은 안내" in g.dropped
    # 네 턴 전 말은 견주지 않는다(REPEAT_TURNS)
    older = [
        *history,
        {"role": "user", "content": "또요?"},
        {"role": "assistant", "content": "네."},
    ]
    g, _ = gate(said=recent_said(older))
    said = run(g, "실리콘은 도배 뒤에 쏴요. 이어서 실측 요청할 도배 업체를 보여 드릴까요?")
    assert said.endswith("보여 드릴까요?")


def test_facts_asked_again_and_new_card_guidance_stay():
    said_before = ["공사는 12월 14일에 시작해요.", "카드를 확인하고 눌러 주세요."]
    g, _ = gate("12월 14일", said=said_before, made={"visit_request"})
    said = run(g, "다시 알려 드릴게요. 공사는 12월 14일에 시작해요. 카드를 확인하고 눌러 주세요.")
    assert said == "다시 알려 드릴게요. 공사는 12월 14일에 시작해요. 카드를 확인하고 눌러 주세요."


def test_repeated_advice_in_the_middle_is_dropped_but_list_rows_stay():
    said_before = ["결도배 [채팅 열기]로 물어보세요.", "- 젖은 면에는 쏘지 마세요."]
    g, _ = gate(said=said_before)
    said = run(
        g,
        "실리콘은 주말에 하세요. 결도배 [채팅 열기]로 물어보세요.\n준비물은 이래요.\n"
        "- 실리콘 건\n- 젖은 면에는 쏘지 마세요.\n궁금하면 알려 주세요.",
    )
    assert "[채팅 열기]" not in said and "- 젖은 면에는 쏘지 마세요." in said


# ---- 할 일 5: 숫자 근거 · 금액 기준 ----


def test_card_summary_numbers_are_grounds():
    """이 턴에 만든 승인 카드 요약의 날짜 · 금액은 근거다(QA r3 s2 9턴: 카드엔 12월 14일이 있는데 글에서 빠짐)."""
    summary = {
        "title": "집 정보 저장",
        "rows": [{"label": "공사 시작 희망", "value": "12월 14일(월)", "sub": "지금 없음"}],
        "amounts": [{"label": "공급가", "won": 220000}, {"label": "부가세", "won": 22000}],
        "approve_label": "맞아요, 저장",
    }
    g, _ = gate()
    g.allow(runtime.summary_ground(summary))
    said = run(g, "12월 14일(월) 시작으로 넣었어요. 추가 금액은 242,000원이에요.")
    assert (
        said == "12월 14일(월) 시작으로 넣었어요. 추가 금액은 242,000원이에요."
    )  # 공급가 + 부가세


VAT_MIX = json.dumps(
    {
        "items": [{"grade": "실크", "total": 2952491}, {"grade": "합지", "total": 1464986}],
        "lines": [
            {"name": "벽지 값(공급가)", "items": [{"amount": 913665}, {"amount": 373941}]},
        ],
    },
    ensure_ascii=False,
)


def test_sum_and_difference_only_within_the_same_vat_basis():
    """부가세 포함 합계 ± 공급가 줄은 다시 만들지 않는다(QA r3 s5 13번 2,952,491 − 913,665 = 2,038,826)."""
    tags = guard.basis([VAT_MIX])
    assert tags[913665.0] == frozenset({guard.SUPPLY}) and tags[2952491.0] == frozenset(
        {guard.INCL}
    )
    g, _ = gate()
    g.allow(VAT_MIX)
    assert run(g, "벽지를 빼면 실크는 2,038,826원이에요.") == ""
    g, _ = gate()
    g.allow(VAT_MIX)
    assert run(g, "차액은 1,487,505원이에요.") == "차액은 1,487,505원이에요."  # 포함 − 포함
    g, _ = gate()
    g.allow(VAT_MIX)
    assert (
        run(g, "벽지 값 차이는 539,724원이에요.") == "벽지 값 차이는 539,724원이에요."
    )  # 공급가끼리
    # 꼬리표가 없는 글(고객 말 · 사실)은 지금처럼
    g, _ = gate("실크 2,952,491원 · 벽지 913,665원")
    assert run(g, "2,038,826원이에요.") == "2,038,826원이에요."


@pytest.mark.parametrize(
    ("text", "tag"),
    [
        ("공급가 220,000원", guard.SUPPLY),
        ("913,665원(공급가)", guard.SUPPLY),
        ("부가세 별도 3,150,000원", guard.SUPPLY),
        ("부가세 포함 합계 1,947,460원", guard.INCL),
        ("부가세 22,000원", guard.VAT),
        ("표준견적서 2,952,491원", guard.ANY),
    ],
)
def test_basis_words_in_text(text, tag):
    assert tag in guard.basis([text])[max(guard.basis([text]))]


def test_basis_of_json_keys_and_labels():
    body = json.dumps(
        {
            "total": 2750000,
            "supply": 2500000,
            "vat": 250000,
            "rows": [{"label": "공급가", "won": 220000}, {"label": "부가세", "won": 22000}],
            "공급가": 913665,
        },
        ensure_ascii=False,
    )
    tags = guard.basis([body])
    assert tags[2750000.0] == {guard.INCL} and tags[2500000.0] == {guard.SUPPLY}
    assert tags[250000.0] == {guard.VAT} and tags[220000.0] == {guard.SUPPLY}
    assert tags[22000.0] == {guard.VAT} and tags[913665.0] == {guard.SUPPLY}
    assert "공급가" in policy.ALLOWED  # 이 이름으로 넘긴 칸이 모델 · 근거에 남는다
    g = guard.ground(body, tags)
    assert 2750000 - 220000 not in g.exact and 2500000 + 250000 in g.exact | g.nums


# ---- 할 일 6: 안쪽 말 ----


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("자료를 더 확인하려 했는데 도구가 실패해서, 아직 알 수 없어요.", "안쪽 말"),
        ("도구 오류로 결과를 못 봤어요.", "안쪽 말"),
        ("서버 오류가 났어요.", "안쪽 말"),
        ("준비할 도구는 커터칼과 헤라예요.", None),
        ("도구를 챙겨 두세요.", None),
    ],
)
def test_tool_failure_is_inside_talk(text, why):
    assert policy.inside(text) == why


# ---- 턴(Claude 대본) ----


def test_turn_keeps_a_list_answer_whole_and_one_question(api, script):
    _, pid = home(api, "a2-list@mitjip.test")
    script([{"text": "안녕하세요! 무엇을 도와드릴까요?"}])
    ok(ask(api, pid, "안녕하세요"))  # 대화 첫 답(LONG 상한)은 지나간다
    script(
        [
            {
                "text": "끝나고 해요. 입주 청소는 도배와 건조가 끝난 뒤에 해요. 주말이면 더 편해요. "
                "이사 전에 여유가 있어요.\n준비물은 이래요.\n- 고무장갑\n- 걸레\n- 중성세제\n"
                "업체 [채팅 열기]로 알려 주세요. 다른 것도 볼까요?"
            }
        ]
    )
    ev = ok(ask(api, pid, "입주 청소는 언제 해요? 뭘 준비해요?"))
    text = tokens(ev)
    # 넷 + 묶음 넷(머리 · 세 줄)이 상한을 넘어 묶음째 빠지고, 넘친 뒤는 마지막 묻는 말만(QA r3 c1 21턴 '- 고무장갑'에서 끊김)
    assert text == (
        "끝나고 해요. 입주 청소는 도배와 건조가 끝난 뒤에 해요. 주말이면 더 편해요. "
        "이사 전에 여유가 있어요. 다른 것도 볼까요?"
    )
    trace = json.loads(turn_row(ev[0][1]["turn_id"])["trace"])
    assert trace["cut"] == 5 and "길이 상한" in trace["dropped"]


def test_turn_allows_the_date_of_the_card_it_made(api, script):
    """제안 도구가 만든 승인 카드 요약의 날짜는 글에서도 쓸 수 있다(QA r3 s2 9턴)."""
    _, pid = home(api, "a2-date@mitjip.test")
    want = date.fromisoformat(START) + timedelta(days=7)
    script(
        [
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_home_info",
                        "input": {"fields": {"start_date": want.isoformat()}},
                    }
                ]
            },
            {
                "text": f"{want.month}월 {want.day}일로 넣은 카드를 만들었어요. 맞으면 저장해 주세요."
            },
        ]
    )
    ev = ok(ask(api, pid, "한 주 늦게 시작할래요"))
    assert proposed(ev)
    assert tokens(ev).startswith(f"{want.month}월 {want.day}일로 넣은 카드를 만들었어요.")


def test_turn_drops_the_repeated_closing_question_across_turns(api, script):
    """QA r3 c3 2~5번: 같은 끝 질문(한 낱말 차이)이 턴마다 되풀이되지 않는다."""
    _, pid = home(api, "a2-repeat@mitjip.test")
    ends = [
        "이어서 실측 요청할 업체를 보여 드릴까요?",
        "이어서 실측 요청할 도배 업체를 보여 드릴까요?",  # '도배' 더함
        "실측 요청할 업체를 보여 드릴까요?",  # '이어서' 뺌
    ]
    got = []
    for n, end in enumerate(ends):
        script([{"text": f"{n + 1}번째 답이에요. {end}"}])
        got.append(tokens(ok(ask(api, pid, f"{n + 1}번째 물음이에요"))))
    assert got[0].endswith(ends[0])
    # 되풀이한 끝 질문은 빼요. 다음 걸음이 없어진 2번째 답에는 지금 할 일 줄이 같은 단계에서 한 번 붙어요(QA r6 c3 M8)
    assert got[1].startswith("2번째 답이에요.") and "보여 드릴까요" not in got[1]
    assert got[1].rstrip().endswith("차례예요.") and got[2] == "3번째 답이에요."
    (saved,) = query(
        "select text from chat_messages where role = 'assistant' order by created_at desc limit 1"
    )
    assert saved["text"] == "3번째 답이에요."


def test_vendor_turn_uses_the_same_gate(api, script):
    """업체 턴도 같은 문장 검사(한자 · 길이 상한)를 지난다(QA r3 c6 T18)."""
    approved_vendor(api, f"a2-vendor-{uuid.uuid4().hex[:6]}@mitjip.test")
    long = "".join(f"{n}번째 말이에요. " for n in range(1, 10))
    script(
        [{"text": "一이 결과엔 고객이 직접 할 일 칸이 없어요. " + long + "오늘 할 일을 볼까요?"}]
    )
    body = {"client_key": uuid.uuid4().hex, "text": "이 공사 고객이 직접 하는 거 있어?"}
    ev = ok(api.post("/vendor/assistant/turns", json=body))
    text = "".join(d["text"] for e, d, _ in ev if e == "token")
    assert text.startswith("이 결과엔 고객이 직접 할 일 칸이 없어요.")
    assert "一" not in text and text.endswith("오늘 할 일을 볼까요?")
    assert text.count("말이에요.") == policy.LONG_LEAD - 1  # 대화 첫 답: 8문장 상한(첫 문장 포함)
