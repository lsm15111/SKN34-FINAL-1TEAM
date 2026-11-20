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
    MarketFact,
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


CHECKED = date(2026, 11, 18)


def _maru() -> VendorScreenFacts:
    ln = ScreenLineFact
    mk = lambda base, stat, p25, p75, n: MarketFact(
        base=base, stat=stat, p25=p25, p75=p75, n=n, checked=CHECKED
    )
    return VendorScreenFacts(
        vendor="마루와벽", grade="basic", total=2_920_005, supply=2_654_550, vat=265_455,
        vs_standard=30.3, grade_diff=-266_805,
        lines=[
            ln(key="paper_silk", name="실크벽지", qty=53.9, unit="벽지 평", unit_price=9_500, amount=512_050,
               basis="벽지(도배지) 면적 1평(3.3058㎡)", market=mk(10_749, "mean", 9_016, 13_223, 279)),
            ln(key="material", name="부자재", note="풀 · 부직포 · 네바리 · 실리콘 등", qty=21, unit="공급 평",
               unit_price=13_000, amount=273_000, basis="공급면적 1평(3.3058㎡)",
               market=mk(6_875, "median", 6_279, 7_586, 129)),
            ln(key="labor", name="인건비", note="품 = 1명이 하루 하는 일", qty=4.5, unit="품", unit_price=300_000,
               amount=1_350_000, basis="1품(1명이 하루 하는 일)", market=mk(270_000, "median", 250_000, 290_000, 22)),
            ln(key="putty", name="퍼티작업", note="사전퍼티 또는 밀작업", qty=21, unit="공급 평", unit_price=20_000,
               amount=420_000, in_standard=False, basis="공급면적 1평(3.3058㎡)"),
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
    row = lambda code, key, name, qty, unit, price, amount, mode="price", std=True, label="", note="": SimpleNamespace(
        code=code, key=key, name=name, qty=Decimal(qty), unit=unit, unit_price=price, amount=amount,
        mode=mode, included_in=None, in_standard=std, label=label, note=note,
    )  # fmt: skip
    est = SimpleNamespace(
        grade="basic", total=2_920_005, supply=2_654_550, vat=265_455, vs_standard_pct=Decimal("30.3"),
        lines=[
            row("1203", "paper_hapji", "합지", "53.9", "벽지 평", 5_000, 269_500),
            row("1204", "paper_silk", "실크", "53.9", "벽지 평", 9_500, 512_050, label="실크벽지"),
            row("1205", "material", "부자재", "21", "공급 평", 13_000, 273_000, note="풀 · 부직포 등"),
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
    assert [x.name for x in v.lines] == [
        "실크벽지",
        "부자재",
        "운송비",
    ]  # 고객 화면 이름(줄 정의 label)
    assert v.lines[1].basis == "공급면적 1평(3.3058㎡)" and v.lines[2].in_standard is False
    assert v.lines[1].note == "풀 · 부직포 등"
    # 시장 기준값은 자료 많은 줄만(부자재 129건 가운데 값). 운송비는 어림 상한이라 없음
    m = v.lines[1].market
    assert m is not None and (m.stat, m.n) == ("median", 129) and v.lines[2].market is None
    assert vendor_screen(SimpleNamespace(estimate_v3=None)) is None


def test_material_question_reads_vendor_line_not_standard_line():
    """'도배 부자재는 왜 이렇게 비싸?' → 마루와벽 부자재 줄(공급 평 × 업체 단가). 전에는 '벽 도배 시공' 줄을 골랐어요."""
    a = _turn("도배 부자재는 왜 이렇게 비싸?", _facts())
    assert a.trace.route == "quote_explanation"
    texts = _texts(a)
    assert texts[:4] == [
        "부자재 줄은 마루와벽이 확인한 단가에 이 집 수량(공급 평)을 곱했어요.",
        "수량은 공급면적 1평(3.3058㎡) 단위로 셌어요.",
        "부자재 줄에는 풀 · 부직포 · 네바리 · 실리콘 등이 들어가요.",
        (
            "믿집이 모은 실견적 129건에서 부자재 단가는 공급면적 1평(3.3058㎡)당 가운데 값이 6,875원(부가세 빼고)이고, "
            "절반이 6,279~7,586원 사이예요(2026.11 기준)."
        ),
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
    """'이 견적서 업체랑 비교할 때 뭘 위주로 봐야해?' → 같은 수량 · 표준에 없는 줄 · 실측 뒤 줄.
    표준견적서와 견준 %는 글 · 계산 상자에 없어요(사용자 결정 2026-11-21)."""
    a = _turn("이 견적서 업체랑 비교할 때 뭘 위주로 봐야해?", _facts())
    assert a.trace.route == "quote_explanation"
    texts = _texts(a)
    assert templates.SCREEN_COMPARE_SAME in texts
    assert (
        "퍼티작업 · 식대 · 운송비 줄은 표준견적서에 없는 줄이에요. 다른 업체도 따로 받는지 봐요."
        in texts
    )
    assert not [t for t in texts if "표준보다" in t or "표준 대비" in t or "견줄 때" in t]
    assert (
        "기존 벽지 철거 · 폐기물 처리는 실측 뒤 업체가 정해서 가견적에 없어요. 실측 견적서에서 꼭 확인해요."
        in texts
    )
    assert templates.STANDARD_IS not in texts  # 전에는 '표준견적서는 업체 견적이 아니에요'만 했어요
    box = next(b for b in a.calc if b.ref == "screen.vendor.total")
    assert (box.amount, box.note) == (2_920_005, "")


def test_man_day_lines_explain_how_pum_is_counted():
    """인건비 · 식대(품 줄): 품을 세는 법. 식대 · 운송비처럼 표준견적서에 없는 줄은 없는 줄이라고만 해요."""
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
    assert "식대는 표준견적서에 없는 줄이에요." in texts


def test_without_screen_facts_no_screen_boxes():
    """화면 사실이 없으면(표준견적서 화면 등) 화면 줄 풀이를 하지 않아요(지금 길 그대로)."""
    a = _turn("도배 부자재는 왜 이렇게 비싸?", _facts(screen=False))
    assert not [b for b in a.calc if b.ref.startswith("screen.")]


def test_screen_line_names_route_before_gate_on_vendor_screen():
    """업체 화면에서 줄 이름(화면 데이터)이 나오면 관문보다 먼저 견적 설명으로(2026-11-20 사용자 결정).
    전에는 운송비 · 식대가 되묻기, 인건비가 공종 담당, 퍼티가 일정 담당으로 갔어요."""
    cases = {
        "운송비는 왜 나오는거야?": "운송비 줄은 마루와벽이 확인한 단가에 이 집 수량(대)을 곱했어요.",
        "식대는 왜 줘야해?": "식대 줄은 마루와벽이 확인한 단가에 이 집 수량(품)을 곱했어요.",
        "도배 인건비는 왜 4품이야?": "인건비 줄은 마루와벽이 확인한 단가에 이 집 수량(품)을 곱했어요.",
        "퍼티 작업이 뭐야?": "퍼티작업 줄은 마루와벽이 확인한 단가에 이 집 수량(공급 평)을 곱했어요.",
    }
    for q, first in cases.items():
        a = _turn(q, _facts())
        assert a.trace.route == "quote_explanation", q
        texts = _texts(a)
        assert texts[0] == first, q
        assert not [b for b in a.calc if b.ref == "plan.range"], q  # 묻지 않은 공정표 상자 없음
    labor = _texts(_turn("도배 인건비는 왜 4품이야?", _facts()))
    assert templates.SCREEN_MAN_DAY in labor
    assert any(t.startswith("믿집이 모은 실견적 22건에서 인건비 단가는") for t in labor)
    truck = _texts(_turn("운송비는 왜 나오는거야?", _facts()))
    assert not [t for t in truck if t.startswith("믿집이 모은 실견적")]  # 운송비는 시장 기준값 없음


def test_policy_questions_keep_their_route_on_vendor_screen():
    """정책 표시(브랜드 추천 등)가 붙으면 줄 이름이 있어도 정책 길 그대로. 화면 사실이 없으면 지금 관문 그대로."""
    brand = _turn("실크벽지 어느 브랜드가 좋아요?", _facts())
    assert brand.trace.route == "trade" and "brand_reco" in brand.trace.policy
    assert any(x.startswith("특정 제품 · 브랜드는 추천하지 않아요") for x in _texts(brand))
    plain = _turn("운송비는 왜 나오는거야?", _facts(screen=False))
    assert plain.trace.route != "quote_explanation"
