"""v2 받은 견적 맞춰 보기 · 업체 가견적 (v10 quoteCheck · estimateFor). 순수 함수만 본다. 기대값은 손으로 검산한 값이다."""

from decimal import Decimal

from app.calc import market_band as mb
from app.calc.v2_check import CheckScope, check, estimate_for, percent_vs
from app.refprice.mvp_market import MARKET_2026_11 as M

D = Decimal
# 공급 100㎡ 실크: 도배 면적 224㎡ → 천장 82.9 · 벽 141.1, 시장 기준 2,444,204원 → 범위 218만 ~ 310만
DOBAE = mb.MarketDobaeInput(D(100), "basic")


def test_percent_vs_rounds_like_v10():
    assert percent_vs(1_100, 1_000) == D("10")
    assert percent_vs(87_650, 100_000) == D("-12.3")  # −12.35 → v10은 −12.3 (올림 쪽)
    assert percent_vs(1, 0) is None


def test_dobae_in_band_and_removal():
    r = check(DOBAE, M, D(2_500_000), "unknown", CheckScope())
    assert (r["lo"], r["hi"], r["where"], r["head"]) == (
        2_180_000,
        3_100_000,
        "in",
        "보통 범위 안이에요",
    )
    assert r["vat_unknown"] is True and r["pct"] == 0
    # 철거: (141.1 + 82.9)㎡ × 600 ~ 2,400원 = 134,400 ~ 537,600
    r = check(DOBAE, M, D(2_000_000), "excluded", CheckScope(removal=True))
    assert (r["lo"], r["hi"], r["where"]) == (2_314_400, 3_637_600, "low")
    # (2,000,000 − 2,314,400) ÷ 2,314,400 = −13.58% → −13.6
    assert r["pct"] == D("-13.6") and r["head"] == "보통보다 13.6% 낮아요"
    assert r["notes"] == ["기존 벽지 철거: 시장 ㎡당 600~2,400원 × 224㎡"]
    assert 0 < r["bar"]["me"] < r["bar"]["band_left"]


def test_vat_included_and_warnings():
    r = check(DOBAE, M, D(3_520_000), "included", CheckScope())
    assert r["supply"] == 3_200_000 and r["where"] == "high"  # 3,520,000 ÷ 1.1
    assert r["pct"] == D("3.2")  # (3,200,000 − 3,100,000) ÷ 3,100,000 = 3.23%
    assert check(DOBAE, M, D(0), "unknown", CheckScope())["warn"] == "받은 금액을 넣어 주세요."
    mok = mb.MarketMokgongInput(D(100), ("molding",))
    assert check(mok, M, D(1_000_000), "unknown", CheckScope(etc=True))["warn"].startswith("수납장")


def test_mokgong_extras_and_casing():
    mok = mb.MarketMokgongInput(D(100), ("molding", "door"), doors=4)
    base = mb.mokgong(mok, M)
    scope = CheckScope(casing9=True, removal=True, extras={"aircon": 12, "jungmun": 3})
    r = check(mok, M, D(5_000_000), "excluded", scope)
    # 에어컨 9곳(최대) 40만~55만 · 중문 한 번 90만~110만 · 9mm 문선 문 4개 × 5만~15만 · 철거 6만~20만
    assert r["lo"] == base.lo + 3_600_000 + 900_000 + 200_000 + 60_000
    assert r["hi"] == base.hi + 4_950_000 + 1_100_000 + 600_000 + 200_000
    assert r["notes"][0] == "현관 중문(3연동): 90만~110만 원 (실견적 4줄)"


def test_estimate_for():
    lines = [
        {"key": "wall", "name": "벽", "qty": D("10.0"), "state": "included"},
        {"key": "paper", "name": "도배지", "qty": D("12.0"), "state": "included"},
        {"key": "removal", "name": "철거", "qty": D("10.0"), "state": "after_visit"},
    ]
    prices = {"wall": D(5000), "paper_basic": D(3000)}
    r = estimate_for(lines, prices, "basic", 100_000)
    # 50,000 + 36,000 = 86,000 + 부가세 8,600 = 94,600 → 표준 100,000보다 −5.4%
    assert r == {"ok": True, "supply": 86_000, "vat": 8_600, "total": 94_600, "pct": D("-5.4")}
    miss = estimate_for(lines, prices, "economy", 100_000)
    assert miss == {"ok": False, "why": "'도배지' 단가를 넣어 주세요"}
