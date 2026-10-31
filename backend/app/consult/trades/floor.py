"""바닥재 공정 스펙: 바닥재 종류와 지금 바닥을 걷어 낼지 묻고 calc.floor로 계산한다.

장판 깔기는 도배가 끝난 뒤에 해서(Step.late) late_order가 있다. 마루 · 데코타일 · 포세린은 도배 앞 본 작업이다.
"""

from app.agent.trade import TradeAgent
from app.calc import floor as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.floor import FLOOR_2026H2

KINDS = (
    Choice("vinyl_18", "장판 · 얇은 것", "값이 가장 싸고 깔기 쉬워요. 무거운 가구 자국이 남아요"),
    Choice("vinyl_22", "장판 · 두꺼운 것", "발이 편하고 충격을 덜어 줘요. 값이 조금 더 들어요"),
    Choice(
        "decotile", "데코타일", "긁힘 · 물에 강하고 상한 곳만 갈기 쉬워요. 딱딱하고 이음매가 보여요"
    ),
    Choice("engineered", "강마루", "단단하고 들뜸 · 소음이 적어요. 나중에 걷어 내기 어려워요"),
    Choice("laminate", "강화마루", "끼워 맞춰 본드 냄새가 적고 교체가 쉬워요. 물에 약해요"),
    Choice("porcelain", "포세린 타일", "물 · 긁힘에 강해요. 무겁고 시공비 · 기간이 가장 커요"),
)
KIND_LABEL = {c.value: c.label for c in KINDS}
REMOVE = (
    Choice("yes", "걷어 내요", "바탕을 새로 잡아요. 철거비는 실측 때 정해요"),
    Choice("no", "그 위에 깔아요", "빠르고 싸요. 위에 깔 수 있는지 실측 때 봐요"),
)
REMOVE_LABEL = {c.value: c.label for c in REMOVE}


def _build(c: Common, v: Values) -> calc.FloorQuote:
    return calc.quote(
        calc.FloorInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            kind=v["kind"],
            occupied=c.occupied,
            remove=v["remove"] == "yes",
            balcony_ext=c.balcony_ext,
        ),
        FLOOR_2026H2,
    )


def _card_lines(c: Common, v: Values) -> list[str]:
    return [f"바닥재: {KIND_LABEL[v['kind']]}", f"지금 바닥: {REMOVE_LABEL[v['remove']]}"]


SPEC = TradeSpec(
    key="floor",
    label="바닥재",
    order=85,
    fields=(
        FieldSpec(
            key="kind",
            label="바닥재 종류",
            question="바닥재는 어떤 걸로 할까요?",
            kind="choice",
            choices=KINDS,
            unknown="engineered",
            hint="'마루'라고만 하면 바꾸지 않아요. 현관 · 베란다 바닥 타일은 타일 공정이에요",
        ),
        FieldSpec(
            key="remove",
            label="지금 바닥",
            question="지금 바닥재는 걷어 낼까요?",
            kind="choice",
            choices=REMOVE,
            unknown="yes",
        ),
    ),
    agent=TradeAgent.load("floor", "바닥재", "floor_v1.md"),
    build=_build,
    card_lines=_card_lines,
    late_order=10,
)
