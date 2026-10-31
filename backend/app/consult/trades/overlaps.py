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


RULES: tuple[Overlap, ...] = (
    Overlap(
        "dobae",
        "window",
        both(always, always),
        "창호를 바꾸면 창 둘레 벽지가 상할 수 있어요. 도배를 같이 하면 창 둘레 도배 보수가 "
        "창호 견적에 또 들어 있지 않은지 봐요.",
    ),
    Overlap(
        "electric",
        "kitchen",
        both(always, always),
        "주방에 인덕션을 두면 전용 회로가 필요할 수 있어요. 주방과 전기 견적에 겹쳐 넣지 말고 "
        "전기 공정에서 같이 봐요.",
    ),
    Overlap(
        "electric",
        "mokgong",
        both(has("light_type", "downlight", "line"), has("items", "flatten")),
        "천장 평탄화를 하면 다운라이트 · 라인 조명 자리를 목공 때 같이 잡아요. 천장 구멍 · 보수가 "
        "전기와 목공 견적에 겹치지 않는지 봐요.",
    ),
    Overlap(
        "film",
        "kitchen",
        both(has("items", "kitchen"), always),
        "주방 가구를 새로 바꾸면 주방 문짝 필름은 하지 않아도 돼요.",
    ),
    Overlap(
        "paint",
        "window",
        both(has("surfaces", "balcony"), always),
        "창호를 먼저 바꾸고 베란다 탄성코트를 칠해요. 창을 떼고 달 때 베란다 벽이 상할 수 있어요.",
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
