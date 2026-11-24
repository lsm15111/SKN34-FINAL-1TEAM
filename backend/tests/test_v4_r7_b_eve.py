"""QA r7 c4 10(r6부터): 공사 전날 준비물 카드에 목공 없는 공사의 '목공이 끝난 뒤에 도배해요' · 곰팡이를 말한 적 없는 집의
'곰팡이 · 습기가 있는 벽은 바탕부터' 줄이 나오고, 12월 빈 집인데 보일러 줄이 없었어요. 이 공사 공정 · 모은 조건 곰팡이 ·
빈 집 · 추운 철에 맞는 줄만 나와요. 유료 호출 0회."""

import uuid
from datetime import date

import pytest
from v3_kb import repo_index

from app.agent.v3.trades import BY_CODE
from app.assistant.tools import aftercare, cards
from app.assistant.tools import diy as diy_tools
from tests.conftest import query
from tests.test_dates import days
from tests.test_v4_assistant_diy import TODAY, as_owner, dobae_in

WOOD, MOLD = BY_CODE["dobae"].cautions  # 목공 순서 · 곰팡이 바탕


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def labels(card) -> list[str]:
    return [x["label"] for x in card.data["checklist"]]


def test_eve_card_keeps_only_cautions_that_fit_this_work_and_home():
    assert "목공" in WOOD and "곰팡이" in MOLD  # 공정 설정 줄이 있어야 이 시험이 뜻이 있어요
    # c4: 도배만 하는 빈 집 · 곰팡이를 말한 적 없음 → 두 줄 다 없어요
    only = cards.prep_card("p", ["dobae"], cards.HomeCtx(occupied=False, trades=("dobae",)))
    assert WOOD not in only.data["lines"] and MOLD not in only.data["lines"]
    # 목공도 하는 공사 · 곰팡이 있어요(모은 조건)면 그대로
    both = cards.HomeCtx(trades=("dobae", "mokgong"), mold=True)
    lines = cards.prep_card("p", ["dobae"], both).data["lines"]
    assert WOOD in lines and MOLD in lines
    # 집을 모르면(home 없음) 예전처럼 다 보여요
    plain = cards.prep_card("p", ["dobae"]).data["lines"]
    assert WOOD in plain and MOLD in plain
    # 목공 카드의 '도배 · 필름보다 먼저'는 도배도 하는 공사면 남아요
    (first,) = BY_CODE["mokgong"].cautions
    wood = cards.prep_card("p", ["mokgong"], cards.HomeCtx(trades=("dobae", "mokgong")))
    assert first in wood.data["lines"]
    alone = cards.prep_card("p", ["mokgong"], cards.HomeCtx(trades=("mokgong",)))
    assert first not in alone.data["lines"]


def test_cold_empty_home_gets_the_boiler_line_on_both_cards():
    cold = cards.HomeCtx(occupied=False, cold=True, trades=("dobae",))
    eve = cards.prep_card("p", ["dobae"], cold)
    assert eve.data["lines"][0] == cards.COLD_LINE
    assert cards.COLD_ITEM in labels(eve) and cards.ENTRY_ITEM in labels(eve)
    week = aftercare.check_card("b", "before", ["dobae"], [], home=cold)
    assert cards.COLD_LINE in week.data["lines"] and cards.COLD_ITEM in labels(week)
    assert "보일러" in cards.COLD_LINE and not any(ch.isdigit() for ch in cards.COLD_LINE)
    # 따뜻한 철이거나 사는 집이면 보일러 줄은 없어요
    for h in (cards.HomeCtx(occupied=False), cards.HomeCtx(occupied=True, cold=True)):
        for card in (
            cards.prep_card("p", ["dobae"], h),
            aftercare.check_card("b", "before", ["dobae"], [], home=h),
        ):
            assert cards.COLD_LINE not in card.data["lines"] and cards.COLD_ITEM not in labels(card)


def test_home_ctx_reads_trades_mold_and_the_month_of_the_next_work_day(api, monkeypatch):
    _, pid, _did = dobae_in(api, 5)
    first = date.fromisoformat(days(5)[0])  # 수락한 공사 첫날(계산 엔진)

    def ctx():
        return as_owner(api, pid, lambda s, u: diy_tools.home_ctx(s, u, uuid.UUID(pid), TODAY))

    monkeypatch.setattr(cards, "COLD_MONTHS", frozenset({first.month}))
    h = ctx()
    assert h.trades == ("dobae",) and h.mold is False and h.cold is True
    query(
        "insert into project_conditions (id, project_id, trade, key, value)"
        " values ($1, $2, 'dobae', 'dobae.mold', '있어요')",
        uuid.uuid4(),
        uuid.UUID(pid),
    )
    monkeypatch.setattr(cards, "COLD_MONTHS", frozenset())
    h = ctx()
    assert h.mold is True and h.cold is False
