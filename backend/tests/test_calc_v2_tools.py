"""v2 셀프 계산기(v10 CALC7). 순수 함수만 본다. 기대값은 손으로 검산한 값이다."""

from app.calc.v2_tools import paint, trim, wallpaper


def test_wallpaper_rolls():
    # 둘레 13.2m × 2.3 − 문 1.8 − 창 1.5 = 27.06㎡, 실크 폭 1.06 → 27.06 ÷ 2.438 = 11.1 → 12폭
    # 한 롤 15.6 ÷ 2.4 = 6폭, 천장 3.6 ÷ 1.06 → 4폭 · 한 롤 15.6 ÷ 3.1 = 5폭
    # 12/6 + 4/5 = 2.8롤 × 1.1 = 3.08 → 4롤
    r = wallpaper(3.6, 3.0, 2.3, 1.06, 15.6, doors=1, windows=1, ceiling=True)
    assert r == {
        "wall_m2": 27.1,
        "ceiling_m2": 10.8,
        "strips": 12,
        "cStrips": 4,
        "per_roll": 6,
        "rolls_raw": 2.8,
        "rolls": 4,
    }
    # 무늬 반복 64cm면 한 폭 3.04m → 한 롤 5폭
    assert wallpaper(3.6, 3.0, 2.3, 1.06, 15.6, repeat=64)["per_roll"] == 5


def test_trim_pieces():
    # 둘레 13.2m × 1.1 ÷ 2.4 = 6.05 → 7개, 걸레받이 13.2 − 0.9 = 12.3m → 5.64 → 6개
    assert trim(3.6, 3.0, doors=1) == {
        "molding_m": 13.2,
        "molding_pcs": 7,
        "base_m": 12.3,
        "base_pcs": 6,
    }


def test_paint_cans():
    # 27.06㎡ × 2회 ÷ 10 = 5.412L → 4L 2통
    assert paint(3.6, 3.0, 2.3, doors=1, windows=1) == {
        "area_m2": 27.1,
        "liters": 5.4,
        "n18": 0,
        "n4": 2,
    }
    # 40㎡ × 2 ÷ 4.5 = 17.8L → 4L 5통(20L)이면 18L 1통으로
    assert paint(5, 5, 2, cover=4.5) == {"area_m2": 40.0, "liters": 17.8, "n18": 1, "n4": 0}
