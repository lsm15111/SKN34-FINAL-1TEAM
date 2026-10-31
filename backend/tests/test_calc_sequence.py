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


def test_demolition_first_and_late_work_after_wallpaper():
    """철거는 짐 정리 다음에 모으고, 장판 · 조명 같은 늦은 작업은 도배 뒤 late_order 순서로 둔다."""
    a = [
        Step("prep", "짐 정리", 1),
        Step("remove", "가 철거", 1),
        Step("work", "가 작업", 2),
        Step("finish", "가 정리", 1),
    ]
    b = [
        Step("remove", "나 철거", 1),
        Step("lay", "나 장판", 2, late=True),
        Step("finish", "정리", 1),
    ]
    c = [Step("prep", "짐 정리", 1), Step("paper", "다 도배", 3), Step("finish", "다 정리", 1)]
    d = [
        Step("wire", "라 배선", 1),
        Step("fixture", "라 조명", 1, late=True),
        Step("finish", "끝", 1),
    ]
    all_steps = {"a": a, "b": b, "c": c, "d": d}
    steps, days = sequence(all_steps, order=("d", "a", "b", "c"), late_order=("b", "d"))
    assert [(s.trade, s.key, s.phase) for s in steps] == [
        ("a", "prep", "prep"),
        ("a", "remove", "remove"),
        ("b", "remove", "remove"),
        ("d", "wire", "main"),
        ("a", "work", "main"),
        ("c", "paper", "main"),
        ("b", "lay", "late"),
        ("d", "fixture", "late"),
        ("d", "finish", "finish"),  # 마지막에 일한 공정의 정리
    ]
    assert days == Decimal(13) / 2
    # late_order가 없으면 늦은 작업은 공정 순서대로
    steps, _ = sequence(all_steps, order=("d", "a", "b", "c"))
    assert [s.key for s in steps if s.phase == "late"] == ["fixture", "lay"]


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
