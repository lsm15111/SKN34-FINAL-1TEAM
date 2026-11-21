"""가견적 '선택' 줄(ADR 0006, 판 2026.11b)을 AI 칸에 넘기기: 퍼티 · 운송비는 금액은 보이고 합계 밖이에요.
화면 사실(vendor_screen)에 optional을 옮기고, 계산 상자 · 글은 '선택 · 합계 밖'으로 보여요.
값은 계산 엔진 → API 출력 그대로예요(화면 · 프롬프트에서 다시 세지 않아요). DB · LLM 없음."""

from decimal import Decimal
from types import SimpleNamespace

from test_v3_agent_quote_screen import _standard, _texts, _turn

from app.agent.v3 import screen_tools
from app.agent.v3.answer import screen_box
from app.agent.v3.schemas import ProjectFacts, ScreenFacts, VendorScreenFacts
from app.calc import dobae, estimate
from app.calc.common import COUNTED
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.chat.tools import separate_names, vendor_screen
from app.refprice.book import DOBAE_MARKET_2026_11B
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market
from app.vendor.service import _estimate_v3_out

# 마루와벽 단가(부가세 빼고). 합지는 안 받아요
PRICES = {
    "putty": estimate.PriceV3("price", 20_000),
    "paper_silk": estimate.PriceV3("price", 9_500),
    "material": estimate.PriceV3("price", 13_000),
    "labor": estimate.PriceV3("price", 300_000),
    "meal": estimate.PriceV3("price", 11_000),
    "truck": estimate.PriceV3("price", 50_000),
}


def _seen() -> VendorScreenFacts:
    """도배만 하는 공사 기준(판 2026.11b) 집의 마루와벽 가견적: 계산 엔진 → API 출력 → 화면 사실"""
    h = dobae.HomeV3(Decimal("69.4"), "supply", "basic", False)
    std = dobae.standard_v3(
        h, DOBAE_MARKET_2026_11B, paper_market("basic"), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2
    )
    e = estimate.estimate_v3(
        PRICES,
        std.qty,
        grade="basic",
        standard_total=std.quote.total,
        standard_keys={ln.key for ln in std.quote.lines if ln.state in COUNTED},
        optional_keys=std.optional_keys,
    )
    d = SimpleNamespace(
        estimate_v3=_estimate_v3_out(e, None, "general"),
        profile=SimpleNamespace(biz_name="마루와벽"),
        grade_diff=None,
    )
    v = vendor_screen(d)
    assert v is not None
    return v


def _facts() -> ProjectFacts:
    return ProjectFacts(
        stage="vendors", area_m2=69.4, area_basis="supply", trades=["dobae"], grade="basic",
        living="vacant", standard=_standard(), screen=ScreenFacts(view="vendor", vendor=_seen()),
    )  # fmt: skip


def test_vendor_screen_copies_optional_lines():
    """API 가견적 줄의 optional(표준견적서 '선택' 일)을 화면 사실에 옮겨요. 합계는 계산 엔진 값 그대로."""
    v = _seen()
    got = {x.key: (x.in_standard, x.optional) for x in v.lines}
    assert got == {
        "putty": (False, True),
        "paper_silk": (True, False),
        "material": (True, False),
        "labor": (True, False),
        "meal": (False, False),  # 표준견적서에 줄이 없어요. 가견적 합계에는 들어요
        "truck": (False, True),
    }
    by = {x.key: x.amount for x in v.lines}
    assert by["putty"] > 0 and by["truck"] > 0  # 선택 줄도 금액은 보여요
    assert v.supply == sum(a for k, a in by.items() if k not in ("putty", "truck"))


def test_screen_box_puts_optional_lines_outside_total():
    """계산 상자: 선택 줄은 금액이 있어도 '선택 · 합계 밖'(in_total False). 화면이 '· 합계 밖'을 붙여요."""
    v = _seen()
    by = {x.key: x for x in v.lines}
    putty, truck, meal = (screen_box(by[k], v.vendor) for k in ("putty", "truck", "meal"))
    assert (putty.label, putty.in_total, putty.amount) == (
        "마루와벽 퍼티작업 · 선택",
        False,
        by["putty"].amount,
    )
    assert (truck.label, truck.in_total) == ("마루와벽 운송비 · 선택", False)
    assert (meal.label, meal.in_total) == ("마루와벽 식대", True)


def test_optional_line_answer_says_it_is_outside_total():
    """'퍼티 작업이 뭐야?'(업체 화면): 표준견적서 선택 줄과 같은 말로, 합계에 없다고 해요."""
    a = _turn("퍼티 작업이 뭐야?", _facts())
    assert a.trace.route == "quote_explanation"
    texts = _texts(a)
    assert texts[0] == "퍼티작업 줄은 마루와벽이 확인한 단가에 이 집 수량(공급 평)을 곱했어요."
    assert "퍼티작업은 고르면 더하는 줄이라 지금 합계에는 없어요." in texts
    assert "퍼티작업은 표준견적서에 없는 줄이에요." not in texts
    box = next(b for b in a.calc if b.ref == "screen.vendor.lines.putty")
    assert (box.label, box.in_total) == ("마루와벽 퍼티작업 · 선택", False)
    meal = _texts(_turn("식대는 왜 줘야해?", _facts()))
    assert "식대는 표준견적서에 없는 줄이에요." in meal  # 선택이 아닌 줄은 그대로


def test_compare_and_separate_skip_optional_lines():
    """견주기 · 따로 받는 줄: 가견적 합계에 든 줄만(식대). 선택 줄(퍼티 · 운송비)은 합계 밖이라 빼요."""
    assert separate_names(_seen()) == ["식대"]
    texts = _texts(_turn("이 견적서 업체랑 비교할 때 뭘 위주로 봐야해?", _facts()))
    assert "식대 줄은 표준견적서에 없는 줄이에요. 다른 업체도 따로 받는지 봐요." in texts
    assert not [t for t in texts if "퍼티작업" in t or "운송비" in t]


def test_screen_text_marks_optional_lines_outside_total():
    """작성기 '보는 화면' 글: 선택 줄은 '선택 · 합계 밖'. 금액은 계산 엔진 값 그대로예요."""
    t = screen_tools.screen_text("vendor", _facts())
    assert t is not None
    rows = {r.split(":")[0]: r for r in t["글"].splitlines() if r.startswith("- ")}
    v = _seen()
    by = {x.key: x for x in v.lines}
    for key, name in (("putty", "퍼티작업"), ("truck", "운송비")):
        row = rows[f"- {name}"]
        assert "선택 · 합계 밖" in row and "표준견적서에 없는 줄" not in row, row
        assert f"= {by[key].amount:,}원" in row, row
    assert "표준견적서에 없는 줄" in rows["- 식대"] and "합계 밖" not in rows["- 식대"]
    assert f"합계 {v.total:,}원" in t["글"]
