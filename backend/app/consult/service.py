"""도배 상담 한 턴. 무엇을 물을지, 언제 계산하고 공정 에이전트를 부를지는 이 코드가 정한다.

LLM은 대화에서 칸 값을 뽑고 짧게 답하는 일(agent.consult)과 공정 의견(agent.wallpaper)만 한다.
숫자는 계산 엔진(calc.dobae)만 만든다. DB에는 쓰지 않는다.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import consult as consult_agent
from app.agent import wallpaper
from app.agent.llm import LlmError
from app.agent.schemas import CardUpdate
from app.auth.models import User
from app.calc import dobae as calc
from app.consult.schemas import (
    Answer,
    CardField,
    CautionOut,
    Choice,
    ConsultIn,
    ConsultOut,
    DobaeCard,
    PlanOut,
    Question,
    QuoteOut,
)
from app.project import service as project_service
from app.refprice.book import DOBAE_2026H2
from app.shared.errors import AppError

REQUIRED: tuple[CardField, ...] = ("area", "area_basis", "grade", "include_ceiling", "occupied")
_UNKNOWN = Choice(value="unknown", label="모르겠어요")
QUESTIONS: dict[CardField, Question] = {
    "area": Question(
        field="area",
        text="집이 몇 평이에요? 분양 평형이나 관리비 고지서에 적힌 숫자를 적어 주세요.",
        choices=[Choice(value=v, label=f"{v}평") for v in ("18", "24", "25", "32", "33", "34")],
    ),
    "area_basis": Question(
        field="area_basis",
        text="그 평수는 분양 평형(공급면적)인가요, 실제로 쓰는 면적(전용면적)인가요?",
        choices=[
            Choice(value="supply", label="분양 평형 (공급)"),
            Choice(value="exclusive", label="전용면적"),
            _UNKNOWN,
        ],
    ),
    "grade": Question(
        field="grade",
        text="벽지는 어떤 걸로 할까요? 합지는 값이 싸고, 실크는 닦을 수 있고 오래 가요.",
        choices=[
            Choice(value="economy", label="저가형 · 합지"),
            Choice(value="basic", label="기본형 · 실크"),
            _UNKNOWN,
        ],
    ),
    "include_ceiling": Question(
        field="include_ceiling",
        text="천장도 도배할까요?",
        choices=[
            Choice(value="yes", label="천장도 해요"),
            Choice(value="no", label="벽만 해요"),
            _UNKNOWN,
        ],
    ),
    "occupied": Question(
        field="occupied",
        text="공사하는 동안 그 집에 살고 계세요?",
        choices=[
            Choice(value="yes", label="살면서 공사해요"),
            Choice(value="no", label="빈집이에요"),
        ],
    ),
}
# '모르겠어요'면 넣는 기본값. 그 칸은 to_check에 남겨 실측 때 확인한다
DEFAULTS: dict[str, object] = {"area_basis": "supply", "grade": "basic", "include_ceiling": True}

FALLBACK_REPLY = "말씀을 잘 알아듣지 못했어요. 아래에서 골라 주시거나 다시 적어 주세요."
OUT_OF_SCOPE = "지금은 도배 상담만 할 수 있어요."
PLAN_FAILED = "설명을 만들지 못했어요. 계산 결과만 보여 드려요."
_AREA = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*(평형|평|㎡|m2|제곱미터)?\s*$")


def missing(c: DobaeCard) -> list[CardField]:
    have = {
        "area": c.area_m2,
        "area_basis": c.area_basis,
        "grade": c.grade,
        "include_ceiling": c.include_ceiling,
        "occupied": c.occupied,
    }
    return [f for f in REQUIRED if have[f] is None]


def _set(c: DobaeCard, field: CardField, value: object | None, unknown: bool = False) -> DobaeCard:
    attr = "area_m2" if field == "area" else field
    to_check = [f for f in c.to_check if f != field]
    if unknown:
        value = DEFAULTS[field]
        to_check.append(field)
    return c.model_copy(update={attr: value, "to_check": to_check})


def _area(num: str, unit: str | None) -> Decimal | None:
    try:
        n = Decimal(num)
    except InvalidOperation:
        return None
    if unit in ("㎡", "m2", "제곱미터"):
        return calc.m2(n) if 10 <= n <= 1000 else None
    return calc.pyeong_to_m2(n) if 3 <= n <= 300 else None


def apply_answer(c: DobaeCard, a: Answer) -> DobaeCard:
    v = a.value
    if a.field == "area":
        m = _AREA.match(v)
        area = _area(m.group(1), m.group(2)) if m else None
        if area is None:
            raise AppError(422, "bad_answer", "평수를 다시 적어 주세요.")
        return _set(c, "area", area)
    allowed = {q.value for q in QUESTIONS[a.field].choices}
    if v not in allowed:
        raise AppError(422, "bad_answer", "선택지에서 다시 골라 주세요.")
    if v == "unknown":
        return _set(c, a.field, None, unknown=True)
    if a.field in ("include_ceiling", "occupied"):
        return _set(c, a.field, v == "yes")
    return _set(c, a.field, v)


def apply_update(c: DobaeCard, u: CardUpdate) -> DobaeCard:
    """LLM이 뽑은 값 중 범위에 맞는 것만 카드에 넣는다."""
    if u.area_m2 is not None:
        area = _area(str(u.area_m2), "㎡")
        if area is not None:
            c = _set(c, "area", area)
    elif u.pyeong is not None:
        area = _area(str(u.pyeong), "평")
        if area is not None:
            c = _set(c, "area", area)
    for field in ("area_basis", "grade"):
        v = getattr(u, field)
        if v is not None:
            c = _set(c, field, None, unknown=True) if v == "unknown" else _set(c, field, v)
    if u.include_ceiling is not None:
        c = (
            _set(c, "include_ceiling", None, unknown=True)
            if u.include_ceiling == "unknown"
            else _set(c, "include_ceiling", u.include_ceiling == "yes")
        )
    if u.occupied is not None:
        c = _set(c, "occupied", u.occupied)
    if u.balcony_ext is not None:
        c = c.model_copy(update={"balcony_ext": u.balcony_ext})
    if u.built_year is not None and 1900 <= u.built_year <= 2100:
        c = c.model_copy(update={"built_year": u.built_year})
    return c


async def _prefill(s: AsyncSession, user: User, project_id: uuid.UUID) -> DobaeCard:
    p = await project_service.get_for(s, user, project_id)
    upd: dict = {"occupied": p.occupied, "balcony_ext": p.balcony_ext, "built_year": p.built_year}
    if p.size.m2 is not None:
        upd |= {"area_m2": p.size.m2, "area_basis": p.size.basis}
    if p.trades.dobae and p.trades.dobae.grade:
        upd["grade"] = p.trades.dobae.grade
    return DobaeCard(**upd)


def card_text(c: DobaeCard) -> str:
    basis = calc.BASIS_LABEL[c.area_basis]
    rows = [
        f"면적: {basis} {c.area_m2}㎡",
        f"도배 등급: {'기본형(실크)' if c.grade == 'basic' else '저가형(합지)'}",
        f"천장: {'포함' if c.include_ceiling else '안 함'}",
        f"사는 집에서 공사: {'예' if c.occupied else '아니요(빈집)'}",
        f"발코니 확장: {'예' if c.balcony_ext else '아니요'}",
    ]
    if c.built_year:
        rows.append(f"준공 연도: {c.built_year}")
    if c.to_check:
        names = {"area_basis": "면적 기준", "grade": "등급", "include_ceiling": "천장 포함"}
        rows.append(
            "고객이 몰라 기본값으로 둔 칸: " + ", ".join(names.get(f, f) for f in c.to_check)
        )
    return "\n".join(rows)


def quote_for(c: DobaeCard) -> calc.DobaeQuote:
    inp = calc.DobaeInput(
        area_m2=c.area_m2,
        area_basis=c.area_basis,
        grade=c.grade,
        include_ceiling=c.include_ceiling,
        occupied=c.occupied,
        balcony_ext=c.balcony_ext,
    )
    return calc.quote(inp, DOBAE_2026H2)


async def turn(s: AsyncSession, user: User, data: ConsultIn) -> ConsultOut:
    card = data.card
    if data.project_id and card == DobaeCard():
        card = await _prefill(s, user, data.project_id)
    # LLM을 기다리는 동안 DB 연결을 붙잡지 않는다
    await s.close()

    reply = None
    if data.answer:
        card = apply_answer(card, data.answer)
    text = (data.message or "").strip()
    if text:
        first = missing(card)[:1]
        m = _AREA.match(text) if first == ["area"] else None
        if m and _area(m.group(1), m.group(2)) is not None:
            card = _set(
                card, "area", _area(m.group(1), m.group(2))
            )  # 숫자만 적으면 LLM 없이 받는다
        else:
            turns = [(t.role, t.text) for t in data.history[-20:]] + [("user", text)]
            try:
                u, _ = await consult_agent.extract(turns, card.model_dump(mode="json"))
                card = apply_update(card, u)
                reply = u.reply.strip() if consult_agent.reply_ok(u.reply) else None
                if u.out_of_scope and reply is None:
                    reply = OUT_OF_SCOPE
            except LlmError:
                reply = FALLBACK_REPLY

    todo = missing(card)
    if todo:
        return ConsultOut(
            card=card,
            reply=reply,
            question=QUESTIONS[todo[0]],
            quote=None,
            plan=None,
            plan_status=None,
            notice=None,
        )

    q = quote_for(card)
    quote = QuoteOut.model_validate(q, from_attributes=True)
    # 처음 다 찼거나 카드가 바뀌었을 때만 공정 에이전트를 부른다 (같은 카드면 화면의 것을 그대로 쓴다)
    if not missing(data.card) and data.card == card:
        return ConsultOut(
            card=card,
            reply=reply,
            question=None,
            quote=quote,
            plan=None,
            plan_status="same",
            notice=None,
        )
    try:
        r = await wallpaper.plan(card_text(card), q)
    except LlmError:
        return ConsultOut(
            card=card,
            reply=reply,
            question=None,
            quote=quote,
            plan=None,
            plan_status="failed",
            notice=PLAN_FAILED,
        )
    plan = PlanOut(
        summary=r.plan.summary,
        steps=r.plan.steps,
        visit_checks=r.plan.visit_checks,
        cautions=[
            CautionOut(text=c.text, source=wallpaper.SOURCES[c.source]) for c in r.plan.cautions
        ],
        prompt_version=wallpaper.PROMPT_VERSION,
    )
    return ConsultOut(
        card=card,
        reply=reply,
        question=None,
        quote=quote,
        plan=plan,
        plan_status="new",
        notice=None,
    )
