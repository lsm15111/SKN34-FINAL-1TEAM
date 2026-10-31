"""공정 레지스트리: 공정 키 → 공정 스펙(TradeSpec), 공정 순서(order)대로. 계약은 base.py 맨 위에 있다.

공정을 더할 때는 아래 import와 _SPECS에 한 줄씩, 이름 순으로 넣는다 (여러 사람이 동시에 더해도 충돌이 덜 나게).
"""

from app.consult.trades import (
    dobae,
    film,
    floor,
    mokgong,
    paint,
    tile,
)
from app.consult.trades.base import TradeSpec

_SPECS: tuple[TradeSpec, ...] = (
    dobae.SPEC,
    film.SPEC,
    floor.SPEC,
    mokgong.SPEC,
    paint.SPEC,
    tile.SPEC,
)
REGISTRY: dict[str, TradeSpec] = {s.key: s for s in sorted(_SPECS, key=lambda s: s.order)}
if len(REGISTRY) != len(_SPECS) or len({s.order for s in _SPECS}) != len(_SPECS):
    raise ValueError("공정 키와 순서(order)는 겹치면 안 돼요")
ORDER: tuple[str, ...] = tuple(REGISTRY)
_LATE = sorted((s for s in _SPECS if s.late_order is not None), key=lambda s: s.late_order)
if len({s.late_order for s in _LATE}) != len(_LATE):
    raise ValueError("늦게 하는 작업 순서(late_order)는 겹치면 안 돼요")
LATE_ORDER: tuple[str, ...] = tuple(s.key for s in _LATE)


def catalog() -> str:
    """라우터 프롬프트에 넣는 전 공정 칸 목록. 레지스트리로 만든 고정 글이라 프롬프트 캐시가 맞는다."""
    parts = [s.catalog() for s in REGISTRY.values()]
    shares: dict[str, list[str]] = {}
    for s in REGISTRY.values():
        for f in s.fields:
            if f.share:
                shares.setdefault(f.share, []).append(f"{s.key}.{f.key}")
    if rows := [f"- share={k}: {', '.join(v)}" for k, v in shares.items() if len(v) > 1]:
        head = "## 같이 쓰는 칸 (고객이 공정을 집어 말하지 않으면 같은 값으로 모두 바꾼다)"
        parts.append("\n".join([head, *rows]))
    return "\n\n".join(parts)
