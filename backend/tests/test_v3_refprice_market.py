"""벽지 시장 평균 가격 · 업체 단가표 기준값(B6) 확인.

- 값이 자료 파일(data/v3)과 같은지, 단위 환산(롤 → ㎡ → 벽지 평)이 맞는지, 10배 경고가 9판 예시와 맞는지 봐요.
"""

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from app.refprice import book, vendor_baseline, wallpaper_market
from app.refprice.vendor_baseline import WARN_RATIO, price_warning, vendor_base
from app.refprice.wallpaper_market import PAPER_PYEONG_M2, ROLL_M2, install_market, paper_market

DATA = Path(__file__).resolve().parents[2] / "data" / "v3"


def won(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@pytest.mark.parametrize("grade", ["economy", "basic"])
def test_paper_price_is_roll_mean_per_paper_pyeong(grade):
    p = paper_market(grade)
    assert p.stat == "mean" and p.version == wallpaper_market.VERSION
    assert p.per_py == won(Decimal(p.roll_mean) * PAPER_PYEONG_M2 / ROLL_M2)
    assert p.per_m2 == (Decimal(p.roll_mean) / ROLL_M2).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    assert p.p25_per_py <= p.median_per_py <= p.p75_per_py
    assert p.n > 0 and p.sources and p.basis


def test_market_values_match_data_files():
    res = json.loads((DATA / "wallpaper_price" / "result.json").read_text(encoding="utf-8"))
    for grade, g in (("economy", "hapji"), ("basic", "silk")):
        cap = res["material"][g]["cap30"]
        p = paper_market(grade)
        assert p.per_py == cap["per_paper_pyeong"]["mean"]
        assert (p.median_per_py, p.p25_per_py, p.p75_per_py) == (
            cap["per_paper_pyeong"]["median"],
            cap["per_paper_pyeong"]["p25"],
            cap["per_paper_pyeong"]["p75"],
        )
        assert (p.roll_mean, p.roll_median, p.n) == (
            cap["roll"]["mean"],
            cap["roll"]["median"],
            cap["n"],
        )
        i, x = install_market(grade), res["install"][g]
        assert i.mean_per_supply_py == x["mean_cap30_weighted"]
        assert i.median_per_supply_py == x["representative_per_pyeong"]
        assert (i.p25, i.p75, i.p10, i.p90) == tuple(
            x["range_cap30"][k] for k in ("p25", "p75", "p10", "p90")
        )
    base = json.loads((DATA / "vendor_baseline" / "baseline.json").read_text(encoding="utf-8"))
    assert base["version"] == vendor_baseline.VERSION and base["warn_ratio"] == WARN_RATIO
    for row in base["rows"]:
        b = vendor_base(row["code"])
        assert (b.key, b.unit, b.base, b.stat, b.p25, b.p75, b.n) == (
            row["key"], row["unit"], row["base"], row["stat"], row["p25"], row["p75"], row["n"],
        )  # fmt: skip


def test_example_house_paper_line_uses_market_mean():
    # 9판 C07 집(공급 69.4㎡ · 실크): 도배지 63.0평. 계산 엔진은 이 단가만 바꿔요(data-model 6장)
    silk = paper_market("basic")
    assert won(Decimal("63.0") * silk.per_py) == 677_187
    assert paper_market("economy").per_py < silk.per_py
    # 예전 값은 그대로 남아요(다른 코드가 써요)
    assert book.SILK_2026["wall-silk-best"].per_py == 9_500


def test_vendor_rows_have_units_and_shared_paper_values():
    codes = ["1201", "1203", "1204", "1205", "1209", "1206", "1207", "1208"]
    assert list(vendor_baseline.VENDOR_BASE_2026_11) == codes
    units = {c: vendor_base(c).unit for c in codes}
    assert units == {
        "1201": "공급 평", "1203": "벽지 평", "1204": "벽지 평", "1205": "공급 평", "1209": "공급 평",
        "1206": "품", "1207": "품", "1208": "대",
    }  # fmt: skip
    assert vendor_base("1204").base == paper_market("basic").per_py
    assert vendor_base("1203").base == paper_market("economy").per_py
    assert all(vendor_base(c).unit_ko for c in codes)


def test_hapji_material_baseline_is_market_median():
    """1209 합지 부자재(2026-11-21): 시장 실견적 합지 집 87건 부자재 줄 ÷ 공급 평형 가운데 값. 자료 파일 밖이라 판이 따로예요.
    표준견적서(도배만 하는 공사 기준) 합지 부자재 3,300원과 같은 자료를 반올림한 값이에요."""
    b = vendor_base("1209")
    assert (b.key, b.base, b.stat, b.p25, b.p75, b.n) == (
        "material_hapji", 3_333, "median", 2_739, 3_820, 87
    )  # fmt: skip
    assert (b.version, b.checked) == (vendor_baseline.VERSION_B, vendor_baseline.CHECKED_B)
    assert vendor_base("1205").version == vendor_baseline.VERSION  # 다른 줄은 앞 판 그대로
    assert round(book.DOBAE_MARKET_2026_11B.profile.material_py["economy"], -2) == round(b.base, -2)
    assert (b.warn_above, b.warn_below) == (33_330, 334)
    # 실크 부자재를 그대로 넣어도(6,900 · 13,000) 경고는 없어요(10배 안)
    assert price_warning("1209", 6_900) is None and price_warning("1209", 13_000) is None


def test_ten_times_warning_matches_9th_draft_examples():
    # D02: 인건비 2,800,000원은 '기준 단가의 10배쯤' 경고
    w = price_warning("1206", 2_800_000)
    assert (
        w
        and w.kind == "too_high"
        and w.message == "기준 단가의 10배쯤이에요. 0을 더 넣지 않았나요?"
    )
    # 9판 C11(업체 상세) · D02(단가표) 예시 단가는 경고가 없어요
    examples = {
        "1201": [20_000, 15_000],
        "1204": [9_500, 9_000],
        "1205": [13_000, 12_000],
        "1206": [300_000],
    }
    for code, values in examples.items():
        for v in values:
            assert price_warning(code, v) is None, (code, v)
    low = price_warning("1206", 26_000)  # 기준 270,000의 10분의 1(27,000)보다 작아요
    assert low and low.kind == "too_low" and "0을 빠뜨리지" in low.message


@pytest.mark.parametrize("code", ["1201", "1203", "1204", "1205", "1209", "1206", "1207", "1208"])
def test_warning_edges_are_exactly_ten_times(code):
    b = vendor_base(code)
    assert price_warning(code, b.base) is None
    assert price_warning(code, b.warn_above) is None
    assert price_warning(code, b.warn_above + 1).kind == "too_high"
    assert price_warning(code, b.warn_below) is None
    if b.warn_below > 1:
        assert price_warning(code, b.warn_below - 1).kind == "too_low"
    with pytest.raises(ValueError):
        price_warning(code, 0)
    with pytest.raises(KeyError):
        price_warning("1202", 1_000)
