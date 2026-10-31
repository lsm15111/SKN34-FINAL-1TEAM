"""주방 공정 스펙: 싱크대 배치 · 길이 · 상판과 함께 바꿀 후드 · 싱크볼을 묻고 calc.kitchen으로 계산한다.
길이를 모르면(집 크기만큼) calc가 평형과 배치로 짐작한다. 주방 벽 타일은 타일 공정에서 본다."""

from decimal import Decimal

from app.agent.trade import TradeAgent
from app.calc import kitchen as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.kitchen import KITCHEN_2026H2

AGENT = TradeAgent.load("kitchen", "주방", "kitchen_v1.md")
FIT = "fit"  # 길이를 모를 때: 집 크기만큼 (calc가 짐작)
LAYOUTS = (
    Choice("straight", "일자", "한 벽에 길게 놓아요"),
    Choice("l_shape", "ㄱ자", "꺾어서 두 벽에 놓아요. 가구와 상판이 길어져요"),
    Choice("parallel", "평행형", "마주 보는 두 줄로 놓아요. 가구와 상판이 길어져요"),
)
LENGTHS = (
    Choice(FIT, "집 크기만큼 (보통)", "평형과 배치로 길이를 잡고 실측 때 재요"),
    *(Choice(x, f"{x}m") for x in ("2.4", "3.0", "3.6", "4.2", "4.8", "5.4")),
)
TOPS = (
    Choice("acrylic", "인조대리석", "가장 많이 써요. 이음매가 덜 보이지만 뜨거운 냄비에 약해요"),
    Choice("quartz", "엔지니어드스톤", "단단하고 긁힘에 강하지만 값이 높아요"),
)
PARTS = (
    Choice("both", "둘 다 바꿔요", "레인지후드와 싱크볼 · 수전"),
    Choice("hood", "레인지후드만"),
    Choice("sink", "싱크볼 · 수전만"),
    Choice("none", "둘 다 그대로 써요"),
)


def _build(c: Common, v: Values) -> calc.KitchenQuote:
    length = v["length"]
    return calc.quote(
        calc.KitchenInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            occupied=c.occupied,
            layout=v["layout"],
            top=v["top"],
            length_m=None if length == FIT else Decimal(str(length)),
            hood=v["parts"] in ("both", "hood"),
            faucet=v["parts"] in ("both", "sink"),
        ),
        KITCHEN_2026H2,
    )


def _label(choices: tuple[Choice, ...], value: object) -> str:
    return next(c.label for c in choices if c.value == value)


def _card_lines(c: Common, v: Values) -> list[str]:
    length = "집 크기로 짐작 (실측 때 재요)" if v["length"] == FIT else "고객이 정했어요"
    return [
        f"싱크대 배치: {_label(LAYOUTS, v['layout'])}",
        f"싱크대 길이: {length}",
        f"상판: {_label(TOPS, v['top'])}",
        f"함께 바꿀 것: {_label(PARTS, v['parts'])}",
    ]


SPEC = TradeSpec(
    key="kitchen",
    label="주방",
    order=60,
    late_order=20,
    fields=(
        FieldSpec(
            key="layout",
            label="싱크대 배치",
            question="싱크대는 어떤 모양으로 놓여 있어요?",
            kind="choice",
            choices=LAYOUTS,
            unknown="straight",
            hint="마주 보는 두 줄(11자)이면 parallel",
        ),
        FieldSpec(
            key="length",
            label="싱크대 길이",
            question="싱크대(하부장) 길이를 아세요? ㄱ자 · 평행형은 두 줄을 더한 길이예요.",
            kind="choice",
            choices=LENGTHS,
            unknown=FIT,
            hint="m로 말하면 가장 가까운 값, 모르면 fit",
        ),
        FieldSpec(
            key="top",
            label="상판",
            question="상판은 무엇으로 할까요?",
            kind="choice",
            choices=TOPS,
            unknown="acrylic",
            hint="인조대리석이면 acrylic, 엔지니어드스톤 · 쿼츠면 quartz",
        ),
        FieldSpec(
            key="parts",
            label="함께 바꿀 것",
            question="레인지후드와 싱크볼 · 수전도 같이 바꿀까요?",
            kind="choice",
            choices=PARTS,
            unknown="both",
        ),
    ),
    agent=AGENT,
    build=_build,
    card_lines=_card_lines,
)
