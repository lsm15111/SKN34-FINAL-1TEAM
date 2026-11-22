"""벽지 롤 수(보이기용): 벽지 양(벽지 평 · ㎡) + 롤 종류 → 롤 수(올림). 금액은 만들지 않아요.

- 돈은 지금처럼 벽지 평으로 세요(표준견적서 도배지 줄). 롤 수는 '몇 롤 사요'를 보이는 값이에요.
- 롤 크기는 제조사 공식 규격(2026-11-22 확인, d10-/data/catalog/roll_sizes.csv):
  실크 106cm × 15.6m(LX Z:IN · 신한벽지 · 개나리벽지), 광폭 합지 93cm × 17.75m(같은 세 곳),
  소폭 합지 53cm × 12.5m(신한벽지 · 개나리벽지).
- 합지는 광폭이 기본이고 소폭은 고를 때만이에요(세 제조사 주력 합지가 광폭이고 LX Z:IN에는 소폭 제품이 없어요).
- 롤 수 = 벽지 ㎡ ÷ 롤 한 개 넓이(폭 × 길이)를 올림. 벽지 평이면 × 3.3058㎡(벽지 1평)로 바꿔 세요.
  벽지 양에는 이미 자르고 남는 양(소요량)이 들어 있어요.
- 여분(1~2롤)은 셈에 넣지 않고 따로 보여 줘요(LX Z:IN 스타일 가이드 2024-10-07: 손상 · 무늬 맞춤에 대비해 더 주문).
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from app.calc.common import PYEONG_M2

VERSION = "rolls-2026.11"
RollKey = Literal["silk", "hapji_wide", "hapji_narrow"]
HapjiWidth = Literal["wide", "narrow"]


@dataclass(frozen=True)
class RollSpec:
    key: RollKey
    name: str  # 실크 · 광폭 합지 · 소폭 합지
    width_m: Decimal
    length_m: Decimal
    source: str

    @property
    def area_m2(self) -> Decimal:
        return self.width_m * self.length_m

    @property
    def size(self) -> str:
        """'106cm × 15.6m'"""
        cm = format((self.width_m * 100).normalize(), "f")
        return f"{cm}cm × {format(self.length_m.normalize(), 'f')}m"


_MAKERS = "제조사 공식 규격(2026-11-22 확인)"
ROLLS: dict[RollKey, RollSpec] = {
    "silk": RollSpec(
        "silk",
        "실크",
        Decimal("1.06"),
        Decimal("15.6"),
        f"{_MAKERS} · LX Z:IN · 신한벽지 · 개나리벽지",
    ),
    "hapji_wide": RollSpec(
        "hapji_wide",
        "광폭 합지",
        Decimal("0.93"),
        Decimal("17.75"),
        f"{_MAKERS} · LX Z:IN · 신한벽지 · 개나리벽지",
    ),
    "hapji_narrow": RollSpec(
        "hapji_narrow",
        "소폭 합지",
        Decimal("0.53"),
        Decimal("12.5"),
        f"{_MAKERS} · 신한벽지 · 개나리벽지",
    ),
}
SPARE = (1, 2)  # 여분 롤(셈 밖, 따로 보이기만)
SPARE_SOURCE = "LX Z:IN 스타일 가이드(2024-10-07) · 손상 · 무늬 맞춤에 대비해 더 주문"


def roll_key(grade: str, hapji: HapjiWidth = "wide") -> RollKey:
    """도배 유형 → 롤 종류. 실크(basic)는 실크 롤, 합지(economy)는 광폭(기본) · 소폭(고를 때만)."""
    if grade == "basic":
        return "silk"
    if grade == "economy":
        return "hapji_narrow" if hapji == "narrow" else "hapji_wide"
    raise ValueError("벽지는 합지 · 실크 중 하나예요")


@dataclass(frozen=True)
class RollNeed:
    key: RollKey
    name: str
    size: str
    count: int  # 롤 수(올림, 여분 빼고)
    spare_min: int
    spare_max: int
    version: str = VERSION

    @property
    def text(self) -> str:
        """화면 · 카드 말: '실크(106cm × 15.6m) 약 11롤 · 여분 1~2롤은 따로'"""
        return (
            f"{self.name}({self.size}) 약 {self.count}롤 · "
            f"여분 {self.spare_min}~{self.spare_max}롤은 따로"
        )


def need(
    key: RollKey, *, paper_py: Decimal | None = None, paper_m2: Decimal | None = None
) -> RollNeed:
    """벽지 양(벽지 평 또는 ㎡ 하나만) → 롤 수(올림). 여분은 셈에 넣지 않아요."""
    if (paper_py is None) == (paper_m2 is None):
        raise ValueError("벽지 양은 벽지 평이나 ㎡ 하나만 넣어요")
    area = paper_m2 if paper_m2 is not None else paper_py * PYEONG_M2  # type: ignore[operator]
    if area < 0:
        raise ValueError("벽지 양은 0 이상이어야 해요")
    spec = ROLLS[key]
    count = int((area / spec.area_m2).to_integral_value(rounding=ROUND_CEILING))
    return RollNeed(key, spec.name, spec.size, count, *SPARE)
