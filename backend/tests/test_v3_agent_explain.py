"""설명 · 우리 집 조건 질문(explain.kind): 일반 설명 섞기 · 공종 블록 · 개요만 먼저 · 확인할 곳 줄. 스텁만 써서 유료 호출 0회."""

import asyncio
import uuid
from datetime import date

import pytest
from v3_kb import repo_kb

from app.agent import llm
from app.agent.v3 import explain, templates
from app.agent.v3.composer import CBlock, CItem, Composed
from app.agent.v3.schemas import TurnContext
from app.agent.v3.turn import run_turn

OVERVIEW_Q = "인테리어할때 도배 목공 공정이 뭐야 설명해줘"
HOUSE_Q = "우리 집 벽에 곰팡이가 좀 있는데 도배해도 될까?"


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(llm, "_stubs", {})

    def put(c: Composed) -> None:
        llm.set_stub("composer", c)

    return put


def turn(q: str, mode: str = "llm"):
    ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 20), mode=mode)  # type: ignore[arg-type]
    return asyncio.run(run_turn(q, ctx, kb=repo_kb())).answer


@pytest.mark.parametrize(
    ("q", "trades", "policy", "want"),
    [
        (OVERVIEW_Q, ["dobae", "mokgong"], [], "explain"),
        ("실크벽지랑 합지벽지 차이가 뭐예요?", ["dobae"], [], "explain"),
        ("저희 집 몰딩 바꿔야 할까?", ["mokgong"], [], "house"),
        (HOUSE_Q, ["dobae"], ["my_house"], "house"),
        ("오래된 아파트인데 초배 꼭 해야 해?", ["dobae"], [], "house"),
        ("도배 얼마야?", ["dobae"], ["price"], None),  # 금액 · 기간은 계산 엔진이 답해요
        ("우리 집 도배 며칠 걸려?", ["dobae"], ["period"], None),
        ("도배 업체 어디가 좋아?", ["dobae"], ["vendor_reco"], None),
        ("목공할 때 콘센트 위치 옮길 수 있어?", ["mokgong"], [], None),  # 위험한 작업
    ],
)
def test_kind_of_question(q, trades, policy, want):
    assert explain.kind(q, "trade", trades, policy) == want


def test_kind_only_for_dobae_mokgong_trade_routes():
    assert explain.kind("필름은 뭐예요?", "trade", ["film"], []) is None
    assert explain.kind("도배가 뭐예요?", "guide", ["dobae"], []) is None


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("목공이 끝난 뒤 도배해요.", True),
        ("도배는 목공이 끝난 뒤에 해요.", True),
        ("목공은 철거 · 전기 바로 다음에 들어가요.", True),
        ("도배 전에 목공 · 필름 · 도장을 끝내요.", True),
        ("철거, 전기, 목공, 도배 순서로 해요.", True),
        ("도배는 거의 마지막 단계예요.", True),
        ("목공과 도배는 같은 날 하지 않아요.", True),
        ("도배 다음에 목공을 해요.", False),
        ("목공은 도배가 끝난 뒤에 해요.", False),
        ("도배, 목공 순서로 해요.", False),
        ("마루는 도배 전에 깔아요.", False),  # 믿집 순서는 도배 → 바닥(근거 조각을 인용하면 써요)
        ("도배는 맨 마지막 공정이에요.", False),  # 바닥 · 주방이 뒤예요
    ],
)
def test_order_ok_follows_trade_order(text, ok):
    assert explain.order_ok(text) is ok


def test_facts_come_from_code_data():
    items = explain.facts(["dobae", "mokgong"])
    assert [x["ref"] for x in items] == [
        "rule:trade-order",
        "rule:trade.dobae",
        "rule:trade.mokgong",
    ]
    assert "목공 → 타일 · 욕실 → 도장 · 필름 → 도배 → 바닥" in items[0]["글"]
    assert "퍼티작업" in items[1]["글"] and "저가형은 합지" in items[1]["글"]
    assert "방문은 문짝만 바꿀지 문틀까지 바꿀지" in items[2]["글"] and "자재" not in items[2]["글"]
    assert "바꿔요 · 그대로 둬요" not in items[2]["글"], (
        "단추 이름을 근거에 넣지 않아요(옮겨 쓰지 않게)"
    )


def overview_stub(stub) -> None:
    stub(Composed(
        new=["목공은 틀을 잡아요", "도배는 마감이에요"],
        verdict="answer",
        lead=CItem(text="쉽게 말하면 목공은 집의 틀을 잡고, 도배는 거의 마지막에 벽지로 마감해요.", cites=[]),
        blocks=[
            CBlock(kind="body", trade="mokgong", rows=[], items=[
                CItem(text="나무 각재와 석고보드로 벽 · 천장의 틀을 잡고 문 · 몰딩을 다는 공정이에요.", cites=[]),
                CItem(text="몰딩을 바꿀지, 방문은 문짝만인지 문틀까지인지, 천장 평탄화를 할지 정해요.", cites=["rule:trade.mokgong"]),
                CItem(text="보통 하루나 이틀이면 끝나요.", cites=[]),  # 일반 설명에 숫자 말 → 빠짐
            ]),
            CBlock(kind="body", trade="dobae", rows=[], items=[
                CItem(text="벽 · 천장의 바탕을 고르고 초배지를 바른 뒤 겉 벽지를 붙이는 마감 공정이에요.", cites=[]),
                CItem(text="도배를 먼저 하고 그다음에 목공을 해요.", cites=[]),  # 순서 틀림 → 빠짐
                CItem(text="벽지는 저가형(합지)과 기본형(실크) 중에 고르고, 천장도 할지 정해요.", cites=["rule:trade.dobae"]),
            ]),
        ],
        follow=[],
    ))  # fmt: skip


def test_overview_mixes_general_and_cited_blocks_per_trade(stub):
    overview_stub(stub)
    a = turn(OVERVIEW_Q)
    assert a.trace.prompts == ["composer_v7"]
    lead = a.sections[0]
    assert (
        lead.source == "general"
        and lead.title == ""
        and lead.sentences[0].text.startswith("쉽게 말하면")
    )
    titles = [s.title for s in a.sections]
    assert "[목공]" in titles and "[도배]" in titles
    general = [x.text for s in a.sections if s.source == "general" for x in s.sentences]
    cited = [x for s in a.sections if s.source == "llm" for x in s.sentences]
    assert any("석고보드" in t for t in general)
    assert cited and all(x.cites for x in cited), "공정 정보로 받친 문장은 인용이 남아요"
    assert any(src["ref"].startswith("rule:trade.") for s in a.sections for src in s.sources)
    texts = [x.text for s in a.sections for x in s.sentences]
    assert "보통 하루나 이틀이면 끝나요." not in texts and "일반 설명: 숫자" in a.trace.dropped
    assert "도배를 먼저 하고 그다음에 목공을 해요." not in texts and "순서 틀림" in a.trace.dropped
    # 개념 설명이라 확인할 곳 줄을 붙이지 않고, 개요만 먼저 보이고 나머지는 '자세히'에 접어요
    assert a.unknown == []
    assert a.brief is not None and [x.text for x in a.brief.lines] == [lead.sentences[0].text]
    assert a.brief.more >= 4


def test_free_mode_overview_unchanged():
    a = turn(OVERVIEW_Q, "free")
    assert a.trace.prompts == [] and templates.UNKNOWN in a.unknown


def test_data_question_still_drops_uncited_sentence(stub):
    """설명 · 우리 집 꼴이 아니면(금액 질문) 인용 없는 문장은 지금처럼 근거 없는 문장으로 빼요."""
    from app.chat.tools import general_facts

    q = "34평 도배하면 며칠 걸려요?"
    stub(Composed(
        new=["짐이 많으면 더 걸려요"], verdict="answer", lead=CItem(text="짐이 많으면 옮기는 만큼 더 걸려요.", cites=[]),
        blocks=[], follow=[],
    ))  # fmt: skip
    ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 20), mode="llm")
    a = asyncio.run(run_turn(q, ctx, kb=repo_kb(), general=general_facts(q))).answer
    assert not any(s.source == "general" for s in a.sections)


def test_house_question_answers_first_and_ends_with_where_line(stub):
    stub(Composed(
        new=["곰팡이가 조금이면 없애고 말린 뒤 도배해요"],
        verdict="answer",
        lead=CItem(text="곰팡이가 조금 핀 정도면 없애고 말린 뒤 도배하는 편이에요.", cites=[]),
        blocks=[CBlock(kind="body", rows=[], items=[
            CItem(text="넓게 번졌거나 같은 자리에 자꾸 생기면 결로 원인부터 잡아야 해요.", cites=[]),
        ])],
        follow=[],
    ))  # fmt: skip
    a = turn(HOUSE_Q)
    texts = [x.text for s in a.sections for x in s.sentences]
    assert texts[0].startswith("곰팡이가 조금 핀 정도면")
    assert templates.MY_HOUSE not in texts, "집 상태 안내는 먼저 보이지 않아요"
    assert a.unknown == [templates.UNKNOWN_WHERE.format(where="실측 때 업체")]
    assert a.brief is None  # 우리 집 꼴은 짧아서 접지 않아요


def test_house_question_keeps_my_house_line_when_composer_fails(stub):
    a = turn(HOUSE_Q)  # 스텁 없음 = 작성기 실패
    assert "작성기 실패" in a.trace.dropped
    assert templates.MY_HOUSE in a.unknown


def test_house_answer_drops_hedges_and_deferrals(stub):
    """우리 집 꼴은 대략 답을 하는 자리라 '상태에 따라 달라요' · '상담 때 정해요'만 하는 문장은 빼요."""
    good = "몰딩이 깨지거나 들뜨고 색이 바랬다면 바꾸는 편이에요."
    stub(Composed(
        new=["깨지거나 색이 바래면 바꿔요"],
        verdict="answer",
        lead=CItem(text="몰딩을 바꿀지는 집의 몰딩 상태에 따라 달라요.", cites=[]),
        blocks=[CBlock(kind="body", rows=[], items=[
            CItem(text=good, cites=[]),
            CItem(text="몰딩을 바꿀지는 목공 상담 때 정해요.", cites=[]),
            CItem(text="믿집 목공 상담에서는 몰딩도 바꿀지 정해요.", cites=["rule:trade.mokgong"]),
        ])],
        follow=[],
    ))  # fmt: skip
    a = turn("저희 집 몰딩 바꿔야 할까?")
    texts = [x.text for s in a.sections for x in s.sentences]
    assert texts == [good]
    assert "뻔한 말" in a.trace.dropped and "미루는 말" in a.trace.dropped


def test_middle_dots_are_spaced_like_screen_text():
    from app.agent.v3.composer import _dots

    c = Composed(
        verdict="answer", lead=CItem(text="문선·몰딩 ·걸레받이", cites=[]), follow=[],
        blocks=[CBlock(kind="compare", items=[], rows=[["값·시공", "합지·실크"]])],
    )  # fmt: skip
    d = _dots(c)
    assert d.lead.text == "문선 · 몰딩 · 걸레받이" and d.blocks[0].rows == [
        ["값 · 시공", "합지 · 실크"]
    ]
