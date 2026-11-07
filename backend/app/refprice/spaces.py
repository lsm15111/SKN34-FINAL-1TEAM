"""공간 종류별 몫 (2026 하반기, 가정값 초안). 조사값으로 고치기 전 자리 잡기용."""

from decimal import Decimal

from app.calc.spaces import SpaceShares

_D = Decimal

_PAPER_30 = {
    "living": _D("0.23"),
    "kitchen": _D("0.10"),
    "master": _D("0.18"),
    "room": _D("0.14"),
    "dress": _D("0.07"),
    "hall": _D("0.09"),
    "entry": _D("0.05"),
}
_EDGE_30 = {
    "living": _D("0.20"),
    "kitchen": _D("0.14"),
    "master": _D("0.16"),
    "room": _D("0.13"),
    "dress": _D("0.08"),
    "hall": _D("0.10"),
    "entry": _D("0.06"),
}
_CEIL_30 = {
    "living": _D("0.25"),
    "kitchen": _D("0.14"),
    "master": _D("0.15"),
    "room": _D("0.10"),
    "dress": _D("0.05"),
    "hall": _D("0.06"),
    "entry": _D("0.03"),
}

SPACES_2026H2 = SpaceShares(
    version="2026H2-s0",
    paper={b: _PAPER_30 for b in ("10", "20", "30", "40", "50")},
    edge={b: _EDGE_30 for b in ("10", "20", "30", "40", "50")},
    ceiling={b: _CEIL_30 for b in ("10", "20", "30", "40", "50")},
    doors={"master": 1, "room": 1},
    doors_whole={"10": 2, "20": 3, "30": 3, "40": 4, "50": 4},
    whole_at=_D("0.85"),
    fallback="room",
    sources={"all": "팀 가정값 초안"},
)

# 지금 계산에 쓰는 공간 몫
SPACES = SPACES_2026H2
