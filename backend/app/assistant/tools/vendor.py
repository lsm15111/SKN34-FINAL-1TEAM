"""업체 비서 읽기 도구 (계약서 5장): request_brief · my_free_slots · quote_checklist · my_jobs.

- 요청은 vendor_visit(내 요청이 아니면 404)으로만 연다. 고객 이름 · 연락처 · 동호수는 오지 않는다.
- 고객이 남긴 말 · 사진 이름표는 자료 상자(policy.data)로만 넘긴다.
- REST(GET /vendor/assistant/briefs · checklists · today)도 같은 함수(brief · checklist · vendor_today)를 쓴다.
"""

import re
import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import actions, policy
from app.assistant.schemas import (
    ActionOut,
    ActionSummary,
    BriefDay,
    BriefEstimate,
    BriefHalves,
    BriefSuggest,
    BriefWindow,
    CardOut,
    ChecklistRow,
    FieldValue,
    FitRow,
    PrevQuote,
    QuoteChecklistData,
    RowAction,
    SummaryRow,
    TodayRow,
    VendorBriefData,
    VendorTodayData,
)
from app.assistant.tools import ToolCtx, ToolError, ToolOut, obj, tool
from app.assistant.tools.cards import GRADE, TRADE
from app.auth.models import User
from app.calc.common import COUNTED
from app.db import SessionLocal
from app.shared.clock import SEOUL
from app.shared.korean import i_ga

if TYPE_CHECKING:
    from app.assistant.runtime import RefTable

REF = {"type": "string", "description": "도구 결과에 나온 이름표"}
VAT = {"included": "부가세 포함", "excluded": "부가세 별도", "exempt": "면세"}


async def open_halves(
    s: AsyncSession, vendor_id: uuid.UUID, start: date, end: date
) -> dict[date, list[str]]:
    """업체 빈 반나절(visit.service.open_halves_for: 날 → ["am", "pm"] 중 빈 것, 고객 정보 없음)."""
    from app.visit import service as visit_service

    return await visit_service.open_halves_for(s, vendor_id, start, end)


def _visit_id(tc: ToolCtx, ref: str | None) -> uuid.UUID:
    if ref:
        return uuid.UUID(tc.refs.get(ref, "visit")["id"])
    if tc.visit_id is None:
        raise ToolError("no_visit", "어느 요청인지 몰라요. 할 일 목록에서 요청을 먼저 골라 주세요.")
    return tc.visit_id


# ---- 브리핑 ----


async def brief(
    s: AsyncSession,
    vendor: User,
    visit_id: uuid.UUID,
    today: date,
    now: datetime,
    refs: "RefTable",
    turn_id: uuid.UUID | None = None,
    *,
    commit: bool = True,
    origin: str = "turn",
    propose_window: bool = True,
) -> tuple[CardOut, dict, VendorBriefData, list[ActionOut], list[ActionOut]]:
    """새 요청 브리핑(UC-V1): 요약 · 맞음 여부(공정 · 지역 · 일정 · 벽지: 맞음 · 확인 필요 · 맞지 않음) · 가견적(요청
    때 고정한 값) · 빈 반나절 · 답할 기간 후보(w…, 카드 단추 'window_answer:w…') · 추천 응답(첫 후보 →
    window_answer 제안 행, 요청함 상태일 때만) · 한 문장(틀). 공정 · 지역이 맞지 않으면 기간 후보 · 제안을 만들지
    않고 맞지 않는 까닭만 보인다(못 받아요는 업체가 고른다). 칸 수는 카드에 보이는 하나(제안 기간의 칸)만 쓴다.
    AI 한 문장은 세션 밖에서 brief_sentence로 바꿔 끼운다. commit=False면 제안 행을 commit하지 않는다
    (먼저 말 걸기가 같은 트랜잭션에서 보낸다). propose_window=False면 제안을 만들지 않는다(무료 모드에서 답하기를
    말하지 않은 턴). 돌려주는 값: (카드, 모델용 값, 브리핑 data, 새 제안, 닫힌 제안)."""
    from app.calc import slots
    from app.refprice.holidays import days_off
    from app.vendor import service as vendor_service
    from app.visit import service as visit_service

    d = await visit_service.vendor_visit(s, vendor, visit_id, today)
    prof = await vendor_service.get_profile(s, vendor)
    ref = refs.put("visit", {"id": str(visit_id), "trade": d.trade})
    tomorrow = today + timedelta(days=1)
    start = max(d.wish_start or tomorrow, tomorrow)
    end = max(d.wish_end or start + timedelta(days=13), start)
    off = days_off(start, end)
    span = slots.days_between(start, min(end, start + timedelta(days=13)))
    taken = {f"{t.day.isoformat()}:{t.half}": t.area_label.split(" · ")[0] for t in d.taken}
    trade = TRADE.get(d.trade, d.trade)
    grade = GRADE.get(d.grade or "")
    in_area = any(a.sgg == d.area_name or a.label == d.region for a in prof.areas)
    wish = f"고객 희망 {start.isoformat()} ~ {end.isoformat()}"
    has_open = (d.open_count or 0) > 0
    fit = [
        _fit("trade", "공정", d.trade in prof.trades, f"{trade} 요청"),
        _fit("area", "지역", in_area, d.region),
        # 칸 수는 쓰지 않는다(카드 · 한 문장의 칸 수는 제안 기간 하나)
        _fit("schedule", "일정", has_open, wish if has_open else f"{wish} · 빈 반나절 없음"),
    ]
    if d.trade == "dobae":  # 고객이 벽지를 아직 안 정했으면 맞지 않음이 아니라 확인 필요
        fit.append(
            FitRow(key="paper", label="벽지", ok=True, text=grade, state="ok")
            if grade
            else FitRow(key="paper", label="벽지", ok=False, text="벽지 미정", state="check")
        )
    misfit = next((f for f in fit if f.key in MISFIT_KEYS and f.state == "no"), None)
    suggest: BriefSuggest | None = None
    made: list[ActionOut] = []
    closed: list[ActionOut] = []
    # 요청함: 답할 기간 후보(w…)를 카드에 둔다(무료 모드에서도 단추로 고르게). 공정 · 지역이 맞지 않으면 두지 않는다
    live = d.status == "requested" and misfit is None
    free = await open_halves(s, vendor.id, start, end) if live else None
    wins = slots.best_windows(free, start, end, today, days_off=off) if free is not None else []
    windows = [
        BriefWindow(
            ref=refs.put(
                "window",
                {
                    "visit_id": str(visit_id),
                    "start": w.start.isoformat(),
                    "end": w.end.isoformat(),
                    "excluded": [x.isoformat() for x in w.excluded],
                    "open_count": w.open_count,
                },
            ),
            start=w.start,
            end=w.end,
            excluded=list(w.excluded),
            open_count=w.open_count,
        )
        for w in wins
    ]
    if wins and propose_window:
        w = wins[0]
        instant = bool(d.instant_default)
        summary = ActionSummary(
            title="이 기간으로 답하기",
            rows=[
                SummaryRow(label="기간", value=f"{w.start.isoformat()} ~ {w.end.isoformat()}"),
                SummaryRow(label="빈 반나절", value=f"{w.open_count}칸"),
            ],
            note="답하면 고객이 그 기간에서 반나절을 골라요",
            approve_label="이 기간으로 답하기",
        )
        row, old = await actions.propose(
            s,
            vendor,
            surface="vendor",
            kind="window_answer",
            target_kind="visit",
            target_id=visit_id,
            target_ver=d.status,
            payload={
                "visit_id": str(visit_id),
                "start": w.start.isoformat(),
                "end": w.end.isoformat(),
                "excluded": [x.isoformat() for x in w.excluded],
                "instant": instant,
            },
            summary=summary,
            now=now,
            expires_at=d.reply_due_at if d.reply_due_at and d.reply_due_at > now else None,
            turn_id=turn_id,
            origin=origin,
        )
        if commit:
            await s.commit()
        made = [actions.out(row)]
        closed = [actions.out(c) for c in old]
        if row.status == "proposed":
            suggest = BriefSuggest(
                action_id=row.id,
                start=w.start,
                end=w.end,
                excluded=list(w.excluded),
                instant=instant,
                open_count=w.open_count,
            )
    facts = [x for x in (d.home_text, f"도배 {grade}" if grade else None, d.when_text) if x]
    if d.work_wish_on:
        facts.append(f"공사 시작 희망 {d.work_wish_on.isoformat()}")
    if d.photos:
        facts.append(f"사진 {len(d.photos)}장")
    data = VendorBriefData(
        visit_id=visit_id,
        title=" · ".join(
            x for x in (d.area_label or d.region, f"{trade} {grade or ''}".strip()) if x
        ),
        facts=facts,
        fit=fit,
        estimate=BriefEstimate(
            total_won=d.estimate_total, basis="요청 때 고정한 가견적(내 단가 × 믿집 수량)"
        )
        if d.estimate_total is not None
        else None,
        halves=BriefHalves(
            days=[BriefDay(day=x, off=x in off) for x in span],
            taken=taken,
            open_count=d.open_count or 0,
        ),
        suggest=suggest,
        windows=windows,
        due_at=d.reply_due_at,
        memo=policy.mask_in(d.message or "") or None,
    )
    data.sentence = brief_template(data)
    card = CardOut(
        card_id=f"brief-{visit_id}", kind="vendor_brief", data=data.model_dump(mode="json")
    )
    model = {
        "ref": ref,
        "status": d.status,
        "title": data.title,
        "facts": facts,
        "fit": [{"label": f.label, "state": f.state, "text": f.text} for f in fit],
        "estimate_won": d.estimate_total,
        "due_at": d.reply_due_at,
        "memo": policy.data(d.message),
        "proposed": bool(made),
        # 공정 · 지역이 맞지 않음(무료 모드 답이 쓴다, 허용 칸이 아니라 모델 값에는 안 감)
        "misfit": misfit.label if misfit else None,
        "windows": [
            {"ref": w.ref, "start": w.start, "end": w.end, "open_count": w.open_count}
            for w in windows
        ],
    }
    return card, model, data, made, closed


MISFIT_KEYS = ("trade", "area")  # 맞지 않으면 기간 답하기를 권하지 않는 칸


def _fit(key, label: str, ok: bool, text: str) -> FitRow:
    return FitRow(key=key, label=label, ok=ok, text=text, state="ok" if ok else "no")


SENTENCE_MAX = 60
SENTENCE_TTL = 86400  # 같은 사실이면 하루 동안 같은 문장(Haiku를 다시 부르지 않는다)


class Sentence(BaseModel):
    text: str


def _md(d: date) -> str:
    return f"{d.month:02d}.{d.day:02d}"


def brief_template(data: VendorBriefData) -> str:
    """브리핑 한 문장 틀(코드 값만): 맞지 않는 것부터(공정 · 지역이면 못 받아요로 답하는 길), 다 맞으면 답하기 좋은
    기간(카드의 제안 칸 수), 그다음 확인 필요(고객이 아직 정하지 않은 것)."""
    bad = next((f for f in data.fit if f.state == "no"), None)
    if bad is not None and bad.key in MISFIT_KEYS:
        return f"{i_ga(bad.label)} 우리 업체와 맞지 않아요. 받기 어려우면 못 받아요로 답해 주세요."
    if bad is not None:
        return f"{i_ga(bad.label)} 맞지 않아요. 요청을 열어 확인해 주세요."
    g = data.suggest
    if g is not None:
        return f"{_md(g.start)}~{_md(g.end)}에 빈 반나절 {g.open_count}칸이 있어 답하기 좋아요."
    check = next((f for f in data.fit if f.state == "check"), None)
    if check is not None:
        return f"{check.label} 확인이 필요해요. 고객이 아직 정하지 않았어요."
    return "공정 · 지역 · 일정이 맞아요. 요청을 열어 확인해 주세요."


def _brief_facts(data: VendorBriefData) -> dict:
    """AI 한 문장에 넘길 사실: 카드에 보이는 값만(칸 수는 제안 기간 하나, 맞음은 세 갈래)."""
    g = data.suggest
    return {
        "title": data.title,
        "fit": [{"label": f.label, "state": f.state, "text": f.text} for f in data.fit],
        "suggest": {"start": _md(g.start), "end": _md(g.end), "open_count": g.open_count}
        if g
        else None,
        "due": data.due_at.astimezone(SEOUL).strftime("%m.%d %H:%M") if data.due_at else None,
    }


HANJA = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")  # 한자(확장 A · 통합): AI 문장에 섞이면 틀로


def sentence_ok(text: str, facts: str) -> bool:
    """짧은 AI 문장 검사(먼저 말 걸기 · 브리핑): 길이 · '요' 끝 · 한자 없음 · 숫자는 사실에 있는 것만 · 한 일처럼
    말하지 않음 · 표준 대비 % · 링크 · 연락처 없음."""
    from app.agent.v3 import check
    from app.agent.v3.schemas import Sentence as Sent
    from app.assistant.runtime import claims_done
    from app.v2 import guard

    t = (text or "").strip()
    if not t or len(t) > SENTENCE_MAX or "\n" in t or not re.search(r"요[.!?]?$", t):
        return False
    if HANJA.search(t):
        return False
    ok, _ = check.sentence_ok(Sent(text=t), guard.numbers(facts), None, None, None)
    return (
        ok is not None and ok.text == t and not claims_done(t) and not policy.VS_STANDARD.search(t)
    )


async def brief_sentence(data: VendorBriefData, user_id: uuid.UUID) -> str:
    """브리핑 AI 한 문장(Haiku, 같은 사실이면 하루 캐시). 못 부르거나 검사에 걸리면 틀(brief_template)."""
    import hashlib
    import json

    from app import queue
    from app.agent import llm
    from app.assistant import prompts
    from app.usage.service import REDIS_ERRORS

    facts = json.dumps(_brief_facts(data), ensure_ascii=False, sort_keys=True)
    key = f"assistant:brief:{data.visit_id}:{hashlib.sha256(facts.encode()).hexdigest()[:16]}"
    try:
        hit = await queue.redis.get(key)
    except REDIS_ERRORS:
        hit = None
    if hit:
        return hit.decode() if isinstance(hit, bytes) else str(hit)
    try:
        with llm.call_ctx(user_id=user_id, purpose="nudge"):
            got = await llm.claude_json(
                "nudge", Sentence, prompts.text("brief"), facts, max_tokens=512
            )
        text = got.text.strip()
    except llm.LLMError:
        return brief_template(data)
    if not sentence_ok(text, facts):
        return brief_template(data)
    try:
        await queue.redis.set(key, text, ex=SENTENCE_TTL)
    except REDIS_ERRORS:
        pass
    return text


# 표준견적서 줄 이름 → 업체가 읽는 이름(고객 화면 frontend/lib/guest/standard.ts nameOf와 같은 규칙).
# 계산 엔진 줄 이름은 그대로 둔다: '실크벽지 시장 평균 가격' → '실크벽지', '벽 도배 시공 (풀 포함)' → '벽 도배 시공'
LINE_NOTE_KEYS = frozenset({"wall", "ceiling", "material", "putty", "meal", "truck"})
LINE_PAPER = re.compile(r"도배지 \((합지|실크)\)")
LINE_MARKET = re.compile(r"(\S+벽지) 시장 평균 가격")


def line_name(key: str, name: str) -> str:
    text = name.strip()
    if text.endswith("(풀 포함)"):
        return text.removesuffix("(풀 포함)").rstrip()
    if m := LINE_PAPER.fullmatch(text):
        return f"{m.group(1)}벽지"
    if m := LINE_MARKET.fullmatch(text):
        return m.group(1)
    # 두 기준 줄은 이름 끝 괄호가 짧은 뜻이다('부자재 (풀 · 부직포 · 네바리 · 실리콘 등)' → '부자재')
    cut = text.rfind("(")
    if key in LINE_NOTE_KEYS and text.endswith(")") and cut > 0:
        return text[:cut].rstrip() or text
    return text


async def checklist(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, today: date, refs: "RefTable"
) -> tuple[CardOut, dict, QuoteChecklistData]:
    """견적서 준비(UC-V3): 이 집 표준견적서 줄(계산 엔진) · 내 견적서 칸(임시 저장 · 보낸 판) · 빠지기 쉬운 것."""
    from sqlalchemy import select

    from app.agent.trades import TRADES
    from app.project import service as project_service
    from app.quote import service as quote_service
    from app.visit import service as visit_service
    from app.visit.models import Visit

    d = await visit_service.vendor_visit(s, vendor, visit_id, today)  # 내 요청이 아니면 404
    refs.put("visit", {"id": str(visit_id), "trade": d.trade})
    pid = await s.scalar(select(Visit.project_id).where(Visit.id == visit_id))  # 읽기 조인
    got = await quote_service.standard_trade(s, await project_service.get_out(s, pid), d.trade)
    lines = got[1] if got else []
    board = await visit_service.quote_board(s, vendor, visit_id)
    cur = board.draft or (board.sent[0] if board.sent else None)
    items = [
        ChecklistRow(
            key=ln.key,
            label=line_name(ln.key, ln.name),
            state="check",
            hint="표준견적서에 있는 줄이에요. 견적서에 넣었는지 확인해요",
        )
        for ln in lines
        if ln.state in COUNTED
    ]
    fields = [
        FieldValue(
            label="낼 금액",
            value=f"{cur.entered_amount:,}원" if cur and cur.entered_amount is not None else None,
        ),
        FieldValue(label="부가세 방식", value=VAT.get(cur.vat_mode or "") if cur else None),
        FieldValue(label="공사 기간", value=f"{cur.days}일" if cur and cur.days else None),
        FieldValue(
            label="유효기간",
            value=cur.valid_until.isoformat() if cur and cur.valid_until else None,
        ),
    ]
    cfg = TRADES.get(d.trade)  # type: ignore[call-overload]
    easy = [*cfg.cautions, *cfg.survey_vars, *cfg.prep] if cfg else []
    last = board.sent[0] if board.sent else None
    data = QuoteChecklistData(
        visit_id=visit_id,
        items=items,
        fields=fields,
        easy_miss=easy,
        prev=PrevQuote(version=last.version, total_won=last.total)
        if last is not None and last.total is not None
        else None,
    )
    card = CardOut(
        card_id=f"check-{visit_id}", kind="quote_checklist", data=data.model_dump(mode="json")
    )
    model = {
        "items": [{"label": x.label} for x in items],
        "fields": [{"label": f.label, "value": f.value} for f in fields],
        "easy_miss": easy,
        "prev": data.prev.model_dump() if data.prev else None,
    }
    return card, model, data


DATES_TODO = ("waiting", "requested")  # 공사 날짜를 낼 공사(아직 안 냄 · 고객이 다른 날짜를 요청함)


async def vendor_today(
    s: AsyncSession, vendor: User, today: date, refs: "RefTable | None" = None
) -> VendorTodayData:
    """업체 작업함 맨 위 '오늘 브리핑': 새 요청 · 오늘 실측 · 보낼 견적서 · 공사 날짜 낼 공사(줄은 코드가 고른다).
    refs를 주면 공사 날짜 줄에 기한이 가까운 공사의 날 후보 첫 것(date_candidates) 이름표를 넣어 단추
    (choice 'dates:d#,n#')로 승인 카드를 받게 한다. REST는 업체 비서 대화의 표, 턴은 그 턴의 표를 준다."""
    from app.schedule import service as schedule_service
    from app.visit import flow

    rows: list[TodayRow] = []
    todo = (await schedule_service.vendor_inbox(s, vendor, "todo", today, None, 50)).items
    new = [r for r in todo if r.status == "requested"]
    if new:
        dues = [r.next.due_at for r in new if r.next and r.next.due_at]
        soon = bool(dues) and min(dues).astimezone(SEOUL).date() <= today + timedelta(days=1)
        rows.append(
            TodayRow(
                id="new",
                icon="inbox",
                title=f"새 요청 {len(new)}",
                sub=" · ".join(dict.fromkeys(r.area_name for r in new[:3])),
                due=soon,
                action=RowAction(label="보기", href=f"/vendor/requests/{new[0].id}"),
            )
        )
    booked = (await flow.vendor_schedule(s, vendor, today, today)).items
    if booked:
        halves = " · ".join("오전" if x.half == "am" else "오후" for x in booked)
        rows.append(
            TodayRow(id="visit", icon="calendar", title=f"오늘 실측 {len(booked)}", sub=halves)
        )
    quote = [r for r in todo if r.status == "visited"]
    if quote:
        rows.append(
            TodayRow(
                id="quote",
                icon="file",
                title=f"보낼 견적서 {len(quote)}",
                sub=" · ".join(dict.fromkeys(r.area_name for r in quote[:3])),
            )
        )
    jobs = (await schedule_service.vendor_inbox(s, vendor, "jobs", today, None, 50)).items
    need = [r for r in jobs if r.deal_id is not None and r.dates_state in DATES_TODO]
    if need:
        far = datetime.max.replace(tzinfo=SEOUL)
        need.sort(key=lambda r: r.next.due_at if r.next and r.next.due_at else far)
        first = need[0]
        due = first.next.due_at if first.next else None
        sub = list(dict.fromkeys(r.area_name for r in need[:3]))
        action = RowAction(label="보기", href=f"/vendor/jobs/{first.deal_id}")
        if refs is not None:
            job = await schedule_service.job_for(s, vendor, first.deal_id, today)
            cands = date_candidates(job, first.deal_id, today)
            if cands:
                c = cands[0]
                d = refs.put("deal", {"id": str(first.deal_id), "trade": first.trade})
                n = refs.put("days", c)
                days = [date.fromisoformat(x) for x in c["days"]]
                sub.append(f"후보 {_md(days[0])}~{_md(days[-1])}")
                action = RowAction(
                    label="공사 날짜 보내기",
                    say="공사 날짜 보낼래요",
                    choice=f"dates:{d},{n}",
                    primary=True,
                )
        rows.append(
            TodayRow(
                id="dates",
                icon="calendar",
                title=f"공사 날짜 낼 공사 {len(need)}",
                sub=" · ".join(sub),
                due=due is not None and due.astimezone(SEOUL).date() <= today + timedelta(days=1),
                action=action,
            )
        )
    return VendorTodayData(date=today, rows=rows)


# ---- 도구 ----


class BriefIn(BaseModel):
    visit_ref: str | None = None


@tool(
    "request_brief",
    surface="vendor",
    kind="read",
    status="요청을 정리하고 있어요",
    description="실측 요청 하나를 요약해요: 집 · 희망 기간 · 우리 업체와 맞는지 · 가견적 · 빈 반나절. "
    "요청함 상태면 추천 기간 답하기 승인 카드도 만들어요. visit_ref를 비우면 지금 보는 요청이에요.",
    model=BriefIn,
    schema=obj({"visit_ref": REF}, required=[]),
)
async def request_brief(tc: ToolCtx, a: BriefIn) -> ToolOut:
    vid = _visit_id(tc, a.visit_ref)
    async with SessionLocal() as s:
        card, model, _, made, closed = await brief(
            s, tc.user, vid, tc.today, tc.now, tc.refs, tc.turn_id
        )
    return ToolOut(data=model, cards=[card], actions=made, closed=closed)


class FreeIn(BaseModel):
    visit_ref: str | None = None
    start: date | None = None
    end: date | None = None


@tool(
    "my_free_slots",
    surface="vendor",
    kind="read",
    status="빈 기간을 찾고 있어요",
    description="우리 업체의 빈 반나절로 답할 기간 후보(w1~w3)를 찾아요. 기간을 비우면 고객 희망 기간이에요.",
    model=FreeIn,
    schema=obj(
        {
            "visit_ref": REF,
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
        },
        required=[],
    ),
)
async def my_free_slots(tc: ToolCtx, a: FreeIn) -> ToolOut:
    from app.calc import slots
    from app.refprice.holidays import days_off
    from app.visit import service as visit_service

    vid = _visit_id(tc, a.visit_ref)
    async with SessionLocal() as s:
        d = await visit_service.vendor_visit(s, tc.user, vid, tc.today)
        lo = a.start or d.wish_start or tc.today + timedelta(days=1)
        hi = a.end or d.wish_end or lo + timedelta(days=13)
        if hi < lo or (hi - lo).days > slots.SPAN_MAX:
            raise ToolError(
                "bad_range", "기간은 시작일부터 끝나는 날까지 62일 안으로 다시 골라 주세요."
            )
        free = await open_halves(s, tc.user.id, lo, hi)
    wins = slots.best_windows(free, lo, hi, tc.today, days_off=days_off(lo, hi))
    out = []
    for w in wins:
        ref = tc.refs.put(
            "window",
            {
                "visit_id": str(vid),
                "start": w.start.isoformat(),
                "end": w.end.isoformat(),
                "excluded": [x.isoformat() for x in w.excluded],
                "open_count": w.open_count,
            },
        )
        out.append(
            {
                "ref": ref,
                "start": w.start,
                "end": w.end,
                "excluded": w.excluded,
                "open_count": w.open_count,
            }
        )
    return ToolOut(data={"windows": out, "count": len(out), "status": d.status})


class CheckIn(BaseModel):
    visit_ref: str | None = None


@tool(
    "quote_checklist",
    surface="vendor",
    kind="read",
    status="견적서 체크리스트를 만들고 있어요",
    description="실측 뒤 견적서를 보내기 전 확인할 것: 이 집 표준견적서 줄 · 내 견적서 칸 · 빠지기 쉬운 항목.",
    model=CheckIn,
    schema=obj({"visit_ref": REF}, required=[]),
)
async def quote_checklist(tc: ToolCtx, a: CheckIn) -> ToolOut:
    vid = _visit_id(tc, a.visit_ref)
    async with SessionLocal() as s:
        card, model, _ = await checklist(s, tc.user, vid, tc.today, tc.refs)
    return ToolOut(data=model, cards=[card])


class NoArgs(BaseModel):
    pass


def date_candidates(job, deal_id: uuid.UUID, today: date) -> list[dict]:
    """공사 날 후보 둘(job_for 결과): 견적서 공사 기간 · 예상 공정표 시작일로 계산 엔진(calc.schedule.free_blocks)이
    고른 일하는 날. 같은 업체의 다른 공사로 찬 날(job.busy_days: 수락한 날 · 낸 날)이 끼지 않게 잇고, 둘째 후보는
    첫 후보 일주일 뒤부터예요(1년 안). 값은 이름표(days) 값 꼴 {deal_id, start, days, crew}.
    my_jobs · 먼저 말 걸기(deal_confirmed) · 오늘 할 일이 같이 쓴다."""
    from app.calc.schedule import WEEKEND, free_blocks
    from app.refprice.holidays import days_off
    from app.schedule.service import AHEAD_DAYS

    count = max(job.quote.days or job.need.days, 1)
    weekend = () if job.weekend_work else WEEKEND
    base = max(job.plan_start or today, today) + timedelta(days=1)
    last = today + timedelta(days=AHEAD_DAYS)
    blocks = free_blocks(base, count, 2, job.busy_days, days_off(base, last), weekend, until=last)
    return [
        {
            "deal_id": str(deal_id),
            "start": picked[0].isoformat(),
            "days": [x.isoformat() for x in picked],
            "crew": job.need.crew,
        }
        for picked in blocks
    ]


@tool(
    "my_jobs",
    surface="vendor",
    kind="read",
    status="할 일을 보고 있어요",
    description="우리 업체의 할 일: 답할 요청 · 보낼 견적서 · 공사 날짜를 낼 공사. 공사 날짜 후보(n1…)도 줘요.",
    model=NoArgs,
    schema=obj({}),
)
async def my_jobs(tc: ToolCtx, _: NoArgs) -> ToolOut:
    from app.schedule import service as schedule_service

    async with SessionLocal() as s:
        todo = (await schedule_service.vendor_inbox(s, tc.user, "todo", tc.today, None, 20)).items
        jobs = (await schedule_service.vendor_inbox(s, tc.user, "jobs", tc.today, None, 20)).items
        requests = [
            {
                "ref": tc.refs.put("visit", {"id": str(r.id), "trade": r.trade}),
                "status": r.status,
                "area": r.area_label or r.area_name,
                "next": r.next.label if r.next else None,
                "due_at": r.next.due_at if r.next else None,
            }
            for r in todo[:10]
        ]
        deals = []
        for r in jobs[:5]:
            if r.deal_id is None:
                continue
            ref = tc.refs.put("deal", {"id": str(r.deal_id), "trade": r.trade})
            row: dict = {
                "ref": ref,
                "trade": r.trade,
                "area": r.area_label or r.area_name,
                "dates_state": r.dates_state,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "due_at": r.dates_due_at,
            }
            if r.dates_state in ("waiting", "requested", "change_requested"):
                from app.assistant.tools import aftercare as aftercare_tools

                job = await schedule_service.job_for(s, tc.user, r.deal_id, tc.today)
                # 고객의 날짜 요청이 열려 있으면 고객이 고른 시작일 후보(먼저 말 걸기 dates_requested와 같은 길)
                got = (
                    aftercare_tools.request_candidates(job, r.deal_id, tc.today)
                    if job.request is not None
                    else date_candidates(job, r.deal_id, tc.today)
                )
                cands = []
                for c in got:
                    picked = [date.fromisoformat(x) for x in c["days"]]
                    nref = tc.refs.put("days", c)
                    cands.append(
                        {"ref": nref, "start": picked[0], "end": picked[-1], "days": picked}
                    )
                count = max(job.quote.days or job.need.days, 1)
                row.update(candidates=cands, crew=job.need.crew, days_needed=count)
            deals.append(row)
    return ToolOut(data={"requests": requests, "deals": deals, "count": len(requests) + len(deals)})
