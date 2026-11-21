"""알아 두기(믿집이 계산하지 않는 공종) 숫자 검사: 계산 엔진 값에 없는 금액 · 기간(LLM이 쓴 글은 모든 숫자)이 든
문장을 뺀다(문장 단위). 회귀: 평가 dev 2쌍(욕실 덧방 · 방수 + 타일)에서 v3가 다른 공정 금액 · 수치를 말했다.
유료 호출 0회(작성기 스텁)."""

import asyncio
import re
import uuid
from datetime import date

import pytest
from v3_kb import repo_kb

from app.agent import llm
from app.agent.v3 import check
from app.agent.v3.composer import CBlock, CItem, Composed
from app.agent.v3.schemas import AgentAnswer, Section, Sentence, TurnContext
from app.agent.v3.turn import run_turn

DEV = {
    "set30:xc004": "화장실은 덧방이 낫다는데 맞는 말이에요?",
    "multi45:mt-009": "화장실 방수 다시 하고 타일까지 새로 하면 같이 맡기면 되나요?",
}
DIGIT = re.compile(r"\d")


def _final(*secs: Section, question: str = "", trades=("bath",)) -> list[str]:
    ans = check.final(AgentAnswer(sections=list(secs)), question=question, trades=list(trades))
    return [x.text for s in ans.sections for x in s.sentences]


def test_know_check_drops_money_and_period_outside_calc():
    money = "철거 후 시공은 덧방보다 50~80만 원 더 들어요."
    period = "철거 후 시공은 덧방보다 약 2일 더 걸려요."
    weight = "덧방 타일은 300~400kg 이상이라 기존 벽이 튼튼해야 해요."
    plain = "덧방은 기존 방수 상태에 기대요."
    card = Section(trade="bath", source="card", sentences=[Sentence(text=x) for x in (money, period, weight, plain)])  # fmt: skip
    assert _final(card) == [weight, plain]  # 카드 · 발췌: 금액 · 기간만 빼요(치수는 둬요)
    dropped = check.final(AgentAnswer(sections=[card]), trades=["bath"]).trace.dropped
    assert dropped == ["알아 두기 금액", "알아 두기 기간"]
    written = card.model_copy(update={"source": "llm", "trade": None})
    assert _final(written) == [plain]  # LLM이 쓴 글: 계산 값 밖 숫자는 모두 빼요
    asked = _final(written, question="300~400kg면 괜찮아요?")
    assert asked == [weight, plain]  # 고객 글의 숫자는 돼요
    own = Section(trade="dobae", source="card", sentences=[Sentence(text="도배는 2일 걸려요.")])
    assert _final(own, trades=("dobae",)) == ["도배는 2일 걸려요."]  # 도배 · 목공은 이 검사 밖
    mixed = Section(source="llm", sentences=[Sentence(text="도배는 2일 걸려요."), Sentence(text="장판은 2일 뒤 깔아요.")])  # fmt: skip
    assert _final(mixed, trades=("dobae", "floor")) == ["도배는 2일 걸려요."]
    # 계산 엔진 값(계산 묶음 글 · 계산 상자)에 있는 숫자는 알아 두기 글에서도 돼요
    days = Section(trade="bath", source="extract", sentences=[Sentence(text="욕실 철거는 2일 걸려요.")])  # fmt: skip
    assert _final(days) == []
    got = check.final(AgentAnswer(sections=[days]), calc="철거 2일", trades=["bath"])
    assert [x.text for s in got.sections for x in s.sentences] == ["욕실 철거는 2일 걸려요."]


def _composed(lead: tuple[str, str], *body: tuple[str, str]) -> Composed:
    return Composed(
        new=["새 사실"],
        verdict="answer",
        lead=CItem(text=lead[0], cites=[lead[1]]),
        blocks=[CBlock(kind="body", items=[CItem(text=t, cites=[r]) for t, r in body], rows=[])],
        follow=[],
    )


@pytest.mark.parametrize("qid", list(DEV))
def test_composer_drops_other_trade_numbers(qid, monkeypatch):
    """작성기가 근거 조각의 다른 공정 금액 · 기간 · 무게를 옮겨도 문장 단위로 빠지고, 숫자 없는 문장은 남아요."""
    monkeypatch.setattr(llm, "_stubs", {})
    keep = "덧방은 기존 방수 상태에 기대고, 철거 후 시공은 방수를 새로 할 수 있어요."
    money = "욕실 1개 기준 철거 후 시공은 덧방보다 약 2일 더 걸리고 비용은 50~80만 원 더 들어요."
    weight = "덧방 타일 무게는 300~400kg 이상이라 기존 타일 벽이 튼튼해야 해요."
    llm.set_stub("composer", _composed((keep, "K202"), (money, "K202"), (weight, "K200")))
    ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 21), mode="llm")
    a = asyncio.run(run_turn(DEV[qid], ctx, kb=repo_kb())).answer
    texts = [x.text for s in a.sections for x in s.sentences]
    assert a.trace.prompts == ["composer_v8"] and keep in texts
    assert not any(DIGIT.search(x) for x in texts), texts
    assert any(d.startswith("알아 두기 숫자") for d in a.trace.dropped), a.trace.dropped
