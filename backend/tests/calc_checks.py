"""계산 엔진 결과가 공정과 상관없이 지켜야 하는 성질. 공정별 성질 테스트가 같이 쓴다."""

from decimal import Decimal

from app.calc.common import COUNTED, won

STATES = {"included", "bundled", "separate", "optional", "after_visit", "excluded"}
BASES = {"public", "assumed", "none"}


def check_quote(r, vat_rate: Decimal = Decimal("0.1")) -> None:
    counted = [ln for ln in r.lines if ln.state in COUNTED]
    # 합계는 '포함' · '따로 계산' 줄의 합이고, 부가세 · 총액은 그 합에서만 나온다
    assert all(ln.amount is not None for ln in counted)
    assert r.subtotal == sum(ln.amount for ln in counted)
    assert r.vat == won(Decimal(r.subtotal) * vat_rate) and r.total == r.subtotal + r.vat
    keys = [ln.key for ln in r.lines]
    assert len(keys) == len(set(keys))
    for ln in r.lines:
        assert ln.state in STATES and ln.basis in BASES and ln.source
        for x in (ln.qty, ln.unit_price, ln.amount):
            assert x is None or x >= 0
        if ln.basis == "none":
            assert ln.amount is None and ln.state not in COUNTED
        if None not in (ln.qty, ln.unit_price, ln.amount):
            assert ln.amount == won(ln.qty * ln.unit_price)
    steps = [s.key for s in r.steps]
    assert len(steps) == len(set(steps)) and steps[-1] == "finish"
    assert all(s.half_days >= 1 for s in r.steps)
    assert r.days == Decimal(sum(s.half_days for s in r.steps)) / 2
    assert r.man_days >= 0 and r.man_days * 2 == int(r.man_days * 2)
