"""전기 · 조명 공정 스펙: 할 일(조명 교체 · 콘센트와 스위치 교체 · 콘센트 자리 늘리기)을 고르고, 고른 것마다
범위 · 개수 · 조명 종류를 묻는다. calc.electric으로 계산한다. 할 일을 하나 이상 골라야 해서 빈 공사가 없다."""

from app.agent.trade import TradeAgent
from app.calc import electric as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.electric import ELECTRIC_2026H2

AGENT = TradeAgent.load("electric", "전기·조명", "electric_v1.md")
ITEMS = (
    Choice("lights", "조명 교체", "기존 등을 떼고 새 조명을 달아요"),
    Choice("outlets", "콘센트 · 스위치 교체", "기존 자리에서 새것으로 바꿔요"),
    Choice("points", "콘센트 자리 늘리기", "배선을 새로 끌어 자리를 늘려요"),
)
RANGES = (Choice("all", "집 전체"), Choice("some", "몇 개만"))
LIGHT_TYPES = (
    Choice("flat", "LED 평판 · 방등", "천장에 바로 붙이는 기본 조명이에요. 바꿔 달기 쉬워요"),
    Choice("downlight", "다운라이트", "넓어 보이지만 천장에 구멍을 내야 해서 옮기기 어려워요"),
    Choice("line", "라인 조명", "길게 이어져요. 천장 홈 작업이 필요할 수 있고 값이 높은 편이에요"),
)


def _has(item: str):
    return lambda v: item in v.get("items", ())


def _some(field: str):
    return lambda v: v.get(field) == "some"


def _build(c: Common, v: Values) -> calc.ElectricQuote:
    items = v["items"]
    return calc.quote(
        calc.ElectricInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            occupied=c.occupied,
            lights=v["light_range"] if "lights" in items else "none",
            light_count=v.get("light_count", 0),
            light_type=v.get("light_type", "flat"),
            outlets=v["outlet_range"] if "outlets" in items else "none",
            outlet_count=v.get("outlet_count", 0),
            new_points=v["new_points"] if "points" in items else 0,
        ),
        ELECTRIC_2026H2,
    )


def _label(choices: tuple[Choice, ...], value: object) -> str:
    return next(c.label for c in choices if c.value == value)


def _card_lines(c: Common, v: Values) -> list[str]:
    items = v["items"]
    rows = ["전기 공사: " + ", ".join(_label(ITEMS, i) for i in items)]
    if "lights" in items:
        rows.append(
            f"조명: {_label(RANGES, v['light_range'])}, {_label(LIGHT_TYPES, v['light_type'])}"
        )
    if "outlets" in items:
        rows.append(f"콘센트 · 스위치: {_label(RANGES, v['outlet_range'])}")
    if "points" in items:
        rows.append("콘센트 자리 늘리기: 해요 (가구 · 가전 배치를 먼저 정해요)")
    return rows


SPEC = TradeSpec(
    key="electric",
    label="전기·조명",
    order=20,
    late_order=30,
    fields=(
        FieldSpec(
            key="items",
            label="전기 공사",
            question="어떤 전기 공사를 할까요? 여러 개 골라도 돼요.",
            kind="multi",
            choices=ITEMS,
            max=len(ITEMS),
            hint="분전반 · 에어컨 · 통신 · 보일러는 전기 항목이 아니에요",
        ),
        FieldSpec(
            key="light_range",
            label="조명 교체 범위",
            question="조명은 집 전체를 바꾸나요, 몇 개만 바꾸나요?",
            kind="choice",
            choices=RANGES,
            unknown="all",
            when=_has("lights"),
        ),
        FieldSpec(
            key="light_count",
            label="바꿀 조명 개수",
            question="바꿀 조명은 몇 개예요?",
            kind="count",
            min=1,
            max=10,
            unknown=5,
            when=_some("light_range"),
            hint="바꿀 조명 개수를 숫자로 말했을 때만",
        ),
        FieldSpec(
            key="light_type",
            label="조명 종류",
            question="주로 어떤 조명을 달까요?",
            kind="choice",
            choices=LIGHT_TYPES,
            unknown="flat",
            when=_has("lights"),
            hint="매입등이면 downlight",
        ),
        FieldSpec(
            key="outlet_range",
            label="콘센트 · 스위치 교체 범위",
            question="콘센트 · 스위치는 집 전체를 바꾸나요, 몇 개만 바꾸나요?",
            kind="choice",
            choices=RANGES,
            unknown="all",
            when=_has("outlets"),
        ),
        FieldSpec(
            key="outlet_count",
            label="바꿀 콘센트 · 스위치 개수",
            question="바꿀 콘센트 · 스위치는 모두 몇 개예요?",
            kind="count",
            min=1,
            max=15,
            unknown=10,
            when=_some("outlet_range"),
            hint="콘센트와 스위치를 더한 개수",
        ),
        FieldSpec(
            key="new_points",
            label="늘릴 콘센트 자리",
            question="콘센트 자리를 몇 곳 늘릴까요?",
            kind="count",
            min=1,
            max=6,
            unknown=2,
            when=_has("points"),
            unit="곳",
        ),
    ),
    agent=AGENT,
    build=_build,
    card_lines=_card_lines,
)
