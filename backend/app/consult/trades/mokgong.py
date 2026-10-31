"""목공 공정 스펙: 항목(천장 몰딩 · 걸레받이 · 방문 · 천장 평탄화)과 방문 개수 · 문틀 교체를 묻고
calc.mokgong으로 계산한다. 방문 칸은 항목에 방문이 있을 때만 묻는다."""

from typing import TYPE_CHECKING

from app.agent.carpentry import AGENT
from app.calc import mokgong as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Value, Values
from app.refprice.book import MOKGONG_2026H2

if TYPE_CHECKING:
    from app.project.schemas import ProjectOut

ITEMS = (
    Choice("molding", "천장 몰딩", "천장과 벽이 만나는 선"),
    Choice("base", "걸레받이", "바닥과 벽이 만나는 선"),
    Choice("door", "방문", "문틀 · 문짝 교체"),
    Choice("flatten", "천장 평탄화", "우물천장 · 등박스를 평평하게"),
)
ITEM_LABEL = {c.value: c.label for c in ITEMS}


def _doors(v: Values) -> bool:
    return "door" in v.get("items", ())


def _build(c: Common, v: Values) -> calc.MokgongQuote:
    items = tuple(v["items"])
    door = "door" in items
    return calc.quote(
        calc.MokgongInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            items=items,
            occupied=c.occupied,
            doors=v["doors"] if door else 0,
            door_frame=v.get("door_frame") != "no",
        ),
        MOKGONG_2026H2,
    )


def _card_lines(c: Common, v: Values) -> list[str]:
    rows = ["목공 항목: " + ", ".join(ITEM_LABEL[i] for i in v["items"])]
    if "door" in v["items"]:
        rows.append(f"방문: {'문짝만' if v.get('door_frame') == 'no' else '문틀까지'} 바꿔요")
    return rows


def _prefill(p: "ProjectOut") -> dict[str, Value]:
    t = p.trades.mokgong
    return {"items": list(t.items)} if t else {}


SPEC = TradeSpec(
    key="mokgong",
    label="목공",
    order=30,
    fields=(
        FieldSpec(
            key="items",
            label="목공 항목",
            question="어떤 목공을 할까요? 여러 개 골라도 돼요.",
            kind="multi",
            choices=ITEMS,
            max=len(ITEMS),
            hint="중문 · 가벽 · 아트월 · 붙박이장은 목공 항목이 아니에요",
        ),
        FieldSpec(
            key="doors",
            label="방문 개수",
            question="바꿀 방문은 몇 개예요?",
            kind="count",
            min=1,
            max=10,
            unknown=3,
            when=_doors,
            hint="바꿀 방문 개수를 숫자로 말했을 때만",
            share="doors",
        ),
        FieldSpec(
            key="door_frame",
            label="문틀 교체",
            question="문틀까지 바꾸나요, 문짝만 바꾸나요?",
            kind="choice",
            choices=(Choice("yes", "문틀까지 바꿔요"), Choice("no", "문짝만 바꿔요")),
            unknown="yes",
            when=_doors,
        ),
    ),
    agent=AGENT,
    build=_build,
    card_lines=_card_lines,
    prefill=_prefill,
)
