"""답 작성기(composer, LLM 모드): 블록 → Section, 출력 검사, 무료 답으로 되돌리기. 스텁만 써서 유료 호출 0회."""

import asyncio
import uuid
from datetime import date

import pytest
from v3_kb import repo_kb

from app.agent import llm
from app.agent.v3.composer import CBlock, CItem, Composed
from app.agent.v3.schemas import TurnContext
from app.agent.v3.turn import run_turn

Q = "실크벽지랑 합지벽지 차이가 뭐예요?"


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(llm, "_stubs", {})

    def put(c: Composed) -> None:
        llm.set_stub("composer", c)

    return put


def ctx(mode: str = "llm") -> TurnContext:
    return TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 19), mode=mode)  # type: ignore[arg-type]


def turn(q: str, mode: str = "llm", **kw):
    return asyncio.run(run_turn(q, ctx(mode), kb=repo_kb(), **kw))


def free_refs() -> tuple[list[str], list[str]]:
    a = turn(Q, "free").answer
    texts = [x.text for s in a.sections for x in s.sentences]
    refs = {c for s in a.sections for x in s.sentences for c in x.cites if c.startswith("K")}
    return texts, sorted(refs)


def test_blocks_become_sections_and_bad_numbers_are_dropped(stub):
    _, refs = free_refs()
    assert refs, "무료 답에 근거 조각이 있어야 시험이 돼요"
    k = refs[0]
    body = [
        CItem(text="오래 살 집이면 실크를 많이 골라요.", cites=[k]),
        CItem(text="실크는 합지보다 37% 비싸요.", cites=[k]),  # 근거에 없는 숫자 → 빠짐
    ]
    stub(
        Composed(
            verdict="answer",
            lead=CItem(text="실크는 코팅이 있어 관리가 쉽고, 합지는 값이 싸요.", cites=[k]),
            blocks=[
                CBlock(
                    kind="compare", items=[], rows=[["관리", "실크가 쉬움"], ["값", "합지가 쌈"]]
                ),
                CBlock(kind="body", items=body, rows=[]),
                CBlock(kind="caution", items=[CItem(text="초배를 꼭 해요.", cites=[k])], rows=[]),
            ],
            follow=["광폭 합지는 뭐예요?", "실크 3배 비싸요?"],
        )
    )
    a = turn(Q).answer
    assert a.trace.prompts == ["composer_v1"] and a.brief is None
    texts = [x.text for s in a.sections for x in s.sentences]
    assert texts[0].startswith("실크는 코팅이 있어")
    assert "실크는 합지보다 37% 비싸요." not in texts
    assert any(s.table == [["관리", "실크가 쉬움"], ["값", "합지가 쌈"]] for s in a.sections)
    assert a.sections[0].sources, "인용한 조각의 출처가 붙어요"
    assert a.suggest == ["광폭 합지는 뭐예요?"]  # 숫자 든 질문은 뺌
    assert any("숫자" in d for d in a.trace.dropped)


def test_unknown_verdict_keeps_free_answer(stub):
    free, _ = free_refs()
    stub(Composed(verdict="unknown", lead=CItem(text="모름", cites=[]), blocks=[], follow=[]))
    a = turn(Q).answer
    assert a.trace.prompts == []
    assert [x.text for s in a.sections for x in s.sentences] == free


def test_lead_with_made_up_number_falls_back_to_free(stub):
    _, refs = free_refs()
    lead = CItem(text="실크는 평당 4만 2천 원이에요.", cites=refs[:1])
    stub(Composed(verdict="answer", lead=lead, blocks=[], follow=[]))
    assert turn(Q).answer.trace.prompts == []


def test_composer_keeps_calc_section_first(stub):
    from app.chat.tools import general_facts

    q = "34평 도배하면 며칠 걸려요?"
    lead = CItem(text="짐이 많으면 옮기는 시간만큼 더 걸려요.", cites=[])
    stub(Composed(verdict="answer", lead=lead, blocks=[], follow=[]))
    a = turn(q, general=general_facts(q)).answer
    assert a.sections[0].source == "calc"
    assert any(x.text == lead.text for s in a.sections for x in s.sentences)


def test_composer_sentence_repeating_calc_numbers_is_dropped(stub):
    from app.chat.tools import general_facts

    q = "34평 도배하면 며칠 걸려요?"
    lead = CItem(
        text="믿집 계산으로 34평 빈집 도배는 약 2.5일이에요.", cites=[]
    )  # 계산 묶음 되풀이
    body = CItem(text="짐이 많으면 옮기는 시간만큼 더 걸려요.", cites=[])
    stub(Composed(verdict="answer", lead=lead, blocks=[CBlock(kind="body", items=[body], rows=[])], follow=[]))  # fmt: skip
    a = turn(q, general=general_facts(q)).answer
    texts = [x.text for s in a.sections for x in s.sentences]
    assert a.sections[0].source == "calc" and a.trace.prompts == ["composer_v1"]
    assert lead.text not in texts and body.text in texts
    assert "계산 되풀이" in a.trace.dropped
