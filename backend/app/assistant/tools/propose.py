"""제안 도구 (계약서 5장): 대기 행동 행만 만든다. 실행은 사람이 승인 카드를 눌러야 actions.execute가 한다.

- 대상은 ref로만 받고 코드가 id로 푼다(모르는 ref는 unknown_ref). 금액 · 날짜 · 판은 기능 service 값이다.
- 제안할 수 없는 상태(잠김 · 견적서 없음 · 겹침 …)는 도구 오류로 돌려준다(행을 만들지 않음).
- 같은 대상의 열린 제안은 하나: 새로 만들면 옛 것은 만료(replaced)되고 그 action 이벤트도 보낸다.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.assistant import actions
from app.assistant.schemas import ActionSummary, AmountRow, LinkOut, SummaryRow
from app.assistant.tools import ToolCtx, ToolError, ToolOut, cards, obj, tool
from app.assistant.tools.customer import TRADE, pid_of
from app.db import SessionLocal
from app.shared.errors import AppError

REF = {"type": "string", "description": "도구 결과에 나온 이름표"}
HALF = {"am": "오전", "pm": "오후"}
FIELD_LABEL = {
    "area_m2": "면적(㎡)",
    "area_basis": "면적 기준",
    "occupied": "사는 중",
    "grade": "벽지",
    "rooms": "방 개수",
    "start_date": "공사 시작 희망",
    "demolition": "철거 범위",
}


def _show(key: str, v) -> str:
    from app.calc.dobae import DEMOLITION

    if v is None:
        return "없음"
    if key == "area_basis":
        return cards.BASIS.get(v, v)
    if key == "grade":
        return cards.GRADE.get(v, v)
    if key == "occupied":
        return "살면서 공사" if v else "빈 집"
    if key == "demolition":
        return DEMOLITION.get(v, v)
    return str(v)


async def _offer(tc: ToolCtx, **kw) -> tuple[ToolOut, dict]:
    """행동 행을 만들고 commit한다. (도구 결과, 모델용 요약)"""
    async with SessionLocal() as s:
        row, closed = await actions.propose(
            s, tc.user, surface=tc.surface, now=tc.now, turn_id=tc.turn_id, **kw
        )
        await s.commit()
    a = actions.out(row)
    model = {
        "proposed": a.status == "proposed",
        "kind": a.kind,
        "summary": {"title": a.summary.title, "approve_label": a.summary.approve_label},
        "expires_at": a.expires_at,
        "note": "승인 카드를 만들었어요. 고객이 버튼을 눌러야 실행돼요.",
    }
    return ToolOut(data=model, actions=[a], closed=[actions.out(c) for c in closed]), model


# ---- 고객 ----


class HomeFields(BaseModel):
    area_m2: Decimal | None = Field(default=None, gt=10, lt=400, decimal_places=1)
    area_basis: Literal["supply", "exclusive"] | None = None
    occupied: bool | None = None
    grade: Literal["economy", "basic"] | None = None
    rooms: int | None = Field(default=None, ge=1, le=5)
    start_date: date | None = None
    demolition: Literal["full", "partial", "none"] | None = None  # 모은 조건(집 정보 칸 아님)


class HomeIn(BaseModel):
    fields: HomeFields


@tool(
    "propose_home_info",
    surface="customer",
    kind="propose",
    status="집 정보 저장을 준비하고 있어요",
    description="고객이 말한 집 정보(면적 · 면적 기준 · 사는 중 · 벽지 · 방 개수 · 공사 시작 희망 · 철거 범위) "
    "바뀜을 승인 카드로 만들어요. 고객이 말한 칸만 넣어요. 실측을 요청한 뒤에는 고칠 수 없어요. "
    "철거 범위는 전체 철거(full) · 부분 철거(partial) · 철거 안 함(none)이고, 전체 철거면 표준견적서가 "
    "리모델링 기준으로 바뀌어요.",
    model=HomeIn,
    schema=obj(
        {
            "fields": obj(
                {
                    "area_m2": {"type": "number", "description": "㎡, 소수 한 자리"},
                    "area_basis": {"type": "string", "enum": ["supply", "exclusive"]},
                    "occupied": {"type": "boolean"},
                    "grade": {"type": "string", "enum": ["economy", "basic"]},
                    "rooms": {"type": "integer"},
                    "start_date": {"type": "string", "format": "date"},
                    "demolition": {
                        "type": "string",
                        "enum": ["full", "partial", "none"],
                        "description": "철거 범위: full 전체 · partial 부분 · none 안 함",
                    },
                },
                required=[],
            )
        }
    ),
)
async def propose_home_info(tc: ToolCtx, a: HomeIn) -> ToolOut:
    from app.calc.dobae import DEMOLITION_KEY
    from app.project import service as project_service
    from app.project.schemas import HomeInfoIn, check_home

    pid = pid_of(tc)
    async with SessionLocal() as s:
        p = await project_service.get_for(s, tc.user, pid)
        card, _ = await cards.home(s, tc.user, pid)
    if p.locked:
        raise ToolError("locked", "실측을 요청한 뒤라 집 정보를 고칠 수 없어요.")
    if p.home is None:
        raise ToolError("no_home", "이 공사는 집 정보 화면에서 고쳐 주세요.")
    now_home = p.home.model_dump(mode="json")  # 철거 범위(모은 조건)도 들어 있다
    home_now = {k: v for k, v in now_home.items() if k != DEMOLITION_KEY}
    asked = a.fields.model_dump(exclude_none=True, mode="json")
    changes = {k: v for k, v in asked.items() if str(now_home.get(k)) != str(v)}
    if not changes:
        raise ToolError("no_change", "바뀐 칸이 없어요.")
    home_changes = {k: v for k, v in changes.items() if k != DEMOLITION_KEY}
    if home_changes:  # 철거 범위만 바꾸면 집 정보는 그대로라 다시 검사하지 않는다
        try:
            merged = HomeInfoIn.model_validate({**home_now, **home_changes})
            check_home(merged, tc.today)
        except (ValidationError, AppError) as e:
            raise ToolError("bad_input", "집 정보 칸을 다시 확인해 주세요.") from e
    rows = [
        SummaryRow(label=FIELD_LABEL[k], value=_show(k, v), sub=f"지금 {_show(k, now_home.get(k))}")
        for k, v in changes.items()
    ]
    out, _ = await _offer(
        tc,
        kind="home_info",
        target_kind="project",
        target_id=pid,
        target_ver=str(p.rev),
        payload={"fields": changes},
        summary=ActionSummary(
            title="집 정보 저장",
            rows=rows,
            note="저장하면 표준견적서를 리모델링 기준으로 새로 계산해요"
            if changes.get(DEMOLITION_KEY) == "full"
            else "저장하면 표준견적서를 새로 계산해요",
            approve_label="맞아요, 저장",
        ),
        expires_at=tc.now + timedelta(days=7),
        project_id=pid,
    )
    card.data = {
        **card.data,
        "changes": [
            {"label": FIELD_LABEL[k], "before": _show(k, now_home.get(k)), "after": _show(k, v)}
            for k, v in changes.items()
        ],
        "action_id": str(out.actions[0].action_id),
    }
    card.say = "이 집 정보가 맞는지 확인해 주세요."
    out.cards.append(card)
    return out


class VisitReqIn(BaseModel):
    trade: Literal["dobae", "mokgong"] = "dobae"
    vendor_refs: list[str] = Field(min_length=1, max_length=3)
    wish_ref: str | None = None


@tool(
    "propose_visit_request",
    surface="customer",
    kind="propose",
    status="실측 요청을 준비하고 있어요",
    description="고른 업체(v1…, 1~3곳)에 보낼 실측 요청을 승인 카드로 만들어요. 희망 기간은 wish_ref(r1…)이고, "
    "비우면 믿집 초안(공사 시작 희망일 − 28 ~ − 14일)이에요.",
    model=VisitReqIn,
    schema=obj(
        {
            "trade": TRADE,
            "vendor_refs": {"type": "array", "items": REF, "description": "업체 이름표 1~3개"},
            "wish_ref": REF,
        },
        required=["trade", "vendor_refs"],
    ),
)
async def propose_visit_request(tc: ToolCtx, a: VisitReqIn) -> ToolOut:
    from app.calc import slots
    from app.project import service as project_service
    from app.visit import service as visit_service

    pid = pid_of(tc)
    picked = {tc.refs.get(r, "vendor")["id"]: r for r in a.vendor_refs}
    async with SessionLocal() as s:
        p = await project_service.get_for(s, tc.user, pid)
        lst = await visit_service.vendors_for(s, tc.user, pid, a.trade)
    cards_by_id = {str(c.vendor_id): c for c in (*lst.local, *lst.nearby)}
    rows = []
    for vid in picked:
        c = cards_by_id.get(vid)
        if c is None or c.state != "ok" or c.estimate_total is None:
            raise ToolError("unavailable", "고른 업체 중 지금 요청할 수 없는 곳이 있어요.")
        rows.append(c)
    if a.wish_ref is not None:
        w = tc.refs.get(a.wish_ref, "wish")
        start, end = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
    else:
        start, end = slots.draft_wish(visit_service.work_start(p), tc.today) or (
            tc.today + timedelta(days=1),
            tc.today + timedelta(days=14),
        )
    if start <= tc.today:
        raise ToolError("past", "희망 기간이 지났어요. 시간 후보를 다시 찾아 주세요.")
    summary = ActionSummary(
        title="실측 요청 보내기",
        amounts=[AmountRow(label=c.name, won=c.estimate_total) for c in rows],
        rows=[
            SummaryRow(label="희망 기간", value=f"{start.isoformat()} ~ {end.isoformat()}"),
            SummaryRow(label="가견적", value="업체가 확인한 단가로 고정돼요"),
        ],
        note="업체마다 48시간 안에 갈 수 있는 기간을 답해요. 연락은 믿집 채팅으로 이어져요",
        approve_label=f"{len(rows)}곳에 요청 보내기",
    )
    out, _ = await _offer(
        tc,
        kind="visit_request",
        target_kind="project",
        target_id=pid,
        target_ver=str(p.rev),
        payload={
            "trade": a.trade,
            "vendor_ids": [str(c.vendor_id) for c in rows],
            "wish_start": start.isoformat(),
            "wish_end": end.isoformat(),
        },
        summary=summary,
        expires_at=tc.now + timedelta(days=3),
        project_id=pid,
    )
    return out


class SlotIn(BaseModel):
    slot_ref: str


def slot_offer(v, slot: dict) -> dict:
    """반나절 하나(pick_view 결과 v · 이름표 값 slot) → 대기 행동 인자. 도구 · 먼저 말 걸기가 같이 쓴다.
    고를 수 있는 때가 아니면 ToolError(stale)."""
    via = slot["via"]
    if via == "proposal":
        if v.status != "proposed" or v.proposal is None:
            raise ToolError("stale", "업체가 낸 날이 바뀌었어요. 시간 후보를 다시 찾아 주세요.")
        due, instant, ver = v.proposal.due_at, True, "업체가 낸 날"
    else:
        if v.status != "offered" or v.window is None:
            raise ToolError("stale", "고를 수 있는 때가 아니에요. 시간 후보를 다시 찾아 주세요.")
        w = v.window
        due, instant = w.pick_due_at, w.instant
        ver = f"업체가 답한 기간 {w.start.isoformat()} ~ {w.end.isoformat()}"
    day = date.fromisoformat(slot["day"])
    summary = ActionSummary(
        title=f"{v.vendor_name} 실측 {day.isoformat()} {HALF[slot['half']]}",
        version=ver,
        rows=[
            SummaryRow(
                label="그 뒤 일",
                value="고르면 바로 확정돼요" if instant else "업체가 수락하면 확정돼요",
            )
        ],
        note="시각은 실측 전날 채팅으로 정해요",
        approve_label="이 시간으로 고르기",
    )
    return {
        "kind": "visit_slot",
        "target_kind": "visit",
        "target_id": v.visit_id,
        "target_ver": v.status,
        "payload": {
            "visit_id": str(v.visit_id),
            "day": slot["day"],
            "half": slot["half"],
            "via": via,
            "instant": instant,
        },
        "summary": summary,
        "expires_at": due,
    }


@tool(
    "propose_visit_slot",
    surface="customer",
    kind="propose",
    status="실측 시간을 준비하고 있어요",
    description="반나절 후보(s1…) 하나를 고르는 승인 카드를 만들어요.",
    model=SlotIn,
    schema=obj({"slot_ref": REF}),
)
async def propose_visit_slot(tc: ToolCtx, a: SlotIn) -> ToolOut:
    from app.visit import service as visit_service

    pid = pid_of(tc)
    slot = tc.refs.get(a.slot_ref, "slot")
    visit_id = uuid.UUID(slot["visit_id"])
    async with SessionLocal() as s:
        v = await visit_service.pick_view(s, tc.user, pid, visit_id, tc.now)
    out, _ = await _offer(tc, project_id=pid, **slot_offer(v, slot))
    return out


class VisitRefIn(BaseModel):
    visit_ref: str


@tool(
    "propose_vendor_confirm",
    surface="customer",
    kind="propose",
    status="업체 확정을 준비하고 있어요",
    description="견적서를 받은 업체(m1…) 하나로 확정하는 승인 카드를 만들어요. 지금 견적서 판으로 고정되고, "
    "업체가 새 판을 보내면 그 카드는 실행되지 않아요.",
    model=VisitRefIn,
    schema=obj({"visit_ref": REF}),
)
async def propose_vendor_confirm(tc: ToolCtx, a: VisitRefIn) -> ToolOut:
    from app.visit import service as visit_service

    pid = pid_of(tc)
    ref = tc.refs.get(a.visit_ref, "visit")
    visit_id = uuid.UUID(ref["id"])
    trade = ref.get("trade") or "dobae"
    async with SessionLocal() as s:
        cmp = await visit_service.compare(s, tc.user, pid, trade, tc.today)
    row = next((r for r in cmp.vendors if r.visit_id == visit_id), None)
    if row is None or row.latest is None or row.status != "quoted" or row.seen_ver is None:
        raise ToolError("not_quoted", "아직 확정할 수 있는 견적서가 없어요.")
    if row.expired:
        raise ToolError("expired", "견적서 유효기간이 지났어요. 다시 받기를 요청해 주세요.")
    q = row.latest
    summary = actions.confirm_summary(row.vendor_name, q.version, q.total, q.days, q.valid_until)
    summary.file = LinkOut(label="견적서 보기", href=cards.href(pid, "/quotes"))
    out, _ = await _offer(
        tc,
        kind="vendor_confirm",
        target_kind="visit",
        target_id=visit_id,
        target_ver=str(row.seen_ver),
        payload={
            "visit_id": str(visit_id),
            "trade": trade,
            "vendor_name": row.vendor_name,
            "version": q.version,
        },
        summary=summary,
        expires_at=actions.confirm_expiry(q.valid_until, tc.now),
        project_id=pid,
    )
    return out


class ProposalIn(BaseModel):
    proposal_ref: str


def dates_offer(sch, proposal_id: str, kind: str, now) -> dict:
    """공사 날짜 제안 하나(schedule_for 결과 sch) → 수락 대기 행동 인자. 도구 · 먼저 말 걸기가 같이 쓴다.
    바뀌었으면 ToolError(stale), 다른 공정과 겹치면 ToolError(conflict)."""
    t = next(
        (x for x in sch.trades if x.proposal is not None and str(x.proposal.id) == proposal_id),
        None,
    )
    if t is None or t.proposal is None or t.proposal.status != "pending":
        raise ToolError("stale", "날짜가 바뀌었어요. 공사 날짜를 다시 봐 주세요.")
    if t.fit is not None and t.fit.conflicts:
        raise ToolError(
            "conflict", "다른 공정과 겹쳐서 수락할 수 없어요. 다른 날짜를 요청해 주세요."
        )
    x = t.proposal
    name = cards.TRADE.get(t.deal.trade, t.deal.trade)
    summary = ActionSummary(
        title=f"{name} {x.start.isoformat()} ~ {x.end.isoformat()} 수락",
        version=f"공정표 {sch.final_version}판" if sch.final_version else "첫 공사 날짜",
        rows=[
            SummaryRow(label="업체", value=t.deal.vendor_name),
            SummaryRow(label="일하는 날", value=f"{x.workdays}일"),
        ],
        note="수락하면 확정 공정표가 만들어져요"
        if kind == "dates_accept"
        else "수락하면 공정표가 바뀐 날짜로 다시 짜여요",
        approve_label="이 날짜로 수락",
    )
    return {
        "kind": kind,
        "target_kind": "proposal",
        "target_id": x.id,
        "target_ver": str(sch.final_version),
        "payload": {"deal_id": str(t.deal.id), "proposal_id": str(x.id)},
        "summary": summary,
        "expires_at": now + timedelta(days=2),
    }


def dates_kind(deal_status: str) -> Literal["dates_accept", "delay_accept"]:
    """수락한 뒤(scheduled) 바뀐 날짜면 연기 수락, 아니면 첫 날짜 수락."""
    return "delay_accept" if deal_status == "scheduled" else "dates_accept"


async def _dates(tc: ToolCtx, a: ProposalIn, kind: Literal["dates_accept", "delay_accept"]):
    from app.schedule import service as schedule_service

    pid = pid_of(tc)
    pr = tc.refs.get(a.proposal_ref, "proposal")
    want = "delay" if kind == "delay_accept" else "dates"
    if pr.get("type") != want:
        other = "propose_delay_accept" if want == "dates" else "propose_dates_accept"
        raise ToolError("wrong_kind", f"이 날짜는 {other}로 제안해 주세요.")
    async with SessionLocal() as s:
        sch = await schedule_service.schedule_for(s, tc.user, pid, tc.today)
    out, _ = await _offer(tc, project_id=pid, **dates_offer(sch, pr["id"], kind, tc.now))
    return out


@tool(
    "propose_dates_accept",
    surface="customer",
    kind="propose",
    status="공사 날짜 수락을 준비하고 있어요",
    description="업체가 처음 올린 공사 날짜(p1…)를 수락하는 승인 카드를 만들어요.",
    model=ProposalIn,
    schema=obj({"proposal_ref": REF}),
)
async def propose_dates_accept(tc: ToolCtx, a: ProposalIn) -> ToolOut:
    return await _dates(tc, a, "dates_accept")


@tool(
    "propose_delay_accept",
    surface="customer",
    kind="propose",
    status="바뀐 날짜 수락을 준비하고 있어요",
    description="이미 수락한 공사의 바뀐(연기된) 날짜(p1…)를 수락하는 승인 카드를 만들어요.",
    model=ProposalIn,
    schema=obj({"proposal_ref": REF}),
)
async def propose_delay_accept(tc: ToolCtx, a: ProposalIn) -> ToolOut:
    return await _dates(tc, a, "delay_accept")


# ---- 업체 ----


def _vendor_visit_id(tc: ToolCtx, ref: str) -> uuid.UUID:
    return uuid.UUID(tc.refs.get(ref, "visit")["id"])


class WindowAnswerIn(BaseModel):
    visit_ref: str
    window_ref: str


@tool(
    "propose_window_answer",
    surface="vendor",
    kind="propose",
    status="기간 답하기를 준비하고 있어요",
    description="요청(m1…)에 기간 후보(w1…)로 답하는 승인 카드를 만들어요.",
    model=WindowAnswerIn,
    schema=obj({"visit_ref": REF, "window_ref": REF}),
)
async def propose_window_answer(tc: ToolCtx, a: WindowAnswerIn) -> ToolOut:
    from app.visit import service as visit_service

    visit_id = _vendor_visit_id(tc, a.visit_ref)
    w = tc.refs.get(a.window_ref, "window")
    if w.get("visit_id") != str(visit_id):
        raise ToolError("mismatch", "이 요청의 기간 후보가 아니에요. 빈 기간을 다시 찾아 주세요.")
    async with SessionLocal() as s:
        d = await visit_service.vendor_visit(s, tc.user, visit_id, tc.today)
    if d.status != "requested":
        raise ToolError("stale", "이미 답했거나 닫힌 요청이에요.")
    instant = bool(d.instant_default)
    summary = ActionSummary(
        title="이 기간으로 답하기",
        rows=[
            SummaryRow(label="기간", value=f"{w['start']} ~ {w['end']}"),
            SummaryRow(label="빼는 날", value=", ".join(w.get("excluded") or []) or "없음"),
            SummaryRow(label="빈 반나절", value=f"{w.get('open_count', 0)}칸"),
            SummaryRow(label="바로 확정", value="켜요" if instant else "꺼요"),
        ],
        note="답하면 고객이 그 기간에서 반나절을 골라요",
        approve_label="이 기간으로 답하기",
    )
    due = d.reply_due_at if d.reply_due_at and d.reply_due_at > tc.now else None
    out, _ = await _offer(
        tc,
        kind="window_answer",
        target_kind="visit",
        target_id=visit_id,
        target_ver=d.status,
        payload={
            "visit_id": str(visit_id),
            "start": w["start"],
            "end": w["end"],
            "excluded": list(w.get("excluded") or []),
            "instant": instant,
        },
        summary=summary,
        expires_at=due,
    )
    return out


class DeclineIn(BaseModel):
    visit_ref: str
    code: Literal["full", "out_of_area", "other"]


DECLINE = {"full": "일정이 꽉 찼어요", "out_of_area": "지역 밖이에요", "other": "그 밖의 까닭"}


@tool(
    "propose_decline",
    surface="vendor",
    kind="propose",
    status="못 받아요를 준비하고 있어요",
    description="요청(m1…)을 못 받는다고 알리는 승인 카드를 만들어요. code: full 일정 꽉 참 · "
    "out_of_area 지역 밖 · other 그 밖.",
    model=DeclineIn,
    schema=obj({"visit_ref": REF, "code": {"type": "string", "enum": list(DECLINE)}}),
)
async def propose_decline(tc: ToolCtx, a: DeclineIn) -> ToolOut:
    from app.visit import service as visit_service

    visit_id = _vendor_visit_id(tc, a.visit_ref)
    async with SessionLocal() as s:
        d = await visit_service.vendor_visit(s, tc.user, visit_id, tc.today)
    if d.status not in ("requested", "offered", "picked", "proposed", "booked", "visited"):
        raise ToolError("stale", "이미 닫혔거나 견적서를 보낸 요청이에요.")
    summary = ActionSummary(
        title="이번 요청 못 받아요",
        rows=[SummaryRow(label="까닭", value=DECLINE[a.code])],
        note="고객에게 까닭이 보이고 고객의 담기 칸이 비어요",
        approve_label="못 받는다고 알리기",
    )
    out, _ = await _offer(
        tc,
        kind="decline",
        target_kind="visit",
        target_id=visit_id,
        target_ver=d.status,
        payload={"visit_id": str(visit_id), "code": a.code},
        summary=summary,
        expires_at=tc.now + timedelta(days=2),
    )
    return out


class DatesPropose(BaseModel):
    deal_ref: str
    days_ref: str


def vendor_dates_offer(job, deal_id: uuid.UUID, days: dict, now) -> dict:
    """공사 날 후보 하나(job_for 결과 job · 이름표 값 days) → 공사 날짜 보내기 대기 행동 인자.
    도구 · 먼저 말 걸기가 같이 쓴다. 지금 낼 수 없으면 ToolError(stale)."""
    if job.dates_state not in ("waiting", "requested", "proposed"):
        raise ToolError("stale", "지금은 공사 날짜를 낼 수 없어요. 공사 화면에서 확인해 주세요.")
    picked = [date.fromisoformat(x) for x in days["days"]]
    summary = ActionSummary(
        title=f"공사 날짜 {picked[0].isoformat()} ~ {picked[-1].isoformat()} 보내기",
        rows=[
            SummaryRow(label="일하는 날", value=f"{len(picked)}일"),
            SummaryRow(label="하루 인원", value=f"{days['crew']}명"),
        ],
        note="고객이 수락하면 확정 공정표가 만들어져요",
        approve_label="이 날짜로 보내기",
    )
    due = job.dates_due_at if job.dates_due_at > now else now + timedelta(days=2)
    return {
        "kind": "dates",
        "target_kind": "deal",
        "target_id": deal_id,
        "target_ver": job.dates_state,
        "payload": {"deal_id": str(deal_id), "days": days["days"], "crew": days["crew"]},
        "summary": summary,
        "expires_at": due,
    }


@tool(
    "propose_dates",
    surface="vendor",
    kind="propose",
    status="공사 날짜 보내기를 준비하고 있어요",
    description="확정된 공사(d1…)에 공사 날 후보(n1…)를 보내는 승인 카드를 만들어요.",
    model=DatesPropose,
    schema=obj({"deal_ref": REF, "days_ref": REF}),
)
async def propose_dates(tc: ToolCtx, a: DatesPropose) -> ToolOut:
    from app.schedule import service as schedule_service

    deal = tc.refs.get(a.deal_ref, "deal")
    days = tc.refs.get(a.days_ref, "days")
    if days.get("deal_id") != deal["id"]:
        raise ToolError("mismatch", "이 공사의 날짜 후보가 아니에요. 할 일을 다시 봐 주세요.")
    deal_id = uuid.UUID(deal["id"])
    async with SessionLocal() as s:
        job = await schedule_service.job_for(s, tc.user, deal_id, tc.today)
    out, _ = await _offer(tc, **vendor_dates_offer(job, deal_id, days, tc.now))
    return out
