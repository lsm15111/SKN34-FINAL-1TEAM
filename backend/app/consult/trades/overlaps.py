"""공정끼리 범위가 겹칠 때 알릴 말. 두 공정을 같이 고르면 같은 곳을 두 번 계산했을 수 있다.

계산은 바꾸지 않는다 (어느 쪽으로 할지는 고객 · 실측이 정한다). 규칙은 한 줄에 하나씩, 공정 키 이름 순으로 더한다.
말은 '-해요'체로 쓰고 숫자를 넣지 않는다.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.consult.trades.base import Values


@dataclass(frozen=True)
class Overlap:
    a: str  # 공정 키
    b: str
    when: Callable[[Values, Values], bool]  # (a 공정 칸 값, b 공정 칸 값) → 겹치는지
    text: str  # 결과에 보일 말


def has(field: str, *values: str) -> Callable[[Values], bool]:
    """칸 값(하나 또는 여러 개)에 values 중 하나라도 있으면 참. 칸이 비어 있으면 거짓."""

    def check(v: Values) -> bool:
        x = v.get(field)
        got = x if isinstance(x, list) else [x]
        return any(y in got for y in values)

    return check


def always(_: Values) -> bool:
    return True


def both(fa: Callable[[Values], bool], fb: Callable[[Values], bool]):
    return lambda a, b: fa(a) and fb(b)


SAME_WALL = (
    "도배와 도장에 같은 벽 · 천장이 들어갔을 수 있으니, 곳마다 도배할지 칠할지 하나로 정해요."
)
DOOR_TWICE = (
    "같은 방문에 칠과 필름이 같이 들어갔을 수 있으니, 문마다 칠할지 필름을 붙일지 하나로 정해요."
)
NEW_DOOR_FILM = (
    "목공에서 새로 다는 방문은 마감된 제품이라, 필름은 그대로 두는 문 · 문틀에만 붙여요."
)
NEW_DOOR_PAINT = "목공에서 새로 다는 방문은 마감된 제품이라, 칠은 그대로 두는 문 · 문틀에만 해요."
NEW_MOLDING = (
    "천장 몰딩을 목공과 필름에 모두 넣었으니, 새 몰딩을 마감된 제품으로 달지"
    " 필름을 붙일지 하나로 정해요."
)

_FILM_DOOR = has("items", "door", "frame")  # 필름: 방문 문짝 · 문틀
_MOKGONG_DOOR = has("items", "door")  # 목공: 방문 교체
_MOLDING = has("items", "molding")  # 목공 · 필름: 천장 몰딩 (칸 · 값 이름이 같다)
_PAINT_DOOR = has("surfaces", "door")  # 도장: 방문 · 문틀


def _same_wall(dobae: Values, paint: Values) -> bool:
    """도배는 벽을 늘 바르고 천장은 고를 때만 바른다."""
    ceiling = has("include_ceiling", "yes")(dobae) and has("surfaces", "ceiling")(paint)
    return has("surfaces", "wall")(paint) or ceiling


def _new_door_film(film: Values, mokgong: Values) -> bool:
    """새 방문은 문짝이 마감된 제품이고, 문틀까지 바꾸면(문짝만이 아니면) 문틀도 그렇다."""
    frame = has("items", "frame")(film) and mokgong.get("door_frame") != "no"
    return _MOKGONG_DOOR(mokgong) and (has("items", "door")(film) or frame)


RULES: tuple[Overlap, ...] = (
    Overlap("dobae", "paint", _same_wall, SAME_WALL),
    Overlap(
        "dobae",
        "window",
        both(always, always),
        "도배를 새로 하니, 창호 견적에 창 둘레 벽지 보수가 또 들어 있지 않은지 봐요.",
    ),
    Overlap(
        "electric",
        "kitchen",
        both(always, always),
        "인덕션 전용 회로가 필요하면 주방과 전기 견적에 겹쳐 넣지 말고 전기 공정에서 같이 봐요.",
    ),
    Overlap(
        "electric",
        "mokgong",
        both(has("light_type", "downlight", "line"), has("items", "flatten")),
        "다운라이트 · 라인 조명 자리는 천장 평탄화 때 같이 잡고, "
        "천장 구멍 · 보수가 전기와 목공 견적에 겹치지 않는지 봐요.",
    ),
    Overlap(
        "film",
        "kitchen",
        both(has("items", "kitchen"), always),
        "주방 가구를 새로 바꾸면 주방 문짝 필름은 하지 않아도 돼요.",
    ),
    Overlap("film", "mokgong", _new_door_film, NEW_DOOR_FILM),
    Overlap("film", "mokgong", both(_MOLDING, _MOLDING), NEW_MOLDING),
    Overlap("film", "paint", both(_FILM_DOOR, _PAINT_DOOR), DOOR_TWICE),
    Overlap("mokgong", "paint", both(_MOKGONG_DOOR, _PAINT_DOOR), NEW_DOOR_PAINT),
    Overlap(
        "paint",
        "window",
        both(has("surfaces", "balcony"), always),
        "창을 떼고 달 때 베란다 벽이 상할 수 있어서, 창호를 먼저 바꾼 뒤 베란다 탄성코트를 칠해요.",
    ),
)


def overlaps(trades: list[str], values: Mapping[str, Values]) -> list[str]:
    """고른 공정끼리 겹치는 규칙의 말 (규칙 순서대로, 같은 말은 한 번)"""
    picked = set(trades)
    out: list[str] = []
    for r in RULES:
        both_picked = r.a in picked and r.b in picked
        if both_picked and r.text not in out and r.when(values.get(r.a, {}), values.get(r.b, {})):
            out.append(r.text)
    return out
