"""창호 공정 스펙: 바꿀 창(집 전체 · 몇 개만) · 창 종류 · 유리를 묻고 calc.window로 계산한다.
발코니 확장 여부는 공통 칸(Common.balcony_ext)을 쓰고 따로 묻지 않는다."""

from app.agent.trade import TradeAgent
from app.calc import window as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.window import WINDOW_2026H2

AGENT = TradeAgent.load("window", "창호", "window_v1.md")
SCOPES = (Choice("all", "집 전체 창"), Choice("some", "몇 개만"))
FRAMES = (
    Choice("pvc", "PVC 이중창", "아파트에서 가장 흔해요. 창이 두 겹이라 단열 · 소음 막기에 좋아요"),
    Choice("system", "알루미늄 시스템창", "창 하나로도 꼭 닫히고 단열이 좋지만 값이 가장 높아요"),
)
GLASSES = (
    Choice("low_e", "로이 복층유리", "열이 덜 빠지고 결로가 줄어요. 일반 복층유리보다 값이 높아요"),
    Choice("clear", "일반 복층유리", "로이 코팅이 없어 값이 낮아요"),
)


def _build(c: Common, v: Values) -> calc.WindowQuote:
    return calc.quote(
        calc.WindowInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            occupied=c.occupied,
            balcony_ext=c.balcony_ext,
            scope=v["scope"],
            count=v.get("count", 0),
            frame=v["frame"],
            glass=v["glass"],
        ),
        WINDOW_2026H2,
    )


def _label(choices: tuple[Choice, ...], value: object) -> str:
    return next(c.label for c in choices if c.value == value)


def _card_lines(c: Common, v: Values) -> list[str]:
    return [
        f"바꿀 창: {_label(SCOPES, v['scope'])}",
        f"창 종류: {_label(FRAMES, v['frame'])}",
        f"유리: {_label(GLASSES, v['glass'])}",
    ]


SPEC = TradeSpec(
    key="window",
    label="창호",
    order=10,
    fields=(
        FieldSpec(
            key="scope",
            label="바꿀 창",
            question="창은 집 전체를 바꾸나요, 몇 개만 바꾸나요?",
            kind="choice",
            choices=SCOPES,
            unknown="all",
            hint="샷시 전체 교체면 all",
        ),
        FieldSpec(
            key="count",
            label="바꿀 창 개수",
            question="바꿀 창은 몇 개예요? 거실 큰 창도 하나로 세요.",
            kind="count",
            min=1,
            max=10,
            unknown=3,
            when=lambda v: v.get("scope") == "some",
            hint="바꿀 창 개수를 숫자로 말했을 때만",
        ),
        FieldSpec(
            key="frame",
            label="창 종류",
            question="어떤 창으로 바꿀까요?",
            kind="choice",
            choices=FRAMES,
            unknown="pvc",
            hint="하이샷시 · PVC면 pvc, 알루미늄 시스템창이면 system",
        ),
        FieldSpec(
            key="glass",
            label="유리",
            question="유리는 어떤 걸로 할까요?",
            kind="choice",
            choices=GLASSES,
            unknown="low_e",
        ),
    ),
    agent=AGENT,
    build=_build,
    card_lines=_card_lines,
)
