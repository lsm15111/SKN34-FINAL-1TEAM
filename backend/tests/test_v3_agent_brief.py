"""짧은 답(brief): 질문 꼴 · 예산 · 새 글 없음 · 정책 글 먼저 · 여러 공종 · 모름 (LLM 없음, DB 없음)."""

import asyncio
import uuid
from datetime import date

import pytest
from v3_kb import repo_kb

from app.agent.v3 import brief, templates
from app.agent.v3.schemas import AgentAnswer, Section, Sentence, Trace, TurnContext
from app.agent.v3.turn import run_turn

KB = repo_kb()
CTX = TurnContext(user_id=uuid.uuid4(), today=date(2026, 11, 19))


def turn(text):
    return asyncio.run(run_turn(text, CTX, kb=KB)).answer


@pytest.mark.parametrize(
    ("text", "form"),
    [
        ("실크 벽지가 뭐예요?", "define"),
        ("벽지에 곰팡이가 자꾸 생기는 이유가 뭐예요?", "cause"),  # '뭐예요'가 있어도 원인
        ("합지랑 실크 중에 뭐로 해야 해요?", "compare"),
        ("도배랑 장판 중에 어느 걸 먼저 해요?", "order"),
        ("계약금을 처음부터 너무 많이 달라는데 괜찮은 거예요?", "yesno"),
        ("도배 평당 얼마예요?", "price"),
        ("도배는 며칠 걸려요?", "period"),
        ("현관 도어락은 어느 회사 게 튼튼해요?", "reco"),
        ("이음매가 보이는데 이 정도면 하자인가요?", "defect"),
        ("셀프 도배는 어떻게 해요?", "howto"),
        (
            "실크벽지 위에 바로 페인트를 칠해도 붙을까요?",
            "yesno",
        ),  # 의문사 없는 '…요?'는 예 · 아니요
        ("화장실 고칠 때 욕조를 둘까요, 뺄까요?", "compare"),  # 둘 중 고르기
        ("전셋집 싱크대 문짝이 떨어졌는데 수리비는 누가 내요?", "other"),  # 의문사(누가) 물음
        ("음", "other"),
    ],
)
def test_question_forms(text, form):
    assert brief.form_of(text) == form


def _ans(*secs, route="trade"):
    return AgentAnswer(sections=list(secs), trace=Trace(route=route))


def _sec(*texts, source="card", title="", route="trade", trade="dobae"):
    return Section(
        sentences=[Sentence(text=t) for t in texts],
        source=source,
        title=title,
        route=route,
        trade=trade,
    )


def test_brief_only_reuses_checked_sentences_and_keeps_budget():
    a = _ans(_sec(
        "실크는 종이에 PVC 코팅을 입힌 벽지예요.",
        "합지는 종이 두 겹으로 만든 벽지라 값이 낮아요.",
        "실크는 물걸레로 닦을 수 있어요.",
        "벽 상태가 나쁘면 실크가 더 티가 나요.",
    ))  # fmt: skip
    b = brief.make(a, "실크 벽지가 뭐예요?")
    every = {x.text for s in a.sections for x in s.sentences}
    assert b.lines and {x.text for x in b.lines} <= every  # 새 글 없음
    n, chars = brief.BUDGET["define"]
    assert len(b.lines) <= n and sum(len(x.text) for x in b.lines) <= chars
    assert b.lines[0].text.startswith("실크는 종이에")  # 가장 맞는 문장이 맨 앞
    assert b.more == 4 - len(b.lines)


def test_policy_line_comes_first_for_reco_and_defect():
    a = _ans(
        _sec(templates.RECO_SHORT[templates.BRAND_RECO], source="template"),
        _sec("도어락은 문 두께에 맞는 것을 골라요."),
    )
    assert (
        brief.make(a, "도어락은 어느 회사 게 튼튼해요?").lines[0].text
        == "특정 제품 · 브랜드는 추천하지 않아요."
    )
    d = _ans(_sec(templates.DEFECT, source="template"), _sec("이음매는 마른 뒤에 다시 봐요."))
    assert brief.make(d, "이 정도면 하자인가요?").lines[0].text == templates.DEFECT


def test_multi_keeps_one_line_per_trade_and_the_failed_line():
    fold = templates.PART_FAILED_WHICH.format(which="필름")
    a = _ans(
        _sec(
            "목공이 끝난 뒤 도배해요.", source="template", title="[순서]", route="multi", trade=None
        ),
        _sec("도배는 네 단계로 해요.", "초배는 바탕을 고르는 일이에요."),
        _sec("몰딩은 길이로 값을 매겨요.", "몰딩은 문선과 같이 바꿔요.", trade="mokgong"),
        _sec(fold, source="template", route="multi", trade=None),
        route="multi",
    )
    b = brief.make(a, "몰딩이랑 도배 뭐부터 해요?")
    texts = [x.text for x in b.lines]
    assert texts[0] == "목공이 끝난 뒤 도배해요."  # 순서를 물었으니 순서 문장 먼저
    assert texts[-1] == fold  # 못 찾은 공종 한 줄은 늘 보인다
    assert any(t.startswith("도배") for t in texts) and any(t.startswith("몰딩") for t in texts)


def test_unknown_only_answer_uses_unknown_lines():
    a = AgentAnswer(unknown=[templates.UNKNOWN, "실측 때 업체에 물어보시면 정확해요."])
    b = brief.make(a, "벽지 밑에 하얀 천 같은 게 뭐예요?")
    assert [x.text for x in b.lines] == a.unknown and b.more == 0


def test_turn_attaches_brief_from_final_answer():
    a = turn("도배랑 장판만 바꾸는데도 관리사무소에 미리 신고해야 해요?")
    assert a.brief is not None and a.brief.lines
    every = {x.text for s in a.sections for x in s.sentences} | set(a.unknown)
    assert {x.text for x in a.brief.lines} <= every
    full = sum(len(x.text) for s in a.sections for x in s.sentences)
    assert sum(len(x.text) for x in a.brief.lines) < full


# ---- 비서에게 넘기는 평문(answer_only text, 말투 점검 docs/v4/06-answer-audit.md 5절 #5) ----
QUOTE = "“마루 찍힘은 가구를 설치하는 작업자 때문인 경우가 많다” (제조사 · [고급] 공사 중 손상된 마감재 복구하기)"
QUOTE_NOUN = "“벽지 이음매 처리 방법과 주의 사항” (시방서 · 도배 공사)"


def _short_ok(text: str) -> None:
    sents = brief.sentences(text)
    assert text and len(sents) <= brief.SHORT_SENTS and len(text) <= brief.SHORT_CHARS, text
    assert "[" not in text and "“" not in text and text.count("물어보시면 정확해요") <= 1, text


def test_short_text_drops_labels_quotes_and_repeated_notes():
    a = _ans(
        _sec(templates.EXTRACT_SUMMARY_LEAD, "도배는 가구를 들어낸 뒤 해요.", QUOTE_NOUN, title="[도배]", source="extract"),
        _sec("콘센트 위치는 도배 전에 정해요.", "전기 공사 업체에 물어보시면 정확해요.", title="[전기 · 알아 두기]", trade="electric"),
        _sec("욕실 공사 업체에 물어보시면 정확해요.", "욕실은 방수를 먼저 봐요.", title="[욕실 · 알아 두기]", trade="bath"),
    )  # fmt: skip
    got = brief.short_text(a)
    _short_ok(got)
    assert (
        got
        == "도배는 가구를 들어낸 뒤 해요. 콘센트 위치는 도배 전에 정해요. 전기 공사 업체에 물어보시면 정확해요."
    )
    a.brief = brief.make(a, "콘센트 위치는 언제 정해요?")  # 짧은 답이 있으면 그 문장(핵심)이 먼저
    assert brief.short_text(a).startswith("콘센트 위치는 도배 전에 정해요.")


def test_short_text_keeps_budget_quotes_as_hearsay_and_unknown_lines():
    s1 = "도배 전에는 가구를 방 가운데로 모으고 콘센트 덮개를 떼어 두면 작업이 훨씬 빨라지고 깔끔해요."
    s2 = "초배지는 벽 바탕의 작은 틈과 얼룩을 가려 주어서 실크 벽지가 들뜨거나 우는 일을 줄여 준다고 해요."
    s3 = "몰딩을 새로 달 계획이면 도배보다 먼저 끝내야 벽지 끝선을 몰딩에 맞춰 깔끔하게 마감할 수 있어요."
    s4 = "장판은 짧게 깔아요."
    got = brief.short_text(_ans(_sec(s1, s2, s3, s4)))
    _short_ok(got)
    assert brief.sentences(got) == [s1, s2, s4]  # 150자를 넘기는 문장은 건너뛰어요
    # 앞 문장을 되풀이하는 문장은 빼요
    echo = _ans(_sec(
        "마루는 도배 전에, 장판은 도배 뒤에 까는 경우가 많아요.",
        "마루는 도배 전에, 장판은 도배 뒤에 시공한다는 안내가 많아요.",
        "장판은 도배가 마른 뒤에 깔아요.",
    ))  # fmt: skip
    assert brief.short_text(echo) == (
        "마루는 도배 전에, 장판은 도배 뒤에 까는 경우가 많아요. 장판은 도배가 마른 뒤에 깔아요."
    )
    # 인용: 한 문장 '-다' 끝은 '…다고 해요'로, 못 바꾸면 빼고, 인용만 남으면 따옴표 · 출처만 떼요
    quoted = brief.short_text(
        _ans(_sec(templates.EXTRACT_LEAD, QUOTE, "사진을 남겨요.", source="extract"))
    )
    assert quoted == "마루 찍힘은 가구를 설치하는 작업자 때문인 경우가 많다고 해요. 사진을 남겨요."
    assert brief.hearsay("원인이다") == "원인이라고 해요." and brief.hearsay("시공합니다") is None
    assert brief.hearsay("하자가 아니다") == "하자가 아니라고 해요."
    assert brief.hearsay("기준입니다") is None
    assert brief.hearsay("먼저 붙인다. 그다음 말린다") is None
    assert (
        brief.short_text(_ans(_sec(QUOTE_NOUN, source="extract")))
        == "벽지 이음매 처리 방법과 주의 사항"
    )
    unknown = AgentAnswer(unknown=[templates.UNKNOWN, "실측 때 업체에 물어보시면 정확해요."])
    assert brief.short_text(unknown) == f"{templates.UNKNOWN} 실측 때 업체에 물어보시면 정확해요."
    # 근거 자료용(unquote): 따옴표 · 출처 괄호만 떼고, 같은 안내는 한 번
    lines = [
        templates.EXTRACT_SUMMARY_LEAD,
        QUOTE,
        "가 업체에 물어보시면 정확해요.",
        "나 업체에 물어보시면 정확해요.",
    ]
    assert brief.clean_lines(lines, unquote=True) == [
        "마루 찍힘은 가구를 설치하는 작업자 때문인 경우가 많다",
        "가 업체에 물어보시면 정확해요.",
    ]


def test_short_text_of_start_steps():
    """시작 순서: 지금 단계 줄이 있으면 그것만, 없으면 목록 표시 없이 앞 단계부터(한 줄로 이어도 '1.'이 문장이 되지 않게)."""
    steps = _sec(
        *templates.START_STEPS,
        source="template",
        title=brief.START_TITLE,
        route="guide",
        trade=None,
    )
    got = brief.short_text(_ans(steps, route="guide"))
    _short_ok(got)
    assert got.startswith("기본 정보에 집 면적과") and not any(c.isdigit() for c in got[:3])
    here = templates.START_HERE["vendors"]
    steps.sentences.append(Sentence(text=here))
    assert brief.short_text(_ans(steps, route="guide")) == here


@pytest.mark.parametrize(
    "text",
    [
        "도배랑 장판 같이 하면 어떤 걸 먼저 해요?",
        "욕실 타일이랑 도배 같이 하면 순서가 어떻게 돼요?",
        "합지랑 실크 중에 뭐로 해야 해요?",
        "마루 찍힘은 왜 생겨요?",
        "처음인데 뭐부터 해요?",
    ],
)
def test_short_text_of_free_turns(text):
    """무료 모드 턴의 평문: 세 문장 · 150자 안쪽, 이름표 · 인용 없음, 같은 안내 한 번."""
    _short_ok(brief.short_text(turn(text)))
