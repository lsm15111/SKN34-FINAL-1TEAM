"""질문 분석기 + 화면 도구 + 작성기 화면 꼴(LLM 모드 데이터 화면, docs/v3/agent-orchestrator.md 3단계).
스텁만 써서 유료 호출 0회. 화면 사실은 test_v3_agent_quote_screen과 같은 값(3300 마루와벽 가견적)."""

import asyncio
import re
import uuid
from datetime import date

import pytest
from test_v3_agent_quote_screen import _facts
from v3_kb import repo_kb

from app.agent import llm
from app.agent.v3 import planner, screen_tools, templates
from app.agent.v3.composer import CBlock, CItem, Composed
from app.agent.v3.planner import Ask, Plan
from app.agent.v3.schemas import ProjectFacts, ScreenFacts, StandardLineFact, TurnContext
from app.agent.v3.turn import run_turn


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(llm, "_stubs", {})
    return llm.set_stub


def ctx(view: str = "vendor", mode: str = "llm") -> TurnContext:
    return TurnContext(
        user_id=uuid.UUID(int=1), project_id=uuid.UUID(int=2), view=view,  # type: ignore[arg-type]
        today=date(2026, 11, 20), mode=mode,  # type: ignore[arg-type]
    )  # fmt: skip


def turn(q: str, facts: ProjectFacts, view: str = "vendor", on_part=None):
    return asyncio.run(run_turn(q, ctx(view), kb=repo_kb(), facts=facts, on_part=on_part)).answer


def std_facts() -> ProjectFacts:
    f = _facts(screen=False)
    f.screen = ScreenFacts(view="standard")
    return f


def texts(a) -> list[str]:
    return [x.text for s in a.sections for x in s.sentences]


def test_items_are_screen_lines_without_numbers():
    v = planner.items_of("vendor", _facts())
    assert [x["key"] for x in v][:3] == ["vendor.paper_silk", "vendor.material", "vendor.labor"]
    assert {"key": "vendor.truck", "name": "운송비", "뜻": "표준견적서에 없는 줄"} in v
    s = planner.items_of("standard", std_facts())
    assert s[0]["key"] == "standard.wall" and "시공비" in s[0]["뜻"]
    # 금액 · 수량은 넘기지 않아요(뜻 글의 '1명이 하루' 같은 정의 말은 괜찮아요)
    assert not any(re.search(r"\d{2,}|\d원|,\d", x["뜻"]) for x in [*v, *s])
    assert planner.items_of("plan", _facts()) == []


def test_vendor_items_say_optional_lines_are_outside_the_total():
    """판 2026.11b(ADR 0006): 도배만 하는 공사 기준의 퍼티 · 운송비는 표준견적서에도 '선택' 줄이라 '표준견적서에 없는 줄'이
    아니에요. 식대는 표준견적서에 줄이 없어 그대로예요."""
    f = _facts()
    assert f.screen is not None and f.screen.vendor is not None
    for x in f.screen.vendor.lines:
        x.optional = x.key in ("putty", "truck")
    got = {x["key"]: x["뜻"] for x in planner.items_of("vendor", f)}
    assert got["vendor.truck"] == "표준견적서에도 있는 선택 줄 · 합계 밖"
    assert got["vendor.putty"] == "사전퍼티 또는 밀작업 · 표준견적서에도 있는 선택 줄 · 합계 밖"
    assert got["vendor.meal"] == "표준견적서에 없는 줄"
    assert got["vendor.labor"] == "품 = 1명이 하루 하는 일"  # 줄 뜻이 있으면 그대로
    assert not any("표준견적서에 없는" in got[k] for k in ("vendor.putty", "vendor.truck"))


def test_standard_items_explain_profile_lines():
    """조건별 두 기준 판의 새 표준 줄(부자재 · 퍼티 · 식대 · 운송 · 경비)도 짧은 해요체 뜻이 붙어요."""
    names = {"material": "부자재", "putty": "퍼티작업", "meal": "식대", "truck": "운송 · 경비"}
    f = std_facts()
    assert f.standard is not None
    f.standard.lines = [
        StandardLineFact(
            key=k, name=n, state="included", qty=1.0, unit="식", unit_price=1, amount=1
        )
        for k, n in names.items()
    ]
    got = {x["key"]: x["뜻"] for x in planner.items_of("standard", f)}
    for k in names:
        meaning = planner.STANDARD_MEANING[k]
        assert meaning.endswith("요") and got[f"standard.{k}"].startswith(meaning), k
    assert "밥값" in got["standard.meal"] and "합계에 들어감" in got["standard.meal"]
    assert not any(re.search(r"\d{2,}|\d원|,\d", x) for x in got.values())


def test_clean_drops_unknown_items_and_caps_pieces():
    p = Plan(
        asks=[Ask(text=f"질문{i}", kind="line", items=["vendor.truck", "vendor.made_up"], trades=["dobae"])
              for i in range(5)],
        out_of_scope=False,
    )  # fmt: skip
    c = planner.clean(p, "원래 질문", {"vendor.truck"})
    assert c is not None and len(c.asks) == planner.MAX_ASKS
    assert all(a.items == ["vendor.truck"] for a in c.asks)
    assert planner.clean(Plan(asks=[], out_of_scope=False), "q", set()) is None


def test_screen_text_lists_lines_by_amount_with_market_and_other_vendors():
    f = _facts()
    t = screen_tools.screen_text("vendor", f)
    assert t is not None and t["ref"] == "rule:screen"
    body = t["글"]
    first = body.index("- 인건비"), body.index("- 실크벽지"), body.index("- 퍼티작업")
    assert first == tuple(sorted(first)), "금액 큰 순서"
    assert "4.5 품 × 300,000원 = 1,350,000원" in body
    assert "합지(저가형)으로 바꾸면 합계가 −266,805원" in body
    assert "실견적 279건" in body and "표준견적서에 없는 줄" in body
    s = screen_tools.screen_text("standard", std_facts())
    assert s is not None and "실측 뒤 업체가 정함" in s["글"] and "1,802,374원" in s["글"]
    # 표준견적서와 견준 %는 '보는 화면' 글에 없어요(사용자 결정 2026-11-21)
    for text in (body, s["글"]):
        assert "표준견적서보다" not in text and "30.3%" not in text and "%" not in text


def plan_stub(stub, *asks: Ask) -> None:
    stub("planner", Plan(asks=list(asks), out_of_scope=False))


def test_judge_and_rank_answer_from_screen_numbers(stub):
    """판단 · 순위 질문: 분석 → 비교 도구(고정 몫) → 작성기가 보는 화면 숫자로 판단해요. 지어낸 숫자는 빠져요."""
    plan_stub(
        stub,
        Ask(text="마루와벽 가견적이 괜찮은 편인가요?", kind="judge", items=[], trades=["dobae"]),
        Ask(
            text="마루와벽 가견적에서 가장 비싼 줄은 무엇인가요?",
            kind="rank",
            items=[],
            trades=["dobae"],
        ),
    )
    judge = "실크벽지 단가 9,500원은 모은 실견적 평균 10,749원보다 낮은 편이에요."
    top = "가장 비싼 줄은 인건비 1,350,000원이에요."
    made_up = "인건비가 전체의 46%를 차지해요."
    stub("composer", Composed(
        new=["인건비가 가장 커요"], verdict="answer",
        lead=CItem(text="벽지 값은 낮은 편이지만 따로 받는 줄 때문에 표준보다 30.3% 많아요.", cites=["rule:screen"]),
        blocks=[CBlock(kind="body", rows=[], items=[
            CItem(text=judge, cites=["rule:screen"]), CItem(text=top, cites=["rule:screen"]),
            CItem(text=made_up, cites=["rule:screen"]),
        ])],
        follow=[],
    ))  # fmt: skip
    got = []

    async def on_part(a):
        got.append(a)

    a = turn("이 견적 괜찮은 거야? 제일 비싼 건 뭐고?", _facts(), on_part=on_part)
    assert a.trace.prompts == ["planner_v1", "composer_v9"]
    assert a.trace.parts == ["quote_explanation:compare"]
    # 비교 도구의 고정 몫(정해 둔 글 · 계산 상자)이 먼저 보이고, 그 아래 작성기 글이 붙어요
    assert (
        got
        and got[0].sections
        and got[0].sections[0].sentences[0].text == templates.SCREEN_COMPARE_SAME
    )
    t = texts(a)
    assert judge in t and top in t and made_up not in t
    # 작성기가 표준 대비 %를 써도 보는 화면에 그 숫자가 없어 숫자 검사에서 빠져요(사용자 결정 2026-11-21)
    assert not [x for x in t if "표준보다" in x or "30.3" in x]
    assert any(src["ref"] == "rule:screen" for s in a.sections for src in s.sources)
    assert any(c.label == "마루와벽 가견적" for c in a.calc)
    assert a.unknown == []


def test_line_piece_uses_picked_item_not_text_matching(stub):
    """'밥값'처럼 줄 이름이 아닌 말도 분석기가 고른 항목(vendor.meal)으로 그 줄을 풀어요."""
    plan_stub(stub, Ask(text="마루와벽 가견적의 식대는 왜 따로 받아요?", kind="line", items=["vendor.meal"],
                        trades=["dobae"]))  # fmt: skip
    a = turn("밥값은 왜 받아?", _facts())
    assert a.trace.parts == ["quote_explanation:vendor.meal"]
    assert texts(a)[0].startswith("식대 줄은 마루와벽이 확인한 단가에")
    assert any(c.ref == "screen.vendor.lines.meal" for c in a.calc)


def test_standard_screen_line_piece(stub):
    plan_stub(stub, Ask(text="이 집 표준견적서에서 철거는 왜 합계에 없어요?", kind="line",
                        items=["standard.demolish"], trades=["dobae"]))  # fmt: skip
    a = turn("철거비는 왜 안 들어가?", std_facts(), view="standard")
    assert a.trace.parts == ["quote_explanation:standard.demolish"]
    assert any(c.ref == "standard.lines.demolish" for c in a.calc)


def test_planner_failure_keeps_current_route(stub):
    """분석 실패(스텁 없음)면 지금 관문 길 그대로예요."""
    a = turn("운송비는 왜 나오는거야?", _facts())
    assert "planner_v1" not in a.trace.prompts
    assert texts(a)[0].startswith("운송비 줄은 마루와벽이 확인한 단가에")


def test_no_planner_on_screens_without_data_or_in_free_mode(stub):
    plan_stub(stub, Ask(text="x", kind="rank", items=[], trades=["dobae"]))
    a = asyncio.run(run_turn("이 견적 괜찮아?", ctx("plan"), kb=repo_kb(), facts=_facts())).answer
    assert "planner_v1" not in a.trace.prompts
    free = asyncio.run(
        run_turn("이 견적 괜찮아?", ctx("vendor", "free"), kb=repo_kb(), facts=_facts())
    ).answer
    assert free.trace.prompts == []


def test_judgment_on_line_survives_repeat_filter_and_screen_numbers_get_cited(stub):
    """줄 판단('적당해?'): 고정 몫(줄 풀이 · 시장 기준값)과 같은 숫자를 써도 판단 말은 남아요.
    인용을 비운 문장도 숫자가 모두 보는 화면 값이면 화면 인용으로 남아요."""
    plan_stub(stub, Ask(text="마루와벽 인건비 4.5품이 적당한가요?", kind="judge", items=["vendor.labor"],
                        trades=["dobae"]))  # fmt: skip
    judge = "인건비 단가 300,000원은 모은 실견적 절반 범위 250,000원~290,000원보다 높은 편이에요."
    uncited = "식대는 1품에 11,000원씩 따로 받아요."
    stub("composer", Composed(
        new=["인건비 단가가 절반 범위보다 높아요"], verdict="answer",
        lead=CItem(text=judge, cites=["rule:screen"]),
        blocks=[CBlock(kind="body", rows=[], items=[CItem(text=uncited, cites=[])])],
        follow=[],
    ))  # fmt: skip
    a = turn("인건비 4.5품이면 적당해?", _facts())
    assert a.trace.parts == ["quote_explanation:vendor.labor"]
    t = texts(a)
    assert judge in t, a.trace.dropped
    assert uncited in t
    s = next(s for s in a.sections for x in s.sentences if x.text == uncited)
    assert s.source == "llm" and "rule:screen" in s.sentences[-1].cites
