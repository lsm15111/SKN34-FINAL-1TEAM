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
