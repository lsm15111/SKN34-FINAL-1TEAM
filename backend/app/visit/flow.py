"""v3 실측 일정 상태 바꾸기 (dev-04 · data-model 5장): 담기 · 요청 · 업체 기간 · 반나절 고르기 · 수락 ·
다른 날 제안 · 일정 바꾸기 · 취소 뒤 한 번 더 · 실측 뒤.

바꾸기는 모두 '프로젝트 잠금 → 요청 잠금 → 허용 전이 확인 → 조건부 UPDATE(1행이 아니면 409) → 같은
트랜잭션에 이력 · 알림 · 기한 일 → commit → 실시간 신호 남기기(router가 응답 전에 보냄)' 순서다.
금액 · 날짜 · 기한은 계산 엔진(calc)만 만든다. 같은 반나절을 거의 같이 고르면 visit_holds 부분 UNIQUE(업체 · 날 · 반나절 · 칸 번호)가 늦은 쪽을
막는다(409 slot_taken). 같은 집 다른 업체 실측이 잡은 반나절은 고를 수 없다(409 slot_clash, 프로젝트 잠금 안에서 본다).
업체에 가는 글에는 고객 이름 · 연락처 · 동 · 호를 넣지 않는다.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.calc import deadline, slots
from app.calc.visit_view import again_wish, half_span
from app.files import service as files_service
from app.jobs import service as jobs_service
from app.notify import service as notify_service
from app.notify.catalog import link, work_name
from app.project import service as project_service
from app.quote import service as quote_service
from app.shared.clock import now_utc
from app.shared.errors import CODES, AppError, app_error
from app.shared.ids import uuid7
from app.shared.korean import i_ga
from app.thread import service as thread_service
from app.visit import repository as repo
from app.visit import service as svc
from app.visit.models import (
    ATTEMPTS_MAX,
    DIY_KEYS,
    LIVE,
    SLOTS,
    WISH_SPAN_MAX,
    Shortlist,
    Visit,
    VisitChange,
    VisitEvent,
    VisitHold,
    VisitPhoto,
    VisitProposal,
    VisitProposalSlot,
    VisitWindow,
)
from app.visit.schemas import (
    BoardRowOut,
    BookedOut,
    ChangeOut,
    FailedOut,
    PickOut,
    ProposeIn,
    ShortlistIn,
    ShortlistOut,
    SlotIn,
    SlotsIn,
    VendorScheduleOut,
    VendorVisitStateOut,
    VisitCreateIn,
    VisitCreateOut,
    VisitedIn,
    VisitPhotoIn,
    VisitStateOut,
    WindowAnswerOut,
    WindowIn,
)

FAILED_MESSAGE = {
    "not_shortlisted": "담은 업체에만 요청할 수 있어요. 다시 열어 주세요.",
    "unavailable": "지금 믿집에서 일할 수 없는 업체예요.",
}
DAY_TAGS = ("visit_pick_due", "visit_accept_due", "visit_reminder", "visit_quote_due")


def _invalid(message: str, loc: list[str | int] | None = None) -> AppError:
    """칸 오류 422 (fields에 칸 이름)"""
    fields = [{"loc": loc, "msg": message}] if loc else None
    return app_error("invalid", message, fields=fields)


def _short(x: uuid.UUID) -> str:
    """알림 · 기한 일 이름에 붙이는 짧은 꼬리 (80자 안)"""
    return x.hex[:8]


async def _locked_in(s: AsyncSession, project_id: uuid.UUID, visit_id: uuid.UUID) -> Visit:
    v = await repo.lock(s, visit_id)
    if v is None or v.project_id != project_id:
        raise AppError(404, "not_found", svc.NOT_FOUND)
    return v


async def _customer_visit(
    s: AsyncSession, user: User, project_id: uuid.UUID, visit_id: uuid.UUID
) -> Visit:
    """내 공사의 요청을 프로젝트 → 요청 순서로 잠그고 다시 읽는다 (남의 것은 404)"""
    p = await project_service.get_for(s, user, project_id)
    await project_service.lock(s, p.id)
    return await _locked_in(s, p.id, visit_id)


async def _vendor_visit(s: AsyncSession, vendor: User, visit_id: uuid.UUID) -> Visit:
    """내가 받은 요청을 프로젝트 → 요청 순서로 잠그고 다시 읽는다 (다른 업체 요청은 404)"""
    v = await svc._mine(s, vendor, visit_id)
    await project_service.lock(s, v.project_id)
    v = await repo.lock(s, visit_id)
    if v is None or v.vendor_id != vendor.id:
        raise AppError(404, "not_found", svc.NOT_FOUND)
    return v


async def _home(s: AsyncSession, v: Visit) -> repo.HomeFacts:
    return (await repo.home_facts(s, [(v.project_id, v.trade)]))[(v.project_id, v.trade)]


async def _area(s: AsyncSession, v: Visit, h: repo.HomeFacts) -> str:
    """노원구 상계동 · 공급 69.4㎡ (계산 엔진)"""
    std = (await quote_service.latest_of(s, [v.project_id])).get((v.project_id, v.trade))
    return svc.area_label(h, std) or h.sgg


def _work(h: repo.HomeFacts, v: Visit) -> str:
    """업체 알림 끝에 붙이는 공사 이름: '노원구 상계동 도배' (이름 · 아파트 · 동호수 없음)"""
    return work_name(h.sgg, h.emd, v.trade)


def _eul(word: str) -> str:
    """받침이 있으면 '을', 없으면 '를'(오전을 · 오후를, QA r2 c6 '오후을'). 한글로 끝나지 않으면 '을'."""
    last = word[-1:] or " "
    if "가" <= last <= "힣":
        return word + ("을" if (ord(last) - 0xAC00) % 28 else "를")
    return word + "을"


def _no_grade(trade: str, grade: str | None) -> None:
    if grade is not None and trade != "dobae":
        raise _invalid("벽지는 도배에서만 골라요.", ["grade"])


def _event(
    v: Visit,
    frm: str | None,
    to: str,
    by: User | None,
    code: str,
    now: datetime,
    day: date | None = None,
    half: str | None = None,
    day_to: date | None = None,
) -> VisitEvent:
    return VisitEvent(
        visit_id=v.id,
        from_status=frm,
        to_status=to,
        by_id=by.id if by else None,
        code=code,
        at=now,
        day=day,
        half=half,
        day_to=day_to,
    )


async def _state_out(s: AsyncSession, visit_id: uuid.UUID, now: datetime) -> VisitStateOut:
    v = await repo.get(s, visit_id)
    x = await svc.load_ctx(s, [v.id])
    return VisitStateOut(visit_id=v.id, status=v.status, next=svc.next_of(v, x, now))


def _in_window(w: VisitWindow, day: date, half: str, today: date) -> None:
    """업체 기간 안 · 빼는 날 아님 · 내일부터 (아니면 422)"""
    if not (w.start_date <= day <= w.end_date) or day in (w.excluded or []):
        raise _invalid("업체가 되는 날에서 골라 주세요.", ["day"])
    if day <= today:
        raise _invalid("내일부터 골라 주세요.", ["day"])


# ---- 반나절 칸 잡기 · 확정 ----

# 같은 집 다른 업체 실측과 같은 반나절(QA edge P8). 업체에는 다른 업체 이름 · 일정을 알리지 않는다
CLASH = "이미 다른 업체 실측이 잡힌 때예요. 다른 일정을 골라 주세요."
CLASH_VENDOR = "고객의 다른 일정과 겹치는 반나절이에요. 다른 날을 내 주세요."


async def _home_taken(s: AsyncSession, v: Visit) -> set[tuple[date, str]]:
    """같은 집 다른 실측 요청이 잡은 반나절(살아 있는 잡기: 확정 · 업체 수락 기다림). 부르는 쪽이 프로젝트를
    먼저 잠가서, 같은 집의 두 고르기가 줄 서고 늦은 쪽이 앞 잡기를 본다."""
    others = [o.id for o in await repo.of_project(s, v.project_id, None) if o.id != v.id]
    return {(h.day, h.half) for h in (await repo.holds_of_visits(s, others)).values()}


async def _check_home(s: AsyncSession, v: Visit, day: date, half: str, *, by_vendor: bool) -> None:
    """같은 집 다른 실측과 같은 반나절이면 409 slot_clash (겹침 판정은 계산 엔진 slots.free_at_home)"""
    if not slots.free_at_home(day, half, await _home_taken(s, v)):
        raise AppError(409, "slot_clash", CLASH_VENDOR if by_vendor else CLASH)


async def take_seat(
    s: AsyncSession,
    v: Visit,
    day: date,
    half: str,
    *,
    kind: str,
    until: datetime | None,
    now: datetime,
    capacity: int,
    by_vendor: bool = False,
) -> VisitHold:
    """반나절 칸 잡기 (L03): 빈 가장 작은 칸 번호(calc.slots.free_seat)로 넣는다. 거의 같이 누른 다른
    고객과 칸 번호가 부딪히면(부분 UNIQUE) 그 사이 들어온 칸을 다시 세어 다음 칸으로 해 본다.
    칸이 다 차면 409 slot_taken('방금 다른 고객이 골랐어요'). 같은 집 다른 업체 실측이 잡은 반나절이면
    409 slot_clash(by_vendor면 업체에 보이는 문구)."""
    await _check_home(s, v, day, half, by_vendor=by_vendor)
    for _ in range(slots.CAPACITY_MAX + 1):
        seat = slots.free_seat(await repo.used_seats(s, v.vendor_id, day, half), capacity)
        if seat is None:
            raise app_error("slot_taken")
        hold = VisitHold(
            id=uuid7(),
            vendor_id=v.vendor_id,
            visit_id=v.id,
            day=day,
            half=half,
            seat=seat,
            kind=kind,
            until=until,
            created_at=now,
        )
        try:
            async with s.begin_nested():
                s.add(hold)
                await s.flush()
        except IntegrityError as exc:
            if "uq_visit_holds_visit" in str(exc.orig):  # 이 요청에 살아 있는 잡기가 이미 있다
                raise app_error("stale") from exc
            continue
        return hold
    raise app_error("slot_taken")


async def _day_jobs(s: AsyncSession, visit_id: uuid.UUID, hold: VisitHold, now: datetime) -> None:
    """실측 날이 정해지거나 바뀌면: 고르기 · 수락 기한 일을 거두고 전날 18:00 알림 · 견적서 기한을 다시"""
    await jobs_service.cancel_refs(s, now=now, ref_ids=[visit_id], kinds=DAY_TAGS)
    tail = _short(hold.id)
    remind = deadline.reminder_at(hold.day)
    if remind > now:
        key = f"{jobs_service.key('visit_reminder', visit_id, remind)}:{tail}"
        await jobs_service.add(
            s, kind="visit_reminder", ref_id=visit_id, run_at=remind, dedup_key=key
        )
    due = deadline.quote_due(hold.day)
    key = f"{jobs_service.key('visit_quote_due', visit_id, due)}:{tail}"
    await jobs_service.add(s, kind="visit_quote_due", ref_id=visit_id, run_at=due, dedup_key=key)


async def _book(
    s: AsyncSession, v: Visit, hold: VisitHold, *, frm: str, by: User, code: str, now: datetime
) -> uuid.UUID:
    """반나절 확정: 요청 → booked · 채팅 열기 + 시스템 카드 · 전날 알림 · 견적서 기한 · 양쪽 알림.
    돌려주는 값: 대화 id."""
    values = {
        "status": "booked",
        "booked_day": hold.day,
        "booked_half": hold.half,
        "quote_due_at": deadline.quote_due(hold.day),
    }
    if not await repo.set_status(s, v.id, allowed_from=(frm,), values=values):
        raise app_error("stale")
    s.add(_event(v, frm, "booked", by, code, now, hold.day, hold.half))
    h = await _home(s, v)
    area = await _area(s, v, h)
    tid = await thread_service.open(
        s,
        project_id=v.project_id,
        vendor_id=v.vendor_id,
        customer_id=h.owner_id,
        visit_id=v.id,
        customer_label=f"{h.emd or h.sgg} 고객",
        vendor_label=v.vendor_name,
        area_label=area,
    )
    svc.card_later(
        s, tid, await thread_service.post_system(s, tid, code="visit_booked", ref_id=v.id)
    )
    await _day_jobs(s, v.id, hold, now)
    key = f"visit_booked:{v.id}:{_short(hold.id)}"
    when = svc.slot_to(hold.day, hold.half)
    await notify_service.add(
        s,
        user_id=h.owner_id,
        kind="visit_booked",
        body=f"실측이 {when} 정해졌어요 · {v.vendor_name}",
        link=link("visit_booked", pid=v.project_id, vid=v.id),
        dedup_key=key,
        project_id=v.project_id,
    )
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_booked",
        body=f"실측이 {when} 정해졌어요 · {area}",
        link=f"/vendor/requests/{v.id}",
        dedup_key=key,
    )
    return tid


async def _back_to_offered(s: AsyncSession, v: Visit, now: datetime) -> None:
    """날짜 고를 차례로 되돌린 뒤 고르기 기한이 이미 지났으면 바로 기한 지남이 되게 기한 일을 넣는다
    (D12 보류 최소 처리, L10: 잡기만 풀고 offered로 · 칸은 비우지 않음)."""
    w = (await repo.windows(s, [v.id])).get(v.id)
    if w is not None and deadline.is_over(now, w.pick_due_at):
        await jobs_service.add(s, kind="visit_pick_due", ref_id=v.id, run_at=now)


# ---- 담기 (C10 · C12 · D06) ----


async def add_shortlist(
    s: AsyncSession, user: User, project_id: uuid.UUID, data: ShortlistIn
) -> ShortlistOut:
    """업체 담기 (공사 · 공종마다 3칸). 프로젝트 행을 잠가 같은 집의 담기가 줄 선다.
    409 already(이미 담음 · 요청 중) · slots_full · no_estimate · paper_unsupported · blocked_retry ·
    locked(업체 확정 뒤)."""
    _no_grade(data.trade, data.grade)
    p, std, lines = await svc._standard(s, user, project_id, data.trade)
    if not await svc.choosable(s, p, data.trade, data.vendor_id):
        raise AppError(404, "not_found", svc.NOT_LISTED)
    await project_service.lock(s, p.id)
    live = await repo.live(s, p.id, data.trade)
    if any(v.status == "chosen" for v in live):
        raise app_error("locked", "업체를 확정한 뒤라 더 담을 수 없어요.")
    actives = await repo.shortlists_active(s, p.id, data.trade)
    if any(x.vendor_id == data.vendor_id for x in actives) or any(
        v.vendor_id == data.vendor_id for v in live
    ):
        raise app_error("already", "이미 담은 업체예요.")
    cards = await svc._cards(s, p, std, lines, data.trade, [data.vendor_id], data.grade)
    card = cards[data.vendor_id]
    if card.state != "ok":
        raise app_error(card.state)
    free = [n for n in range(1, SLOTS + 1) if n not in svc._used_slots(actives, live)]
    if not free:
        raise app_error("slots_full")
    row = Shortlist(
        id=uuid7(),
        project_id=p.id,
        trade=data.trade,
        vendor_id=data.vendor_id,
        slot=free[0],
        grade=data.grade,
    )
    try:
        s.add(row)
        await s.flush()
        await s.commit()
    except IntegrityError as exc:  # 부분 UNIQUE: 같은 업체 · 같은 칸을 다른 곳에서 먼저 담았다
        await s.rollback()
        raise app_error("already" if "uq_shortlists_vendor" in str(exc.orig) else "stale") from exc
    svc.state_later(s, [user.id], row.id, p.id)  # 내 다른 기기도 다시 읽게
    return await svc.shortlist_out(s, p, std, lines, data.trade)


async def remove_shortlist(
    s: AsyncSession, user: User, project_id: uuid.UUID, vendor_id: uuid.UUID, trade: str
) -> None:
    """담기 빼기. 그 업체에 보낸 요청이 살아 있으면 409 locked(요청 취소부터)."""
    p, _, _ = await svc._standard(s, user, project_id, trade)
    await project_service.lock(s, p.id)
    actives = await repo.shortlists_active(s, p.id, trade)
    row = next((x for x in actives if x.vendor_id == vendor_id), None)
    if row is None:
        raise AppError(404, "not_found", "담은 업체가 아니에요.")
    if any(v.vendor_id == vendor_id for v in await repo.live(s, p.id, trade)):
        raise app_error("locked", "실측을 요청한 업체라 뺄 수 없어요. 요청 취소부터 해 주세요.")
    now = now_utc()
    if not await repo.remove_shortlist(s, row.id, "customer", now):
        raise app_error("stale")
    await s.commit()
    svc.state_later(s, [user.id], row.id, p.id)


# ---- 요청 보내기 (C13 · D08) ----


async def request(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    data: VisitCreateIn,
    now: datetime,
    *,
    diy: list[str] | None = None,
    screen: bool = False,
) -> VisitCreateOut:
    """실측 요청 보내기 (v3): 담은 업체에만 · 희망 기간(62일 안) · 시도 번호 · 가견적 사본 · 공사 희망일
    사본(L04) · 프로젝트 잠금 · 담기 칸과 연결 · 답 기한 일(+48시간) · 업체 알림.
    보낼 수 없는 업체는 만들지 않고 failed로 돌려준다(모두 안 되면 409).
    v4 반셀프: diy는 고객이 승인 카드에서 본 '업체에 알릴 것'(직접 할 일 칩 키)이에요. 요청마다 사본으로 고정해요.
    screen(화면에서 보낸 요청)이면 지금 저장된 직접 할 일 칩을 사본으로 고정해요(QA r6 화면 M2: 화면 요청엔 안 갔어요)."""
    from app.project.diy import diy_for

    today = svc.today_of(now)
    told = [k for k in DIY_KEYS if k in set(diy or ())]
    if data.wish_start is None or data.wish_end is None:
        raise _invalid("희망 기간 시작과 끝을 같이 골라 주세요.", ["wish_end"])
    if data.wish_end < data.wish_start or (data.wish_end - data.wish_start).days > WISH_SPAN_MAX:
        raise _invalid("희망 기간을 다시 골라 주세요. (62일 안)", ["wish_end"])
    if data.wish_start <= today:
        raise _invalid("희망 기간은 내일부터 골라 주세요.", ["wish_start"])
    _no_grade(data.trade, data.grade)
    p, std, lines = await svc._standard(s, user, project_id, data.trade)
    await _check_photos(s, user, data.photos)
    await project_service.lock_for_visit(s, p.id)  # 같은 집의 요청이 줄 서고, 기본 정보가 잠긴다
    if screen:  # 잠근 뒤에 읽어요(칩 저장과 줄 서요)
        told = [k for k in DIY_KEYS if k in set(await diy_for(s, p.id) or ())]
    live = await repo.live(s, p.id, data.trade)
    if any(v.status == "chosen" for v in live):
        raise app_error("locked", "업체를 확정한 뒤라 더 요청할 수 없어요.")
    actives = {x.vendor_id: x for x in await repo.shortlists_active(s, p.id, data.trade)}
    busy = {v.vendor_id for v in live}
    local, near, _ = await svc._listed(s, p, data.trade)
    listed = {c.vendor_id for c in local} | {c.vendor_id for c, _ in near}
    asked = [i for i in data.vendor_ids if i in actives and i not in busy and i in listed]
    picked = {
        i: data.grade or actives[i].grade for i in asked
    }  # 요청 벽지 → 담을 때 벽지 → 공사 벽지
    cards = await svc.cards_by_grade(s, p, std, lines, data.trade, list(picked.items()))
    failed: list[FailedOut] = []
    ok: list[uuid.UUID] = []
    for vid in data.vendor_ids:
        if vid not in actives:
            failed.append(FailedOut(vendor_id=vid, code="not_shortlisted"))
        elif vid in busy:
            failed.append(FailedOut(vendor_id=vid, code="already"))
        elif vid not in listed:
            failed.append(FailedOut(vendor_id=vid, code="unavailable"))
        elif cards[vid].state != "ok":
            failed.append(FailedOut(vendor_id=vid, code=cards[vid].state))
        else:
            ok.append(vid)
    if not ok:
        if {f.code for f in failed} == {"already"}:
            raise app_error("already", "이미 실측을 요청한 업체예요.")
        code = failed[0].code
        raise app_error(code) if code in CODES else app_error("stale", FAILED_MESSAGE[code])
    tried = await repo.attempts(s, p.id, data.trade, ok)
    facts = await repo.vendor_facts(s, ok)
    work = svc.work_start(p)
    base = svc._grade(p, std, data.trade)
    rows = [
        Visit(
            id=uuid7(),
            project_id=p.id,
            trade=data.trade,
            vendor_id=vid,
            vendor_name=facts[vid].name,
            slot=actives[vid].slot,
            shortlist_id=actives[vid].id,
            attempt=tried.get(vid, 0) + 1,
            status="requested",
            estimate_set_id=cards[vid].set_id,
            estimate_total=cards[vid].total,
            wish_start=data.wish_start,
            wish_end=data.wish_end,
            work_wish_on=work,
            grade=(picked[vid] or base) if data.trade == "dobae" else None,
            diy=told,
            reply_due_at=deadline.reply_due(now),
            created_at=now,
        )
        for vid in ok
    ]
    try:
        s.add_all(rows)
        await s.flush()
        s.add_all(
            VisitPhoto(visit_id=v.id, file_id=x.file_id, sort=i, label=x.label)
            for v in rows
            for i, x in enumerate(data.photos)
        )
        for v in rows:
            await _asked(s, v, user, now)
        await s.commit()
    except IntegrityError as exc:  # 칸 · 업체 · 시도 UNIQUE: 다른 곳에서 먼저 요청했다
        await s.rollback()
        raise app_error("stale", "다른 곳에서 먼저 요청했어요. 다시 열어 주세요.") from exc
    for v in rows:
        svc.push_later(s, [user.id, v.vendor_id], v)
    return VisitCreateOut(created=[svc._visit_out(v, {}, today) for v in rows], failed=failed)


async def _check_photos(s: AsyncSession, user: User, photos: list[VisitPhotoIn]) -> None:
    """요청 사진은 내가 올린 공간 사진(kind photo)만 (10장 한도는 몸통 검사, 위치 정보는 올릴 때 지움)"""
    if not photos:
        return
    ids = [x.file_id for x in photos]
    got = await files_service.owned(s, user.id, ids)
    if len(got) != len(ids) or any(f.kind != "photo" for f in got.values()):
        raise _invalid("내가 올린 공간 사진만 붙일 수 있어요.", ["photos"])


async def _asked(s: AsyncSession, v: Visit, user: User, now: datetime) -> None:
    """요청 하나를 넣은 뒤 같은 트랜잭션에: 이력 · 답 기한 일 · 업체 알림 (이름 · 연락처 없음)"""
    code = "asked" if v.attempt == 1 else "re_asked"
    s.add(_event(v, None, "requested", user, code, now, v.wish_start, None, v.wish_end))
    await jobs_service.add(s, kind="visit_reply_due", ref_id=v.id, run_at=v.reply_due_at)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_requested",
        body=f"새 실측 요청이 왔어요 · {_work(h, v)}",
        link=link("visit_requested", vid=v.id),
        dedup_key=f"visit_requested:{v.id}",
    )


async def again(
    s: AsyncSession, user: User, project_id: uuid.UUID, visit_id: uuid.UUID, now: datetime
) -> BoardRowOut:
    """한 번 더 요청 (C18): 답 없음 · 고르기 기한 지남 · 취소 뒤 같은 업체에 시도 2. 앞 기간에서 지난 날을
    빼고 다시 보낸다(계산 엔진). 사진 · 벽지 · 공사 희망일은 앞 요청 사본 그대로. 업체에 알릴 직접 할 일(diy)은
    지금 저장된 칩이에요(앞 요청이 닫힌 뒤 바꾼 칩은 사본에 없어서, 리드 결정 11-22 '원본은 칩'). 칩을 아직 안
    골랐으면 앞 요청 사본 그대로예요(QA r2 D4). 두 번째 뒤에는 409 blocked_retry."""
    from app.project.diy import diy_for

    p = await project_service.get_for(s, user, project_id)
    first = await svc.in_project(s, p.id, visit_id)
    p, std, lines = await svc._standard(s, user, project_id, first.trade)
    await project_service.lock_for_visit(s, p.id)
    prev = await _locked_in(s, p.id, visit_id)
    if prev.status not in svc.AGAIN_FROM or not svc.is_v3(prev) or prev.vendor_id is None:
        raise app_error("stale", "한 번 더 요청은 답이 없거나 취소한 뒤에만 할 수 있어요.")
    latest = await repo.latest_of_vendor(s, p.id, prev.trade, prev.vendor_id)
    live = await repo.live(s, p.id, prev.trade)
    if any(o.vendor_id == prev.vendor_id for o in live) or (latest and latest.id != prev.id):
        raise app_error("already", "이미 한 번 더 요청했어요.")
    if prev.attempt >= ATTEMPTS_MAX:
        raise app_error("blocked_retry")
    if any(o.status == "chosen" for o in live):
        raise app_error("locked", "업체를 확정한 뒤라 더 요청할 수 없어요.")
    if not await svc.choosable(s, p, prev.trade, prev.vendor_id):
        raise app_error("stale", FAILED_MESSAGE["unavailable"])
    cards = await svc._cards(s, p, std, lines, prev.trade, [prev.vendor_id], prev.grade)
    card = cards[prev.vendor_id]
    if card.state != "ok":
        raise app_error(card.state)
    actives = await repo.shortlists_active(s, p.id, prev.trade)
    row = next((x for x in actives if x.vendor_id == prev.vendor_id), None)
    if row is None:  # 앞 요청이 끝나며 비운 칸: 빈 칸에 다시 담는다
        free = [n for n in range(1, SLOTS + 1) if n not in svc._used_slots(actives, live)]
        if not free:
            raise app_error("slots_full")
        row = Shortlist(
            id=uuid7(),
            project_id=p.id,
            trade=prev.trade,
            vendor_id=prev.vendor_id,
            slot=free[0],
            grade=prev.grade,
        )
        s.add(row)
    start, end = again_wish(prev.wish_start, prev.wish_end, svc.today_of(now))
    # '업체에 알릴 것'(직접 할 일): 지금 칩, 아직 안 골랐으면 앞 사본
    chips = await diy_for(s, p.id)
    told = set(prev.diy or ()) if chips is None else set(chips)
    v = Visit(
        id=uuid7(),
        project_id=p.id,
        trade=prev.trade,
        vendor_id=prev.vendor_id,
        vendor_name=prev.vendor_name,
        slot=row.slot,
        shortlist_id=row.id,
        attempt=prev.attempt + 1,
        status="requested",
        estimate_set_id=card.set_id,
        estimate_total=card.total,
        wish_start=start,
        wish_end=end,
        work_wish_on=prev.work_wish_on,
        grade=prev.grade,
        diy=[k for k in DIY_KEYS if k in told],
        reply_due_at=deadline.reply_due(now),
        created_at=now,
    )
    photos = (await repo.photos_of(s, [prev.id])).get(prev.id, [])
    try:
        s.add(v)
        await s.flush()
        s.add_all(
            VisitPhoto(visit_id=v.id, file_id=x.file_id, sort=x.sort, label=x.label) for x in photos
        )
        await _asked(s, v, user, now)
        await s.commit()
    except IntegrityError as exc:
        await s.rollback()
        raise app_error("stale", "다른 곳에서 먼저 요청했어요. 다시 열어 주세요.") from exc
    svc.push_later(s, [user.id, v.vendor_id], v)
    return await svc.board_row(s, v, now)


# ---- 업체 기간 답하기 (V04 · D14) ----


async def answer_window(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, data: WindowIn, now: datetime
) -> WindowAnswerOut:
    """requested → offered: 업체가 되는 기간 · 빼는 날 · 바로 확정. 답 기한 일을 거두고 고르기 기한(+7일, 기간
    마지막 날이 오기 전까지)을 넣는다. 기한이 지났으면 409 expired, 고객이 먼저 취소했거나 이미 답했으면 409 stale."""
    v = await _vendor_visit(s, vendor, visit_id)
    if v.status == "expired":
        raise app_error("expired", "답 기한이 지났어요. 고객이 한 번 더 요청하면 답할 수 있어요.")
    if v.status != "requested" or not svc.is_v3(v):
        message = (
            "고객이 요청을 취소했어요."
            if v.status == "cancelled"
            else "이미 답했거나 닫힌 요청이에요."
        )
        raise app_error("stale", message)
    if deadline.is_over(now, v.reply_due_at):
        raise app_error("expired", "답 기한이 지났어요. 고객이 한 번 더 요청하면 답할 수 있어요.")
    today = svc.today_of(now)
    if data.start <= today:
        raise _invalid("기간은 내일부터 골라 주세요.", ["start"])
    if not await repo.set_status(
        s, v.id, allowed_from=("requested",), values={"status": "offered"}
    ):
        raise app_error("stale")
    w = VisitWindow(
        visit_id=v.id,
        start_date=data.start,
        end_date=data.end,
        excluded=sorted(data.excluded),
        instant=data.instant,
        answered_at=now,
        pick_due_at=deadline.pick_due(now, data.end),  # 기간 마지막 날이 오기 전까지(QA r6 화면 M6)
    )
    s.add(w)
    s.add(_event(v, "requested", "offered", vendor, "answered", now, data.start, None, data.end))
    await jobs_service.cancel(s, now=now, kind="visit_reply_due", ref_id=v.id)
    await jobs_service.add(s, kind="visit_pick_due", ref_id=v.id, run_at=w.pick_due_at)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=h.owner_id,
        kind="visit_offered",
        body=f"{i_ga(v.vendor_name)} 기간을 보냈어요. 날짜를 골라 주세요",
        link=link("visit_offered", pid=v.project_id, vid=v.id),
        dedup_key=f"visit_offered:{v.id}",
        project_id=v.project_id,
    )
    await s.commit()
    svc.push_later(s, [h.owner_id, vendor.id], v)
    days = await svc.open_days(s, v, w, await svc.capacity_of(s, vendor.id), today)
    return WindowAnswerOut(
        visit_id=v.id,
        status="offered",
        open_halves=slots.count_open(days),
        pick_due_at=w.pick_due_at,
    )


# ---- 고객 반나절 고르기 (C16 · C19 · C61 · D15 · D16) ----


async def pick(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: SlotIn,
    now: datetime,
) -> PickOut:
    """offered → booked(바로 확정) · picked(업체 수락 기다림, 48시간 · 고른 반나절 시작 전까지 잡아 둠).
    같은 반나절을 다른 고객이 먼저 잡았으면 409 slot_taken, 고르기 기한이 지났으면 409 expired."""
    v = await _customer_visit(s, user, project_id, visit_id)
    if v.status != "offered":
        raise svc.visit_error(v, "날짜를 고를 수 있는 요청이 아니에요.")
    w = (await repo.windows(s, [v.id])).get(v.id)
    if w is None:
        raise app_error("stale")
    if deadline.is_over(now, w.pick_due_at):
        raise app_error("expired", "날짜를 고르는 기한이 지났어요.")
    _in_window(w, data.day, data.half, svc.today_of(now))
    cap = await svc.capacity_of(s, v.vendor_id)
    tid = None
    if w.instant:
        hold = await take_seat(
            s, v, data.day, data.half, kind="booked", until=None, now=now, capacity=cap
        )
        tid = await _book(s, v, hold, frm="offered", by=user, code="booked", now=now)
        status = "booked"
    else:
        # 고른 반나절 시작 전까지(QA r6 화면 M6)
        until = deadline.accept_due(now, data.day, data.half)
        hold = await take_seat(
            s, v, data.day, data.half, kind="hold", until=until, now=now, capacity=cap
        )
        if not await repo.set_status(
            s, v.id, allowed_from=("offered",), values={"status": "picked"}
        ):
            raise app_error("stale")
        s.add(_event(v, "offered", "picked", user, "picked", now, data.day, data.half))
        await jobs_service.add(s, kind="visit_accept_due", ref_id=v.id, run_at=until)
        h = await _home(s, v)
        when = svc.slot_text(data.day, data.half)
        await notify_service.add(
            s,
            user_id=v.vendor_id,
            kind="visit_picked",
            body=f"고객이 {_eul(when)} 골랐어요. 수락해 주세요 · {_work(h, v)}",
            link=link("visit_picked", vid=v.id),
            dedup_key=f"visit_picked:{v.id}:{_short(hold.id)}",
        )
        status = "picked"
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return PickOut(visit_id=v.id, status=status, booked=svc.booked_out(hold), thread_id=tid)


# ---- 업체 수락 · 다른 날 제안 (V06 · V07) ----


async def accept(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, now: datetime
) -> VendorVisitStateOut:
    """picked → booked: 잡아 둔 반나절을 확정한다. 잡아 둔 기한이 지났으면 409 expired."""
    v = await _vendor_visit(s, vendor, visit_id)
    if v.status != "picked":
        raise svc.visit_error(v, "수락할 날짜가 없어요.")
    hold = (await repo.holds_of_visits(s, [v.id])).get(v.id)
    if hold is None or hold.kind != "hold":
        raise app_error("stale")
    if deadline.is_over(now, hold.until):
        raise app_error("expired", "잡아 둔 기한이 지났어요.")
    if not await repo.book_hold(s, hold.id):
        raise app_error("stale")
    tid = await _book(s, v, hold, frm="picked", by=vendor, code="booked", now=now)
    await s.commit()
    owner = (await _home(s, v)).owner_id
    svc.push_later(s, [owner, vendor.id], v)
    booked = BookedOut(day=hold.day, half=hold.half, kind="booked", hold_until=None)
    return VendorVisitStateOut(visit_id=v.id, status="booked", booked=booked, thread_id=tid)


def _check_slots(
    slots_in: list[SlotIn], today: date, *, start: date | None, end: date | None, field: str
) -> None:
    if len({(x.day, x.half) for x in slots_in}) != len(slots_in):
        raise _invalid("같은 반나절을 두 번 골랐어요.", [field])
    for i, x in enumerate(slots_in):
        if start is not None and end is not None and not (start <= x.day <= end):
            raise _invalid("고객 희망 기간 안에서 골라 주세요.", [field, i, "day"])
        if x.day <= today:
            raise _invalid("내일부터 골라 주세요.", [field, i, "day"])


async def propose(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, data: ProposeIn, now: datetime
) -> VendorVisitStateOut:
    """picked → proposed: 잡아 둔 반나절을 풀고 이유 + 반나절 1~3개(고객 희망 기간 안, 밖이면 422)를 낸다.
    고객 고르기 기한은 제안 + 48시간."""
    v = await _vendor_visit(s, vendor, visit_id)
    if v.status != "picked":
        raise svc.visit_error(v, "다른 날을 제안할 수 있는 요청이 아니에요.")
    _check_slots(data.slots, svc.today_of(now), start=v.wish_start, end=v.wish_end, field="slots")
    await repo.release_holds(s, v.id, now)
    if not await repo.set_status(s, v.id, allowed_from=("picked",), values={"status": "proposed"}):
        raise app_error("stale")
    p = VisitProposal(
        id=uuid7(),
        visit_id=v.id,
        reason_code=data.reason_code,
        note=data.note or None,
        due_at=deadline.proposal_due(now),
        created_at=now,
    )
    s.add(p)
    await s.flush()
    s.add_all([VisitProposalSlot(proposal_id=p.id, day=x.day, half=x.half) for x in data.slots])
    first = data.slots[0]
    s.add(_event(v, "picked", "proposed", vendor, "proposed", now, first.day, first.half))
    await jobs_service.cancel(s, now=now, kind="visit_accept_due", ref_id=v.id)
    await jobs_service.add(s, kind="visit_proposal_due", ref_id=p.id, run_at=p.due_at)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=h.owner_id,
        kind="visit_proposed",
        body=f"{i_ga(v.vendor_name)} 다른 날을 제안했어요",
        link=link("visit_proposed", pid=v.project_id, vid=v.id),
        dedup_key=f"visit_proposed:{p.id}",
        project_id=v.project_id,
    )
    await s.commit()
    svc.push_later(s, [h.owner_id, vendor.id], v)
    return VendorVisitStateOut(visit_id=v.id, status="proposed", booked=None, thread_id=None)


async def pick_proposal(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: SlotIn,
    now: datetime,
) -> PickOut:
    """proposed → booked: 업체가 제안한 반나절 하나를 고르면 바로 확정(C21). 그 칸이 차 있으면 409 slot_taken."""
    v = await _customer_visit(s, user, project_id, visit_id)
    if v.status != "proposed":
        raise svc.visit_error(v, "제안한 날을 고를 수 있는 요청이 아니에요.")
    p = (await repo.proposals_open(s, [v.id])).get(v.id)
    if p is None or p.change_id is not None:
        raise app_error("stale")
    if deadline.is_over(now, p.due_at):
        raise app_error("expired", "제안한 날을 고르는 기한이 지났어요.")
    if (data.day, data.half) not in (await repo.proposal_slots(s, [p.id])).get(p.id, []):
        raise _invalid("업체가 제안한 날에서 골라 주세요.", ["day"])
    if data.day <= svc.today_of(now):
        raise app_error("expired", "제안한 날이 지났어요. 다시 골라 주세요.")
    cap = await svc.capacity_of(s, v.vendor_id)
    hold = await take_seat(
        s, v, data.day, data.half, kind="booked", until=None, now=now, capacity=cap
    )
    if not await repo.close_proposal(s, p.id, "picked", now):
        raise app_error("stale")
    tid = await _book(s, v, hold, frm="proposed", by=user, code="proposal_picked", now=now)
    await jobs_service.cancel(s, now=now, kind="visit_proposal_due", ref_id=p.id)
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return PickOut(visit_id=v.id, status="booked", booked=svc.booked_out(hold), thread_id=tid)


async def repick(
    s: AsyncSession, user: User, project_id: uuid.UUID, visit_id: uuid.UUID, now: datetime
) -> VisitStateOut:
    """proposed → offered: 제안 대신 업체 기간에서 다시 고르기 (제안 repicked)."""
    v = await _customer_visit(s, user, project_id, visit_id)
    if v.status != "proposed":
        raise svc.visit_error(v, "다시 고를 수 있는 요청이 아니에요.")
    p = (await repo.proposals_open(s, [v.id])).get(v.id)
    if p is None or not await repo.close_proposal(s, p.id, "repicked", now):
        raise app_error("stale")
    if not await repo.set_status(s, v.id, allowed_from=("proposed",), values={"status": "offered"}):
        raise app_error("stale")
    s.add(_event(v, "proposed", "offered", user, "repick", now))
    await jobs_service.cancel(s, now=now, kind="visit_proposal_due", ref_id=p.id)
    await _back_to_offered(s, v, now)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_repicked",
        body=f"고객이 제안한 날 대신 업체 기간에서 다시 고르기로 했어요 · {_work(h, v)}",
        link=link("visit_repicked", vid=v.id),
        dedup_key=f"visit_repicked:{p.id}",
    )
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return await _state_out(s, v.id, now)


# ---- 실측 뒤 (C32 · D20) ----


async def visited(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: VisitedIn,
    now: datetime,
) -> VisitStateOut:
    """booked → visited('실측 받았어요') · no_show('업체가 안 왔어요'). 반나절이 끝난 뒤(L09)만,
    그 전이면 409 stale. 안 왔으면 담기 칸을 비우고 업체에 알린다."""
    v = await _customer_visit(s, user, project_id, visit_id)
    if v.status != "booked" or v.booked_day is None:
        raise svc.visit_error(v, "실측이 확정된 요청이 아니에요.")
    if not deadline.visited_ok(now, v.booked_day, v.booked_half):
        raise app_error("stale", "실측 시각이 지난 뒤에 눌러 주세요.")
    h = await _home(s, v)
    if data.result == "visited":
        values = {"status": "visited", "visited_at": now}
        if not await repo.set_status(s, v.id, allowed_from=("booked",), values=values):
            raise app_error("stale")
        s.add(_event(v, "booked", "visited", user, "visited", now, v.booked_day, v.booked_half))
        await notify_service.add(
            s,
            user_id=v.vendor_id,
            kind="visit_visited",
            body=f"고객이 '실측 받았어요'를 눌렀어요. 견적서를 보내 주세요 · {_work(h, v)}",
            link=link("visit_visited", vid=v.id),
            dedup_key=f"visit_visited:{v.id}",
        )
    else:
        if not await repo.set_status(
            s, v.id, allowed_from=("booked",), values={"status": "no_show"}
        ):
            raise app_error("stale")
        s.add(_event(v, "booked", "no_show", user, "no_show", now, v.booked_day, v.booked_half))
        await svc.end_visit(s, v, now=now, shortlist_code="no_show")
        await notify_service.add(
            s,
            user_id=v.vendor_id,
            kind="visit_no_show",
            body=f"고객이 '업체가 안 왔어요'를 눌렀어요 · {_work(h, v)}",
            link=link("visit_no_show", vid=v.id),
            dedup_key=f"visit_no_show:{v.id}",
        )
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return await _state_out(s, v.id, now)


async def requote(
    s: AsyncSession, user: User, project_id: uuid.UUID, visit_id: uuid.UUID, now: datetime
) -> VisitStateOut:
    """유효기간이 지난 실측 견적서 '다시 받기'(D20): requote_at을 찍고 업체에 알린다. 한 번만(409 already)."""
    v = await _customer_visit(s, user, project_id, visit_id)
    if v.status != "quoted":
        raise svc.visit_error(v, "견적서가 온 요청만 다시 받을 수 있어요.")
    q = (await quote_service.sent_briefs(s, [v.id])).get(v.id)
    if q is None or q.valid_until is None or q.valid_until >= svc.today_of(now):
        raise app_error("stale", "유효기간이 지난 견적서만 다시 받을 수 있어요.")
    if v.requote_at is not None:
        raise app_error("already", "이미 다시 받기를 요청했어요.")
    if not await repo.set_status(s, v.id, allowed_from=("quoted",), values={"requote_at": now}):
        raise app_error("stale")
    s.add(_event(v, "quoted", "quoted", user, "requote", now))
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="requote_requested",
        body=f"고객이 견적서를 다시 받고 싶어 해요 · {_work(h, v)}",
        link=link("requote_requested", vid=v.id),
        dedup_key=f"requote_requested:{v.id}",
    )
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return await _state_out(s, v.id, now)


# ---- 일정 바꾸기 (C28 · V20) ----


async def _thread_link(s: AsyncSession, v: Visit, kind: str, *, vendor_side: bool) -> str:
    tid = await thread_service.find(s, v.project_id, v.vendor_id) if v.vendor_id else None
    if tid is not None:
        return link(kind, tid=tid)
    return f"/vendor/requests/{v.id}" if vendor_side else f"/projects/{v.project_id}/visits/{v.id}"


async def _post(s: AsyncSession, v: Visit, code: str, ref_id: uuid.UUID) -> None:
    tid = await thread_service.find(s, v.project_id, v.vendor_id) if v.vendor_id else None
    if tid is not None:
        svc.card_later(s, tid, await thread_service.post_system(s, tid, code=code, ref_id=ref_id))


async def request_change(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    data: SlotIn,
    now: datetime,
) -> ChangeOut:
    """확정한 실측 일정 바꾸기 요청 (booked에서만, 열린 요청 하나 409 already). 받기 전까지 원래 반나절
    그대로(C28). 업체 기간 달력에서 고르고, 그 칸이 차 있으면 409 slot_taken. 답 기한 = 요청 + 48시간."""
    v = await _customer_visit(s, user, project_id, visit_id)
    if v.status != "booked" or v.booked_day is None:
        raise svc.visit_error(v, "실측이 확정된 요청만 바꿀 수 있어요.")
    if deadline.visited_ok(now, v.booked_day, v.booked_half):
        raise app_error("stale", "실측 시각이 지나 바꿀 수 없어요.")
    if v.id in await repo.changes_open(s, [v.id]):
        raise app_error("already", "이미 바꾸기 요청을 보냈어요.")
    if (data.day, data.half) == (v.booked_day, v.booked_half):
        raise _invalid("지금 실측 날짜와 다른 일정을 골라 주세요.", ["day"])
    await _check_home(s, v, data.day, data.half, by_vendor=False)
    today = svc.today_of(now)
    w = (await repo.windows(s, [v.id])).get(v.id)
    if w is not None:
        _in_window(w, data.day, data.half, today)
        days = await svc.open_days(s, v, w, await svc.capacity_of(s, v.vendor_id), today)
        if not slots.is_open(days, data.day, data.half):
            raise app_error("slot_taken")
    elif data.day <= today:
        raise _invalid("내일부터 골라 주세요.", ["day"])
    c = VisitChange(
        id=uuid7(),
        visit_id=v.id,
        from_day=v.booked_day,
        from_half=v.booked_half,
        to_day=data.day,
        to_half=data.half,
        due_at=deadline.change_due(now),
        by_id=user.id,
        created_at=now,
    )
    try:
        async with s.begin_nested():
            s.add(c)
            await s.flush()
    except IntegrityError as exc:  # 열린 요청 하나(부분 UNIQUE)
        raise app_error("already", "이미 바꾸기 요청을 보냈어요.") from exc
    s.add(_event(v, "booked", "booked", user, "change_requested", now, data.day, data.half))
    await jobs_service.add(s, kind="visit_change_due", ref_id=c.id, run_at=c.due_at)
    await _post(s, v, "change_requested", c.id)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_change_requested",
        body=f"고객이 실측 일정을 {svc.slot_to(data.day, data.half)} 바꾸고 싶어 해요 · {_work(h, v)}",
        link=await _thread_link(s, v, "visit_change_requested", vendor_side=True),
        dedup_key=f"visit_change_requested:{c.id}",
    )
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return svc.change_out(c, await svc.load_ctx(s, [v.id]))


async def _change_of(s: AsyncSession, v: Visit, change_id: uuid.UUID) -> VisitChange:
    c = await repo.lock_change(s, change_id)
    if c is None or c.visit_id != v.id:
        raise AppError(404, "not_found", "바꾸기 요청을 찾을 수 없어요.")
    return c


async def _change_result(s: AsyncSession, c: VisitChange) -> ChangeOut:
    fresh = await s.get(VisitChange, c.id, populate_existing=True)
    return svc.change_out(fresh, await svc.load_ctx(s, [fresh.visit_id]))


async def withdraw_change(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    change_id: uuid.UUID,
    now: datetime,
) -> ChangeOut:
    """바꾸기 요청 거두기 (open · countered → withdrawn). 업체가 낸 다른 날도 같이 닫는다."""
    v = await _customer_visit(s, user, project_id, visit_id)
    c = await _change_of(s, v, change_id)
    values = {"status": "withdrawn", "closed_at": now}
    if not await repo.set_change(s, c.id, allowed_from=("open", "countered"), values=values):
        raise app_error("stale", "이미 끝난 바꾸기 요청이에요.")
    refs: list[uuid.UUID | None] = [c.id]
    p = (await repo.proposals_open(s, [v.id])).get(v.id)
    if p is not None and p.change_id == c.id:
        await repo.close_proposal(s, p.id, "repicked", now)
        refs.append(p.id)
    await jobs_service.cancel_refs(s, now=now, ref_ids=refs)
    s.add(_event(v, v.status, v.status, user, "change_withdrawn", now, c.to_day, c.to_half))
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_change_withdrawn",
        body=f"고객이 실측 일정 바꾸기 요청을 거뒀어요 · {_work(h, v)}",
        link=link("visit_change_withdrawn", vid=v.id),
        dedup_key=f"visit_change_withdrawn:{c.id}",
    )
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return await _change_result(s, c)


async def _move_booking(
    s: AsyncSession,
    v: Visit,
    c: VisitChange,
    day: date,
    half: str,
    *,
    frm_change: str,
    by: User,
    now: datetime,
) -> VisitHold:
    """바꾸기를 받는다: 옛 확정 잡기를 풀고 새 반나절을 확정으로 잡는다(차 있으면 409 slot_taken,
    트랜잭션이 통째로 되돌아가 옛 일정 그대로). 요청의 확정 사본 · 기한 일을 새 날로."""
    await repo.release_holds(s, v.id, now)
    hold = await take_seat(
        s,
        v,
        day,
        half,
        kind="booked",
        until=None,
        now=now,
        capacity=await svc.capacity_of(s, v.vendor_id),
        by_vendor=by.role == "vendor",
    )
    values = {"status": "accepted", "closed_at": now, "to_day": day, "to_half": half}
    if not await repo.set_change(s, c.id, allowed_from=(frm_change,), values=values):
        raise app_error("stale")
    moved = {"booked_day": day, "booked_half": half, "quote_due_at": deadline.quote_due(day)}
    if not await repo.set_status(s, v.id, allowed_from=("booked",), values=moved):
        raise app_error("stale")
    s.add(_event(v, "booked", "booked", by, "change_accepted", now, day, half))
    await _day_jobs(s, v.id, hold, now)
    await _post(s, v, "change_done", c.id)
    return hold


async def accept_change(
    s: AsyncSession, vendor: User, visit_id: uuid.UUID, change_id: uuid.UUID, now: datetime
) -> VendorVisitStateOut:
    """업체가 바꾸기 요청을 받는다 (open → accepted, 반나절 바꿈). 그 반나절이 차 있으면 409 slot_taken."""
    v = await _vendor_visit(s, vendor, visit_id)
    c = await _change_of(s, v, change_id)
    if v.status != "booked" or c.status != "open":
        raise app_error("stale", "받을 수 있는 바꾸기 요청이 아니에요.")
    if deadline.is_over(now, c.due_at):
        raise app_error("expired", "바꾸기 요청 답 기한이 지났어요.")
    if c.to_day <= svc.today_of(now):
        raise app_error("expired", "바꾸려는 날이 지났어요.")
    hold = await _move_booking(s, v, c, c.to_day, c.to_half, frm_change="open", by=vendor, now=now)
    await jobs_service.cancel(s, now=now, kind="visit_change_due", ref_id=c.id)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=h.owner_id,
        kind="visit_change_accepted",
        body=f"{i_ga(v.vendor_name)} 바꾼 일정을 받았어요 · {svc.slot_text(c.to_day, c.to_half)}",
        link=await _thread_link(s, v, "visit_change_accepted", vendor_side=False),
        dedup_key=f"visit_change_accepted:{c.id}",
        project_id=v.project_id,
    )
    await s.commit()
    svc.push_later(s, [h.owner_id, vendor.id], v)
    tid = await thread_service.find(s, v.project_id, vendor.id)
    return VendorVisitStateOut(
        visit_id=v.id, status="booked", booked=svc.booked_out(hold), thread_id=tid
    )


async def counter_change(
    s: AsyncSession,
    vendor: User,
    visit_id: uuid.UUID,
    change_id: uuid.UUID,
    data: SlotsIn,
    now: datetime,
) -> VendorVisitStateOut:
    """업체가 바꾸기 요청에 다른 날 1~3개를 낸다 (open → countered). 고객이 고를 기한 = + 48시간."""
    v = await _vendor_visit(s, vendor, visit_id)
    c = await _change_of(s, v, change_id)
    if v.status != "booked" or c.status != "open":
        raise app_error("stale", "다른 날을 낼 수 있는 바꾸기 요청이 아니에요.")
    if deadline.is_over(now, c.due_at):
        raise app_error("expired", "바꾸기 요청 답 기한이 지났어요.")
    _check_slots(data.slots, svc.today_of(now), start=None, end=None, field="slots")
    if any((x.day, x.half) == (v.booked_day, v.booked_half) for x in data.slots):
        raise _invalid("지금 날짜와 다른 반나절을 골라 주세요.", ["slots"])
    if not await repo.set_change(s, c.id, allowed_from=("open",), values={"status": "countered"}):
        raise app_error("stale")
    p = VisitProposal(
        id=uuid7(), visit_id=v.id, change_id=c.id, due_at=deadline.proposal_due(now), created_at=now
    )
    s.add(p)
    await s.flush()
    s.add_all([VisitProposalSlot(proposal_id=p.id, day=x.day, half=x.half) for x in data.slots])
    first = data.slots[0]
    s.add(_event(v, "booked", "booked", vendor, "change_countered", now, first.day, first.half))
    await jobs_service.cancel(s, now=now, kind="visit_change_due", ref_id=c.id)
    await jobs_service.add(s, kind="visit_proposal_due", ref_id=p.id, run_at=p.due_at)
    await _post(s, v, "change_countered", c.id)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=h.owner_id,
        kind="visit_change_countered",
        body=f"{i_ga(v.vendor_name)} 다른 날을 냈어요",
        link=await _thread_link(s, v, "visit_change_countered", vendor_side=False),
        dedup_key=f"visit_change_countered:{c.id}",
        project_id=v.project_id,
    )
    await s.commit()
    svc.push_later(s, [h.owner_id, vendor.id], v)
    hold = (await repo.holds_of_visits(s, [v.id])).get(v.id)
    tid = await thread_service.find(s, v.project_id, vendor.id)
    return VendorVisitStateOut(
        visit_id=v.id, status="booked", booked=svc.booked_out(hold), thread_id=tid
    )


async def pick_change(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    visit_id: uuid.UUID,
    change_id: uuid.UUID,
    data: SlotIn,
    now: datetime,
) -> ChangeOut:
    """업체가 바꾸기 요청에 낸 다른 날 고르기 (countered → accepted, 반나절 바꿈). 차 있으면 409 slot_taken."""
    v = await _customer_visit(s, user, project_id, visit_id)
    c = await _change_of(s, v, change_id)
    if v.status != "booked" or c.status != "countered":
        raise app_error("stale", "고를 수 있는 바꾸기 요청이 아니에요.")
    p = (await repo.proposals_open(s, [v.id])).get(v.id)
    if p is None or p.change_id != c.id:
        raise app_error("stale")
    if deadline.is_over(now, p.due_at):
        raise app_error("expired", "업체가 낸 날을 고르는 기한이 지났어요.")
    if (data.day, data.half) not in (await repo.proposal_slots(s, [p.id])).get(p.id, []):
        raise _invalid("업체가 낸 날에서 골라 주세요.", ["day"])
    if data.day <= svc.today_of(now):
        raise app_error("expired", "고른 날이 지났어요. 다시 골라 주세요.")
    if not await repo.close_proposal(s, p.id, "picked", now):
        raise app_error("stale")
    await _move_booking(s, v, c, data.day, data.half, frm_change="countered", by=user, now=now)
    await jobs_service.cancel(s, now=now, kind="visit_proposal_due", ref_id=p.id)
    h = await _home(s, v)
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_booked",
        body=f"실측 일정이 {svc.slot_to(data.day, data.half)} 바뀌었어요 · {await _area(s, v, h)}",
        link=f"/vendor/requests/{v.id}",
        dedup_key=f"visit_booked:{v.id}:{_short(c.id)}",
    )
    await s.commit()
    svc.push_later(s, [user.id, v.vendor_id], v)
    return await _change_result(s, c)


# ---- 캘린더 파일 · 업체 일정 탭 ----


def _ics_text(x: str) -> str:
    return x.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: 한 줄 75바이트 안으로 접는다 (글자를 자르지 않는다)"""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


async def visit_ics(
    s: AsyncSession, user: User, project_id: uuid.UUID, visit_id: uuid.UUID, now: datetime
) -> Response:
    """실측 확정 캘린더 파일 (I1). 주소 · 연락처는 넣지 않는다. 확정 전이면 404."""
    p = await project_service.get_for(s, user, project_id)
    v = await svc.in_project(s, p.id, visit_id)
    if v.status not in ("booked", "visited") or v.booked_day is None:
        raise AppError(404, "not_found", "확정한 실측이 없어요.")
    start, end = half_span(v.booked_day, v.booked_half)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//mitjip//visit//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:visit-{v.id}@mitjip",
        f"DTSTAMP:{_utc(now)}",
        f"DTSTART:{_utc(start)}",
        f"DTEND:{_utc(end)}",
        f"SUMMARY:{_ics_text(f'믿집 실측 · {v.vendor_name}')}",
        "DESCRIPTION:"
        + _ics_text("시각은 채팅에서 정해요. 주소 · 연락처는 채팅으로 직접 알려 줘요."),
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    body = "\r\n".join(_fold(x) for x in lines) + "\r\n"
    headers = {
        "Content-Disposition": 'attachment; filename="mitjip-visit.ics"',
        "Cache-Control": "private, no-store",
    }
    return Response(
        body.encode("utf-8"), media_type="text/calendar; charset=utf-8", headers=headers
    )


async def vendor_schedule(
    s: AsyncSession, vendor: User, start: date, end: date
) -> VendorScheduleOut:
    """업체 일정 탭 (V08): 반나절별 확정 · 잡아 둠 + 동네 · 면적 (62일 안, 고객 이름 없음)"""
    if end < start or (end - start).days > WISH_SPAN_MAX:
        raise _invalid("기간을 다시 골라 주세요. (62일 안)", ["to"])
    return VendorScheduleOut(
        start=start,
        end=end,
        capacity=await svc.capacity_of(s, vendor.id),
        items=await svc.vendor_slots(s, vendor.id, start, end),
    )


# ---- v4 반셀프: 직접 할 일이 바뀌면 요청 사본 맞추기(리드 결정 2026-11-22, QA r2 c2 · r3 c2 · c3 · c6) ----
# 사본(visits.diy)을 맞추는 요청: 살아 있는 요청 모두(요청함 ~ 견적서 옴 · 확정). 확정한 요청도 공사가 시작되기
# 전까지는 맞추고 알려요(견적서 확정 판은 그대로, 직접 할 일은 요청 사본 · 업체 브리핑 쪽). 공사가 시작된 확정만
# 고치지 않고 업체 채팅으로 따로 알려요.

DIY_SYNC = LIVE
DIY_DEALT_NOTE = "공사가 시작된 뒤라 업체에 따로 알려야 해요"
DEAL_BEFORE = ("confirmed", "scheduled")  # 공사 끝 단계 전 확정(scheduled는 시작일 전날까지)


async def _started(s: AsyncSession, visits: list[Visit], today: date) -> set[uuid.UUID]:
    """확정한 요청(chosen) 중 공사가 시작된 것: 확정이 공사 끝 단계(checking · fixing · done)이거나 수락한 시작일이
    오늘이거나 지났어요(읽기 조인)."""
    from app.schedule.models import Deal

    chosen = [v.id for v in visits if v.status == "chosen"]
    if not chosen:
        return set()
    rows = await s.execute(
        select(Deal.visit_id, Deal.status, Deal.start_date).where(
            Deal.visit_id.in_(chosen), Deal.status != "reselected"
        )
    )
    return {
        vid
        for vid, status, start in rows
        if status not in DEAL_BEFORE or (start is not None and start <= today)
    }


@dataclass(frozen=True)
class DiyReach:
    """직접 할 일이 닿는 업체. live: 칩을 바꾸면 믿집이 사본을 고치고 알리는 업체(확정 전 요청 · 공사 시작 전 확정).
    dealt: 공사가 시작된 확정 업체(사본은 그대로, 바꾸면 업체 채팅으로 따로 알려야 해요). missing: dealt 중 사본에
    지금 직접 할 일이 빠진 업체(지금 따로 알려야 해요, 사본이 같으면 알릴 것이 없어요). synced: live 업체 사본이 모두
    지금 직접 할 일과 같아요(이미 업체에 갔어요)."""

    live: list[str]
    dealt: list[str]
    missing: list[str] = field(default_factory=list)
    synced: bool = True


async def diy_reach(s: AsyncSession, project_id: uuid.UUID, today: date | None = None) -> DiyReach:
    """직접 할 일을 바꾸면 닿는 업체와 지금 사본이 칩과 같은지(읽기만). 승인 카드 메모 · 직접 할 일 도구가 같이
    써요. today를 비우면 서울 오늘이에요."""
    from app.project.diy import diy_for

    want = [k for k in DIY_KEYS if k in set(await diy_for(s, project_id) or ())]
    visits = await repo.of_project(s, project_id, None)
    started = await _started(s, visits, today or svc.today_of(now_utc()))
    live: list[str] = []
    dealt: list[str] = []
    missing: list[str] = []
    synced = True
    for v in visits:
        if v.status not in DIY_SYNC:
            continue
        same = list(v.diy or ()) == want
        if v.id in started:
            dealt.append(v.vendor_name)
            if not same:
                missing.append(v.vendor_name)
            continue
        live.append(v.vendor_name)
        synced = synced and same
    return DiyReach(live, dealt, missing, synced)


@dataclass(frozen=True)
class DiySync:
    told: list[str]  # 바뀐 직접 할 일을 알린 업체 이름(확정 전 요청 · 공사 시작 전 확정)
    dealt: list[str]  # 공사가 시작된 확정 업체 이름(사본은 그대로, 업체 채팅으로 따로 알려야 해요)

    @property
    def note(self) -> str | None:
        """도구 · 승인 결과에 붙일 말(공사가 시작된 확정 업체가 있을 때만)."""
        return f"{DIY_DEALT_NOTE}({' · '.join(self.dealt)})" if self.dealt else None


async def sync_diy(
    s: AsyncSession, project_id: uuid.UUID, keys: list[str], now: datetime
) -> DiySync:
    """직접 할 일 칩이 바뀐 뒤 같은 트랜잭션에서 부른다(commit은 부르는 쪽). 살아 있는 실측 요청(확정 포함)의
    '업체에 알릴 것' 사본(visits.diy)을 지금 칩으로 맞추고, 바뀐 요청의 업체에 앱 안 알림 한 줄을 보낸다
    (사본이 이미 같으면 그대로라 두 번 불러도 한 번만 가요). 공사가 시작된 확정 요청은 고치지 않고 업체 이름만
    돌려준다(비서가 업체 채팅으로 따로 알리라고 안내해요). 벽지 직접 구매(paper_buy)도 같은 길이에요."""
    from app.project.diy import DIY, diy_ver

    want = [k for k in DIY_KEYS if k in set(keys)]
    sent: list[str] = []
    dealt: list[str] = []
    visits = await repo.of_project(s, project_id, None)
    started = await _started(s, visits, svc.today_of(now))
    for v in visits:
        if v.status not in DIY_SYNC or list(v.diy or ()) == want:
            continue
        if v.id in started:
            dealt.append(v.vendor_name)
            continue
        res = await s.execute(
            update(Visit)
            .where(Visit.id == v.id, Visit.status.in_(DIY_SYNC), Visit.diy != want)
            .values(diy=want)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:  # 그사이 닫혔거나 이미 같은 사본
            continue
        sent.append(v.vendor_name)
        if v.vendor_id is None:
            continue
        what = " · ".join(DIY[k] for k in want) or "없어요"
        # 어느 요청인지 다른 업체 알림처럼 끝에 공사 이름(QA r4 c2: '· 도봉구 도배'가 없었어요)
        work = _work(await _home(s, v), v)
        await notify_service.add(
            s,
            user_id=v.vendor_id,
            kind="visit_diy_changed",
            body=f"고객이 직접 할 일을 바꿨어요: {what} · {work}",
            link=link("visit_diy_changed", vid=v.id),
            dedup_key=f"visit_diy_changed:{v.id}:{diy_ver(want)}:{now:%Y%m%d%H%M%S}",
        )
    return DiySync(sent, dealt)
