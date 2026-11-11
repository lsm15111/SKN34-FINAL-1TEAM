"""v2 셀프 계산기 (v10 CALC7): 방 하나의 벽지 롤 · 몰딩 · 걸레받이 · 페인트 양.

금액이 아닌 참고 수량이라 v10과 같은 소수 계산으로 둔다. 소수 한 자리는 반올림, 개수는 올림.
"""

import math

DOOR_M2 = 1.8  # 문 하나
WINDOW_M2 = 1.5  # 창 하나


def _up(x: float) -> int:
    return math.ceil(x - 1e-9)


def _r1(x: float) -> float:
    return math.floor(x * 10 + 0.5) / 10


def wallpaper(
    w: float,
    d: float,
    hgt: float,
    roll_w: float,
    roll_len: float,
    doors: float = 0,
    windows: float = 0,
    ceiling: bool = False,
    repeat: float = 0,
    loss: float = 10,
) -> dict:
    """폭 단위로 센다. 한 폭 길이 = 높이 + 재단 여유 10cm(+무늬 반복)."""
    perim = 2 * (w + d)
    wall = max(0, perim * hgt - doors * DOOR_M2 - windows * WINDOW_M2)
    strip = hgt + 0.1 + repeat / 100
    per_roll = max(1, math.floor(roll_len / strip))
    strips = _up(wall / (roll_w * hgt))
    c_per = max(1, math.floor(roll_len / (d + 0.1)))
    c_strips = _up(w / roll_w) if ceiling else 0
    raw = strips / per_roll + (c_strips / c_per if ceiling else 0)
    return {
        "wall_m2": _r1(wall),
        "ceiling_m2": _r1(w * d) if ceiling else 0,
        "strips": strips,
        "cStrips": c_strips,
        "per_roll": per_roll,
        "rolls_raw": _r1(raw),
        "rolls": _up(raw * (1 + loss / 100)),
    }


def trim(
    w: float, d: float, doors: float = 0, door_w: float = 0.9, piece: float = 2.4, loss: float = 10
) -> dict:
    """둘레(걸레받이는 문 폭을 뺌) × (1 + 손실률) ÷ 자재 길이."""
    perim = 2 * (w + d)
    base = max(0, perim - doors * door_w)
    return {
        "molding_m": _r1(perim),
        "molding_pcs": _up(perim * (1 + loss / 100) / piece),
        "base_m": _r1(base),
        "base_pcs": _up(base * (1 + loss / 100) / piece),
    }


def paint(
    w: float,
    d: float,
    hgt: float,
    doors: float = 0,
    windows: float = 0,
    ceiling: bool = False,
    coats: float = 2,
    cover: float = 10,
) -> dict:
    """칠할 면적 × 횟수 ÷ 1L당 칠하는 면적. 통은 18L · 4L로 남는 양이 적게."""
    area = max(0, 2 * (w + d) * hgt - doors * DOOR_M2 - windows * WINDOW_M2) + (
        w * d if ceiling else 0
    )
    liters = area * coats / cover
    n18 = math.floor(liters / 18)
    n4 = _up((liters - 18 * n18) / 4)
    if n4 * 4 >= 18:
        n18, n4 = n18 + 1, 0
    return {"area_m2": _r1(area), "liters": _r1(liters), "n18": n18, "n4": n4}
