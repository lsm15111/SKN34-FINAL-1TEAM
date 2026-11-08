"""고른 공간만큼만 계산: 공간 이름 → 종류, 종류 · 평형대별 몫 → 집 전체 수량에 곱할 비율.

고객은 '도배 · 목공할 공간'만 골라 보낸다(집 전체 목록이 아니다). 그래서 몫은 흔한 평면(판상형 · 평형대별)에서
그 종류 공간 한 곳이 집 전체 수량 중 차지하는 비율로 잡는다. 고른 공간 몫을 더하고, 거의 다 골랐으면
(whole_at 이상) 집 전체로 본다. 몫은 가정값이라 일부만 고르면 범위 계산에서 수량 정밀도를 한 단계 낮춘다.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

SpaceKind = Literal[
    "living", "kitchen", "master", "room", "dress", "hall", "entry", "bath", "utility", "other"
]
KINDS: tuple[SpaceKind, ...] = (
    "living",
    "kitchen",
    "master",
    "room",
    "dress",
    "hall",
    "entry",
    "bath",
    "utility",
    "other",
)
# 앞에서부터 맞춰 본다. '안방 화장실' · '주방' · '드레스룸' · '옷방'이 '방'보다 먼저 걸리게 순서를 둔다
_RULES: tuple[tuple[SpaceKind, re.Pattern[str]], ...] = (
    ("bath", re.compile(r"욕실|화장실|샤워|세면|욕조")),
    ("utility", re.compile(r"다용도|세탁|발코니|베란다|보일러|실외기|창고|팬트리")),
    ("dress", re.compile(r"드레스|옷방|파우더|워크인")),
    ("kitchen", re.compile(r"주방|부엌|식당|다이닝|키친")),
    ("living", re.compile(r"거실|리빙")),
    ("entry", re.compile(r"현관|중문")),
    ("hall", re.compile(r"복도|통로")),
    ("master", re.compile(r"안방|큰방|부부|마스터|침실\s*1(?!\d)")),
    ("room", re.compile(r"방|침실|룸|서재|공부|게스트|작업실")),
)
BANDS = ("10", "20", "30", "40", "50")
_Q = Decimal("0.001")


def kinds_of(name: str) -> tuple[SpaceKind, ...]:
    """공간 이름 → 종류. '거실 · 주방'처럼 둘을 묶은 이름은 둘 다, 모르는 이름은 other."""
    n = name.strip()
    if re.search(r"거실|리빙", n) and re.search(r"주방|부엌|식당|다이닝|키친", n):
        return ("living", "kitchen")
    for kind, pat in _RULES:
        if pat.search(n):
            return (kind,)
    return ("other",)


def band_of(pyeong: Decimal) -> str:
    """공급 평수 → 평형대(10 · 20 · 30 · 40 · 50)"""
    if pyeong <= 0:
        raise ValueError("평수는 0보다 커야 해요")
    tens = int(pyeong // 10) * 10
    return str(min(max(tens, 10), 50))


@dataclass(frozen=True)
class SpaceShares:
    """종류별 몫 한 벌. refprice가 버전별로 만들어 넘긴다. 몫은 모두 '그 종류 한 곳'의 값이다.

    paper: 도배 면적(벽 + 천장) 중 몫, molding · base: 천장 몰딩 · 걸레받이 길이 중 몫,
    ceiling: 전용면적 대비 천장 면적. 표에 없는 종류는 0으로 본다(욕실 · 다용도실은 보통 도배 · 몰딩을 하지 않는다).
    cv: 한 곳 몫의 상대 σ(같은 평형대 안 방 크기 차이). 여러 곳은 서로 독립으로 보고 제곱합으로 묶는다."""

    version: str
    paper: Mapping[str, Mapping[SpaceKind, Decimal]]  # 평형대 → 종류 → 몫
    molding: Mapping[str, Mapping[SpaceKind, Decimal]]
    base: Mapping[str, Mapping[SpaceKind, Decimal]]
    ceiling: Mapping[str, Mapping[SpaceKind, Decimal]]
    cv: Mapping[SpaceKind, Decimal]  # 종류 → 한 곳 몫의 상대 σ
    cv_guess: Decimal  # 이름으로 종류를 몰라 fallback으로 본 곳의 상대 σ
    base_ratio: Decimal  # 걸레받이 길이 ÷ 몰딩 길이 (몰딩 · 걸레받이를 묶은 몫에 쓴다)
    doors: Mapping[SpaceKind, int]  # 종류 → 방문 수
    doors_whole: Mapping[str, int]  # 평형대 → 흔한 평면의 방문 수(방문만 바꾸는 공사의 크기 몫)
    whole_at: Decimal  # 고른 도배 몫 합이 이 이상이면 집 전체로 본다
    fallback: SpaceKind  # 이름으로 종류를 모를 때 쓰는 종류(작은방)
    sources: Mapping[str, str]


@dataclass(frozen=True)
class SpacePick:
    """고른 공간을 수량 몫으로 바꾼 결과. whole이면 몫은 모두 1, σ는 0이다."""

    whole: bool
    paper: Decimal  # 도배 면적에 곱할 몫 (0~1)
    molding: Decimal  # 몰딩 길이에 곱할 몫
    base: Decimal  # 걸레받이 길이에 곱할 몫 (현관만 고르면 0일 수 있다)
    edge: Decimal  # 몰딩 · 걸레받이를 길이로 묶은 몫(공사 크기 · 범위에 쓴다)
    flat_m2_share: Decimal  # 천장 평탄화 면적 = 전용면적 × 이 값 (고른 공간 중 거실 천장, 없으면 고른 공간 천장)
    doors: int  # 고른 공간의 방문 수
    door_share: Decimal  # 방문 수 ÷ 흔한 평면의 방문 수 (0~1, 방문만 바꿀 때 공사 크기)
    paper_sigma: Decimal  # 도배 몫의 상대 σ (범위 share:area)
    edge_sigma: Decimal  # 몰딩 · 걸레받이 몫의 상대 σ (범위 share:edge)
    kinds: tuple[SpaceKind, ...]
    guessed: tuple[str, ...]  # 종류를 몰라 fallback으로 본 이름
    zero: tuple[str, ...]  # 그 공정을 보통 하지 않는 공간(욕실 · 다용도실) 이름
    # 고른 공간(이름)마다 도배 몫. 업체는 벽지 롤을 방마다 따로 세어 올린다(calc.price_range JobRule.per_room).
    # 도배를 보통 안 하는 곳은 빼고, whole이면 비운다
    paper_rooms: tuple[Decimal, ...] = ()


def _share(table: Mapping[SpaceKind, Decimal], kinds: Sequence[SpaceKind]) -> Decimal:
    return sum((table.get(k, Decimal(0)) for k in kinds), Decimal(0))


def _q(x: Decimal) -> Decimal:
    return x.quantize(_Q, rounding=ROUND_HALF_UP)


def _rel_sigma(items: Sequence[tuple[Decimal, Decimal]]) -> Decimal:
    """(몫, 상대 σ) 목록 → 몫 합의 상대 σ. 곳마다 독립으로 본다"""
    total = sum((s for s, _ in items), Decimal(0))
    if total <= 0:
        return Decimal(0)
    var = sum(((s * c) ** 2 for s, c in items), Decimal(0))
    return _q(var.sqrt() / total)


def pick(names: Sequence[str], band: str, r: SpaceShares) -> SpacePick:
    """고른 공간 이름들 → 수량 몫. 같은 종류를 여러 곳 고르면 몫을 그만큼 더한다."""
    if not names:
        raise ValueError("공간을 하나 이상 골라야 해요")
    if band not in r.paper:
        raise ValueError("평형대를 다시 확인해 주세요")
    paper_t, mold_t, base_t, ceil_t = r.paper[band], r.molding[band], r.base[band], r.ceiling[band]
    kinds: list[SpaceKind] = []
    cvs: list[Decimal] = []  # kinds와 같은 순서
    guessed: list[str] = []
    zero: list[str] = []
    rooms: list[Decimal] = []  # 이름마다 도배 몫('거실 · 주방'처럼 묶은 이름은 한 곳)
    for n in names:
        ks = kinds_of(n)
        guess = ks == ("other",)
        if guess:
            guessed.append(n)
            ks = (r.fallback,)
        room = _share(paper_t, ks)
        if room == 0:
            zero.append(n)
        else:
            rooms.append(room)
        kinds.extend(ks)
        cvs.extend(r.cv_guess if guess else r.cv.get(k, Decimal(0)) for k in ks)
    # 욕실 · 다용도실만 골랐어도 0원 견적은 내지 않는다: 작은방 하나로 본다(크기는 모름)
    if len(zero) == len(names):
        kinds, cvs = [r.fallback], [r.cv_guess]
        rooms = [paper_t.get(r.fallback, Decimal(0))]
    paper = _share(paper_t, kinds)
    molding, base = _share(mold_t, kinds), _share(base_t, kinds)
    edge = (molding + r.base_ratio * base) / (1 + r.base_ratio)
    whole = paper >= r.whole_at
    # 평탄화는 보통 거실 천장(우물천장 · 등박스)이다. 거실이 없으면 고른 공간 천장, 그것도 없으면 작은방 하나
    flat = ceil_t.get("living", Decimal(0)) if "living" in kinds else _share(ceil_t, kinds)
    flat = flat or ceil_t.get(r.fallback, Decimal(0))
    doors = sum(r.doors.get(k, 0) for k in kinds)
    door_share = min(Decimal(max(doors, 1)) / Decimal(r.doors_whole[band]), Decimal(1))
    one = Decimal(1)

    def edge_of(k: SpaceKind) -> Decimal:
        m, b = mold_t.get(k, Decimal(0)), base_t.get(k, Decimal(0))
        return (m + r.base_ratio * b) / (1 + r.base_ratio)

    paper_sigma = _rel_sigma(
        [(paper_t.get(k, Decimal(0)), c) for k, c in zip(kinds, cvs, strict=True)]
    )
    edge_sigma = _rel_sigma([(edge_of(k), c) for k, c in zip(kinds, cvs, strict=True)])
    return SpacePick(
        whole=whole,
        paper=one if whole else _q(min(paper, one)),
        molding=one if whole else _q(min(molding, one)),
        base=one if whole else _q(min(base, one)),
        edge=one if whole else _q(min(edge, one)),
        flat_m2_share=_q(flat),
        doors=doors,
        door_share=one if whole else _q(door_share),
        paper_sigma=Decimal(0) if whole else paper_sigma,
        edge_sigma=Decimal(0) if whole else edge_sigma,
        kinds=tuple(kinds),
        guessed=tuple(guessed),
        zero=tuple(zero),
        paper_rooms=() if whole else tuple(rooms),
    )
