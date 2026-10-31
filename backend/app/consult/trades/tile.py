"""타일 공정 스펙: 붙일 곳(주방 벽 · 현관 바닥 · 베란다 바닥)과 타일 크기, 지금 타일을 뗄지 묻고
calc.tile로 계산한다. 거실 · 방 바닥 타일은 바닥재, 욕실 타일은 욕실 공정이다."""

from app.agent.trade import TradeAgent
from app.calc import tile as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.tile import TILE_2026H2

PARTS = (
    Choice("kitchen", "주방 벽", "싱크대 위 벽"),
    Choice("entrance", "현관 바닥", "신발 벗는 곳 바닥"),
    Choice("balcony", "베란다 바닥", "베란다 벽은 빼요"),
)
PART_LABEL = {c.value: c.label for c in PARTS}
SIZES = (
    Choice("small", "작은 타일", "잘라 맞추기 쉬워요. 줄눈이 많아 닦을 곳이 늘어요"),
    Choice("medium", "중간 타일", "주방 벽에 흔히 써요. 줄눈 · 시공비가 알맞아요"),
    Choice("large", "큰 타일", "줄눈이 적어 깔끔해요. 무겁고 붙이기 까다로워요"),
)
SIZE_LABEL = {c.value: c.label for c in SIZES}
METHODS = (
    Choice("remove", "떼고 새로 붙여요", "오래 가요. 철거비 · 기간이 더 들어요"),
    Choice("overlay", "위에 덧붙여요 (덧방)", "빠르고 먼지가 적어요. 들뜬 타일 위에는 못 해요"),
)
METHOD_LABEL = {c.value: c.label for c in METHODS}


def _build(c: Common, v: Values) -> calc.TileQuote:
    return calc.quote(
        calc.TileInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            parts=tuple(v["parts"]),
            size=v["size"],
            method=v["method"],
            occupied=c.occupied,
        ),
        TILE_2026H2,
    )


def _card_lines(c: Common, v: Values) -> list[str]:
    return [
        "타일 붙일 곳: " + ", ".join(PART_LABEL[p] for p in v["parts"]),
        f"타일 크기: {SIZE_LABEL[v['size']]}",
        f"지금 타일: {METHOD_LABEL[v['method']]}",
    ]


SPEC = TradeSpec(
    key="tile",
    label="타일",
    order=50,
    fields=(
        FieldSpec(
            key="parts",
            label="타일 붙일 곳",
            question="어디에 타일을 붙일까요? 여러 개 골라도 돼요.",
            kind="multi",
            choices=PARTS,
            max=len(PARTS),
            hint="욕실 타일 · 거실 바닥 타일은 이 칸이 아니에요",
        ),
        FieldSpec(
            key="size",
            label="타일 크기",
            question="타일은 어떤 크기로 할까요?",
            kind="choice",
            choices=SIZES,
            unknown="medium",
        ),
        FieldSpec(
            key="method",
            label="지금 타일",
            question="지금 붙어 있는 타일은 어떻게 할까요?",
            kind="choice",
            choices=METHODS,
            unknown="remove",
            hint="덧방 · 위에 붙이기면 overlay",
        ),
    ),
    agent=TradeAgent.load("tile", "타일", "tile_v1.md"),
    build=_build,
    card_lines=_card_lines,
)
