"""욕실 공정 스펙: 고칠 욕실 수와 공사 범위를 묻고, 전체 공사면 기존 타일 · 욕조 · 천장재를 더 묻는다.
calc.bath로 계산한다. 도기 · 수전만 바꾸면 욕조는 그대로 둔다 (욕조를 바꾸거나 없애면 전체 공사로 고른다)."""

from app.agent.trade import TradeAgent
from app.calc import bath as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.bath import BATH_2026H2

AGENT = TradeAgent.load("bath", "욕실", "bath_v1.md")
SCOPES = (
    Choice("full", "전체 공사", "방수 · 타일 · 천장재 · 도기 · 수전 · 욕조까지 새로 해요"),
    Choice("fixtures", "도기 · 수전만", "타일은 그대로 두고 변기 · 세면대 · 수전만 바꿔요"),
)
METHODS = (
    Choice("remove", "다 뜯고 새로", "새 방수층을 믿을 수 있어요. 값과 기간이 더 들어요"),
    Choice("overlay", "덧방 (위에 덧붙이기)", "빠르고 싸요. 기존 방수층을 그대로 믿고 가요"),
)
TUBS = (
    Choice("keep", "그대로 둬요"),
    Choice("remove", "없애고 샤워 공간으로", "욕조 자리 바닥 타일 · 방수를 새로 해요"),
    Choice("new", "새 욕조로 바꿔요"),
)
CEILINGS = (
    Choice("smc", "SMC 천장", "습기에 강한 강화플라스틱 판이에요"),
    Choice("pvc", "PVC 천장", "긴 판을 끼워 맞춘 평평한 천장이에요"),
)
_KO = {1: "한", 2: "두", 3: "세"}  # 공정 의견 글에 숫자를 줄인다


def _full(v: Values) -> bool:
    return v.get("scope") == "full"


def _build(c: Common, v: Values) -> calc.BathQuote:
    return calc.quote(
        calc.BathInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            occupied=c.occupied,
            baths=v["baths"],
            scope=v["scope"],
            tile_method=v.get("tile_method", "remove"),
            tub=v.get("tub", "keep"),
            ceiling=v.get("ceiling", "smc"),
        ),
        BATH_2026H2,
    )


def _label(choices: tuple[Choice, ...], value: object) -> str:
    return next(c.label for c in choices if c.value == value)


def _card_lines(c: Common, v: Values) -> list[str]:
    rows = [
        f"고칠 욕실: {_KO[v['baths']]} 칸",
        f"공사 범위: {_label(SCOPES, v['scope'])}",
    ]
    if _full(v):
        rows += [
            f"기존 타일: {_label(METHODS, v['tile_method'])}",
            f"욕조: {_label(TUBS, v['tub'])}",
            f"천장재: {_label(CEILINGS, v['ceiling'])}",
        ]
    return rows


SPEC = TradeSpec(
    key="bath",
    label="욕실",
    order=40,
    fields=(
        FieldSpec(
            key="baths",
            label="고칠 욕실 수",
            question="고칠 욕실은 몇 칸이에요?",
            kind="count",
            min=1,
            max=calc.MAX_BATHS,
            unknown=1,
            unit="칸",
            hint="고칠 욕실 칸 수를 숫자로 말했을 때만",
        ),
        FieldSpec(
            key="scope",
            label="욕실 공사 범위",
            question="욕실은 어디까지 고칠까요?",
            kind="choice",
            choices=SCOPES,
            unknown="full",
            hint="타일 · 방수까지 새로 하면 full, 변기 · 세면대 · 수전만 바꾸면 fixtures",
        ),
        FieldSpec(
            key="tile_method",
            label="기존 타일",
            question="기존 타일은 어떻게 할까요?",
            kind="choice",
            choices=METHODS,
            unknown="remove",
            when=_full,
            hint="기존 타일 위에 새 타일을 붙이면 overlay",
        ),
        FieldSpec(
            key="tub",
            label="욕조",
            question="욕조는 어떻게 할까요?",
            kind="choice",
            choices=TUBS,
            unknown="keep",
            when=_full,
        ),
        FieldSpec(
            key="ceiling",
            label="욕실 천장재",
            question="욕실 천장은 어떤 판으로 할까요?",
            kind="choice",
            choices=CEILINGS,
            unknown="smc",
            when=_full,
        ),
    ),
    agent=AGENT,
    build=_build,
    card_lines=_card_lines,
)
