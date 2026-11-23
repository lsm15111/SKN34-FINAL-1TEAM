"""고객 질문 10개(2026-11-23 '이런 질문들에 답변이 안돼'): AS 기간 답 길 · 표준견적서 근거(how) · 줄이는 길(save) ·
합계 밖 줄. 유료 호출 0회(대본 · 스텁). 실제 LLM 재현은 evaluation/v4/qa10_live.py.

- AS 기간: 모델이 'AS기간'을 period로 불러도 공정표 길(v3)이 아니라 일반 답 길로 가요(도커에서 타일 글 조각만 받았어요).
- 표준견적서 도구 값: 줄 수량 × 단가 글 · 합계 밖 줄(선택 · 실측 후) · how(평수 · 면적 · 벽지 평 · 품 · 기간 · 식대) ·
  save(벽지 종류는 두고 줄이는 길, 계산 엔진 금액). how 숫자로 쓴 답 문장은 숫자 검사를 지나요.
HOME: 공급 69.4㎡(21평) 실크 · 빈 집 → 방 2개, 도배 면적 148.4㎡(천장 51.9 · 벽 96.5), 품 4.138 × 0.91 = 3.765 → 4품.
"""

import json

import pytest

from app.assistant import policy
from app.assistant.tools import answer
from app.config import settings
from tests.test_v4_assistant_answer import _gate, _turn, repo_search, script  # noqa: F401
from tests.test_v4_assistant_copy_fixes import result_of
from tests.test_v4_assistant_offers import tokens
from tests.test_v4_assistant_turns import ask, home, ok


@pytest.mark.parametrize(
    ("kind", "q", "want"),
    [
        ("period", "AS기간은 보통 어떻게돼?", "general"),
        ("period", "A/S 기간은 얼마예요?", "general"),
        ("price", "하자 보수 비용은 누가 내요?", "general"),
        ("price", "환불은 얼마나 받아요?", "general"),
        ("period", "도배 기간은 며칠이에요?", "period"),
        ("price", "견적서 왜 이렇게 비싸?", "price"),
        ("process", "AS 받으려면 어떻게 해요?", "process"),  # 금액 · 기간 종류만 바꿔요
    ],
)
def test_kind_of_sends_warranty_questions_to_general(kind, q, want):
    assert answer.kind_of(kind, q) == want


@pytest.mark.parametrize(
    ("q", "want"),
    [
        ("AS기간은 보통 어떻게돼?", "하자 보수(A/S)기간은 보통 어떻게돼?"),
        (
            "도배 시공 AS 기간은 보통 어떻게 되나요?",
            "도배 시공 하자 보수(A/S) 기간은 보통 어떻게 되나요?",
        ),
        ("A/S는 몇 년이에요?", "하자 보수(A/S)는 몇 년이에요?"),
        ("as 기간 알려 줘", "하자 보수(A/S) 기간 알려 줘"),
        ("하자 AS 기간은요?", "하자 AS 기간은요?"),  # 이미 '하자'가 있으면 그대로
        ("GAS 배관 옮겨요?", "GAS 배관 옮겨요?"),  # 영어 낱말 안의 as는 아니에요
        ("도배 기간은 며칠이에요?", "도배 기간은 며칠이에요?"),
    ],
)
def test_search_words_spell_out_as(q, want):
    """'AS'만 쓴 질문은 '하자 보수(A/S)'로 바꿔 넘겨요(지식 조각이 '하자 · 보수'로 적혀 있어요). 바꾼 말도 하자 질문이라
    기간 · 금액 종류를 일반으로 돌려요."""
    got = answer.search_words(q)
    assert got == want
    if got != q:
        assert answer.kind_of("period", got) == "general"


def test_warranty_period_question_skips_schedule_route(api, script, monkeypatch, repo_search):  # noqa: F811
    """기본 길(period=v3 · price=v3 · 나머지 v2g+v3): AS 기간은 v2 근거, 공사 기간은 계산 엔진 값을 쓰는 v3예요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", "period=v3,price=v3,*=v2g+v3")
    _gate(monkeypatch, "trade")
    _, res = _turn(api, pid, script, "AS기간은 보통 어떻게돼?", "period")
    assert json.loads(res)["route"] == "v2g"
    _, res = _turn(api, pid, script, "도배 기간은 며칠이에요?", "period")
    assert json.loads(res)["route"] != "v2g"


HOW_ANSWER = (
    "벽 96.5㎡와 천장 51.9㎡에 표준품셈을 적용하면 약 4.14품이에요. "
    "시장 품 비 0.91을 곱해 약 3.77품이 되고, 0.5 단위로 올려 4품이에요."
)


def test_standard_tool_gives_how_save_and_outside_lines(api, script):  # noqa: F811
    _, pid = home(api)
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "s", "name": "get_standard_quote", "input": {"trade": "dobae"}}
                ]
            },
            {"text": HOW_ANSWER},
        ]
    )
    ev = ok(ask(api, pid, "인건비 4품은 어떻게 나온거야?"))
    got = result_of(log, 1)
    how = "\n".join(got["how"])
    assert "공급 69.4㎡ ÷ 3.3058 = 공급 21평" in how and "방 2개 × 20.4㎡ = 148.4㎡" in how
    assert "벽 96.5㎡ × 0.024 + 천장 51.9㎡ × 0.0351 = 약 4.14품" in how and "올려 4품" in how
    assert "식대를 따로 줄로 두지 않아요" in how  # 도배만 하는 공사 기준
    lines = {x["name"]: x for x in got["lines"]}
    assert lines["벽 도배 시공 (풀 포함)"]["text"] == "96.5㎡ × 5,993원(공급가)"
    assert (
        lines["부자재 (풀 · 부직포 · 네바리 · 실리콘 등)"]["text"] == "21 공급 평 × 6,900원(공급가)"
    )
    outside = {x["name"]: x for x in got["excluded"]}
    assert outside["퍼티작업 (사전퍼티 · 밑작업)"]["state"] == "선택(합계 밖)"
    assert outside["기존 벽지 철거"]["state"] == "실측 후(합계 밖)"
    saves = {x["name"]: x for x in got["save"]}
    assert {"천장 빼고 벽만", "벽지 직접 구매", "부분 공사", "업체 견주기"} <= set(saves)
    walls = saves["천장 빼고 벽만"]
    assert walls["total"] + walls["diff_won"] == got["total"]  # 바꾼 합계 + 줄어드는 돈 = 지금 합계
    assert f"{walls['total']:,}원(부가세 포함)으로 {walls['diff_won']:,}원 줄어요" in walls["text"]
    paper = got["paper"]["rows"][0]["won"]  # 벽지 값(부가세 포함) = 벽지 직접 구매로 줄어드는 돈
    assert saves["벽지 직접 구매"]["diff_won"] == paper
    assert "빈 집에서 공사" not in saves  # 이미 빈 집
    # how 숫자로 쓴 문장은 숫자 검사를 지나요. 다음 걸음 없는 답이라 끝에 지금 할 일 줄이 붙어요(QA r6 c3 M8)
    got_text = tokens(ev)
    assert got_text.startswith(HOW_ANSWER) and got_text.rstrip().endswith("차례예요."), got_text


def test_how_and_save_pass_the_model_filter():
    assert {"how", "save"} <= policy.ALLOWED
    v = policy.to_model(
        {"how": ["품은 4품이에요."], "save": [{"name": "x", "diff_won": 1, "text": "y"}]}
    )
    assert v["how"] == ["품은 4품이에요."] and v["save"][0]["diff_won"] == 1
