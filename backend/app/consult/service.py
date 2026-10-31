"""상담 한 턴. 무엇을 물을지, 언제 계산하고 누구를 부를지는 이 코드가 정한다.

공정마다 다른 것은 공정 스펙(consult.trades)에 있고, 여기서는 공정 이름으로 갈라지지 않는다.
1. 처음이면 프로젝트(견적 받기)로 칸을 채운다. 프로젝트 없이 시작하면 고른 공정(기본 도배)으로.
2. 폼 답을 스펙으로 검사해 넣는다.
3. 메시지가 있으면 라우터(LLM 한 번)가 바꿀 칸과 공정별 질문을 뽑는다. 바꿀 칸은 스펙에 맞는 것만 넣는다.
4. 질문은 그 공정 전문가가 답하고, 칸이 다 차면 공정마다 계산한 뒤 바뀐 공정만 공정 의견을 다시 만든다 (모두 병렬).
5. 공정표 · 합계 · 기간은 계산 엔진이 만든다. LLM은 숫자를 만들지 않고, 여기서는 DB에 쓰지 않는다.
"""

import asyncio
import re
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import consult as router_agent
from app.agent.llm import LlmError
from app.agent.schemas import Change, RouterOut
from app.auth.models import User
from app.calc.common import BASIS_LABEL, Quote, m2, pyeong_to_m2
from app.calc.sequence import sequence, totals
from app.consult.schemas import (
    Answer,
    BasisCounts,
    CautionOut,
    ChoiceOut,
    ConsultCard,
    ConsultIn,
    ConsultOut,
    Fact,
    PlanOut,
    Question,
    QuoteOut,
    ScheduleStepOut,
    SummaryOut,
    TradeOut,
)
from app.consult.trades import LATE_ORDER, ORDER, REGISTRY, SHARED_QUESTIONS, catalog
from app.consult.trades.base import UNKNOWN, Common, FieldSpec, TradeSpec, Value
from app.consult.trades.overlaps import overlaps
from app.project import service as project_service
from app.shared.errors import AppError

DEFAULT_TRADES = ("dobae",)
_UNKNOWN_CHOICE = ChoiceOut(value=UNKNOWN, label="모르겠어요")
COMMON_QUESTIONS: dict[str, Question] = {
    "area": Question(
        field="area",
        trade=None,
        kind="text",
        text="집이 몇 평이에요? 분양 평형이나 관리비 고지서에 적힌 숫자를 적어 주세요.",
        choices=[ChoiceOut(value=v, label=f"{v}평") for v in ("18", "24", "25", "32", "33", "34")],
    ),
    "area_basis": Question(
        field="area_basis",
        trade=None,
        kind="choice",
        text="그 평수는 분양 평형(공급면적)인가요, 실제로 쓰는 면적(전용면적)인가요?",
        choices=[
            ChoiceOut(value="supply", label="분양 평형 (공급)"),
            ChoiceOut(value="exclusive", label="전용면적"),
            _UNKNOWN_CHOICE,
        ],
    ),
    "occupied": Question(
        field="occupied",
        trade=None,
        kind="choice",
        text="공사하는 동안 그 집에 살고 계세요?",
        choices=[
            ChoiceOut(value="yes", label="살면서 공사해요"),
            ChoiceOut(value="no", label="빈집이에요"),
        ],
    ),
}
AREA_BASIS_DEFAULT = "supply"  # '모르겠어요'면 분양 평형으로 보고 실측 때 확인한다
MAX_EXPERTS = 3  # 한 턴에 부르는 공정 전문가 수

ROUTER_SYSTEM = router_agent.system(catalog())
NOT_YET = "아직 안 정했어요"
FALLBACK_REPLY = "지금은 답을 만들지 못했어요. 잠시 뒤 다시 적어 주세요."
CHANGED_REPLY = "알겠어요. 바꾼 값으로 다시 계산했어요."
OUT_OF_SCOPE = f"지금은 {' · '.join(s.label for s in REGISTRY.values())} 상담만 할 수 있어요."
PLAN_FAILED = "설명을 만들지 못했어요. 계산 결과만 보여 드려요."
EXPERT_FAILED = "답을 만들지 못했어요. 실측 때 업체에게 물어봐 주세요."
_AREA = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*(평형|평|㎡|m2|제곱미터)?\s*$")


def _specs(c: ConsultCard) -> list[TradeSpec]:
    """카드의 공정을 공정 순서(order)대로"""
    return sorted((s for k, s in REGISTRY.items() if k in c.trades), key=lambda s: s.order)


def _common_missing(c: ConsultCard) -> list[str]:
    have = {"area": c.area_m2, "area_basis": c.area_basis, "occupied": c.occupied}
    return [f for f, v in have.items() if v is None]


def _question(spec: TradeSpec, f: FieldSpec) -> Question:
    choices = [ChoiceOut(value=c.value, label=c.label, desc=c.desc) for c in f.choices]
    if f.unknown is not None:
        choices.append(_UNKNOWN_CHOICE)
    lo = hi = None
    if f.kind == "count":
        lo, hi = f.min, f.max
    elif f.kind == "multi":
        lo, hi = f.min, min(f.max, len(f.choices))
    return Question(
        field=f"{spec.key}.{f.key}",
        trade=spec.key,
        text=f.question,
        kind=f.kind,
        choices=choices,
        min=lo,
        max=hi,
    )


def questions(c: ConsultCard) -> list[Question]:
    """아직 비어 있는 필수 칸: 공통 칸 먼저, 공정은 공정 순서 · 스펙 칸 순서대로.

    share가 같은 칸(예: 방문 개수)은 처음 한 번만 묻고, 같이 쓰는 공정 이름을 질문 끝에 붙인다.
    """
    out = [COMMON_QUESTIONS[f] for f in _common_missing(c)]
    missing = [(sp, f) for sp in _specs(c) for f in sp.missing(c.values.get(sp.key, {}))]
    asked: set[str] = set()
    for spec, f in missing:
        if f.share in asked:
            continue
        q = _question(spec, f)
        if f.share:
            asked.add(f.share)
            users = [sp.label for sp, g in missing if g.share == f.share]
            if len(users) > 1:
                q = q.model_copy(
                    update={
                        "text": f"{SHARED_QUESTIONS.get(f.share, f.question)} "
                        f"{' · '.join(users)}에 같이 넣고, 공정마다 다르면 대화로 바꿀 수 있어요."
                    }
                )
        out.append(q)
    return out


def _area(num: str, unit: str | None) -> Decimal | None:
    try:
        n = Decimal(num)
    except InvalidOperation:
        return None
    if unit in ("㎡", "m2", "제곱미터"):
        return m2(n) if 10 <= n <= 1000 else None
    return pyeong_to_m2(n) if 3 <= n <= 300 else None


def _set_common(c: ConsultCard, check: bool = False, **upd) -> ConsultCard:
    if "area_basis" in upd:
        to_check = [x for x in c.to_check if x != "area_basis"] + (["area_basis"] if check else [])
        upd["to_check"] = to_check
    return c.model_copy(update=upd)


def _set_value(c: ConsultCard, trade: str, key: str, v: Value, unknown: bool) -> ConsultCard:
    name = f"{trade}.{key}"
    values = {t: dict(vs) for t, vs in c.values.items()}
    values.setdefault(trade, {})[key] = v
    to_check = [x for x in c.to_check if x != name] + ([name] if unknown else [])
    return c.model_copy(update={"values": values, "to_check": to_check})


def _trade_field(c: ConsultCard, name: str) -> tuple[TradeSpec, FieldSpec] | None:
    trade, _, key = name.partition(".")
    spec = REGISTRY.get(trade) if trade in c.trades else None
    f = spec.field(key) if spec else None
    return (spec, f) if spec and f else None


def apply_answer(c: ConsultCard, a: Answer) -> ConsultCard:
    """폼 답 하나를 넣는다. 칸 · 선택지 · 범위에 맞지 않으면 422."""
    v = a.value
    if a.field == "area":
        m = _AREA.match(v) if isinstance(v, str) else None
        area = _area(m.group(1), m.group(2)) if m else None
        if area is None:
            raise AppError(422, "bad_answer", "평수를 다시 적어 주세요.")
        return _set_common(c, area_m2=area)
    if a.field == "area_basis" and v in ("supply", "exclusive", UNKNOWN):
        unknown = v == UNKNOWN
        return _set_common(c, unknown, area_basis=AREA_BASIS_DEFAULT if unknown else v)
    if a.field == "occupied" and v in ("yes", "no"):
        return _set_common(c, occupied=v == "yes")
    found = _trade_field(c, a.field)
    try:
        if found is None:
            raise ValueError(a.field)
        value, unknown = found[1].read(v)
    except ValueError:
        raise AppError(422, "bad_answer", "선택지에서 다시 골라 주세요.") from None
    return _set_value(c, found[0].key, found[1].key, value, unknown)


def apply_change(c: ConsultCard, ch: Change) -> ConsultCard:
    """라우터가 뽑은 공정 칸 변경. 없는 공정 · 칸, 선택지 · 범위 밖 값은 버린다."""
    found = _trade_field(c, ch.field)
    if found is None:
        return c
    spec, f = found
    value = ch.value.strip()
    try:
        if ch.op == "set":
            raw: str | list[str] = value
            if f.kind == "multi" and value != UNKNOWN:
                raw = [x.strip() for x in value.split(",") if x.strip()]
            v, unknown = f.read(raw)
        elif f.kind == "multi":
            cur = c.values.get(spec.key, {}).get(f.key, [])
            cur = cur if isinstance(cur, list) else []
            nxt = cur + [value] if ch.op == "add" else [x for x in cur if x != value]
            v, unknown = f.read(nxt)
        else:
            return c
    except ValueError:
        return c
    return _set_value(c, spec.key, f.key, v, unknown)


def apply_trades(c: ConsultCard, add: list[str], remove: list[str]) -> ConsultCard:
    """대화로 공정을 더하거나 뺀다. 등록된 공정만, 하나는 남긴다. 뺀 공정의 칸 값은 prune이 지운다."""
    picked = (set(c.trades) | {k for k in add if k in REGISTRY}) - set(remove)
    trades = [k for k in ORDER if k in picked]
    if not trades or trades == c.trades:
        return c
    return c.model_copy(update={"trades": trades})


def apply_route(c: ConsultCard, r: RouterOut) -> ConsultCard:
    """라우터가 뽑은 값 중 범위 · 스펙에 맞는 것만 카드에 넣는다. 공정을 먼저 바꾸고 칸을 바꾼다."""
    c = apply_trades(c, r.trades_add[:10], r.trades_remove[:10])
    if r.area_m2 is not None:
        area = _area(str(r.area_m2), "㎡")
        c = _set_common(c, area_m2=area) if area is not None else c
    elif r.pyeong is not None:
        area = _area(str(r.pyeong), "평")
        c = _set_common(c, area_m2=area) if area is not None else c
    if r.area_basis is not None:
        unknown = r.area_basis == UNKNOWN
        c = _set_common(c, unknown, area_basis=AREA_BASIS_DEFAULT if unknown else r.area_basis)
    if r.occupied is not None:
        c = _set_common(c, occupied=r.occupied)
    if r.balcony_ext is not None:
        c = _set_common(c, balcony_ext=r.balcony_ext)
    if r.built_year is not None and 1900 <= r.built_year <= 2100:
        c = _set_common(c, built_year=r.built_year)
    for ch in r.changes[:20]:
        c = apply_change(c, ch)
    return c


def prune(c: ConsultCard) -> ConsultCard:
    """조건이 꺼진 칸(예: 방문을 빼면 방문 개수)의 값과 확인 표시를 지운다."""
    values = {}
    for spec in _specs(c):
        kept = spec.relevant(c.values.get(spec.key, {}))
        if kept:
            values[spec.key] = kept
    names = {f"{t}.{k}" for t, vs in values.items() for k in vs}
    to_check = [x for x in c.to_check if "." not in x or x in names]
    if values == c.values and to_check == c.to_check:
        return c
    return c.model_copy(update={"values": values, "to_check": to_check})


def share_fill(c: ConsultCard) -> ConsultCard:
    """share가 같은 칸은 한 번만 묻는다: 다른 공정에 값이 있으면 비어 있는 칸에 그 값을 넣는다.

    '모르겠어요' 표시도 같이 옮긴다. 이미 값이 있는 칸(공정마다 다르게 정한 값)은 건드리지 않는다.
    """
    known: dict[str, tuple[Value, bool]] = {}
    for spec in _specs(c):
        vals = c.values.get(spec.key, {})
        for f in spec.asked(vals):
            if f.share and f.key in vals and f.share not in known:
                known[f.share] = (vals[f.key], f"{spec.key}.{f.key}" in c.to_check)
    for spec in _specs(c):
        for f in spec.missing(c.values.get(spec.key, {})):
            if f.share in known and f.ok(known[f.share][0]):
                v, unknown = known[f.share]
                c = _set_value(c, spec.key, f.key, f.norm(v), unknown)
    return c


def normalize(c: ConsultCard) -> ConsultCard:
    """조건이 꺼진 칸을 지우고(prune) 같이 쓰는 칸을 채운다(share_fill)."""
    return share_fill(prune(c))


def facts(c: ConsultCard) -> list[Fact]:
    """카드 값을 화면 말로. 묻는 칸은 비어 있어도 '아직 안 정했어요'로 보인다."""
    if c.area_m2 is None:
        area = NOT_YET
    else:
        basis = f"{BASIS_LABEL[c.area_basis]} " if c.area_basis else ""
        area = f"{basis}{c.area_m2}㎡"
    occupied = NOT_YET if c.occupied is None else "살면서 공사해요" if c.occupied else "빈집이에요"
    out = [
        Fact(trade=None, label="공정", text=" · ".join(s.label for s in _specs(c))),
        Fact(trade=None, label="면적", text=area, check="area_basis" in c.to_check),
        Fact(trade=None, label="집 상태", text=occupied),
    ]
    if c.balcony_ext:
        out.append(Fact(trade=None, label="발코니", text="확장했어요"))
    if c.built_year:
        out.append(Fact(trade=None, label="준공 연도", text=f"{c.built_year}년"))
    for spec in _specs(c):
        vals = c.values.get(spec.key, {})
        for f in spec.asked(vals):
            v = vals.get(f.key)
            out.append(
                Fact(
                    trade=spec.key,
                    label=f.label,
                    text=NOT_YET if v is None else f.text(v),
                    check=f"{spec.key}.{f.key}" in c.to_check,
                )
            )
        if c.spaces.get(spec.key):
            names = " · ".join(c.spaces[spec.key])
            out.append(Fact(trade=spec.key, label=f"{spec.label} 공간", text=names))
    return out


def _common(c: ConsultCard) -> Common:
    return Common(
        area_m2=c.area_m2,
        area_basis=c.area_basis,
        occupied=c.occupied,
        balcony_ext=c.balcony_ext,
        built_year=c.built_year,
    )


def plan_text(c: ConsultCard, spec: TradeSpec, common: Common) -> str:
    """공정 의견 에이전트에 넘기는 집 정보: 공통 줄 + 공정 칸 줄(스펙) + 공간 · 같이 하는 공정 · 모르는 칸"""
    rows = [
        f"면적: {BASIS_LABEL[c.area_basis]} {c.area_m2}㎡",
        f"사는 집에서 공사: {'예' if c.occupied else '아니요(빈집)'}",
        f"발코니 확장: {'예' if c.balcony_ext else '아니요'}",
    ]
    if c.built_year:
        rows.append(f"준공 연도: {c.built_year}")
    rows += spec.card_lines(common, c.values.get(spec.key, {}))
    if c.spaces.get(spec.key):
        rows.append(f"{spec.label} 공간: " + ", ".join(c.spaces[spec.key]))
    together = _specs(c)
    if len(together) > 1:
        rows.append("같이 하는 공정 (작업 순서): " + " → ".join(s.label for s in together))
    checks = ["면적 기준"] if "area_basis" in c.to_check else []
    checks += [f.label for f in spec.fields if f"{spec.key}.{f.key}" in c.to_check]
    if checks:
        rows.append("고객이 몰라 기본값으로 둔 칸: " + ", ".join(checks))
    return "\n".join(rows)


def _expert_text(fs: list[Fact], trade: str) -> str:
    """전문가에게 넘기는 집 정보 (칸이 덜 찼어도 된다)"""
    return "\n".join(f"{f.label}: {f.text}" for f in fs if f.trade in (None, trade))


def _same_key(c: ConsultCard, trade: str) -> tuple:
    """공정 의견을 다시 만들지 정하는 값: 공통 칸 + 고른 공정(의견의 '같이 하는 공정' 줄) + 그 공정 칸.

    공정을 더하거나 빼면 순서 이야기가 바뀌므로 모든 공정 의견을 다시 만든다 (같은 입력은 캐시가 받는다).
    """
    vals = {k: sorted(v) if isinstance(v, list) else v for k, v in c.values.get(trade, {}).items()}
    common = (c.area_m2, c.area_basis, c.occupied, c.balcony_ext, c.built_year)
    return (*common, tuple(c.trades), vals)


async def _prefill(s: AsyncSession, user: User, project_id: uuid.UUID) -> ConsultCard:
    p = await project_service.get_for(s, user, project_id)
    names = {sp.id: sp.name for sp in p.spaces}
    trades, values, spaces = [], {}, {}
    for key, spec in REGISTRY.items():
        t = getattr(p.trades, key, None)
        if t is None:
            continue
        trades.append(key)
        vals = {}
        for k, v in (spec.prefill(p) if spec.prefill else {}).items():
            f = spec.field(k)
            if f is not None and f.ok(v):
                vals[k] = f.norm(v)
        if vals:
            values[key] = vals
        if picked := [names[i] for i in getattr(t, "spaces", []) if i in names]:
            spaces[key] = picked
    upd: dict = {
        "trades": trades or list(DEFAULT_TRADES),
        "values": values,
        "spaces": spaces,
        "occupied": p.occupied,
        "balcony_ext": p.balcony_ext,
        "built_year": p.built_year,
    }
    if p.size.m2 is not None:
        upd |= {"area_m2": p.size.m2, "area_basis": p.size.basis}
    return ConsultCard(**upd)


async def _start(s: AsyncSession, user: User | None, data: ConsultIn) -> ConsultCard:
    if data.project_id:
        return await _prefill(s, user, data.project_id)
    picked = set(data.trades or DEFAULT_TRADES)
    return ConsultCard(trades=[k for k in ORDER if k in picked])


async def _plan(spec: TradeSpec, text: str, q: Quote) -> tuple[PlanOut | None, str]:
    try:
        r = await spec.agent.plan(text, q)
    except LlmError:
        return None, "failed"
    plan = PlanOut(
        summary=r.plan.summary,
        steps=r.plan.steps,
        visit_checks=r.plan.visit_checks,
        cautions=[
            CautionOut(text=x.text, source=spec.agent.sources[x.source]) for x in r.plan.cautions
        ],
        prompt_version=spec.agent.plan_prompt_version,
    )
    return plan, "new"


async def _answer(spec: TradeSpec, question: str, context: str) -> str:
    try:
        r = await spec.agent.answer(question, context)
    except LlmError:
        return f"{spec.label}: {EXPERT_FAILED}"
    return f"{spec.label}: {r.answer.answer}"


def _asks(r: RouterOut | None) -> list[tuple[TradeSpec, str]]:
    """라우터가 넘긴 질문: 레지스트리에 있는 공정만, 공정마다 하나, 한 턴에 MAX_EXPERTS개까지"""
    picked: dict[str, tuple[TradeSpec, str]] = {}
    for q in r.questions if r else []:
        spec, text = REGISTRY.get(q.trade), q.question.strip()[:300]
        if spec and text and spec.key not in picked:
            picked[spec.key] = (spec, text)
    return list(picked.values())[:MAX_EXPERTS]


def _reply(r: RouterOut | None, failed: bool, changed: bool, answers: list[str]) -> str | None:
    if failed:
        return FALLBACK_REPLY
    head = None
    if r and router_agent.reply_ok(r.reply):
        head = r.reply.strip()
    elif r and r.out_of_scope:
        head = OUT_OF_SCOPE
    elif changed:
        head = CHANGED_REPLY
    return "\n".join(x for x in (head, *answers) if x) or None


async def turn(s: AsyncSession, user: User | None, data: ConsultIn) -> ConsultOut:
    card = data.card or await _start(s, user, data)
    # LLM을 기다리는 동안 DB 연결을 붙잡지 않는다
    await s.close()

    for a in data.answers:
        card = apply_answer(card, a)
    route: RouterOut | None = None
    failed = changed = False
    text = (data.message or "").strip()
    if text:
        turns = [(t.role, t.text) for t in data.history[-20:]] + [("user", text)]
        try:
            route, _ = await router_agent.route(
                ROUTER_SYSTEM, turns, card.trades, card.model_dump(mode="json")
            )
        except LlmError:
            failed = True
        else:
            routed = normalize(apply_route(card, route))
            changed = routed != normalize(card)
            card = routed
    card = normalize(card)
    fs = facts(card)
    labels = {s.key: s.label for s in _specs(card)}
    cross = overlaps(card.trades, card.values)
    experts = [_answer(spec, q, _expert_text(fs, spec.key)) for spec, q in _asks(route)]

    todo = questions(card)
    if todo:
        answers = list(await asyncio.gather(*experts))
        return ConsultOut(
            card=card,
            trade_labels=labels,
            reply=_reply(route, failed, changed, answers),
            questions=todo,
            facts=fs,
            results=[],
            schedule=[],
            summary=None,
            overlaps=cross,
            notice=None,
        )

    common = _common(card)
    specs = _specs(card)
    quotes = {sp.key: sp.build(common, card.values.get(sp.key, {})) for sp in specs}
    # 처음 다 찼거나 그 공정 칸(공통 칸 포함)이 바뀌었을 때만 공정 의견을 다시 만든다
    prev = normalize(data.card) if data.card is not None else None
    before = prev if prev is not None and not questions(prev) else None
    redo = [
        sp
        for sp in specs
        if before is None
        or sp.key not in before.trades
        or _same_key(before, sp.key) != _same_key(card, sp.key)
    ]
    plans = [_plan(sp, plan_text(card, sp, common), quotes[sp.key]) for sp in redo]
    done = await asyncio.gather(*experts, *plans)
    answers = list(done[: len(experts)])
    made = dict(zip([sp.key for sp in redo], done[len(experts) :], strict=True))

    results = [
        TradeOut(
            trade=sp.key,
            label=sp.label,
            quote=QuoteOut.model_validate(quotes[sp.key], from_attributes=True),
            plan=made[sp.key][0] if sp.key in made else None,
            plan_status=made[sp.key][1] if sp.key in made else "same",
        )
        for sp in specs
    ]
    steps, days = sequence({k: q.steps for k, q in quotes.items()}, ORDER, LATE_ORDER)
    t = totals(quotes.values())
    return ConsultOut(
        card=card,
        trade_labels=labels,
        reply=_reply(route, failed, changed, answers),
        questions=[],
        facts=fs,
        results=results,
        schedule=[ScheduleStepOut.model_validate(st, from_attributes=True) for st in steps],
        summary=SummaryOut(
            subtotal=t.subtotal,
            vat=t.vat,
            total=t.total,
            days=days,
            basis_counts=BasisCounts(**t.basis_counts),
        ),
        overlaps=cross,
        notice=PLAN_FAILED if any(r.plan_status == "failed" for r in results) else None,
    )
