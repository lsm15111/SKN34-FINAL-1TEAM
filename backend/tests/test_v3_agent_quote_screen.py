"""보던 화면(업체 자세히)의 가견적 줄을 견적 설명이 읽어요. 값은 화면과 같은 계산 엔진 값(vendor_detail) 그대로.
3300 업체 화면 질문(2026-11-20): 부자재 · 인건비 · 식대 · 견주기. DB · LLM 없음."""

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from v3_kb import repo_kb

from app.agent.v3 import quote_explain, templates
from app.agent.v3.answer import Task
from app.agent.v3.schemas import (
    ProjectFacts,
    ScreenFacts,
    ScreenLineFact,
    StandardFacts,
    StandardLineFact,
    TurnContext,
    VendorScreenFacts,
)
from app.agent.v3.turn import run_turn
from app.chat.tools import vendor_screen

TODAY = date(2026, 11, 20)


def _standard() -> StandardFacts:
    ln = StandardLineFact
    return StandardFacts(
        total=1_802_374, supply=1_638_522, vat=163_852,
        lines=[
            ln(key="wall", name="벽 도배 시공 (풀 포함)", state="included", qty=96.5, unit="㎡",
               unit_price=5_993, amount=578_325),
            ln(key="ceiling", name="천장 도배 시공 (풀 포함)", state="included", qty=51.9, unit="㎡",
               unit_price=8_531, amount=442_759),
            ln(key="paper", name="실크벽지 시장 평균 가격", state="included", qty=53.9, unit="벽지 평",
               unit_price=10_749, amount=579_371),
            ln(key="demolish", name="기존 벽지 철거", state="after_visit", qty=148.4, unit="㎡",
               unit_price=1_727, amount=256_287),
            ln(key="waste", name="폐기물 처리", state="after_visit"),
        ],
    )  # fmt: skip


def _maru() -> VendorScreenFacts:
    ln = ScreenLineFact
    return VendorScreenFacts(
        vendor="마루와벽", grade="basic", total=2_920_005, supply=2_654_550, vat=265_455,
        vs_standard=30.3, grade_diff=-266_805,
        lines=[
            ln(key="paper_silk", name="실크", qty=53.9, unit="벽지 평", unit_price=9_500, amount=512_050,
               basis="벽지(도배지) 면적 1평(3.3058㎡)"),
            ln(key="material", name="부자재", qty=21, unit="공급 평", unit_price=13_000, amount=273_000,
               basis="공급면적 1평(3.3058㎡)"),
            ln(key="labor", name="인건비", qty=4.5, unit="품", unit_price=300_000, amount=1_350_000,
               basis="1품(1명이 하루 하는 일)"),
            ln(key="putty", name="퍼티작업", qty=21, unit="공급 평", unit_price=20_000, amount=420_000,
               in_standard=False, basis="공급면적 1평(3.3058㎡)"),
            ln(key="meal", name="식대", qty=4.5, unit="품", unit_price=11_000, amount=49_500,
               in_standard=False, basis="1품"),
            ln(key="truck", name="운송비", qty=1, unit="대", unit_price=50_000, amount=50_000,
               in_standard=False, basis="1대"),
        ],
    )  # fmt: skip


def _facts(screen: bool = True) -> ProjectFacts:
    return ProjectFacts(
        stage="vendors", area_m2=69.4, area_basis="supply", trades=["dobae"], grade="basic",
        living="vacant", standard=_standard(),
        screen=ScreenFacts(view="vendor", vendor=_maru()) if screen else None,
    )  # fmt: skip


def _ctx() -> TurnContext:
    return TurnContext(
        user_id=uuid.UUID(int=1),
        project_id=uuid.UUID(int=2),
        view="vendor",
        today=TODAY,
        mode="free",
    )


def _turn(q: str, facts: ProjectFacts):
    return asyncio.run(run_turn(q, _ctx(), kb=repo_kb(), facts=facts)).answer


def _texts(a) -> list[str]:
    return [x.text for s in a.sections for x in s.sentences]


def test_vendor_screen_copies_engine_values_and_hides_other_paper():
    """VendorDetailOut → 화면 사실: 값은 옮기기만, 보여 준 벽지가 아닌 도배지 · 빼기 줄은 화면처럼 빼요."""
    row = lambda code, key, name, qty, unit, price, amount, mode="price", std=True: SimpleNamespace(
        code=code, key=key, name=name, qty=Decimal(qty), unit=unit, unit_price=price, amount=amount,
        mode=mode, included_in=None, in_standard=std,
    )  # fmt: skip
    est = SimpleNamespace(
        grade="basic", total=2_920_005, supply=2_654_550, vat=265_455, vs_standard_pct=Decimal("30.3"),
        lines=[
            row("1203", "paper_hapji", "합지", "53.9", "벽지 평", 5_000, 269_500),
            row("1204", "paper_silk", "실크", "53.9", "벽지 평", 9_500, 512_050),
            row("1205", "material", "부자재", "21", "공급 평", 13_000, 273_000),
            row("1208", "truck", "운송비", "1", "대", 50_000, 50_000, std=False),
            row("1207", "meal", "식대", "4.5", "품", None, 0, mode="excluded", std=False),
        ],
    )  # fmt: skip
    d = SimpleNamespace(
        estimate_v3=est, profile=SimpleNamespace(biz_name="마루와벽"), grade_diff=-266_805
    )
    v = vendor_screen(d)
    assert v is not None and (v.vendor, v.grade, v.total, v.vs_standard) == (
        "마루와벽",
        "basic",
        2_920_005,
        30.3,
    )
    assert [x.key for x in v.lines] == ["paper_silk", "material", "truck"]
    assert v.lines[1].basis == "공급면적 1평(3.3058㎡)" and v.lines[2].in_standard is False
    assert vendor_screen(SimpleNamespace(estimate_v3=None)) is None


def test_material_question_reads_vendor_line_not_standard_line():
    """'도배 부자재는 왜 이렇게 비싸?' → 마루와벽 부자재 줄(공급 평 × 업체 단가). 전에는 '벽 도배 시공' 줄을 골랐어요."""
    a = _turn("도배 부자재는 왜 이렇게 비싸?", _facts())
    assert a.trace.route == "quote_explanation"
    texts = _texts(a)
    assert texts[:2] == [
        "부자재 줄은 마루와벽이 확인한 단가에 이 집 수량(공급 평)을 곱했어요.",
        "수량은 공급면적 1평(3.3058㎡) 단위로 셌어요.",
    ]
    assert not [t for t in texts if "벽 도배 시공" in t]
    box = next(b for b in a.calc if b.ref == "screen.vendor.lines.material")
    assert (box.label, box.qty, box.unit, box.unit_price, box.amount) == (
        "마루와벽 부자재",
        21,
        "공급 평",
        13_000,
        273_000,
    )


def test_compare_question_on_vendor_screen_lists_what_to_check():
    """'이 견적서 업체랑 비교할 때 뭘 위주로 봐야해?' → 같은 수량 · 표준 대비 %의 뜻 · 표준에 없는 줄 · 실측 뒤 줄."""
    a = _turn("이 견적서 업체랑 비교할 때 뭘 위주로 봐야해?", _facts())
    assert a.trace.route == "quote_explanation"
    texts = _texts(a)
    assert templates.SCREEN_COMPARE_SAME in texts
    assert (
        "퍼티작업 · 식대 · 운송비 줄은 표준견적서에 없어서 견줄 때 빼고, 다른 업체도 따로 받는지 봐요."
        in texts
    )
    assert (
        "기존 벽지 철거 · 폐기물 처리는 실측 뒤 업체가 정해서 가견적에 없어요. 실측 견적서에서 꼭 확인해요."
        in texts
    )
    assert templates.STANDARD_IS not in texts  # 전에는 '표준견적서는 업체 견적이 아니에요'만 했어요
    box = next(b for b in a.calc if b.ref == "screen.vendor.total")
    assert (box.amount, box.note) == (2_920_005, "표준보다 30.3% 많아요")


def test_man_day_lines_explain_how_pum_is_counted():
    """인건비 · 식대(품 줄): 품을 세는 법. 식대 · 운송비처럼 표준견적서에 없는 줄은 견줄 때 빼는 줄이라고 해요."""
    kb = repo_kb()

    def run(q: str):
        task = Task(
            text=q,
            route="quote_explanation",
            trades=["dobae"],
            policy=[],
            ctx=_ctx(),
            facts=_facts(),
        )
        return quote_explain.run(task, kb)

    labor = run("도배 인건비는 왜 4품이야?")
    texts = [x.text for s in labor.sections for x in s.sentences]
    assert texts[0] == "인건비 줄은 마루와벽이 확인한 단가에 이 집 수량(품)을 곱했어요."
    assert templates.SCREEN_MAN_DAY in texts
    assert [(b.qty, b.unit, b.amount) for b in labor.calc] == [(4.5, "품", 1_350_000)]
    meal = run("식대는 왜 줘야해?")
    texts = [x.text for s in meal.sections for x in s.sentences]
    assert templates.SCREEN_MAN_DAY in texts
    assert "식대는 표준견적서에 없는 줄이라 표준견적서와 견줄 때는 빼요." in texts


def test_without_screen_facts_no_screen_boxes():
    """화면 사실이 없으면(표준견적서 화면 등) 화면 줄 풀이를 하지 않아요(지금 길 그대로)."""
    a = _turn("도배 부자재는 왜 이렇게 비싸?", _facts(screen=False))
    assert not [b for b in a.calc if b.ref.startswith("screen.")]
