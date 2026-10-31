"""공정 플러그인 계약 (TradeSpec). 공정 하나 = 파일 묶음 하나이고, 상담은 이 계약만 보고 공정을 다룬다.

새 공정이 따를 계약
- 키: 영어 소문자 10자 이하. dobae · mokgong · floor · film · paint · tile · bath · kitchen · electric · window
- 파일 (공정 하나에 한 벌)
  - calc/<키>.py: 순수 계산. 입력 · 단가 · 견적 dataclass와 quote(입력, 단가). 견적은 calc.common.Quote 모양
    (version · lines · subtotal · vat · total · man_days · steps · days · assumptions), 줄은 Line(basis 포함).
    공정표 단계 키 prep(짐 정리 · 보양) · finish(정리 · 청소)는 공정을 이을 때 한 번만 남는다.
  - refprice/<키>.py: 단가 한 벌. 값마다 출처 · 적용 시점 · 근거 수준(public · assumed · none).
  - agent/skills/<이름>/SKILL.md(끝에 '## 출처'와 "- [id] 이름" 줄) · agent/prompts/<이름>_v1.md(공정 의견).
    <이름>은 새 공정이면 키와 같다 (도배 · 목공만 wallpaper · carpentry). 전문가 답 프롬프트는 공통(expert_v1).
  - consult/trades/<키>.py: SPEC = TradeSpec(...). consult/trades/__init__.py에 import와 목록을 한 줄씩 이름 순으로.
- 칸 값: choice → str (예/아니요도 "yes" · "no"), multi → list[str], count → int. "unknown"은 선택지 값으로 못 쓴다.
  unknown이 있으면 폼에 '모르겠어요'를 보이고, 고르면 그 값을 넣은 뒤 to_check에 남긴다 (실측 때 확인).
  when(values)이 있으면 그 조건일 때만 묻는다 (값이 빈 칸일 수 있다). 조건이 꺼지면 그 칸 값은 지운다.
  share가 같은 칸(예: "doors" 방문 개수)은 여러 공정을 골라도 한 번만 묻고, 답은 비어 있는 같은 share 칸에
  모두 넣는다. 공정마다 값이 달라지면(대화로 한 공정만 바꿈) 그대로 둔다.
- build(common, values) -> Quote: 값은 이미 검사됐고 물을 칸은 다 찼다. calc 입력을 만들고 refprice 단가로
  calc를 부른다. 금액 · 수량 · 기간은 calc만 만든다.
- 공정표: 단계 키 remove(철거)는 공정을 이을 때 맨 앞(짐 정리 다음)에 모인다. 도배가 끝난 뒤에 하는 작업
  (장판 깔기 · 가구 설치 · 조명 교체)은 calc가 Step(late=True)로 표시하고, 스펙의 late_order 순서로 뒤에 모인다.
- card_lines(common, values) -> list[str]: 공정 의견 에이전트에 넘길 이 공정 칸 설명. 공통 칸 · 공간 ·
  같이 하는 공정 · 모른다고 한 칸 줄은 오케스트레이터가 붙인다.
- prefill(project) -> dict: 견적 받기(ProjectOut)로 채울 칸 값. 견적 받기에 이 공정 칸이 없으면 prefill=None.
- agent: TradeAgent.load(이름, 화면 말, "<이름>_v1.md").

공정 순서 order (본 작업, 작은 수가 먼저. 철거는 공정마다 앞으로 모인다):
window 10 · electric 20 · mokgong 30 · bath 40 · tile 50 · kitchen 60 · paint 70 · film 75 · floor 85 · dobae 90
- 도장 뒤에 필름 (퍼티 샌딩 먼지가 필름 접착을 망친다), 마루 · 포세린은 도배 앞, 장판은 도배 뒤(late).
늦게 하는 작업 late_order (Step.late인 단계만): floor 10 (장판) · kitchen 20 (가구 설치) · electric 30 (조명 · 스위치)
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from app.agent.trade import TradeAgent
from app.calc.common import AreaBasis, Quote

if TYPE_CHECKING:
    from app.project.schemas import ProjectOut

Kind = Literal["choice", "multi", "count"]
Value = str | int | list[str]
Values = Mapping[str, Value]
UNKNOWN = "unknown"  # 폼 · 라우터에서 '모르겠어요'를 뜻하는 값
_KEY = re.compile(r"[a-z]{1,10}")
_FIELD = re.compile(r"[a-z][a-z_]{0,19}")


@dataclass(frozen=True)
class Choice:
    value: str
    label: str  # 화면 말
    desc: str = ""  # 폼에 보일 한 줄 설명


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str  # 화면 말 (예: 도배 유형)
    question: str  # 폼 질문
    kind: Kind
    choices: tuple[Choice, ...] = ()
    min: int = 1  # multi는 고를 개수, count는 숫자 범위
    max: int = 10
    unknown: Value | None = None  # '모르겠어요'일 때 넣는 기본값. None이면 '모르겠어요'가 없다
    when: Callable[[Values], bool] | None = None  # 이 조건일 때만 묻는다
    unit: str = "개"  # count 값 뒤에 붙는 화면 단위
    hint: str = ""  # 라우터가 칸을 헷갈리지 않게 붙이는 짧은 설명
    share: str | None = None  # 같은 값을 여러 공정이 같이 쓰는 칸 (한 번만 묻는다). 예: "doors"

    def __post_init__(self) -> None:
        if not _FIELD.fullmatch(self.key) or (self.share and not _FIELD.fullmatch(self.share)):
            raise ValueError(f"칸 키 · share는 영어 소문자 · _ 20자 이하예요: {self.key}")
        if self.kind == "count":
            if self.choices or not 0 <= self.min <= self.max:
                raise ValueError(f"count 칸은 선택지 없이 min <= max예요: {self.key}")
        elif (
            not self.choices
            or len(set(self.values)) != len(self.choices)
            or UNKNOWN in self.values
            or not 0 <= self.min <= self.max
        ):
            raise ValueError(f"선택지가 비었거나 겹쳐요: {self.key}")
        if self.unknown is not None and not self.ok(self.unknown):
            raise ValueError(f"모르겠어요 기본값이 칸에 맞지 않아요: {self.key}")

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(c.value for c in self.choices)

    def asks(self, values: Values) -> bool:
        return self.when is None or self.when(values)

    def ok(self, v: object) -> bool:
        """카드에 든 값이 이 칸에 맞는지 (모르겠어요 기본값도 이 검사를 지난다)."""
        if self.kind == "choice":
            return isinstance(v, str) and v in self.values
        if self.kind == "multi":
            return (
                isinstance(v, list)
                and all(isinstance(x, str) and x in self.values for x in v)
                and len(set(v)) == len(v)
                and self.min <= len(v) <= self.max
            )
        return isinstance(v, int) and not isinstance(v, bool) and self.min <= v <= self.max

    def norm(self, v: Value) -> Value:
        """multi는 선택지 순서로 맞춘다 (같은 것을 고르면 같은 값)."""
        if self.kind == "multi" and isinstance(v, list):
            return [c.value for c in self.choices if c.value in v]
        return v

    def read(self, raw: str | list[str]) -> tuple[Value, bool]:
        """폼 답 · 라우터 값을 칸 값으로 바꾼다: (값, 모르겠어요였는지). 맞지 않으면 ValueError."""
        if raw == UNKNOWN or raw == [UNKNOWN]:
            if self.unknown is None:
                raise ValueError("모르겠어요를 고를 수 없는 칸이에요")
            return self.unknown, True
        v: object = raw
        if self.kind == "count" and isinstance(raw, str):
            s = raw.strip().removesuffix(self.unit).strip()
            v = int(s) if s.isascii() and s.isdigit() else None
        elif self.kind == "multi":
            v = [raw] if isinstance(raw, str) else list(dict.fromkeys(raw))
        if not self.ok(v):
            raise ValueError("칸에 맞지 않는 값이에요")
        return self.norm(v), False

    def text(self, v: Value) -> str:
        """칸 값을 화면 말로"""
        if self.kind == "count":
            return f"{v}{self.unit}"
        labels = {c.value: c.label for c in self.choices}
        if isinstance(v, list):
            return " · ".join(labels.get(x, x) for x in v)
        return labels.get(str(v), str(v))


@dataclass(frozen=True)
class Common:
    """공정이 같이 쓰는 집 정보. 공통 칸이 다 찬 뒤에만 만든다."""

    area_m2: Decimal
    area_basis: AreaBasis
    occupied: bool
    balcony_ext: bool = False
    built_year: int | None = None


@dataclass(frozen=True)
class TradeSpec:
    key: str  # 영어 소문자 10자 이하
    label: str  # 화면 말 (예: 도배)
    order: int  # 공정 순서 (작은 수가 먼저)
    fields: tuple[FieldSpec, ...]
    agent: TradeAgent
    build: Callable[[Common, Values], Quote]
    card_lines: Callable[[Common, Values], list[str]]
    prefill: Callable[["ProjectOut"], dict[str, Value]] | None = None
    late_order: int | None = (
        None  # Step(late=True) 단계가 있는 공정만. 도배 뒤 작업 순서 (작은 수가 먼저)
    )

    def __post_init__(self) -> None:
        if not _KEY.fullmatch(self.key):
            raise ValueError(f"공정 키는 영어 소문자 10자 이하예요: {self.key}")
        keys = [f.key for f in self.fields]
        if len(set(keys)) != len(keys) or self.order <= 0 or (self.late_order or 1) <= 0:
            raise ValueError(f"칸 키가 겹치거나 순서가 0 이하예요: {self.key}")

    def field(self, key: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.key == key), None)

    def asked(self, values: Values) -> list[FieldSpec]:
        """지금 묻는 칸 (조건이 켜진 칸)"""
        return [f for f in self.fields if f.asks(values)]

    def missing(self, values: Values) -> list[FieldSpec]:
        return [f for f in self.asked(values) if f.key not in values]

    def relevant(self, values: Values) -> dict[str, Value]:
        """지금 묻는 칸의 값만 남긴다. 조건이 다른 칸에 기대면 바뀌지 않을 때까지 되풀이한다."""
        cur = {k: v for k, v in values.items() if self.field(k) is not None}
        while True:
            keep = {k: v for k, v in cur.items() if self.field(k).asks(cur)}
            if keep == cur:
                return keep
            cur = keep

    def catalog(self) -> str:
        """라우터 프롬프트에 넣는 칸 목록: 칸 이름 | 화면 말 | 종류 | 값=뜻 | 구분 설명"""
        rows = [f"## {self.key} {self.label}"]
        for f in self.fields:
            if f.kind == "count":
                vals = f"숫자 {f.min}~{f.max}"
            else:
                vals = ", ".join(f"{c.value}={c.label}" for c in f.choices)
            if f.unknown is not None:
                vals += f", {UNKNOWN}=모르겠어요"
            hint = f" | {f.hint}" if f.hint else ""
            hint += f" | 같이 쓰는 칸 share={f.share}" if f.share else ""
            rows.append(f"- {self.key}.{f.key} | {f.label} | {f.kind} | {vals}{hint}")
        return "\n".join(rows)
