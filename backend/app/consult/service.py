"""도배 · 목공 상담 한 턴. 무엇을 물을지, 언제 계산하고 공정 에이전트를 부를지는 이 코드가 정한다.

필수 칸은 프로젝트 정보로 채우고, 빈 칸은 첫 화면 폼(questions)으로 한 번에 받는다.
LLM은 대화에서 바꿀 칸 값을 뽑고 짧게 답하는 일(agent.consult)과 공정 의견(agent.wallpaper ·
agent.carpentry)만 한다. 숫자는 계산 엔진(calc)만 만든다. DB에는 쓰지 않는다.
"""

import asyncio
import re
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import carpentry, wallpaper
from app.agent import consult as consult_agent
from app.agent.llm import LlmError
from app.agent.schemas import CardUpdate
from app.auth.models import User
from app.calc import dobae as calc
from app.calc import mokgong as mok_calc
from app.calc.sequence import sequence
from app.consult.schemas import (
    Answer,
    CardField,
    CautionOut,
    Choice,
    ConsultCard,
    ConsultIn,
    ConsultOut,
    PlanOut,
    Question,
    QuoteOut,
    ScheduleStepOut,
    Trade,
    TradeOut,
)
from app.project import service as project_service
from app.refprice.book import DOBAE_2026H2, MOKGONG_2026H2
from app.shared.errors import AppError

_UNKNOWN = Choice(value="unknown", label="모르겠어요")
QUESTIONS: dict[CardField, Question] = {
    "area": Question(
        field="area",
        trade=None,
        text="집이 몇 평이에요? 분양 평형이나 관리비 고지서에 적힌 숫자를 적어 주세요.",
        choices=[Choice(value=v, label=f"{v}평") for v in ("18", "24", "25", "32", "33", "34")],
    ),
    "area_basis": Question(
        field="area_basis",
        trade=None,
        text="그 평수는 분양 평형(공급면적)인가요, 실제로 쓰는 면적(전용면적)인가요?",
        choices=[
            Choice(value="supply", label="분양 평형 (공급)"),
            Choice(value="exclusive", label="전용면적"),
            _UNKNOWN,
        ],
    ),
    "occupied": Question(
        field="occupied",
        trade=None,
        text="공사하는 동안 그 집에 살고 계세요?",
        choices=[
            Choice(value="yes", label="살면서 공사해요"),
            Choice(value="no", label="빈집이에요"),
        ],
    ),
    "grade": Question(
        field="grade",
        trade="dobae",
        text="벽지는 어떤 걸로 할까요? 합지는 값이 싸고, 실크는 닦을 수 있고 오래 가요.",
        choices=[
            Choice(value="economy", label="저가형 · 합지"),
            Choice(value="basic", label="기본형 · 실크"),
            _UNKNOWN,
        ],
    ),
    "include_ceiling": Question(
        field="include_ceiling",
        trade="dobae",
        text="천장도 도배할까요?",
        choices=[
            Choice(value="yes", label="천장도 해요"),
            Choice(value="no", label="벽만 해요"),
            _UNKNOWN,
        ],
    ),
    "doors": Question(
        field="doors",
        trade="mokgong",
        text="바꿀 방문은 몇 개예요?",
        choices=[Choice(value=str(n), label=f"{n}개") for n in range(1, 7)] + [_UNKNOWN],
    ),
    "door_frame": Question(
        field="door_frame",
        trade="mokgong",
        text="문틀까지 바꾸나요, 문짝만 바꾸나요?",
        choices=[
            Choice(value="yes", label="문틀까지 바꿔요"),
            Choice(value="no", label="문짝만 바꿔요"),
            _UNKNOWN,
        ],
    ),
}
# '모르겠어요'면 넣는 기본값. 그 칸은 to_check에 남겨 실측 때 확인한다
DEFAULTS: dict[str, object] = {
    "area_basis": "supply",
    "grade": "basic",
    "include_ceiling": True,
    "doors": 3,
    "door_frame": True,
}
_ATTR = {"area": "area_m2"}
_YES_NO = ("occupied", "include_ceiling", "door_frame")
CHECK_NAMES = {
    "area_basis": "면적 기준",
    "grade": "등급",
    "include_ceiling": "천장 포함",
    "doors": "방문 개수",
    "door_frame": "문틀 교체",
}
MOK_LABEL = {"molding": "천장 몰딩", "base": "걸레받이", "door": "방문", "flatten": "천장 평탄화"}

FALLBACK_REPLY = "말씀을 잘 알아듣지 못했어요. 다시 적어 주세요."
CHANGED_REPLY = "알겠어요. 바꾼 값으로 다시 계산했어요."
OUT_OF_SCOPE = "지금은 도배와 목공(몰딩 · 걸레받이 · 방문 · 천장 평탄화) 상담만 할 수 있어요."
PLAN_FAILED = "설명을 만들지 못했어요. 계산 결과만 보여 드려요."
_AREA = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*(평형|평|㎡|m2|제곱미터)?\s*$")


def missing(c: ConsultCard) -> list[CardField]:
    need: list[CardField] = ["area", "area_basis", "occupied"]
    if "dobae" in c.trades:
        need += ["grade", "include_ceiling"]
    if "mokgong" in c.trades and "door" in c.mok_items:
        need += ["doors", "door_frame"]
    return [f for f in need if getattr(c, _ATTR.get(f, f)) is None]


def _set(
    c: ConsultCard, field: CardField, value: object | None, unknown: bool = False
) -> ConsultCard:
    to_check = [f for f in c.to_check if f != field]
    if unknown:
        value = DEFAULTS[field]
        to_check.append(field)
    return c.model_copy(update={_ATTR.get(field, field): value, "to_check": to_check})


def _area(num: str, unit: str | None) -> Decimal | None:
    try:
        n = Decimal(num)
    except InvalidOperation:
        return None
    if unit in ("㎡", "m2", "제곱미터"):
        return calc.m2(n) if 10 <= n <= 1000 else None
    return calc.pyeong_to_m2(n) if 3 <= n <= 300 else None


def apply_answer(c: ConsultCard, a: Answer) -> ConsultCard:
    v = a.value
    if a.field == "area":
        m = _AREA.match(v)
        area = _area(m.group(1), m.group(2)) if m else None
        if area is None:
            raise AppError(422, "bad_answer", "평수를 다시 적어 주세요.")
        return _set(c, "area", area)
    if v not in {q.value for q in QUESTIONS[a.field].choices}:
        raise AppError(422, "bad_answer", "선택지에서 다시 골라 주세요.")
    if v == "unknown":
        return _set(c, a.field, None, unknown=True)
    if a.field in _YES_NO:
        return _set(c, a.field, v == "yes")
    if a.field == "doors":
        return _set(c, "doors", int(v))
    return _set(c, a.field, v)


def _tri(c: ConsultCard, field: CardField, v: str | None) -> ConsultCard:
    """yes · no · unknown 세 값 칸"""
    if v is None:
        return c
    return _set(c, field, None, unknown=True) if v == "unknown" else _set(c, field, v == "yes")


def apply_update(c: ConsultCard, u: CardUpdate) -> ConsultCard:
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
    c = _tri(c, "include_ceiling", u.include_ceiling)
    c = _tri(c, "door_frame", u.door_frame)
    if u.occupied is not None:
        c = _set(c, "occupied", u.occupied)
    if u.doors is not None and 1 <= u.doors <= 10:
        c = _set(c, "doors", u.doors)
    if u.balcony_ext is not None:
        c = c.model_copy(update={"balcony_ext": u.balcony_ext})
    if u.built_year is not None and 1900 <= u.built_year <= 2100:
        c = c.model_copy(update={"built_year": u.built_year})
    return c


async def _prefill(s: AsyncSession, user: User, project_id: uuid.UUID) -> ConsultCard:
    p = await project_service.get_for(s, user, project_id)
    trades: list[Trade] = [t for t in ("dobae", "mokgong") if getattr(p.trades, t)]
    upd: dict = {
        "trades": trades,
        "occupied": p.occupied,
        "balcony_ext": p.balcony_ext,
        "built_year": p.built_year,
    }
    if p.size.m2 is not None:
        upd |= {"area_m2": p.size.m2, "area_basis": p.size.basis}
    if p.trades.dobae and p.trades.dobae.grade:
        upd["grade"] = p.trades.dobae.grade
    if p.trades.mokgong:
        names = {sp.id: sp.name for sp in p.spaces}
        upd["mok_items"] = list(p.trades.mokgong.items)
        upd["mok_spaces"] = [names[i] for i in p.trades.mokgong.spaces if i in names]
    return ConsultCard(**upd)


def _common_text(c: ConsultCard) -> list[str]:
    rows = [
        f"면적: {calc.BASIS_LABEL[c.area_basis]} {c.area_m2}㎡",
        f"사는 집에서 공사: {'예' if c.occupied else '아니요(빈집)'}",
        f"발코니 확장: {'예' if c.balcony_ext else '아니요'}",
    ]
    if c.built_year:
        rows.append(f"준공 연도: {c.built_year}")
    return rows


def _check_text(c: ConsultCard, fields: tuple[str, ...]) -> list[str]:
    names = [CHECK_NAMES[f] for f in c.to_check if f in fields]
    return ["고객이 몰라 기본값으로 둔 칸: " + ", ".join(names)] if names else []


def card_text(c: ConsultCard) -> str:
    """도배 공정 에이전트에 넘기는 집 정보"""
    rows = _common_text(c) + [
        f"도배 등급: {'기본형(실크)' if c.grade == 'basic' else '저가형(합지)'}",
        f"천장: {'포함' if c.include_ceiling else '안 함'}",
    ]
    if "mokgong" in c.trades:
        rows.append("목공을 같이 해요 (목공이 끝난 뒤 도배)")
    return "\n".join(rows + _check_text(c, ("area_basis", "grade", "include_ceiling")))


def mokgong_text(c: ConsultCard) -> str:
    """목공 공정 에이전트에 넘기는 집 정보"""
    rows = _common_text(c) + ["목공 항목: " + ", ".join(MOK_LABEL[i] for i in c.mok_items)]
    if c.mok_spaces:
        rows.append("목공 공간: " + ", ".join(c.mok_spaces))
    if "door" in c.mok_items:
        rows.append(f"방문: {'문틀까지' if c.door_frame else '문짝만'} 바꿔요")
    if "dobae" in c.trades:
        rows.append("도배를 같이 해요 (목공이 먼저)")
    return "\n".join(rows + _check_text(c, ("area_basis", "doors", "door_frame")))


def inputs(c: ConsultCard) -> dict[Trade, calc.DobaeInput | mok_calc.MokgongInput]:
    """다 찬 카드에서 공정별 계산 엔진 입력을 만든다 (목공 → 도배 순)."""
    out: dict[Trade, calc.DobaeInput | mok_calc.MokgongInput] = {}
    if "mokgong" in c.trades:
        out["mokgong"] = mok_calc.MokgongInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            items=tuple(c.mok_items),
            occupied=c.occupied,
            doors=c.doors or 0,
            door_frame=c.door_frame is not False,
        )
    if "dobae" in c.trades:
        out["dobae"] = calc.DobaeInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            grade=c.grade,
            include_ceiling=c.include_ceiling,
            occupied=c.occupied,
            balcony_ext=c.balcony_ext,
        )
    return out


def _quote(trade: Trade, inp) -> calc.DobaeQuote | mok_calc.MokgongQuote:
    if trade == "dobae":
        return calc.quote(inp, DOBAE_2026H2)
    return mok_calc.quote(inp, MOKGONG_2026H2)


async def _plan(trade: Trade, c: ConsultCard, q) -> tuple[PlanOut | None, str]:
    agent, text = (wallpaper, card_text(c)) if trade == "dobae" else (carpentry, mokgong_text(c))
    try:
        r = await agent.plan(text, q)
    except LlmError:
        return None, "failed"
    plan = PlanOut(
        summary=r.plan.summary,
        steps=r.plan.steps,
        visit_checks=r.plan.visit_checks,
        cautions=[CautionOut(text=x.text, source=agent.SOURCES[x.source]) for x in r.plan.cautions],
        prompt_version=agent.PROMPT_VERSION,
    )
    return plan, "new"


async def turn(s: AsyncSession, user: User, data: ConsultIn) -> ConsultOut:
    card = data.card or ConsultCard()
    if data.card is None and data.project_id:
        card = await _prefill(s, user, data.project_id)
    # LLM을 기다리는 동안 DB 연결을 붙잡지 않는다
    await s.close()

    for a in data.answers:
        card = apply_answer(card, a)
    reply = None
    text = (data.message or "").strip()
    if text:
        turns = [(t.role, t.text) for t in data.history[-20:]] + [("user", text)]
        try:
            u, _ = await consult_agent.extract(turns, card.model_dump(mode="json"))
            changed = apply_update(card, u)
            reply = u.reply.strip() if consult_agent.reply_ok(u.reply) else None
            if reply is None and u.out_of_scope:
                reply = OUT_OF_SCOPE
            elif reply is None and changed != card:
                reply = CHANGED_REPLY
            card = changed
        except LlmError:
            reply = FALLBACK_REPLY

    todo = missing(card)
    if todo:
        return ConsultOut(
            card=card,
            reply=reply,
            questions=[QUESTIONS[f] for f in todo],
            results=[],
            schedule=[],
            days=None,
            notice=None,
        )

    now = inputs(card)
    quotes = {t: _quote(t, inp) for t, inp in now.items()}
    # 처음 다 찼거나 그 공정 칸이 바뀌었을 때만 공정 에이전트를 부른다 (둘이면 동시에)
    before = inputs(data.card) if data.card and not missing(data.card) else {}
    redo = [t for t in now if before.get(t) != now[t]]
    made = dict(zip(redo, await asyncio.gather(*(_plan(t, card, quotes[t]) for t in redo))))
    results = [
        TradeOut(
            trade=t,
            quote=QuoteOut.model_validate(quotes[t], from_attributes=True),
            plan=made[t][0] if t in made else None,
            plan_status=made[t][1] if t in made else "same",
        )
        for t in now
    ]
    steps, days = sequence({t: q.steps for t, q in quotes.items()})
    return ConsultOut(
        card=card,
        reply=reply,
        questions=[],
        results=results,
        schedule=[ScheduleStepOut.model_validate(st, from_attributes=True) for st in steps],
        days=days,
        notice=PLAN_FAILED if any(r.plan_status == "failed" for r in results) else None,
    )
