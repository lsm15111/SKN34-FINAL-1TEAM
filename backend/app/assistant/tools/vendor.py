"""업체 비서 읽기 도구 (계약서 5장): request_brief · my_free_slots · quote_checklist · my_jobs.

- 요청은 vendor_visit(내 요청이 아니면 404)으로만 연다. 고객 이름 · 연락처 · 동호수는 오지 않는다.
- 고객이 남긴 말 · 사진 이름표는 자료 상자(policy.data)로만 넘긴다.
- REST(GET /vendor/assistant/briefs · checklists · today)도 같은 함수(brief · checklist · vendor_today)를 쓴다.
"""

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

if TYPE_CHECKING:
    from app.assistant.runtime import RefTable

REF = {"type": "string", "description": "도구 결과에 나온 이름표"}
VAT = {"included": "부가세 포함", "excluded": "부가세 별도", "exempt": "면세"}


async def open_halves(s: AsyncSession, vendor_id: uuid.UUID, start: date, end: date):
    """업체 빈 반나절(도메인 담당 visit.service.open_halves_for: 날 → ["am", "pm"]). 아직 없으면 None."""
    from app.visit import service as visit_service

    fn = getattr(visit_service, "open_halves_for", None)
    return None if fn is None else await fn(s, vendor_id, start, end)


def _visit_id(tc: ToolCtx, ref: str | None) -> uuid.UUID:
    if ref:
        return uuid.UUID(tc.refs.get(ref, "visit")["id"])
    if tc.visit_id is None:
        raise ToolError("no_visit", "어느 요청인지 몰라요. my_jobs로 요청을 먼저 찾아 주세요.")
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
) -> tuple[CardOut, dict, VendorBriefData, list[ActionOut], list[ActionOut]]:
    """새 요청 브리핑(UC-V1): 요약 · 맞음 여부(공정 · 지역 · 일정 · 벽지) · 가견적(요청 때 고정한 값) ·
    빈 반나절 · 추천 응답(기간 초안 → window_answer 제안 행, 요청함 상태일 때만).
    돌려주는 값: (카드, 모델용 값, 브리핑 data, 새 제안, 닫힌 제안)."""
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
    fit = [
        FitRow(key="trade", label="공정", ok=d.trade in prof.trades, text=f"{trade} 요청"),
        FitRow(key="area", label="지역", ok=in_area, text=d.region),
        FitRow(
            key="schedule",
            label="일정",
            ok=(d.open_count or 0) > 0,
            text=f"고객 희망 {start.isoformat()} ~ {end.isoformat()} · 빈 반나절 {d.open_count or 0}칸",
        ),
    ]
    if d.trade == "dobae":
        fit.append(
            FitRow(key="paper", label="벽지", ok=grade is not None, text=grade or "벽지 미정")
        )
    suggest: BriefSuggest | None = None
    made: list[ActionOut] = []
    closed: list[ActionOut] = []
    free = await open_halves(s, vendor.id, start, end) if d.status == "requested" else None
    wins = slots.best_windows(free, start, end, today, days_off=off) if free is not None else []
    if wins:
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
        )
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
        due_at=d.reply_due_at,
        memo=policy.mask_in(d.message or "") or None,
    )
    card = CardOut(
        card_id=f"brief-{visit_id}", kind="vendor_brief", data=data.model_dump(mode="json")
    )
    model = {
        "ref": ref,
        "status": d.status,
        "title": data.title,
        "facts": facts,
        "fit": [{"label": f.label, "ok": f.ok, "text": f.text} for f in fit],
        "estimate_won": d.estimate_total,
        "open_count": d.open_count,
        "due_at": d.reply_due_at,
        "memo": policy.data(d.message),
        "proposed": bool(made),
    }
    return card, model, data, made, closed


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
            label=ln.name,
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


async def vendor_today(s: AsyncSession, vendor: User, today: date) -> VendorTodayData:
    """업체 작업함 맨 위 '오늘 브리핑': 새 요청 · 오늘 실측 · 보낼 견적서(줄은 코드가 고른다)."""
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
            raise ToolError("bad_range", "기간을 62일 안으로 다시 골라 주세요.")
        free = await open_halves(s, tc.user.id, lo, hi)
    if free is None:
        raise ToolError("not_ready", "빈 시간을 아직 볼 수 없어요.")
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
    from app.calc.schedule import WEEKEND, workdays
    from app.refprice.holidays import days_off
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
            if r.dates_state in ("waiting", "requested"):
                job = await schedule_service.job_for(s, tc.user, r.deal_id, tc.today)
                count = max(job.quote.days or job.need.days, 1)
                weekend = () if job.weekend_work else WEEKEND
                base = max(job.plan_start or tc.today, tc.today) + timedelta(days=1)
                cands = []
                for start in (base, base + timedelta(days=7)):
                    off = days_off(start, start + timedelta(days=count * 3 + 14))
                    picked = workdays(start, count, off, weekend)
                    nref = tc.refs.put(
                        "days",
                        {
                            "deal_id": str(r.deal_id),
                            "start": picked[0].isoformat(),
                            "days": [x.isoformat() for x in picked],
                            "crew": job.need.crew,
                        },
                    )
                    cands.append(
                        {"ref": nref, "start": picked[0], "end": picked[-1], "days": picked}
                    )
                row.update(candidates=cands, crew=job.need.crew, days_needed=count)
            deals.append(row)
    return ToolOut(data={"requests": requests, "deals": deals, "count": len(requests) + len(deals)})
