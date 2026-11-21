"""카드 만들기 (계약서 3장 카드 kind). 기능 service 공개 함수 결과를 카드 data와 모델용 값으로 옮긴다.

- 금액 · 날짜 · 수는 기능 service(계산 엔진) 값 그대로다. 여기서 더하거나 빼지 않는다.
- '표준 대비 %'는 넣지 않는다(업체 추천 사유에서도 뗀다).
- 모델용 값(dict)에는 id를 넣지 않고 ref만 넣는다. 고객 · 웹 글은 policy.data()로 자료 상자에 담는다.
- 업체가 쓴 자유 글(벽지 사양 · 다른 날 메모 · 날짜 바꾼 까닭)은 카드 '업체가 적은 말'(vendor_note, 40자)에만 둔다.
  모델 값에는 있는지만(vendor_note=True) 넣어 비서 문장 · 요약 · 버튼 문구로 옮겨지지 않게 한다.
- 읽기 도구 · show_card · 무료 모드 단계 카드 · REST(보드 · 오늘 · 브리핑 · 체크리스트)가 같이 쓴다.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import policy
from app.assistant.schemas import (
    CardOut,
    CheckItem,
    CompareCol,
    CompareFileOut,
    DateRange,
    HomeArea,
    HomeInfoData,
    KnowledgeData,
    LinkOut,
    NameWon,
    QuoteCompareData,
    ScheduleData,
    ScheduleDay,
    SlotCandidate,
    StandardQuoteData,
    VendorPick,
    VendorPicksData,
    VersionDiff,
    VisitSlotsData,
    WishOut,
)
from app.auth.models import User
from app.calc.common import COUNTED
from app.shared.clock import SEOUL
from app.shared.korean import i_ga

if TYPE_CHECKING:
    from app.assistant.runtime import RefTable
    from app.assistant.schemas import BoardVendorRow, TaskOut, TodayRow

GRADE = {"economy": "합지", "basic": "실크"}
SCOPE = {"full": "전체", "partial": "부분"}
BASIS = {"supply": "공급", "exclusive": "전용"}
TRADE = {"dobae": "도배", "mokgong": "목공"}
HALF = {"am": "오전", "pm": "오후"}
PICK_BASIS = [
    "이 구에서 일하고 이 공정을 해요",
    "업체가 단가를 확인해 가견적이 있어요",
    "별점 · 끝낸 공사 · 가견적으로 점수를 매겨요",
]


def href(pid: uuid.UUID, tail: str = "") -> str:
    return f"/projects/{pid}{tail}"


def seoul_text(at: datetime | None) -> str | None:
    """시각 → 모델에 줄 서울 시각 글 '11월 23일(월) 오후 6시'. 시각(UTC)을 그대로 넘기면 모델이 09:00Z를 '오전
    9시'로 읽어요(QA r1 c6). 말하는 꼴 그대로라 문장 숫자 검사에도 그 숫자가 들어가요."""
    if at is None:
        return None
    x = at.astimezone(SEOUL)
    hour = x.hour % 12 or 12
    minute = f" {x.minute}분" if x.minute else ""
    half = "오전" if x.hour < 12 else "오후"
    return f"{x.month}월 {x.day}일({'월화수목금토일'[x.weekday()]}) {half} {hour}시{minute}"


def _m2(x: Decimal | float | None) -> str | None:
    return None if x is None else f"{Decimal(str(x)).quantize(Decimal('0.1'))}㎡"


# ---- 집 정보 ----


async def home(s: AsyncSession, user: User, pid: uuid.UUID) -> tuple[CardOut, dict]:
    """집 정보 카드. 철거 범위(모은 조건 demolition, 코드 값)도 같이 보여 준다(전체 철거면 리모델링 기준).
    직접 할 일(diy 칩)은 화면 이름으로 보인다: 아직 안 물었으면 빼고(모델 값 None), '없어요'면 빈 목록."""
    from app.calc.dobae import DEMOLITION, DEMOLITION_KEY
    from app.project import diy as project_diy
    from app.project import service as project_service
    from app.quote import service as quote_service

    p = await project_service.get_for(s, user, pid)
    h = p.home
    std = next(iter((await quote_service.latest_of(s, [p.id])).values()), None)
    demo = (await project_service.conditions(s, p.id)).get(DEMOLITION_KEY)
    demo = demo if demo in DEMOLITION else None
    picked = await project_diy.diy_for(s, p.id)
    diy = None if picked is None else [project_diy.DIY[k] for k in picked]
    m2 = h.area_m2 if h else p.size.m2
    basis = h.area_basis if h else p.size.basis
    facts = [p.region]
    if m2 is not None and basis:
        facts.append(f"{BASIS.get(basis, basis)} {_m2(m2)}")
    if std is not None and std.pyeong:
        facts.append(f"{Decimal(std.pyeong).normalize():f}평")
    facts.append("살면서 공사" if p.occupied else "빈 집")
    if h is not None:
        facts.append(
            f"도배 · {GRADE.get(h.grade or '', '벽지 미정')} · {SCOPE.get(h.scope, h.scope)}"
        )
        if h.rooms:
            facts.append(f"방 {h.rooms}개")
        # 사실 줄은 카드 · 보드 · 턴 사실이 같이 써요: '12월 15일(화)'(ISO 날짜를 보이지 않고, 비서 문장의 월 · 일
        # 숫자 검사에도 그 숫자가 들어가게)
        start = md_long(h.start_date) if h.start_date else "아직 몰라요"
        facts.append(f"공사 시작 희망 {start}")
    if demo is not None:
        facts.append(DEMOLITION[demo])
    if diy is not None:
        facts.append(f"직접 할 일 {', '.join(diy) or '없어요'}")
    area = (
        HomeArea(m2=m2, basis=basis, pyeong=std.pyeong if std else None)
        if m2 is not None and basis in ("supply", "exclusive")
        else None
    )
    data = HomeInfoData(facts=facts, area=area, locked=p.locked, demolition=demo)
    card = CardOut(card_id="home", kind="home_info", data=data.model_dump(mode="json"))
    model = {
        "region": p.region,
        "area_m2": m2,
        "area_basis": basis,
        "pyeong": std.pyeong if std else None,
        "occupied": p.occupied,
        "grade": h.grade if h else None,
        "scope": h.scope if h else None,
        "rooms": h.rooms if h else None,
        "start_date": h.start_date if h else (p.when.start if p.when else None),
        "demolition": demo,
        # 직접 할 일: 고른 목록 · '없어요'(빈 목록) · 아직 안 고름(저장했는지 비서가 짐작하지 않게 늘 적어요)
        "diy": diy if diy else "없어요" if diy is not None else "아직 고르지 않았어요",
        "locked": p.locked,
        "facts": facts,
    }
    return card, model


# ---- 표준견적서 ----


async def standard(
    s: AsyncSession, user: User, pid: uuid.UUID, trade: str | None = None
) -> tuple[CardOut, dict]:
    from app.quote import service as quote_service

    out = await quote_service.standard_for(s, user, pid)
    one = next((t for t in out.trades if t.trade == trade), None)
    trades = [one] if one is not None else out.trades
    counted = [
        (t.trade, ln)
        for t in trades
        for ln in t.lines
        if ln.state in COUNTED and ln.amount is not None and ln.amount > 0
    ]
    top = sorted(counted, key=lambda x: -x[1].amount)[:6]
    # 한 공정이면 그 공정 합계, 아니면 전체 합계(둘 다 계산 엔진 값)
    total, supply, vat = (
        (one.total, one.supply, one.vat) if one else (out.total, out.supply, out.vat)
    )
    grade = next((GRADE.get(t.grade or "") for t in trades if t.grade), None)
    # 벽지 직접 구매: 도배지 줄 고객 구매(합계 밖)
    own = next((t for t in trades if t.own_paper), None)
    label = " · ".join(
        x
        for x in (
            " · ".join(TRADE.get(t.trade, t.trade) for t in trades),
            grade,
            f"{BASIS.get(out.area_basis, out.area_basis)} {_m2(out.area_m2)}",
            "부분 공사" if out.scope == "partial" else None,
            "벽지 고객 구매" if own else None,
        )
        if x
    )
    data = StandardQuoteData(
        total_won=total,
        label=label,
        lines=[NameWon(name=ln.name, won=ln.amount) for _, ln in top],
        days=out.days,
        partial=out.scope == "partial",
        href=href(pid, "/standard"),
    )
    card = CardOut(card_id="standard", kind="standard_quote", data=data.model_dump(mode="json"))
    model = {
        "trades": [TRADE.get(t.trade, t.trade) for t in trades],
        "total": total,
        "supply": supply,
        "vat": vat,
        "days": out.days,
        "days_for": [TRADE.get(t.trade, t.trade) for t in out.trades],  # 예상 일수는 이 공정들의 합
        "area_m2": out.area_m2,
        "area_basis": out.area_basis,
        "pyeong": out.pyeong,
        "lines": [
            {"name": ln.name, "amount": ln.amount, "state": ln.state, "trade": t}
            for t, ln in counted
        ],
        "version": out.price_ver,
    }
    # 벽지(칸 이름은 policy.ALLOWED 안): 롤 수(계산 엔진, 보이기용) · 벽지 직접 구매면 합계 밖 도배지 줄 · 가견적 안내(틀)
    rolled = next((t for t in trades if t.rolls is not None), None)
    if rolled is not None and rolled.rolls is not None:
        box: dict = {"count": rolled.rolls.count, "text": rolled.rolls.text}
        paper = next((ln for ln in rolled.lines if ln.key == "paper"), None)
        if rolled.own_paper and paper is not None:
            box |= {"state": "고객 구매(합계 밖)", "line": paper.name, "amount": paper.amount}
            box["note"] = rolled.paper_note
        model["paper"] = box
    if trade and one is None:  # 물은 공정이 이 공사 표준견적서에 없다
        asked = TRADE.get(trade, trade)
        model["missing"] = (
            f"이 공사 표준견적서에는 {i_ga(asked)} 없어요(고객이 고른 공정만 계산해요). "
            f"위 값은 {' · '.join(model['trades'])} 값이에요."
        )
    return card, model


# ---- 업체 추천 ----

# 업체가 적은 금액의 부가세 방식(코드 값 → 화면 말). 합계는 계산 엔진이 부가세를 더한 고객이 낼 금액이다
VAT_WAY = {
    "included": "부가세 포함으로 적음",
    "excluded": "부가세 별도로 적음(합계에 부가세를 더함)",
    "exempt": "면세",
}


async def vendor_picks(
    s: AsyncSession,
    user: User,
    pid: uuid.UUID,
    trade: str,
    refs: "RefTable",
    exclude: frozenset[uuid.UUID] = frozenset(),
) -> tuple[CardOut, dict]:
    """업체 고르기 화면과 같은 카드에서 계산 엔진 점수로 3곳(calc.vendor_pick). 사유는 틀 글(표준 대비 % 뗌).
    exclude: 고르지 않을 업체(07 업체가 빠짐: 이미 요청 · 확정한 업체). 이 공사에서 빠진 업체(못 받음 · 무응답 ·
    멈춤)와 이미 실측을 요청해 진행 중인 업체는 늘 뺀다(다시 [실측 요청] 단추로 넣지 않게, 진행 중인 업체는 모델 값
    note로 알린다). 열린 실측 요청 승인 카드에 든 업체는 모델 값에 proposed로 알린다(새로 만들지 않게)."""
    from app.assistant import aftercare
    from app.assistant import repository as repo
    from app.calc import vendor_pick
    from app.visit import service as visit_service

    live = {v for _p, t, v in await repo.live_visits(s, [pid]) if t == trade and v is not None}
    exclude = exclude | live | await aftercare.out_vendors(s, pid, trade)
    opened = [
        a
        for a in await repo.open_on(s, user.id, "project", pid)
        if a.kind == "visit_request" and (a.payload or {}).get("trade") == trade
    ]
    asked = {uuid.UUID(v) for a in opened for v in (a.payload or {}).get("vendor_ids", [])}
    lst = await visit_service.vendors_for(s, user, pid, trade)
    by_id = {c.vendor_id: c for c in (*lst.local, *lst.nearby)}
    cands = [
        vendor_pick.Candidate(
            vendor_id=str(c.vendor_id),
            name=c.name,
            local=local,
            estimate_total=c.estimate_total,
            vs_standard_pct=None if c.vs_standard_pct is None else int(c.vs_standard_pct),
            rating=None if c.rating is None else float(c.rating),
            review_count=c.review_count or 0,
            done_count=c.done_count or 0,
            instant=bool(c.instant_badge),
        )
        for local, cards in ((True, lst.local), (False, lst.nearby))
        for c in cards
        if c.state == "ok" and c.vendor_id not in exclude
    ]
    picks = []
    for p in vendor_pick.pick(cands):
        c = by_id[uuid.UUID(p.c.vendor_id)]
        ref = refs.put("vendor", {"id": str(c.vendor_id), "name": c.name, "trade": trade})
        picks.append(
            VendorPick(
                ref=ref,
                vendor_id=c.vendor_id,
                name=c.name,
                rating=None if c.rating is None else float(c.rating),
                reviews=c.review_count or 0,
                done_jobs=c.done_count or 0,
                estimate_won=c.estimate_total or 0,
                reasons=[r for r in vendor_pick.reasons(p) if "표준" not in r],
                badge="바로 확정" if c.instant_badge else None,
                picked=c.shortlisted,
                href=href(pid, "/vendors"),
            )
        )
    # 벽지 직접 구매면 가견적 안내 한 줄(틀)을 기준 줄 끝에 더해요(가견적은 벽지 값이 든 값)
    basis = [*PICK_BASIS, lst.paper_note] if lst.paper_note else PICK_BASIS
    data = VendorPicksData(
        area_name=lst.area_name, picks=picks, basis=basis, more_href=href(pid, "/vendors")
    )
    card = CardOut(
        card_id=f"picks-{trade}",
        kind="vendor_picks",
        data=data.model_dump(mode="json"),
        say=f"{lst.area_name}에서 이 집 조건에 맞는 곳이에요." if picks else None,
    )
    model = {
        "area": lst.area_name,
        "trade": trade,
        "basis": basis,  # 고른 기준(카드 아래 줄과 같은 글)
        "picks": [
            {
                "ref": x.ref,
                "name": x.name,
                "rating": x.rating,
                "reviews": x.reviews,
                "done_jobs": x.done_jobs,
                "estimate_won": x.estimate_won,
                "reasons": x.reasons,
                "picked": x.picked,
                "instant": x.badge is not None,
                "proposed": x.vendor_id in asked,  # 열린 실측 요청 승인 카드에 든 업체
            }
            for x in picks
        ],
        "count": len(picks),
    }
    notes = []
    if opened:
        names = [x.name for x in picks if x.vendor_id in asked]
        notes.append(
            f"{' · '.join(names) or '고른 업체'}에 보낼 실측 요청 승인 카드가 이미 열려 있어요. "
            "새로 만들지 말고 그 카드를 확인하고 눌러 달라고 안내해요."
        )
    going = sorted(by_id[v].name for v in live if v in by_id)
    if going:  # 진행 중인 요청은 추천에서 뺐다: 다시 요청하라고 하지 않고 그 진행을 안내한다
        notes.append(f"{' · '.join(going)}에는 이미 실측을 요청해 진행 중이라 추천에서 뺐어요.")
    if notes:
        model["note"] = " ".join(notes)
    return card, model


# ---- 실측 시간 후보 ----

# 반나절 후보 까닭 코드(calc.slots.SlotPick.why) → 화면 말. 카드 · 모델 값에 같이 쓴다(화면은 글을 그대로 보여요)
WHY = {
    "prefer_half": "말한 시간대예요",
    "prefer_day": "말한 요일이에요",
    "earliest": "가장 빠른 날이에요",
    "start_minus_20": "공사 시작 20일 전쯤이에요",
    "weekday": "평일이에요",
    "weekend": "주말이에요",
    "vendor_proposal": "업체가 낸 날이에요",
}


def why_words(codes) -> list[str]:
    return [WHY[c] for c in codes if c in WHY]


async def wishes(
    s: AsyncSession,
    user: User,
    pid: uuid.UUID,
    vendor: dict,
    today: date,
    refs: "RefTable",
    *,
    prefer: str,
    days: str,
) -> tuple[CardOut, dict]:
    """요청 전: 업체 빈 반나절(칸 수만, visit.service.open_halves_for) × 희망 기간 초안 → r1~r2."""
    from datetime import timedelta

    from app.calc import slots
    from app.project import service as project_service
    from app.refprice.holidays import days_off
    from app.visit import service as visit_service

    p = await project_service.get_for(s, user, pid)
    work = visit_service.work_start(p)
    lo, hi = slots.draft_wish(work, today) or (
        today + timedelta(days=1),
        today + timedelta(days=slots.WISH_FALLBACK_DAYS),
    )
    free = await visit_service.open_halves_for(s, uuid.UUID(vendor["id"]), lo, hi)
    found = slots.wish_candidates(
        free, work, today, prefer=prefer, days=days, days_off=days_off(lo, hi)
    )
    out = [
        WishOut(
            ref=refs.put("wish", {"start": w.start.isoformat(), "end": w.end.isoformat()}),
            start=w.start,
            end=w.end,
            open_count=w.open_count,
        )
        for w in found
    ]
    data = VisitSlotsData(
        vendor_name=vendor["name"], window=None, wishes=out, calendar_href=href(pid, "/visits")
    )
    card = CardOut(
        card_id=f"wish-{vendor['ref']}", kind="visit_slots", data=data.model_dump(mode="json")
    )
    model = {
        "vendor": vendor["name"],
        "work_start": work,
        "wishes": [
            {"ref": w.ref, "start": w.start, "end": w.end, "open_count": w.open_count} for w in out
        ],
        "basis": "공사 시작 희망일 − 28 ~ − 14일 안에서 업체 빈 반나절이 많은 기간",
    }
    return card, model


async def visit_slots(
    s: AsyncSession,
    user: User,
    pid: uuid.UUID,
    visit_id: uuid.UUID,
    now: datetime,
    refs: "RefTable",
    *,
    prefer: str,
    days: str,
) -> tuple[CardOut, dict]:
    """요청 뒤: 날짜 고르기 화면(pick_view)의 열린 반나절 → calc.slots.candidates → s1~s3.
    업체가 다른 날을 냈으면(proposed) 그 날들이 후보다(고르면 바로 확정)."""
    from app.calc import slots
    from app.refprice.holidays import days_off
    from app.visit import service as visit_service

    v = await visit_service.pick_view(s, user, pid, visit_id, now)
    today = visit_service.today_of(now)
    taken = {(m.day, m.half) for m in v.mine}  # 같은 집 다른 업체 실측이 잡은 반나절은 빼요(P8)
    picks: list[tuple[date, str, list[str], str]] = []
    if v.status == "proposed" and v.proposal is not None:
        for x in [x for x in v.proposal.slots if slots.free_at_home(x.day, x.half, taken)][:3]:
            day_kind = "weekend" if x.day.weekday() >= 5 else "weekday"
            picks.append((x.day, x.half, ["vendor_proposal", day_kind], "proposal"))
    elif v.status == "offered" and v.days:
        opened = [slots.DayOpen(d.day, d.am_left, d.pm_left) for d in v.days]
        found = slots.candidates(
            opened,
            v.work_wish_on,
            today,
            prefer=prefer,
            day_prefer=days,
            days_off=days_off(opened[0].day, opened[-1].day),
            taken=taken,
        )
        picks = [(c.day, c.half, list(c.why), "pick") for c in found]
    cands = [
        SlotCandidate(
            ref=refs.put(
                "slot",
                {"visit_id": str(v.visit_id), "day": d.isoformat(), "half": h, "via": via},
            ),
            vendor_name=v.vendor_name,
            day=d,
            half=h,  # type: ignore[arg-type]
            why=why_words(why),
        )
        for d, h, why, via in picks
    ]
    w = v.window
    data = VisitSlotsData(
        vendor_name=v.vendor_name,
        window=DateRange(start=w.start, end=w.end) if w else None,
        candidates=cands,
        instant=v.instant or v.status == "proposed",
        calendar_href=href(pid, f"/visits/{v.visit_id}"),
        vendor_note=policy.vendor_note(v.proposal.note if v.proposal else None),
    )
    card = CardOut(
        card_id=f"slots-{v.visit_id}", kind="visit_slots", data=data.model_dump(mode="json")
    )
    model = {
        "vendor": v.vendor_name,
        "status": v.status,
        "window": {"start": w.start, "end": w.end, "excluded": w.excluded} if w else None,
        "instant": data.instant,
        "candidates": [
            {"ref": c.ref, "day": c.day, "half": HALF[c.half], "why": c.why} for c in cands
        ],
        "vendor_note": data.vendor_note is not None,  # 업체 글은 카드 칸에만(모델에는 있는지만)
    }
    return card, model


# ---- 견적서 비교 ----


def _file(pid: uuid.UUID, q) -> CompareFileOut | None:
    f = q.files[0] if q.files else None
    if f is None:
        return None
    ct = (getattr(f, "content_type", "") or "").lower()
    kind = "pdf" if "pdf" in ct else "image" if ct.startswith("image/") else "sheet"
    return CompareFileOut(
        kind=kind, label=kind.upper() if kind == "pdf" else "파일", href=href(pid, "/quotes")
    )


async def compare(
    s: AsyncSession,
    user: User,
    pid: uuid.UUID,
    trade: str,
    today: date,
    refs: "RefTable",
) -> tuple[CardOut, dict]:
    """visit.service.compare 값 그대로(표준 대비 %는 옮기지 않는다). 업체가 적은 칸은 자료 상자로."""
    from app.calc import visit_view
    from app.visit import service as visit_service

    out = await visit_service.compare(s, user, pid, trade, today)
    decided = any(r.status == "chosen" for r in out.vendors)
    # 실측이 확정된(채팅이 열린) 업체에는 '채팅 열기'를 단다: 다른 업체를 확정해 닫힌 요청은 빼요
    chats = await chat_links(s, pid, [r.vendor_id for r in out.vendors if r.status in CHAT_STATES])
    cols: list[CompareCol] = []
    model_cols: list[dict] = []
    for r in out.vendors:
        ref = refs.put(
            "visit",
            {"id": str(r.visit_id), "vendor_name": r.vendor_name, "seen_ver": r.seen_ver},
        )
        q = r.latest
        prev = r.history[0] if r.history else None
        changed = (
            VersionDiff(
                from_version=prev.version, diff_won=visit_view.grade_diff(q.total, prev.total)
            )
            if q is not None and prev is not None and q.total is not None and prev.total is not None
            else None
        )
        col = CompareCol(
            ref=ref,
            visit_id=r.visit_id,
            vendor_name=r.vendor_name,
            state="quoted" if q is not None else "waiting",
            version=q.version if q else None,
            received_on=q.sent_at.astimezone(SEOUL).date() if q and q.sent_at else None,
            total_won=q.total if q else None,
            changed=changed,
            diff_vs_estimate_won=r.diff_vs_estimate,
            days=q.days if q else None,
            valid_until=q.valid_until if q else None,
            valid_soon=r.valid_soon,
            expired=r.expired,
            demolish=q.incl_removal if q else None,
            waste=q.incl_waste if q else None,
            vendor_note=policy.vendor_note(q.paper_spec) if q else None,
            warranty_months=q.warranty_months if q else None,
            file=_file(pid, q) if q else None,
            wait_note=None if q else "견적서 기다림",
            chosen=r.status == "chosen",
            chat_href=chats.get(r.vendor_id) if r.vendor_id else None,
        )
        cols.append(col)
        model_cols.append(
            {
                "ref": ref,
                "vendor_name": r.vendor_name,
                "status": r.status,
                "links": [{"label": CHAT_MODEL}] if col.chat_href else [],
                "version": col.version,
                "total": col.total_won,  # 고객이 낼 금액(부가세 포함)
                "vat_way": VAT_WAY.get(q.vat_mode or "") if q else None,
                "supply": q.supply if q else None,
                "vat": q.vat if q else None,
                "changed": changed.model_dump() if changed else None,
                "diff_vs_estimate": col.diff_vs_estimate_won,
                "days": col.days,
                "valid_until": col.valid_until,
                "valid_soon": col.valid_soon,
                "expired": col.expired,
                "demolish": col.demolish,
                "waste": col.waste,
                "vendor_note": col.vendor_note is not None,  # 업체 글은 카드 칸에만
                "warranty_months": col.warranty_months,
                "file_count": len(q.files) if q else 0,
            }
        )
    asks = (
        ["폐기물 처리도 포함인가요?"]
        if any(c.waste is None for c in cols if c.state == "quoted")
        else []
    )
    data = QuoteCompareData(
        cols=cols, gap_won=out.gap_total, ask_chips=asks, href=href(pid, "/quotes"), decided=decided
    )
    quoted = sum(1 for c in cols if c.state == "quoted")
    card = CardOut(
        card_id=f"compare-{trade}",
        kind="quote_compare",
        data=data.model_dump(mode="json"),
        say=f"실측 견적서가 {quoted}곳 왔어요." if quoted else None,
    )
    model = {"trade": trade, "cols": model_cols, "gap_won": out.gap_total}
    if decided:  # 확정했으면 지금 공사 금액(승인한 추가 금액 포함)
        from app.schedule import service as schedule_service

        works = await schedule_service.work_money(s, user, pid)
        w = next((x for x in works if x.trade == trade), None)
        if w is not None:
            model["money"] = money_model(w)
    return card, model


# ---- 공사 날짜 · 공정표 ----

# 공사 날짜 상태(schedule.service dates_state) → 모델에 줄 화면 말(끝난 일을 기다리라고 하지 않게)
DATES_STATE = {
    "waiting": "업체가 공사 날짜를 정하는 중이에요",
    "proposed": "업체가 올린 공사 날짜를 수락할 차례예요",
    "requested": "다른 날짜를 요청했어요. 업체 답을 기다려요",
    "scheduled": "공사 날짜를 수락했어요",
    "change_requested": "날짜 바꾸기를 요청했어요. 업체가 새 날짜를 올리면 수락할 수 있어요",
    "change_proposed": "업체가 바뀐 날짜를 올렸어요. 수락할 차례예요",
    "closed": "다시 고른 업체예요",
}


async def schedule(
    s: AsyncSession, user: User, pid: uuid.UUID, today: date, refs: "RefTable"
) -> tuple[CardOut | None, dict]:
    """수락 기다리는 공사 날짜가 있으면 그 날짜(dates), 없고 확정 공정표가 있으면 공정표(final).
    그 날짜의 수락 승인 카드가 열려 있으면 카드 단추(proposal_ref · proposal_kind)를 비우고 action_id를 단다
    (같은 수락 단추가 카드와 승인 카드에 두 번 보이지 않게)."""
    from app.assistant import repository as repo
    from app.schedule import service as schedule_service

    sch = await schedule_service.schedule_for(s, user, pid, today)
    links = await chat_links(s, pid, [t.deal.vendor_id for t in sch.trades])
    chats = [
        LinkOut(label=f"{t.deal.vendor_name} 채팅 열기", href=links[t.deal.vendor_id])
        for t in sch.trades
        if t.deal.vendor_id in links
    ]
    deals: list[dict] = []
    card: CardOut | None = None
    for t in sch.trades:
        d = t.deal
        dref = refs.put("deal", {"id": str(d.id), "trade": d.trade, "vendor_name": d.vendor_name})
        row: dict = {
            "ref": dref,
            "trade": d.trade,
            "vendor_name": d.vendor_name,
            "status": d.status,
            "dates_state": t.dates_state,
            "state": DATES_STATE.get(t.dates_state),  # 지금 공사 날짜 상태(화면 말)
            "start_date": d.start_date,
            "end_date": d.end_date,
            "money": money_model(t.extras),
            "links": [{"label": CHAT_MODEL}] if d.vendor_id in links else [],
        }
        x = t.proposal
        if x is not None and x.status == "pending":
            kind = "delay" if d.status == "scheduled" else "dates"
            pref = refs.put(
                "proposal",
                {
                    "id": str(x.id),
                    "deal_id": str(d.id),
                    "seen_version": sch.final_version,
                    "type": kind,
                    "start": x.start.isoformat(),
                    "end": x.end.isoformat(),
                    "vendor_name": d.vendor_name,
                    "trade": d.trade,
                },
            )
            row["proposal"] = {
                "ref": pref,
                "start": x.start,
                "end": x.end,
                "work_days": x.workdays,
                "days": x.days,
                "change": kind == "delay",
                "vendor_note": bool(x.reason),  # 바꾼 까닭(업체 글)은 카드 칸에만
                "conflicts": [o.trade for o in t.fit.conflicts] if t.fit else [],
            }
            if card is None:
                name = TRADE.get(d.trade, d.trade)
                picked = x.days or []
                accept = next(
                    (
                        a.id
                        for a in await repo.open_on(s, user.id, "proposal", x.id)
                        if a.kind in ("dates_accept", "delay_accept")
                    ),
                    None,
                )
                data = ScheduleData(
                    phase="dates",
                    vendor_name=d.vendor_name,
                    start=x.start,
                    end=x.end,
                    work_days=x.workdays,
                    days=[ScheduleDay(day=day, am=name, pm=name) for day in picked],
                    conflicts=[
                        TRADE.get(o.trade, o.trade) for o in (t.fit.conflicts if t.fit else [])
                    ],
                    plan_version=sch.final_version,
                    href=href(pid, "/schedule"),
                    vendor_note=policy.vendor_note(x.reason),
                    proposal_ref=None if accept else pref,
                    proposal_kind=None
                    if accept
                    else "delay_accept"
                    if kind == "delay"
                    else "dates_accept",
                    action_id=accept,
                    chats=[LinkOut(label=f"{d.vendor_name} 채팅 열기", href=links[d.vendor_id])]
                    if d.vendor_id in links
                    else [],
                )
                card = CardOut(
                    card_id=f"dates-{x.id}",
                    kind="schedule",
                    data=data.model_dump(mode="json"),
                    say=f"{d.vendor_name}{'가' if _batchim_free(d.vendor_name) else '이'} 공사 날짜를 올렸어요.",
                )
        deals.append(row)
    model: dict = {"final_version": sch.final_version, "deals": deals}
    plan = (
        await schedule_service.plan_for(s, user, pid, today, "final")
        if sch.final_version > 0
        else None
    )
    if plan is not None:
        model["period"] = plan_model(plan)  # 카드에 보이는 날짜별 이름을 비서도 읽게
    if card is None and plan is not None:
        by_day: dict[date, list[str]] = {}
        for dd in plan.days:
            by_day.setdefault(dd.day, []).extend(dd.names)
        data = ScheduleData(
            phase="final",
            vendor_name=", ".join(sorted({b.vendor_name for b in plan.blocks if b.vendor_name})),
            start=plan.start,
            end=plan.end,
            work_days=plan.work_days,
            days=[
                ScheduleDay(day=dd, am=" · ".join(n) or None, pm=" · ".join(n) or None, off=not n)
                for dd, n in sorted(by_day.items())
            ],
            plan_version=plan.version,
            href=href(pid, "/plan"),
            ics_href=f"/api/projects/{pid}/plan.ics",
            chats=chats,
        )
        card = CardOut(
            card_id=f"plan-{plan.version}",
            kind="schedule",
            data=data.model_dump(mode="json"),
            say="확정 공정표예요.",
        )
    return card, model


WORK_MONEY = "지금 공사 금액(확정 금액 + 승인한 추가 금액, 부가세 포함)"


def money_model(w) -> dict:
    """공정 하나의 지금 공사 금액(schedule TradeExtrasOut, 계산 엔진 값 그대로) → 모델 값. 더하지 않아요."""
    rows = [{"label": "확정 금액", "won": w.deal_total}]
    for label, m in (
        ("승인한 추가 금액", w.ok),
        ("답을 기다리는 추가 금액", w.pending),
        ("채팅으로 물어본 추가 금액", w.talk),
    ):
        if m.total:
            rows.append({"label": label, "won": m.total})
    return {"label": WORK_MONEY, "total": w.grand_total, "rows": rows}


def work_total(money, works: dict) -> tuple[int, int]:
    """보드 돈 줄(공사 요약 money · 공정마다 work_money): 확정한 공정은 지금 공사 금액(확정 + 승인한 추가 금액),
    아니면 표준견적서. 더하기는 계산 엔진(sum_won). (합계, 그중 승인한 추가 금액)."""
    from app.calc.common import sum_won

    vals: list[int] = []
    extra: list[int] = []
    for x in money.by_trade:
        w = works.get(x.trade)
        if x.source == "deal" and w is not None and w.grand_total is not None:
            vals.append(w.grand_total)
            extra.append(w.ok.total)
        else:
            vals.append(x.total)
    return sum_won(vals), sum_won(extra)


BLOCK_LABEL = {"dry": "자연 건조", "clean": "입주 청소 · 고객이 직접"}
PLAN_STATE = {"pending": "수락 전"}  # 수락 기다리는 날짜로 놓은 공정(확정은 따로 말하지 않아요)


def plan_model(plan) -> dict:
    """확정 공정표(schedule.service.plan_for, '고객이 직접' 줄 포함) → 모델 값. 날짜는 계산 엔진 값 그대로예요.
    rows는 줄마다 이름 · 처음 · 끝(업체 공사 · 자연 건조 · 입주 청소 · 고객이 직접 할 일), days는 이름이 있는 날만."""
    rows: list[dict] = []
    for b in sorted(plan.blocks, key=lambda b: (b.start, b.end)):
        if b.kind == "work":
            label = f"{TRADE.get(b.trade or '', b.label)} 공사"
        elif b.kind == "diy":
            label = f"{b.label} · 고객이 직접"
        else:
            label = BLOCK_LABEL.get(b.kind, b.label)
        row: dict = {"label": label, "start": b.start, "end": b.end}
        if b.kind == "work":
            row["work_days"] = b.days
            if b.vendor_name:
                row["vendor_name"] = b.vendor_name
            if b.state in PLAN_STATE:
                row["state"] = PLAN_STATE[b.state]
        rows.append(row)
    return {
        "phase": "확정 공정표",
        "plan_version": plan.version,
        "start": plan.start,
        "end": plan.end,
        "work_days": plan.work_days,
        "rows": rows,
        "days": [{"day": d.day, "names": list(d.names)} for d in plan.days if d.names],
    }


def _batchim_free(word: str) -> bool:
    """마지막 글자에 받침이 없으면 True('결도배가'). 한글이 아니면 '가'."""
    ch = word[-1:] if word else ""
    return not ("가" <= ch <= "힣") or (ord(ch) - 0xAC00) % 28 == 0


# ---- 작업 카드(status.task) ----

ENDED_TEXT = {
    "booked": "실측 확정",
    "visited": "실측 받음",
    "quoted": "견적서 옴",
    "chosen": "확정",
    "closed": "닫힘",
    "declined": "못 받아요",
    "expired": "기한 지남",
    "cancelled": "취소",
    "no_show": "안 옴",
}
ENDED = ("closed", "declined", "expired", "cancelled", "no_show")


def visit_task(pid: uuid.UUID, o, now: datetime) -> "TaskOut | None":
    """실측 요청 진행(업체마다 한 줄)을 작업 카드 하나로(공사 요약 schedule.overview_for의 vendors 그대로).
    고객 차례 need · 업체 차례 waiting · 끝 done · 닫힘 cancelled. 요청이 없으면 None."""
    from app.assistant.schemas import LinkOut, TaskOut, TaskRow

    if not o.vendors:
        return None
    rows: list[TaskRow] = []
    for v in o.vendors:
        n = v.next
        if v.status in ENDED:
            state = "cancelled"
        elif n.who == "customer":
            state = "need"
        elif n.who == "vendor":
            state = "waiting"
        else:
            state = "done"
        text = NEXT_TEXT.get(n.kind) if n.kind != "none" and state != "cancelled" else None
        rows.append(
            TaskRow(
                label=v.vendor_name,
                state=state,  # type: ignore[arg-type]
                text=text or ENDED_TEXT.get(v.status, "진행 중"),
                note=n.due_at.astimezone(SEOUL).strftime("%m.%d %H:%M까지")
                if n.due_at and state in ("need", "waiting")
                else None,
            )
        )
    quoted = any(v.status in ("quoted", "chosen") for v in o.vendors)
    live = any(r.state in ("need", "waiting") for r in rows)
    return TaskOut(
        task_id="visits",
        title=f"{'실측 · 견적서' if quoted else '실측 요청'} {len(rows)}곳",
        state="waiting" if live else "done",
        at=now,
        rows=rows,
        link=LinkOut(label="실측 일정 보기", href=href(pid, "/visits")),
    )


WEEK = "월화수목금토일"


def md_week(d: date) -> str:
    """'12.14(월)'"""
    return f"{d.month:02d}.{d.day:02d}({WEEK[d.weekday()]})"


def md_list(days) -> str:
    """'12.24(목) · 12.28(월)'(날마다, 주말 · 휴일을 건너뛴 날이 보이게)."""
    return " · ".join(md_week(d) for d in days)


def md_range(start: date, end: date) -> str:
    """'12.07(월)~12.21(월)': 승인 카드 요약 줄 · 판 글의 기간(짧은 꼴). ISO 날짜를 화면에 그대로 보이지 않는다."""
    return f"{md_week(start)}~{md_week(end)}"


def md_long(d: date) -> str:
    """'12월 15일(화)': 승인 카드 제목 · 사실 줄처럼 비서도 읽는 날짜 글(긴 꼴). 짧은 꼴 '12.15'는 문장 숫자 검사가
    한 수(12.15)로 읽어 비서가 '12월 15일'이라고 말하면 그 문장을 버리므로, 비서가 읽는 글은 월 · 일이 따로 보이게 쓴다."""
    return f"{d.month}월 {d.day}일({WEEK[d.weekday()]})"


def long_range(start: date, end: date) -> str:
    """'12월 1일(화)~4일(금)', 달이 바뀌면 '12월 29일(화)~1월 2일(토)'(긴 꼴 기간)."""
    if (start.year, start.month) == (end.year, end.month):
        return f"{md_long(start)}~{end.day}일({WEEK[end.weekday()]})"
    return f"{md_long(start)}~{md_long(end)}"


def day_list(days: list[date]) -> str:
    """일하는 날 칸: '2일 · 12.24(목) · 12.28(월)'."""
    return f"{len(days)}일 · {md_list(days)}"


# 보드 업체 줄 · 확정한 업체: 공사 요약의 지금 할 일 코드(calc.progress) → (상태, 화면 말)
DEAL_TEXT: dict[str, tuple[str, str]] = {
    "dates_waiting": ("waiting", "공사 날짜 기다림"),
    "dates_overdue": ("need", "공사 날짜가 늦어요"),
    "dates_received": ("need", "공사 날짜 수락할 차례"),
    "dates_requested": ("waiting", "날짜 요청 답 기다림"),
    "dates_change": ("need", "바뀐 날짜 수락할 차례"),
    "extra": ("need", "추가 금액 답할 차례"),
    "working": ("running", "공사 중"),
    "fixing": ("waiting", "남은 일 하는 중"),
    "check": ("need", "공사 끝 확인할 차례"),
    "done": ("done", "공사 끝"),
}


def board_row(v, o, works: dict, today: date) -> "BoardVendorRow":
    """보드 업체 줄 하나(공사 요약 schedule.overview_for의 업체 v). 확정한 업체는 공사 단계와 지금 공사 금액,
    닫힌 요청은 닫힌 까닭(다른 업체를 확정했으면 '고르지 않음'), 그 밖은 다음 할 일."""
    from app.assistant.schemas import BoardVendorRow

    if v.status == "chosen":
        t = next((x for x in o.trades if x.trade == v.trade), None)
        code = t.todo.code if t is not None and t.todo is not None else ""
        if code == "before_work" and t is not None and t.start_date is not None:
            state, text = "done", f"{md_week(t.start_date)} 공사 시작"
        else:
            state, text = DEAL_TEXT.get(code, ("done", ENDED_TEXT["chosen"]))
        w = works.get(v.trade)
        won = w.grand_total if w is not None and w.grand_total is not None else v.total
        return BoardVendorRow(name=v.vendor_name, state=state, text=text, won=won)  # type: ignore[arg-type]
    if v.status in ENDED:
        other = any(x.status == "chosen" and x.trade == v.trade for x in o.vendors)
        text = "고르지 않음" if v.status == "closed" and other else ENDED_TEXT[v.status]
        return BoardVendorRow(name=v.vendor_name, state="cancelled", text=text, won=v.total)
    n = v.next
    state = "need" if n.who == "customer" else "waiting" if n.who == "vendor" else "done"
    text = NEXT_TEXT.get(n.kind) or ENDED_TEXT.get(v.status, "진행 중")
    return BoardVendorRow(name=v.vendor_name, state=state, text=text, won=v.total)  # type: ignore[arg-type]


# 공사 요약의 지금 할 일(o.todo) 코드 → 오늘 정할 일 · 보드에서 어디에 두는지(업체 차례 · 공사 중은 기다리는 일)
TODO_WAIT = frozenset({"dates_waiting", "dates_requested", "working", "fixing"})
TODO_SKIP = frozenset({"visit_requested"})  # 실측 요청 뒤: 업체마다 '답 기다림' 줄이 따로 있어요


def todo_kind(todo) -> str | None:
    """'todo'(고객이 정할 일) · 'waiting'(기다리는 일) · None(따로 보이지 않음)."""
    if todo is None or todo.code in TODO_SKIP:
        return None
    return "waiting" if todo.code in TODO_WAIT else "todo"


async def visit_task_for(
    s: AsyncSession, user: User, pid: uuid.UUID, today: date, now: datetime
) -> "TaskOut | None":
    from app.schedule import service as schedule_service

    return visit_task(pid, await schedule_service.overview_for(s, user, pid, today), now)


# ---- 지식 ----


@dataclass(frozen=True)
class HomeCtx:
    """공사 전 할 일 · 전날 준비물을 이 집에 맞추는 코드 사실(tools.diy.home_ctx가 읽는다)."""

    occupied: bool = True  # 살면서 공사(빈 집이면 가구 · 짐 줄을 뺀다)
    pet: bool = False  # 기억: 반려동물이 있어요
    away_weekdays: bool = False  # 기억: 주말에만 시간이 돼요(평일엔 집을 비워요)
    weekday_work: bool = False  # 수락한 공사 날에 평일이 있어요
    diy: tuple[str, ...] = ()  # 고른 직접 할 일 칩 키


FURNITURE = re.compile(r"가구|짐")
ENTRY_ITEM = "공사 날 출입 방법(비밀번호 · 열쇠)을 업체와 믿집 채팅으로 정하기"
PET_ITEM = "공사 날 반려동물이 지낼 곳 정하기"
AWAY_LINE = (
    "평일에 공사해요. 집을 비우시면 출입 방법(비밀번호 · 열쇠)을 업체와 믿집 채팅으로 정해 두세요."
)
PET_LINE = "반려동물은 풀 냄새 · 먼지 · 소음을 피해 공사 날 지낼 곳을 미리 정해 두세요."


def fit_items(items, h: "HomeCtx | None") -> list[str]:
    """빈 집이면 가구 · 짐 줄을 뺀다(정해 둔 글은 그대로)."""
    return [x for x in items if h is None or h.occupied or not FURNITURE.search(x)]


def home_lines(h: "HomeCtx | None") -> list[str]:
    """살면서 하는 집의 평일 공사(집을 비움) · 반려동물 줄."""
    if h is None or not h.occupied:
        return []
    out = [AWAY_LINE] if h.weekday_work and h.away_weekdays else []
    return [*out, *([PET_LINE] if h.pet else [])]


def prep_card(card_id: str, trades: list[str], home: "HomeCtx | None" = None) -> CardOut:
    """공사 전날 준비물(공정 설정 agent.v3.trades의 고객 준비 · 주의점, 정해 둔 글). home이 있으면 이 집에 맞춘다:
    빈 집은 가구 줄을 빼고 출입 방법을, 평일에 집을 비우면 출입 방법을, 반려동물이 있으면 지낼 곳을 더한다."""
    from app.agent.v3.trades import SPECS

    specs = [x for x in SPECS if x.code in trades] or [x for x in SPECS if x.code == "dobae"]
    prep = fit_items(dict.fromkeys(p for x in specs for p in x.prep), home)
    if home is not None:
        if not home.occupied or (home.weekday_work and home.away_weekdays):
            prep.append(ENTRY_ITEM)
        if home.occupied and home.pet:
            prep.append(PET_ITEM)
    cautions = list(dict.fromkeys(c for x in specs for c in x.cautions))
    data = KnowledgeData(
        title="공사 전날 준비물",
        lines=[*home_lines(home), *prep, *cautions][:6],
        source="믿집 안내",
        checklist=[CheckItem(key=f"prep{i}", label=p) for i, p in enumerate(prep[:5], 1)],
    )
    return CardOut(card_id=card_id, kind="knowledge", data=data.model_dump(mode="json"))


EXCERPT_MAX = 160
_UNIT = re.compile(r"(?<=[.!?])\s+|\n+")


def excerpt(text: str, n: int = EXCERPT_MAX) -> str:
    """발췌 한 줄: 문장(또는 줄) 단위로 n자 안에서 끊는다. 첫 문장부터 n자를 넘으면 그 앞 띄어쓰기에서 자르고 '…'."""
    units = [u.strip() for u in _UNIT.split(text or "") if u.strip()]
    out = ""
    for u in units:
        joined = f"{out} {u}".strip()
        if len(joined) > n:
            break
        out = joined
    if out or not units:
        return out
    cut = units[0][: n - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > n // 2 else cut).rstrip(" ,·") + "…"


def public_source(h) -> str:
    """카드에 보일 출처 이름: 공공 · 표준 · 제조사 · 협회(official)는 펴낸 곳 · 제목, 그 밖(안내서 · 후기 …)은 자료
    종류 이름만(내부 참고 자료 이름은 보이지 않는다)."""
    if getattr(h, "official", False):
        return h.publisher or h.title or "믿집 자료"
    return getattr(h, "source_type", "") or "믿집 자료"


def knowledge_card(card_id: str, title: str, hits: list, source: str = "") -> CardOut:
    lines = [x for x in (excerpt(h.text) for h in hits[:3]) if x]
    src = source or " · ".join(dict.fromkeys(public_source(h) for h in hits[:3]))
    data = KnowledgeData(title=title, lines=lines, source=src or "믿집 자료")
    return CardOut(card_id=card_id, kind="knowledge", data=data.model_dump(mode="json"))


# ---- 오늘 정할 일 ----


def news_line(body: str) -> tuple[str, str | None]:
    """알림 글 '문장 · 덧말(공정 · 지역 · 업체)' → (문장, 덧말). 새 소식 줄이 문장으로 끝나게 덧말은 sub로 뗀다."""
    head, sep, tail = body.partition(" · ")
    if sep and head.rstrip(". ").endswith("요"):
        return head, tail or None
    return body, None


ACTION_ICON = {
    "home_info": "doc", "visit_request": "inbox", "visit_slot": "calendar",
    "vendor_confirm": "doc", "dates_accept": "calendar", "delay_accept": "calendar",
}  # fmt: skip
NEXT_TEXT = {
    "reply": "답 기다림",
    "pick": "날짜 고를 차례",
    "accept": "업체 수락 기다림",
    "proposal": "업체가 낸 날 고를 차례",
    "change": "일정 바꾸기 답 차례",
    "visit": "실측 예정",
    "quote": "견적서 기다림",
    "confirm": "견적서 보고 확정할 차례",
}


async def chat_links(s: AsyncSession, pid: uuid.UUID, vendor_ids) -> dict[uuid.UUID, str]:
    """업체 → 이 공사의 열린 믿집 채팅 주소(/chat/{id}). 채팅은 실측이 확정되면 열려요. 닫힌(읽기만) 채팅은 빼요.
    비서는 연락처를 보이지 않고 연락은 믿집 채팅으로 해요(ADR 0005). 읽기 조인."""
    from sqlalchemy import select

    from app.thread.models import Thread

    ids = [v for v in dict.fromkeys(vendor_ids) if v is not None]
    if not ids:
        return {}
    rows = await s.execute(
        select(Thread.vendor_id, Thread.id).where(
            Thread.project_id == pid, Thread.vendor_id.in_(ids), Thread.status == "open"
        )
    )
    return {v: f"/chat/{t}" for v, t in rows}


CHAT_LABEL = "채팅 열기"
CHAT_STATES = ("booked", "visited", "quoted", "chosen")  # 실측이 확정된 뒤(믿집 채팅이 열린 요청)
CHAT_MODEL = "이 업체와 믿집 채팅이 열려 있어요(카드의 [채팅 열기])"  # 모델 값: 물어볼 때 누를 곳
CONTACT = "연락처 보기"  # v3 할 일 단추(연락처를 보여 줘요): 비서 화면은 채팅 열기로 바꾸거나 빼요


async def _todo_row(s: AsyncSession, pid: uuid.UUID, o, *, primary: bool) -> "TodayRow":
    """공사 요약 지금 할 일(o.todo) → 오늘 정할 일 줄. v3 [연락처 보기]는 채팅이 열렸으면 [채팅 열기], 아니면 뺀다."""
    from app.assistant.schemas import RowAction, TodayRow

    t = o.todo
    title, action = t.text, RowAction(label=t.action, href=t.link, primary=primary)
    if t.action == CONTACT:
        tp = next((x for x in o.trades if x.trade == t.trade), None)
        chosen = [v.vendor_id for v in o.vendors if v.trade == t.trade and v.status == "chosen"]
        links = await chat_links(s, pid, chosen)
        href = next(iter(links.values()), None)
        action = RowAction(label=CHAT_LABEL, href=href, primary=primary) if href else None
        if t.code == "done" and tp is not None and tp.vendor_name:
            title = f"공사가 끝났어요 · 하자가 보이면 {tp.vendor_name}에 믿집 채팅으로 알려요"
    icon = "chat" if action is not None and action.label == CHAT_LABEL else "doc"
    return TodayRow(id=f"t-{t.code}", icon=icon, title=title, action=action)  # type: ignore[arg-type]


async def today(
    s: AsyncSession, user: User, pid: uuid.UUID, today_: date, now: datetime, refs: "RefTable"
) -> tuple[CardOut, dict]:
    """오늘 정할 일(UC-C8): 줄은 코드가 고른다. 할 일(열린 제안 · 공사 할 일 · 고객 차례 업체) ·
    기다림(업체 차례) · 새 소식(이틀 안 안 읽은 알림). 기한 가까운 순."""
    from datetime import timedelta

    from app.assistant import repository as repo
    from app.assistant.actions import out as action_out
    from app.assistant.schemas import RowAction, TodayData, TodayRow
    from app.notify import service as notify_service
    from app.schedule import service as schedule_service

    o = await schedule_service.overview_for(s, user, pid, today_)
    acts = await repo.actions_of(s, user.id, "customer", project_id=pid, status="proposed")
    todo: list[TodayRow] = []
    model_todo: list[dict] = []
    for a in acts:
        x = action_out(a)
        soon = a.expires_at - now <= timedelta(hours=24)
        todo.append(
            TodayRow(
                id=f"a-{a.id}",
                icon=ACTION_ICON.get(a.kind, "doc"),  # type: ignore[arg-type]
                title=x.summary.title,
                sub=f"{a.expires_at.astimezone(SEOUL).strftime('%m.%d %H:%M')}까지 승인",
                due=soon,
            )
        )
        model_todo.append(
            {"title": x.summary.title, "kind": a.kind, "due_at": seoul_text(a.expires_at)}
        )
    waiting: list[TodayRow] = []
    model_wait: list[dict] = []
    kind = todo_kind(o.todo)
    if o.todo is not None and kind is not None:
        row = await _todo_row(s, pid, o, primary=kind == "todo" and not todo)
        (todo if kind == "todo" else waiting).append(row)
        (model_todo if kind == "todo" else model_wait).append({"title": row.title})
    from app.assistant.tools import diy as diy_tools  # 반셀프: 마감이 7일 안인 직접 할 일

    diy_rows, diy_items = await diy_tools.today_rows(s, user, pid, today_)
    todo += diy_rows
    model_todo += diy_items
    for v in o.vendors:
        n = v.next
        if n.kind == "none":
            continue
        ref = refs.put(
            "visit", {"id": str(v.visit_id), "vendor_name": v.vendor_name, "trade": v.trade}
        )
        row = TodayRow(
            id=f"v-{v.visit_id}",
            icon="calendar" if n.kind in ("pick", "proposal", "visit") else "inbox",
            title=f"{v.vendor_name} {NEXT_TEXT.get(n.kind, '')}".strip(),
            sub=n.due_at.astimezone(SEOUL).strftime("%m.%d %H:%M까지") if n.due_at else None,
            due=n.soon or n.overdue,
        )
        item = {
            "ref": ref,
            "vendor_name": v.vendor_name,
            "next": NEXT_TEXT.get(n.kind, n.kind),
            "due_at": seoul_text(n.due_at),
        }
        if n.who == "customer":
            todo.append(row)
            model_todo.append(item)
        else:
            waiting.append(row)
            model_wait.append(item)
    page = await notify_service.page(s, user.id, pid)
    fresh = [x for x in page.items if not x.read and now - x.created_at <= timedelta(days=2)]
    # 비서 카드로 할 일을 끝낸 알림('날짜를 골라 주세요' 뒤 시간을 골랐어요)은 새 소식에서 뺀다
    done = await repo.settled_events(s, user.id, [x.id for x in fresh])
    news = [
        TodayRow(
            id=f"n-{x.id}",
            icon="file",
            title=news_line(x.body)[0],
            sub=news_line(x.body)[1],
            action=RowAction(label="보기", href=x.link),
        )
        for x in fresh
        if x.id not in done
    ][:3]
    data = TodayData(date=today_, todo=todo, waiting=waiting, news=news)
    card = CardOut(card_id="today", kind="today", data=data.model_dump(mode="json"))
    model = {
        "date": today_,
        "todo": model_todo,
        "waiting": model_wait,
        "news": [{"title": x.title, "sub": x.sub} for x in news],
        "count": len(todo),
    }
    return card, model


# ---- 무료 모드 단계 카드 ----


async def step_card(tc, route: str) -> CardOut | None:
    """무료 모드(계약서 4장 9): 입구 관문 길에 맞는 카드 하나. 못 만들면 None(답 카드만)."""
    from app.shared.errors import AppError

    try:
        from app.db import SessionLocal

        async with SessionLocal() as s:
            if tc.surface == "vendor":
                if tc.visit_id is None:
                    return None
                from app.assistant.tools.vendor import brief

                card, *_ = await brief(
                    s, tc.user, tc.visit_id, tc.today, tc.now, tc.refs, propose_window=False
                )
                return card
            if tc.project_id is None:
                return None
            if route == "quote_explanation":
                card, _model = await compare(s, tc.user, tc.project_id, "dobae", tc.today, tc.refs)
                if any(c["state"] == "quoted" for c in card.data["cols"]):
                    return card
                return (await standard(s, tc.user, tc.project_id))[0]
            if route == "schedule":
                card, _ = await schedule(s, tc.user, tc.project_id, tc.today, tc.refs)
                return card
            if route in ("guide", "multi"):
                return (await today(s, tc.user, tc.project_id, tc.today, tc.now, tc.refs))[0]
    except AppError:
        return None
    return None
