"""도장 공정 스펙: 칠할 곳(벽 · 천장 · 방문 · 베란다)과 페인트 종류 · 퍼티 범위 · 방문 개수를 묻고
calc.paint로 계산한다. 페인트는 벽 · 천장 · 방문을, 퍼티는 벽 · 천장을, 방문 개수는 방문을 고를 때만 묻는다.
방문 개수는 목공 · 필름과 같이 쓰는 칸(share="doors")이다."""

from app.agent.trade import TradeAgent
from app.calc import paint as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.paint import PAINT_2026H2

SURFACES = (
    Choice("wall", "벽", "방 · 거실 벽을 벽지 대신 페인트로"),
    Choice("ceiling", "천장", "방 · 거실 천장"),
    Choice("door", "방문 · 문틀", "문짝 양면과 문틀"),
    Choice("balcony", "베란다 (탄성코트)", "곰팡이 · 잔금이 생기는 베란다 벽 · 천장"),
)
SURFACE_LABEL = {c.value: c.label for c in SURFACES}
PAINTS = (
    Choice("standard", "일반 수성", "값이 싸고 냄새가 적어요"),
    Choice("eco", "친환경 수성", "유해물질이 적다는 인증 제품이에요. 값이 더 들어요"),
)
PAINT_LABEL = {c.value: c.label for c in PAINTS}
PUTTIES = (
    Choice("spot", "구멍 · 틈만", "싸고 빨라요. 벽이 고르고 이미 칠이 돼 있을 때 맞아요"),
    Choice("joint", "이음매만 (줄퍼티)", "올퍼티보다 싸요. 벽이 고르지 않으면 티가 나요"),
    Choice("full", "벽 전체 (올퍼티)", "가장 매끈해요. 벽지를 떼고 칠하면 대개 필요해요"),
)
PUTTY_LABEL = {c.value: c.label for c in PUTTIES}


def _painted(v: Values) -> bool:
    return any(s in v.get("surfaces", ()) for s in ("wall", "ceiling", "door"))


def _flat(v: Values) -> bool:
    return any(s in v.get("surfaces", ()) for s in ("wall", "ceiling"))


def _door(v: Values) -> bool:
    return "door" in v.get("surfaces", ())


def _build(c: Common, v: Values) -> calc.PaintQuote:
    # 묻지 않은 칸(베란다만 칠할 때 페인트 · 퍼티 등)은 계산 엔진 기본값을 쓴다
    asked = {k: v[k] for k in ("paint", "putty", "doors") if k in v}
    return calc.quote(
        calc.PaintInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            surfaces=tuple(v["surfaces"]),
            occupied=c.occupied,
            balcony_ext=c.balcony_ext,
            **asked,
        ),
        PAINT_2026H2,
    )


def _card_lines(c: Common, v: Values) -> list[str]:
    rows = ["칠할 곳: " + ", ".join(SURFACE_LABEL[s] for s in v["surfaces"])]
    if "paint" in v:
        rows.append(f"페인트: {PAINT_LABEL[v['paint']]}")
    if "putty" in v:
        rows.append(f"퍼티 범위: {PUTTY_LABEL[v['putty']]}")
    if "doors" in v:
        rows.append(f"칠할 방문: {v['doors']}개")
    return rows


SPEC = TradeSpec(
    key="paint",
    label="도장",
    order=70,
    fields=(
        FieldSpec(
            key="surfaces",
            label="칠할 곳",
            question="어디를 칠할까요? 여러 개 골라도 돼요.",
            kind="multi",
            choices=SURFACES,
            max=len(SURFACES),
            hint="벽지를 바르는 도배는 이 칸이 아니에요. 외벽 · 방수도 아니에요",
        ),
        FieldSpec(
            key="paint",
            label="페인트 종류",
            question="페인트는 어떤 걸로 할까요?",
            kind="choice",
            choices=PAINTS,
            unknown="standard",
            when=_painted,
        ),
        FieldSpec(
            key="putty",
            label="퍼티 범위",
            question="칠하기 전에 벽 · 천장 바탕은 어디까지 고를까요?",
            kind="choice",
            choices=PUTTIES,
            unknown="full",
            when=_flat,
            hint="올퍼티면 full, 줄퍼티면 joint, 구멍 · 틈만 메우면 spot",
        ),
        FieldSpec(
            key="doors",
            label="칠할 방문 개수",
            question="칠할 방문은 몇 개예요?",
            kind="count",
            min=1,
            max=10,
            unknown=3,
            when=_door,
            hint="칠할 방문 개수를 숫자로 말했을 때만",
            share="doors",
        ),
    ),
    agent=TradeAgent.load("paint", "도장", "paint_v1.md"),
    build=_build,
    card_lines=_card_lines,
)
