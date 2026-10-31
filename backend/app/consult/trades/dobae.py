"""도배 공정 스펙: 도배 유형(저가형 · 기본형)과 천장 도배 여부를 묻고 calc.dobae로 계산한다."""

from typing import TYPE_CHECKING

from app.agent.wallpaper import AGENT
from app.calc import dobae as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Value, Values
from app.refprice.book import DOBAE_2026H2

if TYPE_CHECKING:
    from app.project.schemas import ProjectOut


def _build(c: Common, v: Values) -> calc.DobaeQuote:
    return calc.quote(
        calc.DobaeInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            grade=v["grade"],
            include_ceiling=v["include_ceiling"] == "yes",
            occupied=c.occupied,
            balcony_ext=c.balcony_ext,
        ),
        DOBAE_2026H2,
    )


def _card_lines(c: Common, v: Values) -> list[str]:
    return [
        f"도배 등급: {'기본형(실크)' if v['grade'] == 'basic' else '저가형(합지)'}",
        f"천장: {'포함' if v['include_ceiling'] == 'yes' else '안 함'}",
    ]


def _prefill(p: "ProjectOut") -> dict[str, Value]:
    t = p.trades.dobae
    return {"grade": t.grade} if t and t.grade else {}


SPEC = TradeSpec(
    key="dobae",
    label="도배",
    order=90,
    fields=(
        FieldSpec(
            key="grade",
            label="도배 유형",
            question="벽지는 어떤 걸로 할까요? 합지는 값이 싸고, 실크는 닦을 수 있고 오래 가요.",
            kind="choice",
            choices=(
                Choice("economy", "저가형 · 합지", "값이 싸요. 오염 · 습기에 약해요"),
                Choice("basic", "기본형 · 실크", "닦을 수 있고 오래 가요"),
            ),
            unknown="basic",
            hint="합지 · 싼 것이면 economy, 실크 · 기본이면 basic",
        ),
        FieldSpec(
            key="include_ceiling",
            label="천장 도배",
            question="천장도 도배할까요?",
            kind="choice",
            choices=(Choice("yes", "천장도 해요"), Choice("no", "벽만 해요")),
            unknown="yes",
            hint="'천장도 해야 하나요?'처럼 묻기만 하면 바꾸지 않아요. 천장 평탄화(목공)는 이 칸이 아니에요",
        ),
    ),
    agent=AGENT,
    build=_build,
    card_lines=_card_lines,
    prefill=_prefill,
)
