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
    BriefPicked,
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
from app.assistant.tools.cards import GRADE, HALF, TRADE, seoul_text
from app.auth.models import User
from app.calc.common import COUNTED
from app.db import SessionLocal
from app.shared import kdate
from app.shared.clock import SEOUL
from app.shared.kdate import md_list, md_week
from app.shared.korean import i_ga

if TYPE_CHECKING:
    from app.assistant.runtime import RefTable

REF = {"type": "string", "description": "도구 결과에 나온 이름표"}
VAT = {"included": "부가세 포함", "excluded": "부가세 별도", "exempt": "면세"}
INSTANT = {
    True: "켜요 · 고객이 고르면 바로 잡혀요",
    False: "꺼요 · 고객이 고르면 한 번 더 수락해요",
}
INCL = {True: "포함", False: "빠짐"}  # 견적서 칸 철거 · 폐기물(비면 None)
FURNITURE = re.compile(r"가구|짐")
# 고객이 반나절을 고른 요청: 수락은 요청 화면 단추로만 해요(비서는 수락 승인 카드를 만들지 않아요)
PICKED_NOTE = "고객이 고른 반나절이에요. 요청 화면(요청 열기)에서 수락해 주세요."


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
    keep_open: bool | None = None,
    show_open: bool = False,
) -> tuple[CardOut, dict, VendorBriefData, list[ActionOut], list[ActionOut]]:
    """새 요청 브리핑(UC-V1): 요약 · 맞음 여부(공정 · 지역 · 일정 · 벽지: 맞음 · 확인 필요 · 맞지 않음) · 가견적(요청
    때 고정한 값) · 빈 반나절 · 답할 기간 후보(w…, 카드 단추 'window_answer:w…') · 추천 응답(첫 후보 →
    window_answer 제안 행, 요청함 상태일 때만) · 한 문장(틀). 공정이 맞지 않으면 기간 후보 · 제안을 만들지 않고 맞지
    않는 까닭만 보인다(못 받아요는 업체가 고른다). 지역은 고객이 이미 보낸 요청이라 막지 않고 서비스 지역 밖이면
    '확인 필요'로 보인다(가까운 구 업체로 간 요청, 리드 결정 D11). 칸 수는 카드에 보이는 하나(제안 기간의 칸)만 쓴다.
    AI 한 문장은 세션 밖에서 brief_sentence로 바꿔 끼운다. commit=False면 제안 행을 commit하지 않는다
    (먼저 말 걸기가 같은 트랜잭션에서 보낸다). propose_window=False면 제안을 만들지 않는다(무료 모드에서 답하기를
    말하지 않은 턴 · REST 읽기).
    keep_open: 이 요청에 열린 제안(종류 상관없이, 대화에서 고른 못 받아요 · 다른 기간 포함)이 있으면 새로 만들지 않고
    덮지 않는다(그 행이 기간 답하기면 그것을 보인다). 바꿔치기는 사람이 고른 턴(대화 · 단추)에서만 한다(리뷰 B3).
    None이면 먼저 말 걸기(origin nudge)만 켠다. show_open: 제안을 만들지 않을 때도 열린 기간 답하기 제안을 보인다
    (REST 읽기). 돌려주는 값: (카드, 모델용 값, 브리핑 data, 새 제안 · 다시 쓴 열린 제안, 닫힌 제안)."""
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
    wish = f"고객 희망 {kdate.md_range(start, end, today)}"
    has_open = (d.open_count or 0) > 0
    fit = [
        _fit("trade", "공정", d.trade in prof.trades, f"{trade} 요청"),
        _fit("area", "지역", True, d.region)
        if in_area
        else FitRow(
            key="area",
            label="지역",
            ok=False,
            text=f"{d.region} · {OUT_AREA}{NEAR if _near(d.region, prof.areas) else ''}",
            state="check",
        ),
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
    # 요청함: 답할 기간 후보(w…)를 카드에 둔다(무료 모드에서도 단추로 고르게). 공정이 맞지 않으면 두지 않는다
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
    keep = origin == "nudge" if keep_open is None else keep_open
    held: list = []
    if wins and propose_window and keep:
        from app.assistant import repository as repo

        await repo.lock_target(s, vendor.id, visit_id)  # 대화의 제안 만들기와 줄 선다(덮지 않게)
        held = await _open_on(s, vendor.id, visit_id, now)
    elif wins and show_open:
        held = await _open_on(s, vendor.id, visit_id, now)
    # 열린 제안을 덮지 않는다: 기간 답하기면 그 행을 보이고, 다른 종류(못 받아요 …)면 제안 없이
    if held:
        same = next((a for a in held if a.kind == "window_answer"), None)
        suggest = _suggest_of(same, wins) if same is not None else None
        if same is not None and propose_window:
            made = [actions.out(same)]
    elif wins and propose_window:
        w = wins[0]
        instant = bool(d.instant_default)
        summary = ActionSummary(
            title="이 기간으로 답하기",
            rows=[
                SummaryRow(label="기간", value=kdate.md_range(w.start, w.end, today)),
                SummaryRow(label="빈 반나절", value=f"{w.open_count}칸"),
                SummaryRow(label="바로 확정", value=INSTANT[instant]),
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
        facts.append(f"공사 시작 희망 {md_week(d.work_wish_on, today)}")
    if d.photos:
        facts.append(f"사진 {len(d.photos)}장")
    # 고객이 반나절을 골랐으면(업체 수락 차례) 그 날과 수락 기한 · 누를 곳(요청 화면)
    b = d.booked if d.status == "picked" else None
    picked = (
        BriefPicked(
            day=b.day, half=b.half, due_at=b.hold_until, href=f"/vendor/requests/{visit_id}"
        )
        if b is not None
        else None
    )
    if picked is not None:
        due = seoul_text(picked.due_at)
        facts.insert(
            0,
            f"고객이 고른 날 {md_week(b.day, today)} {HALF[b.half]}"
            + (f" · {due}까지 수락" if due else ""),
        )
    from app.assistant.tools import diy as diy_tools  # 반셀프: 요청 때 고정한 '고객이 직접 할 일'

    told = await diy_tools.told_labels(s, visit_id)
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
        # 답한 뒤에는 지난 답 기한을 두지 않아요
        due_at=d.reply_due_at if d.status == "requested" else None,
        memo=policy.mask_in(d.message or "") or None,
        diy=told,
        picked=picked,
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
        # 날짜 값(ISO): 화면 글은 '12.15(화)' 꼴이라 모델이 '12월 15일'로 말해도 문장 숫자 검사가 이 값으로 본다
        "wish_start": start,
        "wish_end": end,
        "work_wish_on": d.work_wish_on,
        "estimate_won": d.estimate_total,
        "due_at": seoul_text(data.due_at),  # 서울 시각 글(UTC를 그대로 읽지 않게)
        "picked": {
            "day": b.day,
            "half": HALF[b.half],
            "due_at": seoul_text(b.hold_until),
            "note": PICKED_NOTE,
        }
        if b is not None
        else None,
        "memo": policy.data(d.message),
        "diy": policy.data("고객이 직접 할 일: " + " · ".join(told)) if told else None,
        "proposed": bool(made),
        # 공정이 맞지 않음(무료 모드 답이 쓴다, 허용 칸이 아니라 모델 값에는 안 감)
        "misfit": misfit.label if misfit else None,
        "windows": [
            {"ref": w.ref, "start": w.start, "end": w.end, "open_count": w.open_count}
            for w in windows
        ],
    }
    return card, model, data, made, closed


# 맞지 않으면 기간 답하기를 권하지 않는 칸. 지역은 넣지 않는다: 고객이 이미 보낸 요청이라 서비스 지역 밖이어도
# 막지 않고 '확인 필요'로 보인다(이 집 구에 업체가 없으면 가까운 구 업체로 가요, 리드 결정 D11)
MISFIT_KEYS = ("trade",)
OUT_AREA = "서비스 지역 밖"
NEAR = "(가까운 구)"
CHECK_SAY = {  # 확인 필요 칸 → 브리핑 한 문장 틀
    "paper": "벽지 확인이 필요해요. 고객이 아직 정하지 않았어요.",
    "area": "서비스 지역 밖 요청이에요. 요청을 열어 확인해 주세요.",
}


def _fit(key, label: str, ok: bool, text: str) -> FitRow:
    return FitRow(key=key, label=label, ok=ok, text=text, state="ok" if ok else "no")


def _near(region: str, areas) -> bool:
    """업체 출장 지역에 이 집 구의 이웃 구(shared.regions.NEIGHBORS)가 있는지(가까운 구 업체로 간 요청)."""
    from app.shared.regions import NEIGHBORS, region_label

    for (sido, sgg), near in NEIGHBORS.items():
        if region_label(sido, sgg) == region:
            return any((a.sido, a.sgg) in near for a in areas)
    return False


async def _open_on(s: AsyncSession, vendor_id: uuid.UUID, visit_id: uuid.UUID, now: datetime):
    """이 요청에 열린 업체 제안(종류 상관없이, 기한 안). 대상마다 열린 제안은 하나다."""
    from app.assistant import repository as repo

    return [a for a in await repo.open_on(s, vendor_id, "visit", visit_id) if a.expires_at > now]


def _suggest_of(a, wins) -> BriefSuggest | None:
    """열린 기간 답하기 제안 → 추천 응답(지금 후보 기간과 같을 때만, 칸 수는 지금 값)."""
    p = a.payload or {}
    w = next(
        (
            x
            for x in wins
            if (x.start.isoformat(), x.end.isoformat()) == (p.get("start"), p.get("end"))
        ),
        None,
    )
    if w is None:
        return None
    return BriefSuggest(
        action_id=a.id,
        start=w.start,
        end=w.end,
        excluded=list(w.excluded),
        instant=bool(p.get("instant")),
        open_count=w.open_count,
    )


SENTENCE_MAX = 60
SENTENCE_TTL = 86400  # 같은 사실이면 하루 동안 같은 문장(Haiku를 다시 부르지 않는다)


class Sentence(BaseModel):
    text: str


def brief_template(data: VendorBriefData) -> str:
    """브리핑 한 문장 틀(코드 값만): 맞지 않는 것부터(공정이면 못 받아요로 답하는 길), 다 맞으면 답하기 좋은
    기간(카드의 제안 칸 수), 그다음 확인 필요(고객이 아직 정하지 않은 것 · 서비스 지역 밖)."""
    if data.picked is not None:  # 고객이 반나절을 골랐어요: 수락 차례
        p = data.picked
        half = f"{HALF[p.half]}{'을' if p.half == 'am' else '를'}"  # 오전을 · 오후를
        return f"고객이 {md_week(p.day)} {half} 골랐어요. 요청 화면에서 수락해 주세요."
    bad = next((f for f in data.fit if f.state == "no"), None)
    if bad is not None and bad.key in MISFIT_KEYS:
        return f"{i_ga(bad.label)} 우리 업체와 맞지 않아요. 받기 어려우면 못 받아요로 답해 주세요."
    if bad is not None:
        return f"{i_ga(bad.label)} 맞지 않아요. 요청을 열어 확인해 주세요."
    g = data.suggest
    if g is not None:
        days = kdate.md_range(g.start, g.end)
        return f"{days}에 빈 반나절 {g.open_count}칸이 있어 답하기 좋아요."
    check = next((f for f in data.fit if f.state == "check"), None)
    if check is not None:
        return CHECK_SAY.get(
            check.key, f"{check.label} 확인이 필요해요. 요청을 열어 확인해 주세요."
        )
    return "공정 · 지역 · 일정이 맞아요. 요청을 열어 확인해 주세요."


def _brief_facts(data: VendorBriefData) -> dict:
    """AI 한 문장에 넘길 사실: 카드에 보이는 값만(칸 수는 제안 기간 하나, 맞음은 세 갈래). 날짜 · 시각은 긴 꼴 글
    ('12월 7일(월)' · '11월 27일(금) 오후 6시'): 문장 검사(sentence_ok)가 월 · 일 · 시를 따로 본다."""
    g = data.suggest
    return {
        "title": data.title,
        "fit": [{"label": f.label, "state": f.state, "text": f.text} for f in data.fit],
        "suggest": {
            "start": kdate.md_long(g.start),
            "end": kdate.md_long(g.end),
            "open_count": g.open_count,
        }
        if g
        else None,
        "due": seoul_text(data.due_at),
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


async def brief_sentence(data: VendorBriefData, user_id: uuid.UUID, *, call: bool = True) -> str:
    """브리핑 AI 한 문장(Haiku, 같은 사실이면 하루 캐시). 못 부르거나 검사에 걸리면 틀(brief_template).
    call=False면 Haiku를 부르지 않고 캐시만 본다(REST 읽기 GET: 다른 사이트가 열어도 비용이 들지 않게)."""
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
    if not call:
        return brief_template(data)
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
            value=md_week(cur.valid_until) if cur and cur.valid_until else None,  # 화면 날짜 꼴
        ),
        # 고객 견적 비교 카드에 보이는 칸(철거 · 폐기물 · 하자 보증)도 같이 본다
        FieldValue(label="철거", value=INCL.get(cur.incl_removal) if cur else None),
        FieldValue(label="폐기물 처리", value=INCL.get(cur.incl_waste) if cur else None),
        FieldValue(
            label="하자 보증",
            value=f"{cur.warranty_months}개월" if cur and cur.warranty_months else None,
        ),
    ]
    cfg = TRADES.get(d.trade)  # type: ignore[call-overload]
    easy = [*cfg.cautions, *cfg.survey_vars, *cfg.prep] if cfg else []
    if not d.occupied:  # 빈 집이면 가구 · 짐 옮기기는 빼요
        easy = [x for x in easy if not FURNITURE.search(x)]
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
    missing = [f.label for f in fields if f.value is None]
    model = {
        "missing": missing,  # 비어 있는 칸(먼저 말할 것)
        "fields": [{"label": f.label, "value": f.value} for f in fields],
        # 유효기간 날짜 값(ISO): 칸 글은 '12.15(화)' 꼴이라 문장 숫자 검사가 이 값으로 본다
        "valid_until": cur.valid_until if cur else None,
        "items": [{"label": x.label} for x in items],
        "easy_miss": easy,
        "prev": data.prev.model_dump() if data.prev else None,
    }
    return card, model, data


# 공사 날짜를 낼 공사: 아직 안 냄 · 고객이 다른 날짜를 요청함 · 수락한 뒤 날짜 바꾸기를 요청함
DATES_TODO = ("waiting", "requested", "change_requested")
PICK_DAYS = 30  # 고객이 고른 반나절(수락 기다림)을 찾는 기간
VISIT_DAYS = 7  # 다가오는 실측 일정(my_jobs)


async def visit_slots_of(
    s: AsyncSession, vendor: User, today: date, days: int
) -> tuple[list, list]:
    """(수락 기다리는 고객이 고른 반나절, 다가오는 실측) — 업체 일정(visit.flow.vendor_schedule) 중 요청 상태가
    고른 날(picked) · 실측 확정(booked)인 것만. 오늘부터 days일, 날 · 반나절 순. 고객 이름 없음(동네 · 면적만)."""
    from app.assistant import repository as repo
    from app.visit import flow

    slots = (await flow.vendor_schedule(s, vendor, today, today + timedelta(days=days))).items
    states = await repo.visit_states(s, [x.visit_id for x in slots])
    picked = [x for x in slots if x.kind == "hold" and states.get(x.visit_id) == "picked"]
    booked = [x for x in slots if x.kind == "booked" and states.get(x.visit_id) == "booked"]
    return picked, booked


def _slot_text(x) -> str:
    return f"{md_week(x.day)} {HALF[x.half]}"


async def vendor_today(
    s: AsyncSession, vendor: User, today: date, refs: "RefTable | None" = None
) -> VendorTodayData:
    """업체 작업함 맨 위 '오늘 브리핑': 새 요청 · 날짜 수락(고객이 고른 반나절) · 오늘 · 내일 실측 · 보낼 견적서 ·
    공사 날짜 낼 공사(줄은 코드가 고른다). refs를 주면 공사 날짜 줄에 기한이 가까운 공사의 날 후보 첫 것(고객 날짜
    요청이면 request_candidates) 이름표를 넣어 단추(choice 'dates:d#,n#')로 승인 카드를 받게 한다."""
    from app.schedule import service as schedule_service

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
                title=f"새 요청 {len(new)}건",
                sub=" · ".join(dict.fromkeys(r.area_name for r in new[:3])),
                due=soon,
                action=RowAction(label="보기", href=f"/vendor/requests/{new[0].id}"),
            )
        )
    picked, booked = await visit_slots_of(s, vendor, today, PICK_DAYS)
    if picked:  # 고객이 반나절을 골랐어요: 요청 화면에서 수락해요
        first = min(picked, key=lambda x: x.hold_until or datetime.max.replace(tzinfo=SEOUL))
        due = seoul_text(first.hold_until)
        rows.append(
            TodayRow(
                id="pick",
                icon="calendar",
                title=f"날짜 수락 {len(picked)}건",
                sub=" · ".join(
                    x
                    for x in (
                        first.area_label.split(" · ")[0],
                        _slot_text(first),
                        due and f"{due}까지",
                    )
                    if x
                ),
                due=first.hold_until is not None
                and first.hold_until.astimezone(SEOUL).date() <= today + timedelta(days=1),
                action=RowAction(
                    label="수락하러 가기", href=f"/vendor/requests/{first.visit_id}", primary=True
                ),
            )
        )
    for day, key, word in (
        (today, "visit", "오늘"),
        (today + timedelta(days=1), "tomorrow", "내일"),
    ):
        mine = [x for x in booked if x.day == day]
        if mine:
            rows.append(
                TodayRow(
                    id=key,
                    icon="calendar",
                    title=f"{word} 실측 {len(mine)}건",
                    sub=" · ".join(
                        f"{HALF[x.half]} {x.area_label.split(' · ')[0]}" for x in mine[:3]
                    ),
                )
            )
    quote = [r for r in todo if r.status == "visited"]
    if quote:
        rows.append(
            TodayRow(
                id="quote",
                icon="file",
                title=f"보낼 견적서 {len(quote)}건",
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
            from app.assistant.tools import aftercare as aftercare_tools

            job = await schedule_service.job_for(s, vendor, first.deal_id, today)
            # 고객이 날짜를 요청했으면 고객이 고른 날(모두 막히면 가장 가까운 빈 날, 다른 날 제안)
            cands = (
                aftercare_tools.request_candidates(job, first.deal_id, today)
                if job.request is not None
                else date_candidates(job, first.deal_id, today)
            )
            if cands:
                c = cands[0]
                d = refs.put("deal", {"id": str(first.deal_id), "trade": first.trade})
                n = refs.put("days", c)
                days = [date.fromisoformat(x) for x in c["days"]]
                sub.append(f"후보 {kdate.md(days[0], today)}~{kdate.md(days[-1], today)}")
                if c.get("alt"):
                    sub.append("고객이 바란 날은 다른 공사와 겹쳐요")
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
                title=f"공사 날짜 낼 공사 {len(need)}건",
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
        # 읽기 도구: 이 요청에 열린 제안(대화에서 고른 못 받아요 등)이 있으면 덮지 않는다(리뷰 B3)
        card, model, _, made, closed = await brief(
            s, tc.user, vid, tc.today, tc.now, tc.refs, tc.turn_id, keep_open=True
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
    tomorrow = today + timedelta(days=1)  # 예상 시작일 그날부터(내일보다 앞이면 내일부터)
    base = max(job.plan_start or tomorrow, tomorrow)
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
    description="우리 업체의 할 일: 답할 요청 · 날짜 수락(고객이 고른 반나절, 요청 화면에서 수락) · 보낼 견적서 · "
    "공사 날짜를 낼 공사(고객이 날짜를 요청했으면 고객이 바란 날 · 겹침) · 다가오는 실측 일정(7일). 공사 날짜 "
    "후보(n1…)도 줘요. 시각은 서울 시각이에요.",
    model=NoArgs,
    schema=obj({}),
)
async def my_jobs(tc: ToolCtx, _: NoArgs) -> ToolOut:
    from app.schedule import service as schedule_service

    async with SessionLocal() as s:
        todo = (await schedule_service.vendor_inbox(s, tc.user, "todo", tc.today, None, 20)).items
        jobs = (await schedule_service.vendor_inbox(s, tc.user, "jobs", tc.today, None, 20)).items
        picked, booked = await visit_slots_of(s, tc.user, tc.today, PICK_DAYS)
        held = {x.visit_id: x for x in picked}
        requests = []
        for r in todo[:10]:
            row: dict = {
                "ref": tc.refs.put("visit", {"id": str(r.id), "trade": r.trade}),
                "status": r.status,
                "area": r.area_label or r.area_name,
                "next": r.next.label if r.next else None,
                "due_at": seoul_text(r.next.due_at) if r.next else None,  # 서울 시각 글
            }
            if r.id in held:  # 고객이 고른 반나절: 요청 화면에서 수락
                x = held[r.id]
                row["picked"] = {"day": x.day, "half": HALF[x.half], "note": PICKED_NOTE}
            requests.append(row)
        deals = []
        for r in jobs[:5]:
            if r.deal_id is None:
                continue
            ref = tc.refs.put("deal", {"id": str(r.deal_id), "trade": r.trade})
            row = {
                "ref": ref,
                "trade": r.trade,
                "area": r.area_label or r.area_name,
                "dates_state": r.dates_state,
                "state": DEAL_STATE.get(r.dates_state),
                "start_date": r.start_date,
                "end_date": r.end_date,
                "due_at": seoul_text(r.dates_due_at) if r.dates_state == "waiting" else None,
            }
            if r.dates_state in DATES_TODO:
                from app.assistant.tools import aftercare as aftercare_tools

                job = await schedule_service.job_for(s, tc.user, r.deal_id, tc.today)
                # 고객의 날짜 요청이 열려 있으면 고객이 고른 시작일 후보(먼저 말 걸기 dates_requested와 같은 길),
                # 고른 날이 모두 다른 공사와 겹치면 가장 가까운 빈 날(다른 날 제안)
                got = (
                    aftercare_tools.request_candidates(job, r.deal_id, tc.today)
                    if job.request is not None
                    else date_candidates(job, r.deal_id, tc.today)
                )
                cands = []
                for c in got:
                    days = [date.fromisoformat(x) for x in c["days"]]
                    nref = tc.refs.put("days", c)
                    cands.append({"ref": nref, "start": days[0], "end": days[-1], "days": days})
                count = max(job.quote.days or job.need.days, 1)
                row.update(candidates=cands, crew=job.need.crew, days_needed=count)
                if job.request is not None:
                    # 날짜 요청 답 기한은 요청 + 48시간(공사 날짜 기한이 아니에요)
                    wish = sorted(job.request.wish_dates)
                    row["due_at"] = seoul_text(job.request.due_at)
                    row["wish"] = wish
                    if got and got[0].get("alt"):
                        row["note"] = (
                            f"고객이 바란 날({md_list(wish)})은 우리 업체의 다른 공사와 "
                            "겹쳐요. 가장 가까운 빈 날 후보로 다른 날을 제안할 수 있어요(고객이 수락해야 바뀌어요)."
                        )
                    elif not got:
                        row["note"] = (
                            "보낼 수 있는 빈 날이 없어요. 공사 화면에서 확인하거나 믿집 채팅으로 이야기해요."
                        )
            deals.append(row)
        visits = [  # 다가오는 실측(7일, 확정한 반나절만)
            {
                "label": "실측 예정",
                "day": x.day,
                "half": HALF[x.half],
                "area": x.area_label.split(" · ")[0],
            }
            for x in booked
            if x.day <= tc.today + timedelta(days=VISIT_DAYS)
        ]
    return ToolOut(
        data={
            "requests": requests,
            "deals": deals,
            "items": visits,  # 다가오는 실측 일정(없으면 7일 안에 잡힌 실측이 없어요)
            "count": len(requests) + len(deals),
        }
    )


# 업체 쪽 공사 날짜 상태(dates_state) → 모델에 줄 화면 말
DEAL_STATE = {
    "waiting": "공사 날짜를 낼 차례예요",
    "proposed": "보낸 공사 날짜를 고객이 보고 있어요",
    "requested": "고객이 다른 날짜를 요청했어요. 답할 차례예요",
    "scheduled": "고객이 공사 날짜를 수락했어요",
    "change_requested": "고객이 날짜 바꾸기를 요청했어요. 답할 차례예요",
    "change_proposed": "바꾼 날짜를 고객이 보고 있어요",
}
