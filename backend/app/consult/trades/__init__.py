"""공정 레지스트리: 공정 키 → 공정 스펙(TradeSpec), 공정 순서(order)대로. 계약은 base.py 맨 위에 있다.

공정을 더할 때는 아래 import와 _SPECS에 한 줄씩, 이름 순으로 넣는다 (여러 사람이 동시에 더해도 충돌이 덜 나게).
"""

from app.consult.trades import (
    dobae,
    mokgong,
)
from app.consult.trades.base import TradeSpec

_SPECS: tuple[TradeSpec, ...] = (
    dobae.SPEC,
    mokgong.SPEC,
)
REGISTRY: dict[str, TradeSpec] = {s.key: s for s in sorted(_SPECS, key=lambda s: s.order)}
if len(REGISTRY) != len(_SPECS) or len({s.order for s in _SPECS}) != len(_SPECS):
    raise ValueError("공정 키와 순서(order)는 겹치면 안 돼요")
ORDER: tuple[str, ...] = tuple(REGISTRY)


def catalog() -> str:
    """라우터 프롬프트에 넣는 전 공정 칸 목록. 레지스트리로 만든 고정 글이라 프롬프트 캐시가 맞는다."""
    return "\n\n".join(s.catalog() for s in REGISTRY.values())
