"""도배 자재 준비(반셀프 '벽지 직접 구매' · 도배 전 점검): 이 집 도배 면적(벽 + 천장 ㎡) + 벽지 종류 → 벽지 롤 수 ·
자투리 몫 · 여분 롤 · 부자재(풀 · 초배지 · 부직포) 양과 표준견적서에서의 포함 상태. 금액은 만들지 않아요.

- 순수 함수예요(DB · HTTP · 시계 없음). 면적 · 벽지 종류 · 소요량 · 표준견적서 줄은 부르는 쪽이 넣어요.
- 롤 규격(폭 · 길이 · 넓이)은 calc.rolls.ROLLS(제조사 공식 규격, 2026-11-22 확인) 그대로예요. 합지는 광폭이 기본이에요.
- 로스율(벽지 소요량): 도배 면적 × 소요량 = 사서 바를 벽지 양(자르고 남는 자투리 포함).
  · 공공 기준 PAPER_RATIO 1.2(아래 출처). 부르는 쪽이 값을 넣지 않으면 이 값으로 세요.
  · 표준견적서 판(refprice)이 시장 보정 소요량을 쓰면(실크 1.248 · 리모델링 1.58) 부르는 쪽이 그 값을 넣어요. 그러면
    필요 롤 수가 표준견적서 화면 롤 수(quote.service.rolls_of)와 같아요(같은 반올림 · 같은 calc.rolls 올림).
- 올림 규칙(여기서만 정해요)
  · 벽지 양 = 도배 면적 × 소요량 → ㎡ 소수 한 자리 → 벽지 평(÷ 3.3058) 소수 한 자리(둘 다 반올림, 표준견적서 도배지 줄과
    같은 셈)
  · 필요 롤 = 벽지 평 × 3.3058 ÷ 롤 넓이를 올림(calc.rolls.need). 면적만 덮는 롤 = 도배 면적 ÷ 롤 넓이를 올림.
    필요 롤은 면적만 덮는 롤보다 적지 않아요(소요량 1에서 벽지 평 반올림으로 모자라는 일을 막아요).
    자투리 몫 = 필요 롤 − 면적만 덮는 롤
  · 여분 롤(SPARE 1~2, 손상 · 무늬 맞춤 대비)은 셈 밖이라 따로 보여요(calc.rolls.SPARE와 같은 값 · 출처).
  · 부자재 양은 소수 한 자리로 올려요(모자라지 않게).
- 부자재: 풀 · 초배지 양은 표준품셈 같은 줄 재료량(할증 포함)이에요. 벽은 콘크리트 · 모르타르면, 천장은 합판 · 석고보드면으로
  봐요(표준견적서 옛 초배지 줄과 같은 가정, refprice primer_wall_ratio · primer_ceiling_ratio). 부직포는 공공 · 업계 양 기준을
  찾지 못해 양을 세지 않고 '업체 확인'이에요(지어내지 않아요).
- 포함 상태: 표준견적서 줄 중 그 자재 이름을 단 줄(부자재 · 시공 · 초배지 줄)의 상태(포함 상태 6종) 그대로예요. 뺀 면처럼
  '안 함'인 줄은 다른 줄이 없을 때만 봐요. 그런 줄이 하나도 없으면 None('업체 확인')이에요.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Protocol

from app.calc import rolls
from app.calc.common import LineState, m2
from app.calc.dobae import paper_py

VERSION = "dobae-rolls-2026.11"
# 정배지(벽지) 소요량 1.2㎡/도배 면적 ㎡, 할증 포함(자르고 남는 몫 · 무늬 맞춤): 2026 건설공사 표준품셈(국토교통부 ·
# 한국건설기술연구원, 2026-01-01 적용) 5-3-7 도배바름 [주] ④ 재료량. 합판 · 석고보드면 · 콘크리트 · 모르타르면 같은 값
PAPER_RATIO = Decimal("1.2")
PAPER_RATIO_SOURCE = "2026 건설공사 표준품셈 5-3-7 도배바름 재료량 정배지 1.2㎡/㎡(할증 포함)"
_STD = "2026 건설공사 표준품셈 5-3-7 도배바름 재료량"
CHECK = "업체 확인"  # 공공 · 업계 기준이 없어 셀 수 없는 칸 · 표준견적서에 그 자재를 단 줄이 없음
SPARE = rolls.SPARE  # 여분 롤 1~2(셈 밖): LX Z:IN 스타일 가이드(2024-10-07) 손상 · 무늬 맞춤 대비
SPARE_SOURCE = rolls.SPARE_SOURCE
_TENTH = Decimal("0.1")

MaterialKey = Literal["paste", "primer", "nonwoven"]


@dataclass(frozen=True)
class MaterialSpec:
    key: MaterialKey
    name: str  # 풀 · 초배지 · 부직포
    unit: str | None  # ㎏ · ㎡ · None(양을 셀 기준 없음)
    wall: Decimal | None  # 벽 도배 면적 ㎡당 양(할증 포함)
    ceiling: Decimal | None  # 천장 도배 면적 ㎡당 양
    words: tuple[str, ...]  # 표준견적서 줄 이름에서 찾을 낱말
    keys: tuple[str, ...]  # 볼 줄 key(앞에서부터)
    source: str


MATERIALS: tuple[MaterialSpec, ...] = (
    # 풀 0.3㎏/㎡(두 바탕면 같음). v4 두 기준 판은 부자재 줄 '(풀 · 부직포 · …)', 옛 판은 시공 줄 '(풀 포함)'에 들어 있어요
    MaterialSpec(
        "paste",
        "풀",
        "㎏",
        Decimal("0.3"),
        Decimal("0.3"),
        ("풀",),
        ("material", "wall", "ceiling", "primer"),
        f"{_STD} 풀 0.3㎏/㎡(할증 포함)",
    ),
    # 초배지 콘크리트 · 모르타르면(벽) 1.2 · 합판 · 석고보드면(천장) 0.8㎡/㎡. 옛 판만 초배지 줄이 있어요
    MaterialSpec(
        "primer",
        "초배지",
        "㎡",
        Decimal("1.2"),
        Decimal("0.8"),
        ("초배",),
        ("primer", "material"),
        f"{_STD} 초배지 콘크리트 · 모르타르면 1.2 · 합판 · 석고보드면 0.8㎡/㎡(할증 포함)",
    ),
    # 부직포: 양 기준(공공 · 제조사)을 찾지 못했어요. 두 기준 판 부자재 줄 이름에만 있어요
    MaterialSpec("nonwoven", "부직포", None, None, None, ("부직포",), ("material",), CHECK),
)


class _Line(Protocol):
    key: str
    name: str
    state: str


@dataclass(frozen=True)
class Material:
    key: MaterialKey
    name: str
    qty: Decimal | None  # 양(소수 한 자리 올림). None이면 셀 기준이 없어 업체 확인
    unit: str | None
    # 그 자재를 단 표준견적서 줄의 포함 상태. None이면 그런 줄이 없어 업체 확인
    state: LineState | None
    line: str | None  # 그 줄 이름
    source: str  # 양의 출처(없으면 CHECK)


@dataclass(frozen=True)
class DobaeRolls:
    key: rolls.RollKey
    name: str  # 실크 · 광폭 합지 · 소폭 합지
    size: str  # '106cm × 15.6m'
    roll_m2: Decimal  # 롤 하나 넓이(폭 × 길이)
    area_m2: Decimal  # 도배 면적(벽 + 천장)
    ratio: Decimal  # 벽지 소요량(도배 면적 × 이 값 = 벽지 양, 자투리 포함)
    paper_m2: Decimal  # 벽지 양 ㎡
    paper_py: Decimal  # 벽지 평
    base: int  # 면적만 덮는 롤(올림)
    count: int  # 필요 롤(자투리 포함, 올림)
    spare_min: int  # 여분 롤(셈 밖, 따로 보이기만)
    spare_max: int
    materials: tuple[Material, ...]
    version: str = VERSION

    @property
    def loss(self) -> int:
        """자투리 몫 롤(필요 롤 − 면적만 덮는 롤)."""
        return self.count - self.base

    @property
    def loss_rate(self) -> Decimal:
        """로스율(소요량 − 1, 1.2면 0.2)."""
        return (self.ratio - 1).normalize()


def _up(x: Decimal) -> Decimal:
    return x.quantize(_TENTH, rounding=ROUND_CEILING)


def _state(spec: MaterialSpec, lines: Sequence[_Line]) -> tuple[LineState | None, str | None]:
    """그 자재를 이름에 단 줄(spec.keys 순서)의 (상태, 이름). '안 함' 줄은 다른 줄이 없을 때만 써요."""
    hits = [
        ln
        for key in spec.keys
        for ln in lines
        if ln.key == key and any(w in ln.name for w in spec.words)
    ]
    hit = next((ln for ln in hits if ln.state != "excluded"), hits[0] if hits else None)
    if hit is None:
        return None, None
    return hit.state, hit.name  # type: ignore[return-value]


def _material(
    spec: MaterialSpec, wall: Decimal, ceiling: Decimal, lines: Sequence[_Line]
) -> Material:
    qty = None
    if spec.wall is not None and spec.ceiling is not None:
        qty = _up(wall * spec.wall + ceiling * spec.ceiling)
    state, line = _state(spec, lines)
    return Material(spec.key, spec.name, qty, spec.unit, state, line, spec.source)


def need(
    wall_m2: Decimal,
    ceiling_m2: Decimal,
    grade: str,
    *,
    ratio: Decimal = PAPER_RATIO,
    lines: Sequence[_Line] = (),
    hapji: rolls.HapjiWidth = "wide",
) -> DobaeRolls:
    """도배 면적(벽 · 천장 ㎡, 하지 않는 면은 0) + 벽지 종류(grade) → 롤 수 · 여분 · 부자재. lines는 이 집 표준견적서 도배
    줄(포함 상태를 읽어요), ratio는 벽지 소요량(그 표준견적서 판 값을 넣으면 롤 수가 표준견적서와 같아요)."""
    if wall_m2 < 0 or ceiling_m2 < 0:
        raise ValueError("도배 면적은 0 이상이어야 해요")
    area = wall_m2 + ceiling_m2
    if area <= 0:
        raise ValueError("도배 면적이 있어야 해요")
    if ratio < 1:
        raise ValueError("벽지 소요량은 1 이상이어야 해요")
    key = rolls.roll_key(grade, hapji)  # 합지 · 실크 밖이면 ValueError
    spec = rolls.ROLLS[key]
    paper_m2 = m2(area * ratio)
    py = paper_py(paper_m2)
    count = rolls.need(key, paper_py=py).count
    base = rolls.need(key, paper_m2=area).count
    mats = tuple(_material(x, wall_m2, ceiling_m2, lines) for x in MATERIALS)
    return DobaeRolls(
        key=key,
        name=spec.name,
        size=spec.size,
        roll_m2=spec.area_m2,
        area_m2=area,
        ratio=ratio,
        paper_m2=paper_m2,
        paper_py=py,
        base=base,
        count=max(count, base),
        spare_min=SPARE[0],
        spare_max=SPARE[1],
        materials=mats,
    )
