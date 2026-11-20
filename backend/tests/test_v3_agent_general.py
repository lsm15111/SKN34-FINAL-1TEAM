"""일반 설명(LLM 모드, 믿집 자료 밖): 고르는 규칙 · 출력 검사 · 턴 연결. 스텁만 써서 유료 호출 0회."""

import asyncio
import uuid
from datetime import date

import pytest
from v3_kb import repo_kb

from app.agent import llm
from app.agent.v3 import general, orchestrator, templates
from app.agent.v3.answer import Part
from app.agent.v3.general import General
from app.agent.v3.schemas import TurnContext
from app.agent.v3.turn import run_turn

Q = "초배지는 어떻게 골라요?"
WHERE = templates.UNKNOWN_WHERE.format(where="실측 때 업체")


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(llm, "_stubs", {})  # 작성기 스텁은 없음 → 작성기 실패 → 일반 설명 차례

    def put(g: General) -> None:
        llm.set_stub("general", g)

    return put


@pytest.fixture
def no_data(monkeypatch):
    """믿집 자료가 없는 공종 답(모름 + 확인할 곳)만 돌려주는 담당."""

    def fake(task, kb):
        p = Part(route="trade", trade="dobae")
        p.unknown = [templates.UNKNOWN, WHERE]
        return p

    monkeypatch.setitem(orchestrator.AGENTS, "trade", fake)


def turn(q: str, mode: str = "llm"):
    ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 20), mode=mode)  # type: ignore[arg-type]
    return asyncio.run(run_turn(q, ctx, kb=repo_kb()))


@pytest.mark.parametrize(
    "q,ok",
    [
        ("초배지는 어떻게 골라요?", True),
        ("무몰딩 마감은 뭐예요?", True),
        ("합판이랑 MDF는 뭐가 달라요?", True),
        ("실크 도배 평당 얼마예요?", False),  # 숫자
        ("문틀 교체 며칠 걸려요?", False),
        ("벽지 몇 롤 필요해요?", False),
        ("도배 잘하는 업체 어디예요?", False),  # 업체
        ("어느 브랜드 벽지가 좋아요?", False),
        ("이음매가 벌어졌는데 하자인가요?", False),  # 하자
        ("도배 A/S는 어떻게 받아요?", False),
        ("도배 계약서에는 뭘 써야 해요?", False),  # 계약 · 법률
        ("콘센트 위치는 어떻게 옮겨요?", False),  # 위험한 작업
        ("베란다 방수는 어떻게 해요?", False),
        ("우리 집 벽 상태 좀 봐 주세요", False),
        ("도배", False),  # '무엇 · 어떻게'가 아님
    ],
)
def test_eligible_rules(q, ok):
    assert general.eligible(q, "trade", ["dobae"], []) is ok


def test_eligible_only_for_dobae_mokgong_trade_route():
    assert general.eligible(Q, "trade", ["mokgong"], [])
    assert not general.eligible(Q, "trade", ["bath"], [])
    assert not general.eligible(Q, "trade", ["dobae", "bath"], [])
    assert not general.eligible(Q, "guide", [], [])
    assert not general.eligible(Q, "multi", ["dobae", "mokgong"], [])
    assert not general.eligible(Q, "trade", ["dobae"], ["price"])


def test_output_with_numbers_vendor_or_judgement_is_dropped():
    dropped: list[str] = []
    g = General(
        ok=True, lead="초배지는 벽 상태와 겉 벽지에 맞춰 골라요.", kind="body",
        items=[
            "바탕이 고르지 않으면 부직포 초배를 많이 써요.",
            "보통 두 겹 붙이고 하루 말려요.",  # 숫자 말
            "도배 시공 3일 안에 생긴 들뜸은 하자예요.",  # 숫자 · 하자 판정
            "전기 배선이 지나는 벽은 피해요.",  # 위험 작업 낱말
        ],
    )  # fmt: skip
    secs = general.to_sections(g, route="trade", trade="dobae", dropped=dropped)
    assert [x.text for s in secs for x in s.sentences] == [
        "초배지는 벽 상태와 겉 벽지에 맞춰 골라요.",
        "바탕이 고르지 않으면 부직포 초배를 많이 써요.",
    ]
    assert all(s.source == "general" for s in secs)
    assert dropped.count("일반 설명: 숫자") == 2 and "일반 설명: 빼는 말" in dropped


def test_lead_with_number_means_no_general_answer():
    g = General(ok=True, lead="초배는 2번 해요.", kind="body", items=["바탕을 고르게 해요."])
    assert general.to_sections(g, route="trade", trade="dobae", dropped=[]) == []


def test_unknown_what_how_question_gets_general_explanation(stub, no_data):
    stub(General(
        ok=True, lead="초배지는 벽 상태와 겉 벽지에 맞춰 골라요.", kind="steps",
        items=["벽에 얼룩 · 요철이 있는지 봐요.", "바탕이 고르지 않으면 부직포 초배를 골라요.", "실측 때 업체와 같이 정해요."],
    ))  # fmt: skip
    a = turn(Q).answer
    assert a.trace.prompts == ["general_v1"]
    assert [s.source for s in a.sections] == ["general", "general"]
    assert a.sections[1].steps and len(a.sections[1].sentences) == 3
    assert a.unknown == [WHERE]  # '확인하지 못했어요'는 빼고 확인할 곳만 둬요


def test_general_declines_or_fails_keep_unknown_answer(stub, no_data):
    stub(General(ok=False, lead="", kind="body", items=[]))
    a = turn(Q).answer
    assert a.trace.prompts == [] and templates.UNKNOWN in a.unknown and not a.sections
    assert "일반 설명: 답하지 않음" in a.trace.dropped


def test_free_mode_and_excluded_questions_never_get_general(stub, no_data):
    stub(General(ok=True, lead="일반 설명이에요.", kind="body", items=[]))
    assert turn(Q, "free").answer.trace.prompts == []  # 무료 모드는 LLM 0회
    a = turn("어느 브랜드 초배지가 좋아요?").answer  # 브랜드
    assert a.trace.prompts == [] and not any(s.source == "general" for s in a.sections)
