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
            follow=["광폭 합지는 뭐예요?", "실크 3배 비싸요?", "몇 평인지 알려 주실래요?"],
        )
    )
    a = turn(Q).answer
    assert a.trace.prompts == ["composer_v3"] and a.brief is None
    texts = [x.text for s in a.sections for x in s.sentences]
    assert texts[0].startswith("실크는 코팅이 있어")
    assert "실크는 합지보다 37% 비싸요." not in texts
    assert any(s.table == [["관리", "실크가 쉬움"], ["값", "합지가 쌈"]] for s in a.sections)
    assert a.sections[0].sources, "인용한 조각의 출처가 붙어요"
    # 이어 묻기는 답할 수 있는 카드의 열쇠 질문으로 바꾸고, 숫자 든 말 · 고객에게 되묻는 말은 빼요
    assert a.suggest == ["광폭 합지와 소폭 합지는 뭐가 달라요?"]
    assert any(
        "숫자" in d or "인용" in d for d in a.trace.dropped
    )  # 근거에 없는 숫자 · 맞지 않는 인용


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


PERIOD_Q = "34평 도배하면 며칠 걸려요?"
PAINT = "도장과는 일정을 겹치지 않게 잡아요. 벽지 작업이 습해 페인트가 마르지 않을 수 있어요."


def period_stub(stub) -> None:
    """기간 질문(계산만 있는 답)에 덧붙일 글: 계산 숫자 되풀이 lead(빠짐) + 검색 위 조각 K182로 받친 문장."""
    stub(Composed(
        verdict="answer",
        lead=CItem(text="34평 도배는 빈집이면 약 2.5일이에요.", cites=[]),
        blocks=[CBlock(kind="body", rows=[], items=[CItem(text=PAINT, cites=["K182"])])],
        follow=[],
    ))  # fmt: skip


def test_calc_only_answer_gets_composer_context_after_calc(stub):
    """계산만 있는 답도 작성기를 불러요. 계산 묶음은 맨 앞에 그대로 두고, 작성기는 덧붙일 것만 써요(숫자 되풀이는 빠짐)."""
    from app.chat.tools import general_facts

    period_stub(stub)
    a = turn(PERIOD_Q, general=general_facts(PERIOD_Q)).answer
    assert a.trace.prompts == ["composer_v3"]
    assert a.sections[0].source == "calc"
    assert a.sections[0].sentences[0].text.startswith("믿집 계산으로 34평 도배는")
    assert [x.text for s in a.sections if s.source == "llm" for x in s.sentences] == [PAINT]
    assert "계산 되풀이" in a.trace.dropped


def test_llm_mode_sends_fixed_part_first_and_keeps_it_in_front(stub):
    """LLM 모드: 고정 몫(계산 결과 · 정해 둔 글)만 먼저 보내고, 마지막 답은 그 묶음을 그대로 앞에 둔 채 아래에 붙여요."""
    from app.chat.tools import general_facts

    period_stub(stub)
    got = []

    async def on_part(a):
        got.append(a)

    r = turn(PERIOD_Q, general=general_facts(PERIOD_Q), on_part=on_part)
    assert len(got) == 1
    first = got[0]
    assert [s.source for s in first.sections] == ["calc"]
    assert not (first.cards or first.calc or first.suggest or first.unknown or first.failed)
    n = len(first.sections)
    assert r.answer.sections[:n] == first.sections  # 화면에 이미 보인 글은 그대로
    assert len(r.answer.sections) > n and r.answer.brief is None
    assert first.fixed == r.answer.fixed == n
    assert r.answer.cards, "다음 단추 카드는 마지막 답에만 붙어요"


def test_part_is_sent_even_without_fixed_lines_and_free_mode_sends_none(stub):
    """고정 몫이 없어도 빈 part를 보내 화면이 'AI가 쓰는 중'을 알아요. 무료 모드는 보내지 않아요."""
    stub(Composed(verdict="unknown", lead=CItem(text="모름", cites=[]), blocks=[], follow=[]))
    got = []

    async def on_part(a):
        got.append(a)

    turn(Q, on_part=on_part)
    assert len(got) == 1 and got[0].sections == []
    turn(Q, "free", on_part=on_part)
    assert len(got) == 1


def test_compose_keeps_template_lines_first():
    """정해 둔 글(가이드 시작 순서 · 정책 줄)은 작성기 답에서도 원래 순서로 앞에 그대로 남아요."""
    from app.agent.v3 import composer
    from app.agent.v3.answer import Part
    from app.agent.v3.schemas import Section, Sentence

    fixed = Section(
        title="[시작 순서]", source="template", route="guide",
        sentences=[Sentence(text="처음이면 아래 순서로 하면 돼요."), Sentence(text="1. 기본 정보에 집 면적을 넣어요.")],
    )  # fmt: skip
    card = Section(
        source="card", route="guide",
        sentences=[Sentence(text="표준견적서는 공공 기준 단가로 계산한 참고 금액이라 업체 견적과 달라요.", cites=["card:t.std"])],
    )  # fmt: skip
    part = Part(sections=[fixed, card], route="guide")
    llm.set_stub("composer", Composed(
        verdict="answer", blocks=[], follow=[],
        lead=CItem(text="표준견적서는 업체 견적이 아니라 공공 기준으로 계산한 참고 금액이에요.", cites=["card:t.std"]),
    ))  # fmt: skip
    new = asyncio.run(composer.compose(part, repo_kb(), "처음이라 순서를 알고 싶어요", trade=None))
    assert new is not None
    assert [s.source for s in new.sections] == ["template", "llm"]
    assert new.sections[0] == fixed


def test_composer_drops_repeats_and_data_talk():
    """계산 숫자 되풀이 · 정해 둔 글 되풀이 · '자료로 확인하지 못했어요' 말은 빼고, 계산 묶음이 있으면 lead가 빠져도 이어 가요."""
    from app.agent.v3 import composer
    from app.agent.v3.answer import Part
    from app.agent.v3.schemas import Section, Sentence

    calc = Section(
        sentences=[Sentence(text="믿집 계산으로 34평 도배는 빈집이면 약 2.5일이에요.")],
        source="calc",
    )
    fixed = Section(
        sentences=[Sentence(text="벽 + 천장 전체를 반나절 단위로 센 작업 일수예요.")],
        source="template",
    )
    part = Part(sections=[calc, fixed], route="trade", trade="dobae")
    ev = {
        "refs": set(),
        "allowed": "믿집 계산으로 34평 도배는 빈집이면 약 2.5일이에요.",
        "calc": calc.sentences[0].text,
    }
    c = Composed(
        verdict="partial",
        lead=CItem(text="34평은 약 2.5일이에요.", cites=[]),  # 계산 숫자 되풀이
        blocks=[CBlock(kind="body", rows=[], items=[
            CItem(text="벽과 천장 전체를 반나절 단위로 센 작업 일수예요.", cites=[]),  # 정해 둔 글 되풀이
            CItem(text="문 교체 순서는 자료로 확인하지 못했어요.", cites=[]),  # 자료 말
            CItem(text="짐이 많으면 옮기는 시간만큼 더 걸려요.", cites=[]),
        ])],
        follow=[],
    )  # fmt: skip
    dropped: list[str] = []
    secs = composer.to_sections(c, ev, part, None, route="trade", trade="dobae", dropped=dropped)  # type: ignore[arg-type]
    texts = [x.text for s in secs or [] for x in s.sentences]
    assert texts == ["짐이 많으면 옮기는 시간만큼 더 걸려요."]
    assert {"계산 되풀이", "정해 둔 글 되풀이", "자료 말"} <= set(dropped)


def test_composer_drops_sentence_whose_cites_do_not_match(stub):
    """인용을 달았는데 그 조각과 글이 전혀 안 맞으면(겹침 0.18 미만) 문장을 빼요(장식용 출처 막기)."""
    _, refs = free_refs()
    k = refs[0]
    lead = CItem(text="실크는 코팅이 있어 관리가 쉽고, 합지는 값이 싸요.", cites=[k])
    odd = CItem(text="주차장 차단기는 관리사무소에서 등록해요.", cites=[k])  # 조각과 상관없는 글
    stub(Composed(verdict="answer", lead=lead, blocks=[CBlock(kind="body", items=[odd], rows=[])], follow=[]))  # fmt: skip
    a = turn(Q).answer
    texts = [x.text for s in a.sections for x in s.sentences]
    assert lead.text in texts and odd.text not in texts
    assert "인용 안 맞음" in a.trace.dropped


def test_composer_drops_paraphrased_fixed_lines_and_table_repeats():
    """먼저 보인 계산 문장을 말만 바꿔 되풀이한 문장(포함률 COVER 이상) · 계산 값을 다시 쓴 비교 표 줄 ·
    '~에 따라 달라요'만 덧붙인 뻔한 말은 빼요."""
    from app.agent.v3 import composer
    from app.agent.v3.answer import Part
    from app.agent.v3.schemas import Section, Sentence

    calc = Section(
        source="calc",
        sentences=[
            Sentence(text="믿집 표준견적서 계산으로 33평 전체 도배는 실크(기본형) 약 280만 원, 합지(저가형) 약 223만 원이에요."),
            Sentence(text="기존 벽지를 뜯는 시간은 들어 있지 않아요. 실측 뒤 업체가 정해요."),
        ],
    )  # fmt: skip
    part = Part(sections=[calc], route="trade", trade="dobae")
    text = " ".join(x.text for x in calc.sentences)
    ev = {"refs": set(), "allowed": text, "calc": text, "fixed": ""}
    new_line = "짐이 많으면 옮기는 시간만큼 더 걸려요."
    c = Composed(
        verdict="answer",
        lead=CItem(text="예상 일정에는 기존 벽지를 뜯는 시간이 포함되지 않으며, 실측 뒤 업체가 정해요.", cites=[]),
        blocks=[
            CBlock(kind="compare", items=[], rows=[["실크(기본형)", "약 280만 원"], ["합지(저가형)", "약 223만 원"]]),
            CBlock(kind="body", rows=[], items=[
                CItem(text=new_line, cites=[]),
                CItem(text="실크와 합지 중 벽지 종류에 따라 비용 차이가 있어요.", cites=[]),  # 뻔한 말
            ]),
        ],
        follow=[],
    )  # fmt: skip
    dropped: list[str] = []
    secs = composer.to_sections(
        c, ev, part, repo_kb(), route="trade", trade="dobae", dropped=dropped
    )
    assert [x.text for s in secs or [] for x in s.sentences] == [new_line]
    assert not any(s.table for s in secs or [])
    assert "정해 둔 글 되풀이" in dropped and dropped.count("계산 되풀이") == 2
    assert "뻔한 말" in dropped


def test_composer_drops_order_repeats_and_keeps_new_order_info():
    """고정 몫([기간] · [순서])이 이미 말한 '목공 다음 도배'를 말만 바꿔 쓴 작성기 문장은 빼고(3300 두 턴 답),
    새 정보가 든 문장은 남겨요. 남는 새 말이 없으면 작성기 묶음을 붙이지 않아요."""
    from app.agent.v3 import composer
    from app.agent.v3.answer import Part
    from app.agent.v3.schemas import Section, Sentence

    period = Section(source="calc", title="[기간]", sentences=[
        Sentence(text="믿집 계산으로 몰딩 · 걸레받이 목공과 도배는 빈집 기준 이만큼 걸려요."),
        Sentence(text="기본 정보를 넣으면 두 공정을 이어 붙인 예상 공정표 날짜로 잡아 드려요."),
    ])  # fmt: skip
    order = Section(
        source="template", title="[순서]", sentences=[Sentence(text="목공이 끝난 뒤 도배해요.")]
    )
    part = Part(sections=[period, order], route="multi")
    text = " ".join(x.text for s in (period, order) for x in s.sentences)
    ev = {"refs": set(), "allowed": text, "calc": text, "fixed": text}
    repeats = [
        "목공과 도배는 순서대로 진행해요.",
        "목공을 마친 뒤 도배하고, 실제 날짜는 공정표에서 확인해요.",
        "목공을 먼저 마친 뒤 도배를 이어서 진행해요.",
    ]
    new = "목공이 끝나면 몰딩 페인트가 다 마른 다음에 도배해야 벽지가 들뜨지 않아요."

    def run(lead: str, items: list[str]) -> tuple[list[str], list[str]]:
        body = CBlock(kind="body", rows=[], items=[CItem(text=t, cites=[]) for t in items])
        c = Composed(verdict="answer", lead=CItem(text=lead, cites=[]), blocks=[body], follow=[])
        dropped: list[str] = []
        secs = composer.to_sections(
            c, ev, part, repo_kb(), route="multi", trade=None, dropped=dropped
        )
        return [x.text for s in secs or [] for x in s.sentences], dropped

    kept, dropped = run(repeats[0], [*repeats[1:], new])
    assert kept == [new] and dropped.count("순서 되풀이") == 3
    assert run(repeats[0], repeats[1:])[0] == []  # 새 말이 없으면 작성기 묶음이 없어요


def test_composer_drops_date_restatements_and_same_day_order_talk():
    """날짜 대화(3300 '12월 1일부터 · 32평' → '목공도 같이 하면요?'): 계산 묶음이 보인 날짜 · 요일을 다시 말하거나
    '계산 결과는 ~ 기준이며'처럼 조건을 다는 문장, 순서에서 바로 나오는 '같은 날 안 해요'는 빼고 새 정보만 남겨요."""
    from app.agent.v3 import composer
    from app.agent.v3.answer import Part
    from app.agent.v3.schemas import Section, Sentence

    period = Section(source="calc", title="[기간]", sentences=[
        Sentence(text="믿집 계산으로 32평을 12.1(화)에 시작하면 목공은 12.1(화) ~ 12.3(목), 도배는 12.4(금) ~ 12.8(화)이에요(빈집 · 주말 · 공휴일 빼고)."),
        Sentence(text="자연 건조 · 입주 청소까지 넣으면 12.11(금)에 끝나요."),
    ])  # fmt: skip
    order = Section(
        source="template", title="[순서]", sentences=[Sentence(text="목공이 끝난 뒤 도배해요.")]
    )
    part = Part(sections=[period, order], route="multi")
    text = " ".join(x.text for s in (period, order) for x in s.sentences)
    ev = {"refs": set(), "allowed": text, "calc": text, "fixed": text}
    new = "목공에서 나온 톱밥과 먼지를 치운 뒤에 도배하면 벽지가 깨끗하게 붙어요."
    lead = "계산 결과는 12.1(화) 시작 기준이며, 12월 1일이 다른 요일이면 날짜를 확정하기 어려워요."
    same_day = "목공이 끝나야 도배할 수 있어 두 공정을 같은 날 진행하진 않아요."
    body = CBlock(
        kind="body", rows=[], items=[CItem(text=same_day, cites=[]), CItem(text=new, cites=[])]
    )
    c = Composed(verdict="answer", lead=CItem(text=lead, cites=[]), blocks=[body], follow=[])
    dropped: list[str] = []
    secs = composer.to_sections(c, ev, part, repo_kb(), route="multi", trade=None, dropped=dropped)
    assert [x.text for s in secs or [] for x in s.sentences] == [new]
    assert "날짜 되풀이" in dropped and "순서 되풀이" in dropped
