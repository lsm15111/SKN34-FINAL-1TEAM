"""부분 공사 공간 몫 (D02 A): 고른 공간이 집 전체 도배 면적(벽 + 천장)에서 차지하는 비율.

- 팀 가정값이에요. 9판 C60의 '거실 32% · 주방 14%'는 그림 예시라 쓰지 않았어요.
  공개 평면도 20곳(refprice.floor_plans `plans-2026.11-v9`)을 calc.plan_qty로 셈해
  공간 종류마다 가운뎃값을 소수 두 자리로 잡았어요.
  - 안방 = 이름이 안방인 방(없으면 가장 넓은 방), 작은방 1 · 2 = 나머지 방 중 넓은 순이에요.
  - 작은방 2는 방이 셋 이상인 평면 12곳, 드레스룸은 15곳에만 있어요.
- 고른 몫을 더해 1을 넘으면 1로 둬요. 판(version)은 견적에 고정해요(standard_quotes.share_ver, 20자).
- 공간 몫 표 자료(B6)가 생기면 refprice로 옮기고 판을 올려요.
- 방 개수별 표(SPACE_SHARE_ROOMS, docs/v3/research/whole-house-area.md 방안 4): 방 칩은 방 개수만큼
  안방 · 작은방 1 … 이 생기고, 판마다 칩 몫을 다 더하면 1이에요(모두 켜면 집 전체).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class SpaceShares:
    """공간 몫 표 한 판. share: 공간 종류(project.models.SPACE_KINDS) → 몫(0~1)"""

    version: str
    share: dict[str, Decimal]
    source: str

    def for_rooms(self, rooms: int) -> "SpaceShares":
        """방 개수와 상관없는 한 장짜리 표 (옛 판)"""
        return self


SPACE_SHARE_2026_11 = SpaceShares(
    version="space-share-2026.11",
    share={
        "living": D("0.21"),  # 거실
        "kitchen": D("0.11"),  # 주방 (싱크대 · 타일 벽이라 벽지는 절반으로 셈)
        "master": D("0.19"),  # 안방
        "room1": D("0.17"),  # 작은방 1
        "room2": D("0.15"),  # 작은방 2
        "hall": D("0.08"),  # 복도
        "entry": D("0.06"),  # 현관
        "dress": D("0.08"),  # 드레스룸
    },
    source="팀 가정값 · 공개 평면도 20곳 공간별 도배 면적 비율 가운뎃값 (plans-2026.11-v9)",
)


# 방 칩 순서: 방 1개 = 안방, 2개 = 안방 · 작은방 1 … 5개 = 작은방 4까지
ROOM_KINDS = ("master", "room1", "room2", "room3", "room4")
OTHER_KINDS = ("living", "kitchen", "hall", "entry", "dress")
ROOMS_MIN, ROOMS_MAX = 1, 5


def room_kinds(rooms: int) -> tuple[str, ...]:
    """방 개수 → 방 칩 종류. 1~5 밖이면 ValueError"""
    if not ROOMS_MIN <= rooms <= ROOMS_MAX:
        raise ValueError(f"방 개수는 {ROOMS_MIN}~{ROOMS_MAX}개예요")
    return ROOM_KINDS[:rooms]


def rooms_needed(kinds: Iterable[str]) -> int:
    """고른 공간에 든 방 칩을 다 담는 가장 작은 방 개수 (방 칩이 없으면 0)"""
    return max((ROOM_KINDS.index(k) + 1 for k in kinds if k in ROOM_KINDS), default=0)


@dataclass(frozen=True)
class RoomSpaceShares:
    """방 개수별 공간 몫 표 한 판. tables: 방 개수 → {공간 종류 → 몫}, 판마다 합 1"""

    version: str
    tables: dict[int, dict[str, Decimal]]
    source: str

    def for_rooms(self, rooms: int) -> SpaceShares:
        room_kinds(rooms)
        return SpaceShares(self.version, self.tables[rooms], self.source)


def _rooms_table(rooms: tuple[str, ...], other: tuple[str, ...]) -> dict[str, Decimal]:
    return dict(zip(ROOM_KINDS, map(D, rooms), strict=False)) | dict(
        zip(OTHER_KINDS, map(D, other), strict=True)
    )


# 방 몫(큰 방부터)은 확장 평면도 20곳 가운뎃값: 2방 0.25 · 0.22, 3방 0.18 · 0.16 · 0.15,
# 4방 0.17 · 0.16 · 0.11 · 0.05. 1방 · 5방은 평면이 없어 팀 가정값(1방 0.35, 5방 합 0.50).
# 나머지 공간(거실 · 주방 · 복도 · 현관 · 드레스룸)은 옛 표(0.21 · 0.11 · 0.08 · 0.06 · 0.08)를
# 1 − 방 몫 합에 맞춰 줄이고 소수 두 자리로 맞췄어요(나머지가 큰 칸부터 0.01씩).
SPACE_SHARE_ROOMS_2026_11 = RoomSpaceShares(
    version="space-rooms-2026.11",
    tables={
        1: _rooms_table(("0.35",), ("0.25", "0.13", "0.10", "0.07", "0.10")),
        2: _rooms_table(("0.25", "0.22"), ("0.20", "0.11", "0.08", "0.06", "0.08")),
        3: _rooms_table(("0.18", "0.16", "0.15"), ("0.20", "0.10", "0.08", "0.06", "0.07")),
        4: _rooms_table(("0.17", "0.16", "0.11", "0.05"), ("0.20", "0.10", "0.08", "0.06", "0.07")),
        5: _rooms_table(
            ("0.15", "0.12", "0.10", "0.07", "0.06"), ("0.20", "0.10", "0.07", "0.06", "0.07")
        ),
    },
    source="팀 가정값 · 공개 평면도 20곳 방 개수별 공간 몫 (plans-2026.11-v9, 1 · 5방은 늘려 잡음)",
)


def share_of(kinds: Iterable[str], t: SpaceShares) -> Decimal:
    """고른 공간 몫의 합 (1을 넘으면 1). 모르는 공간 종류는 KeyError, 아무것도 안 고르면 ValueError."""
    picked = list(dict.fromkeys(kinds))
    if not picked:
        raise ValueError("부분 공사할 공간을 골라야 해요")
    return min(sum((t.share[k] for k in picked), D(0)), D(1))
