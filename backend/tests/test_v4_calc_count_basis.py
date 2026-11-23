"""표준견적서 근거(calc.dobae.count_basis) · 줄이는 길(save_ways). 2026-11-23 고객 질문 '인건비 5품은 어떻게 나온거야?' ·
'18평인데 왜 21.6평이에요?' · '식대를 왜 내요?' · '줄일 방법은?'에 비서가 계산 엔진 글로 답한다.

기대값은 손으로 검산했다.
- 전용 18평(59.5㎡) 실크 · 빈 집 · 도배만: 공급 59.5 × 1.2 ÷ 3.3058 = 21.6평. 면적 공급 59.5 × 1.315 = 78.2425㎡,
  방 3개(23.7평 → 3) → 78.2425 × 1.55 + 3 × 20.4 = 182.48 → 182.5㎡, 천장 63.9 · 벽 118.6. 벽지 182.5 × 1.248 = 227.8㎡
  ÷ 3.3058 = 68.9 벽지 평. 품 118.6 × 0.024 + 63.9 × 0.0351 = 5.089 → × 0.91 = 4.631 → 0.5 올림 5품. 4명 → 1.5일 + 마감 = 2일.
- 공급 18평 실크 · 짐 있는 집 · 리모델링: 방 2개 → 133.0㎡(천장 46.6 · 벽 86.4). 품 3.709 × 0.91 = 3.375 ÷ 0.85 = 3.971
  → 4품. 식대 4 × 15,000 = 60,000원.
"""

from dataclasses import replace
from decimal import Decimal

from app.calc import dobae
from app.calc.common import pyeong_to_m2
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.refprice.book import DOBAE_PROFILES
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market

PY18 = pyeong_to_m2(Decimal(18))  # 59.5㎡
ONLY, REMODEL = DOBAE_PROFILES["paper_only"], DOBAE_PROFILES["remodel"]


def std(h: dobae.HomeV3, p: dobae.DobaePrices, own: bool = False) -> dobae.StandardV3:
    return dobae.standard_v3(
        h, p, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2, own_paper=own
    )


def basis(h: dobae.HomeV3, p: dobae.DobaePrices) -> str:
    return "\n".join(dobae.count_basis(h, p, HOUSE_2026H2, std(h, p)))


def test_exclusive_18_explains_21_6_pyeong_and_5_man_days():
    h = dobae.HomeV3(PY18, "exclusive", "basic", False)
    v = std(h, ONLY)
    assert (v.pyeong, v.qty.floor_py, v.qty.paper_py, v.qty.man_day) == (
        Decimal("21.6"), Decimal("21.6"), Decimal("68.9"), Decimal("5.0")
    )  # fmt: skip
    got = basis(h, ONLY)
    for part in (
        "전용 59.5㎡(전용 18평)에 전용 → 공급 환산 1.2배를 곱해 공급 21.6평",
        "부자재 · 퍼티 수량(공급 평)은 이 21.6평",
        "공급 78.2㎡(전용 × 1.315) × 1.55 + 방 3개 × 20.4㎡ = 182.5㎡",
        "천장이 35%",
        "182.5㎡ × 소요량 1.248 = 227.8㎡",
        "68.9 벽지 평",
        "벽 118.6㎡ × 0.024 + 천장 63.9㎡ × 0.0351 = 약 5.09품(표준품셈)",
        "시장 품 비 × 0.91 = 약 4.63품",
        "0.5 단위로 올려 5품",
        "업체 가견적의 인건비 · 식대 수량(품)도 이 값",
        "벽지 바르기는 1.5일이고, 마감 · 청소를 더해 예상 2일",
        "도배만 하는 공사 기준은 식대를 따로 줄로 두지 않아요",
    ):
        assert part in got, part
    assert "짐 있는 집" not in got and "고른 공간 몫" not in got


def test_remodel_occupied_has_meal_line_and_occupied_step():
    h = dobae.HomeV3(PY18, "supply", "basic", True)
    v = std(h, REMODEL)
    meal = next(ln for ln in v.quote.lines if ln.key == "meal")
    assert (v.quote.man_days, meal.amount) == (Decimal("4.0"), 60_000)
    got = basis(h, REMODEL)
    assert "내 집 평수는 공급 59.5㎡ ÷ 3.3058 = 공급 18평" in got
    assert "방 2개 × 20.4㎡ = 133㎡" in got
    assert "짐 있는 집 ÷ 0.85 = 약 3.97품" in got and "0.5 단위로 올려 4품" in got
    assert "짐 정리 · 보양, 마감 · 청소를 더해" in got
    assert "식대는 4품 × 15,000원 = 60,000원(공급가)" in got and "리모델링 기준" in got


def test_partial_walls_only_names_share_and_skips_ceiling_term():
    h = dobae.HomeV3(PY18, "supply", "economy", False, "partial", ("master", "living"), ("wall",))
    v = std(h, ONLY)
    got = basis(h, ONLY)
    assert f"고른 공간 몫 × {dobae.num(v.share)}" in got
    assert f"= {dobae.num(v.qty.floor_py)}평" in got
    assert "천장은 빼고 벽만 셌어요" in got
    assert "천장 0㎡" not in got and "시장 품 비 × 0.5005" in got  # 합지 품 배수 0.91 × 0.55


def test_basis_is_empty_when_values_do_not_match():
    """다른 집으로 센 결과를 넘기면(틀린 근거) 빈 목록이에요."""
    h = dobae.HomeV3(PY18, "exclusive", "basic", False)
    other = std(replace(h, area_basis="supply"), ONLY)
    assert dobae.count_basis(h, ONLY, HOUSE_2026H2, other) == []


def test_save_ways_are_engine_differences_sorted():
    h = dobae.HomeV3(PY18, "supply", "basic", True)
    base = std(h, ONLY)
    ways = {
        "own_paper": std(h, ONLY, own=True),
        "walls_only": std(replace(h, faces=("wall",)), ONLY),
        "empty_home": std(replace(h, occupied=False), ONLY),
        "same": std(h, ONLY),  # 줄지 않으면 빠져요
    }
    got = dobae.save_ways(base, ways)
    assert [w.key for w in got] == sorted(
        ("own_paper", "walls_only", "empty_home"),
        key=lambda k: -(base.quote.total - ways[k].quote.total),
    )
    for w in got:
        assert w.total == ways[w.key].quote.total and w.less == base.quote.total - w.total > 0
    paper = dobae.paper_split(base.quote.lines, ONLY.vat_rate)
    own = next(w for w in got if w.key == "own_paper")
    assert own.less == paper.share and own.total == paper.without_paper.total  # 벽지 칸 값과 같아요
