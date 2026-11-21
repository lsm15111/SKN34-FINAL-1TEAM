"""카드 만들기 (계약서 3장 카드 kind). 기능 service 공개 함수 결과를 카드 data와 모델용 값으로 옮긴다.

- 금액 · 날짜 · 수는 기능 service(계산 엔진) 값 그대로다. 여기서 더하거나 빼지 않는다.
- '표준 대비 %'는 넣지 않는다(업체 추천 사유에서도 뗀다).
- 모델용 값(dict)에는 id를 넣지 않고 ref만 넣는다. 고객 · 웹 글은 policy.data()로 자료 상자에 담는다.
- 업체가 쓴 자유 글(벽지 사양 · 다른 날 메모 · 날짜 바꾼 까닭)은 카드 '업체가 적은 말'(vendor_note, 40자)에만 둔다.
  모델 값에는 있는지만(vendor_note=True) 넣어 비서 문장 · 요약 · 버튼 문구로 옮겨지지 않게 한다.
- 읽기 도구 · show_card · 무료 모드 단계 카드 · REST(보드 · 오늘 · 브리핑 · 체크리스트)가 같이 쓴다.
"""

import uuid
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

if TYPE_CHECKING:
    from app.assistant.runtime import RefTable
    from app.assistant.schemas import TaskOut

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


def _m2(x: Decimal | float | None) -> str | None:
    return None if x is None else f"{Decimal(str(x)).quantize(Decimal('0.1'))}㎡"


# ---- 집 정보 ----


async def home(s: AsyncSession, user: User, pid: uuid.UUID) -> tuple[CardOut, dict]:
    """집 정보 카드. 철거 범위(모은 조건 demolition, 코드 값)도 같이 보여 준다(전체 철거면 리모델링 기준)."""
    from app.calc.dobae import DEMOLITION, DEMOLITION_KEY
    from app.project import service as project_service
    from app.quote import service as quote_service

    p = await project_service.get_for(s, user, pid)
    h = p.home
    std = next(iter((await quote_service.latest_of(s, [p.id])).values()), None)
    demo = (await project_service.conditions(s, p.id)).get(DEMOLITION_KEY)
    demo = demo if demo in DEMOLITION else None
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
        if h.start_date:
            facts.append(f"공사 시작 희망 {h.start_date.isoformat()}")
    if demo is not None:
        facts.append(DEMOLITION[demo])
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
    label = " · ".join(
        x
        for x in (
            " · ".join(TRADE.get(t.trade, t.trade) for t in trades),
            grade,
            f"{BASIS.get(out.area_basis, out.area_basis)} {_m2(out.area_m2)}",
            "부분 공사" if out.scope == "partial" else None,
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
        "total": total,
        "supply": supply,
        "vat": vat,
        "days": out.days,
        "area_m2": out.area_m2,
        "area_basis": out.area_basis,
        "pyeong": out.pyeong,
        "lines": [
            {"name": ln.name, "amount": ln.amount, "state": ln.state, "trade": t}
            for t, ln in counted
        ],
        "version": out.price_ver,
    }
    return card, model


# ---- 업체 추천 ----


async def vendor_picks(
    s: AsyncSession,
    user: User,
    pid: uuid.UUID,
    trade: str,
    refs: "RefTable",
    exclude: frozenset[uuid.UUID] = frozenset(),
) -> tuple[CardOut, dict]:
    """업체 고르기 화면과 같은 카드에서 계산 엔진 점수로 3곳(calc.vendor_pick). 사유는 틀 글(표준 대비 % 뗌).
    exclude: 고르지 않을 업체(07 업체가 빠짐: 이미 요청 · 확정한 업체)."""
    from app.calc import vendor_pick
    from app.visit import service as visit_service

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
    data = VendorPicksData(
        area_name=lst.area_name, picks=picks, basis=PICK_BASIS, more_href=href(pid, "/vendors")
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
            }
            for x in picks
        ],
        "count": len(picks),
    }
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
    picks: list[tuple[date, str, list[str], str]] = []
    if v.status == "proposed" and v.proposal is not None:
        for x in v.proposal.slots[:3]:
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
        )
        cols.append(col)
        model_cols.append(
            {
                "ref": ref,
                "vendor_name": r.vendor_name,
                "status": r.status,
                "version": col.version,
                "total": col.total_won,
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
        cols=cols, gap_won=out.gap_total, ask_chips=asks, href=href(pid, "/quotes")
    )
    quoted = sum(1 for c in cols if c.state == "quoted")
    card = CardOut(
        card_id=f"compare-{trade}",
        kind="quote_compare",
        data=data.model_dump(mode="json"),
        say=f"실측 견적서가 {quoted}곳 왔어요." if quoted else None,
    )
    return card, {"trade": trade, "cols": model_cols, "gap_won": out.gap_total}


# ---- 공사 날짜 · 공정표 ----


async def schedule(
    s: AsyncSession, user: User, pid: uuid.UUID, today: date, refs: "RefTable"
) -> tuple[CardOut | None, dict]:
    """수락 기다리는 공사 날짜가 있으면 그 날짜(dates), 없고 확정 공정표가 있으면 공정표(final).
    그 날짜의 수락 승인 카드가 열려 있으면 카드 단추(proposal_ref · proposal_kind)를 비우고 action_id를 단다
    (같은 수락 단추가 카드와 승인 카드에 두 번 보이지 않게)."""
    from app.assistant import repository as repo
    from app.schedule import service as schedule_service

    sch = await schedule_service.schedule_for(s, user, pid, today)
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
            "start_date": d.start_date,
            "end_date": d.end_date,
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
                )
                card = CardOut(
                    card_id=f"dates-{x.id}",
                    kind="schedule",
                    data=data.model_dump(mode="json"),
                    say=f"{d.vendor_name}{'가' if _batchim_free(d.vendor_name) else '이'} 공사 날짜를 올렸어요.",
                )
        deals.append(row)
    if card is None and sch.final_version > 0:
        plan = await schedule_service.plan_for(s, user, pid, today, "final")
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
        )
        card = CardOut(
            card_id=f"plan-{plan.version}",
            kind="schedule",
            data=data.model_dump(mode="json"),
            say="확정 공정표예요.",
        )
    return card, {"final_version": sch.final_version, "deals": deals}


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


async def visit_task_for(
    s: AsyncSession, user: User, pid: uuid.UUID, today: date, now: datetime
) -> "TaskOut | None":
    from app.schedule import service as schedule_service

    return visit_task(pid, await schedule_service.overview_for(s, user, pid, today), now)


# ---- 지식 ----


def prep_card(card_id: str, trades: list[str]) -> CardOut:
    """공사 전날 준비물(공정 설정 agent.v3.trades의 고객 준비 · 주의점, 정해 둔 글)."""
    from app.agent.v3.trades import SPECS

    specs = [x for x in SPECS if x.code in trades] or [x for x in SPECS if x.code == "dobae"]
    prep = list(dict.fromkeys(p for x in specs for p in x.prep))
    cautions = list(dict.fromkeys(c for x in specs for c in x.cautions))
    data = KnowledgeData(
        title="공사 전날 준비물",
        lines=[*prep, *cautions][:6],
        source="믿집 안내",
        checklist=[CheckItem(key=f"prep{i}", label=p) for i, p in enumerate(prep[:5], 1)],
    )
    return CardOut(card_id=card_id, kind="knowledge", data=data.model_dump(mode="json"))


def knowledge_card(card_id: str, title: str, hits: list, source: str = "") -> CardOut:
    lines = [h.text.strip()[:160] for h in hits[:3] if h.text.strip()]
    src = source or " · ".join(dict.fromkeys(h.publisher or h.title for h in hits[:3] if h.title))
    data = KnowledgeData(title=title, lines=lines, source=src or "믿집 자료")
    return CardOut(card_id=card_id, kind="knowledge", data=data.model_dump(mode="json"))


# ---- 오늘 정할 일 ----

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
        model_todo.append({"title": x.summary.title, "kind": a.kind, "due_at": a.expires_at})
    if o.todo is not None:
        todo.append(
            TodayRow(
                id=f"t-{o.todo.code}",
                icon="doc",
                title=o.todo.text,
                action=RowAction(label=o.todo.action, href=o.todo.link, primary=not todo),
            )
        )
        model_todo.append({"title": o.todo.text})
    from app.assistant.tools import diy as diy_tools  # 반셀프: 마감이 7일 안인 직접 할 일

    diy_rows, diy_items = await diy_tools.today_rows(s, user, pid, today_)
    todo += diy_rows
    model_todo += diy_items
    waiting: list[TodayRow] = []
    model_wait: list[dict] = []
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
        item = {"ref": ref, "vendor_name": v.vendor_name, "next": n.kind, "due_at": n.due_at}
        if n.who == "customer":
            todo.append(row)
            model_todo.append(item)
        else:
            waiting.append(row)
            model_wait.append(item)
    page = await notify_service.page(s, user.id, pid)
    news = [
        TodayRow(
            id=f"n-{x.id}", icon="file", title=x.body, action=RowAction(label="보기", href=x.link)
        )
        for x in page.items
        if not x.read and now - x.created_at <= timedelta(days=2)
    ][:3]
    data = TodayData(date=today_, todo=todo, waiting=waiting, news=news)
    card = CardOut(card_id="today", kind="today", data=data.model_dump(mode="json"))
    model = {
        "date": today_,
        "todo": model_todo,
        "waiting": model_wait,
        "news": [{"title": x.title} for x in news],
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
