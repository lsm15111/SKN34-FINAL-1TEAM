"""공정 잇기 · 합계. 순서는 부르는 쪽이 넘기고, 합계는 공정 금액을 더하기만 한다."""

from decimal import Decimal

import pytest

from app.calc import dobae, mokgong
from app.calc.common import Step
from app.calc.sequence import sequence, totals
from app.refprice.book import DOBAE_2026H2, MOKGONG_2026H2

D = dobae.quote(
    dobae.DobaeInput(Decimal("112.4"), "supply", "economy", False, occupied=True), DOBAE_2026H2
)
M = mokgong.quote(
    mokgong.MokgongInput(Decimal("112.4"), "supply", ("molding", "door"), True, 2), MOKGONG_2026H2
)


def test_order_comes_from_the_caller():
    a = [Step("prep", "짐 정리", 1), Step("work", "가 작업", 2), Step("finish", "정리", 1)]
    b = [Step("prep", "짐 정리", 1), Step("work", "나 작업", 3), Step("finish", "정리", 1)]
    steps, days = sequence({"a": a, "b": b}, order=("b", "a"))
    assert [(s.trade, s.key) for s in steps] == [
        ("b", "prep"),
        ("b", "work"),
        ("a", "work"),
        ("a", "finish"),
    ]
    assert days == Decimal(7) / 2
    # 순서에 없는 공정을 조용히 버리지 않는다
    with pytest.raises(ValueError):
        sequence({"a": a, "c": b}, order=("a", "b"))


def test_totals_add_up_each_trade():
    t = totals([D, M])
    assert (t.subtotal, t.vat, t.total) == (
        D.subtotal + M.subtotal,
        D.vat + M.vat,
        D.total + M.total,
    )
    # 천장을 안 하면 그 줄('안 함')은 근거 개수에서 뺀다
    lines = [ln for q in (D, M) for ln in q.lines if ln.state != "excluded"]
    assert sum(t.basis_counts.values()) == len(lines)
    assert t.basis_counts["assumed"] == sum(ln.basis == "assumed" for ln in lines) >= 2
    assert t.basis_counts["none"] == sum(ln.basis == "none" for ln in lines) >= 1
    assert totals([]).total == 0
