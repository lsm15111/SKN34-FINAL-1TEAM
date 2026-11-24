"""고객-업체 대화 (dev-05).

- 다른 기능 service가 부르는 계약 함수: open · post_system · set_read_only · find (부르는 쪽 트랜잭션 안,
  commit · realtime.push는 부르는 쪽이 commit 뒤에).
- 화면 API(목록 · 머리 · 글 · 보내기 · 읽음 · 사진 · 차단)는 여기서 commit하고 commit 뒤에 줄기로 알린다.
- seq는 대화 행 UPDATE(잠금) 아래에서만 올린다 → 같은 대화의 글은 빈틈 없이 1, 2, 3 …
- 업체 쪽 응답에는 고객 이름 · 휴대폰 · 이메일이 없다(이름표 '상계동 고객'만). 고객이 직접 쓴 글은 그대로(D05 A).
"""

import uuid
from collections.abc import Collection
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.files.models import File
from app.realtime import service as realtime
from app.shared.clock import now_utc
from app.shared.errors import AppError, app_error
from app.shared.ids import uuid7
from app.thread import repository as repo
from app.thread import rules
from app.thread.models import (
    RO_REASONS,
    SYSTEM_CODES,
    THREAD_CONTACT_RETENTION_DAYS,
    Thread,
    ThreadMessage,
)
from app.thread.schemas import (
    MessageIn,
    MessageOut,
    ThreadCanOut,
    ThreadLastOut,
    ThreadLinksOut,
    ThreadOut,
    ThreadRowOut,
)

RoReason = Literal["other_chosen", "cancelled", "declined", "withdrawn", "blocked", "admin"]
Side = Literal["customer", "vendor"]
# 고객 차단 · 관리자 쓰기 막기로 닫힌 대화는 실측이 다시 확정돼도 자동으로 열지 않는다
STICKY = ("blocked", "admin")
PREVIEW_MAX = 80
# 채팅 목록 미리 보기의 시스템 카드 말 (카드 본문이 있으면 그것을 쓴다)
SYSTEM_PREVIEW = {
    "visit_booked": "실측 날짜가 정해졌어요",
    "change_requested": "일정 바꾸기 요청이 왔어요",
    "change_done": "실측 일정이 바뀌었어요",
    "change_countered": "업체가 다른 날을 냈어요",
    "visit_cancelled": "실측이 취소됐어요",
    "quote_sent": "실측 견적서가 왔어요",
    "extra_sent": "추가 금액 안내가 왔어요",
    "extra_asked": "추가 금액을 물어봤어요",
    "deal_confirmed": "업체로 확정했어요",
    "other_chosen": "다른 업체로 정했어요",
}
# 띠 · 목록에 실측 날짜를 보이는 실측 상태
BOOKED_LIKE = ("booked", "visited", "quoted", "chosen")
WEEKDAYS = "월화수목금토일"
MUTED = "관리자가 이 대화의 채팅 쓰기를 막았어요."


def _not_found() -> AppError:
    return app_error("not_found", "대화를 찾을 수 없어요.")


def side_of(user: User) -> Side:
    if user.role not in ("customer", "vendor"):
        raise app_error("forbidden")
    return "customer" if user.role == "customer" else "vendor"


def _other(t: Thread, side: Side) -> uuid.UUID | None:
    return t.vendor_id if side == "customer" else t.customer_id


def visit_label(status: str | None, day: date | None, half: str | None) -> str | None:
    """'실측 12.15(화) 오전' (확정한 반나절이 있을 때만)"""
    if status not in BOOKED_LIKE or day is None or half is None:
        return None
    return f"실측 {day:%m.%d}({WEEKDAYS[day.weekday()]}) {'오전' if half == 'am' else '오후'}"


def _preview(m: ThreadMessage) -> str | None:
    if m.kind == "photo":
        return "사진"
    if m.kind == "system":
        return (m.body or SYSTEM_PREVIEW.get(m.system_code or "", ""))[:PREVIEW_MAX] or None
    return None if m.redacted_at or m.body is None else m.body[:PREVIEW_MAX]


def message_out(m: ThreadMessage, me: uuid.UUID, side: Side) -> MessageOut:
    if m.sender_role == "system":
        sender = "system"
    else:
        sender = "me" if m.sender_id == me else "them"
    return MessageOut(
        seq=m.seq,
        id=m.id,
        sender=sender,
        kind=m.kind,
        body=None if m.redacted_at else m.body,
        file_id=m.file_id,
        system_code=m.system_code,
        ref_id=m.ref_id,
        warn=m.warn if side == "customer" else None,  # 주의 줄은 고객 화면만 (D05 A)
        at=m.created_at,
    )


# ---- 다른 기능 service가 부르는 계약 함수 (contract.md 4.1) ----


async def open(  # 계약 이름 thread.service.open (내장 open을 가린다)
    s: AsyncSession,
    *,
    project_id: uuid.UUID,
    vendor_id: uuid.UUID,
    customer_id: uuid.UUID,
    visit_id: uuid.UUID,
    customer_label: str,
    vendor_label: str,
    area_label: str,
) -> uuid.UUID:
    """실측이 확정될 때 visit.service가 부른다. (공사, 업체) 대화가 없으면 만들고, 있으면 가장 최근
    확정 요청(visit_id)으로 바꾸고 다시 연다(차단 · 관리자로 닫힌 것, 고객이 차단한 것은 그대로).
    돌려주는 값: 대화 id.

    이름표는 만든 때 사본이다: customer_label '상계동 고객' · vendor_label 상호 · area_label
    '노원구 상계동 69.4㎡'. 업체 화면에 고객 이름 · 휴대폰을 넣지 않는다.
    """
    sticky = Thread.ro_reason.in_(STICKY)
    blocked = Thread.blocked_at.is_not(None)
    q = (
        insert(Thread)
        .values(
            id=uuid7(),
            project_id=project_id,
            vendor_id=vendor_id,
            customer_id=customer_id,
            visit_id=visit_id,
            customer_label=customer_label[:40],
            vendor_label=vendor_label[:100],
            area_label=area_label[:60],
        )
        .on_conflict_do_update(
            constraint="uq_threads_project_vendor",
            set_={
                "visit_id": visit_id,
                "status": case((sticky, Thread.status), (blocked, "read_only"), else_="open"),
                "ro_reason": case((sticky, Thread.ro_reason), (blocked, "blocked"), else_=None),
                "closed_at": case((or_(sticky, blocked), Thread.closed_at), else_=None),
            },
        )
        .returning(Thread.id)
    )
    return (await s.execute(q)).scalar_one()


async def post_system(
    s: AsyncSession,
    thread_id: uuid.UUID,
    *,
    code: str,
    ref_id: uuid.UUID | None = None,
    body: str | None = None,
) -> int:
    """시스템 카드 한 줄(실측 확정 · 바꾸기 요청 · 견적서 보냄 · 추가 금액 등). 대화 행을 UPDATE로 잠가
    seq를 하나 올리고 그 번호로 글을 넣는다. 돌려주는 값: 새 seq. code는 thread.models.SYSTEM_CODES.
    commit 뒤에 부르는 쪽이 `notify_message(s, thread_id, seq)`로 두 사람의 줄기에 알린다."""
    if code not in SYSTEM_CODES:
        raise ValueError(f"알 수 없는 시스템 카드: {code}")
    now = now_utc()
    seq = (
        await s.execute(
            update(Thread)
            .where(Thread.id == thread_id)
            .values(last_seq=Thread.last_seq + 1, last_message_at=now)
            .returning(Thread.last_seq)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one()
    s.add(
        ThreadMessage(
            id=uuid7(),
            thread_id=thread_id,
            seq=seq,
            sender_role="system",
            kind="system",
            body=body,
            system_code=code,
            ref_id=ref_id,
            created_at=now,
        )
    )
    await s.flush()
    return seq


async def set_read_only(
    s: AsyncSession,
    *,
    reason: RoReason,
    thread_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """대화를 읽기만(read_only)으로 바꾼다. thread_id 또는 (project_id, vendor_id)로 찾는다.
    이미 읽기만이면 사유를 바꾸지 않는다(처음 사유가 남음). 돌려주는 값: 바뀐 대화 id (없거나 이미면 None).
    부르는 곳: 다른 업체 확정(other_chosen) · 실측 취소(cancelled) · 못 받아요(declined) · 탈퇴(withdrawn) ·
    고객 차단(blocked) · 관리자(admin)."""
    if reason not in RO_REASONS:
        raise ValueError(f"알 수 없는 사유: {reason}")
    if thread_id is None and (project_id is None or vendor_id is None):
        raise ValueError("thread_id 또는 (project_id, vendor_id)가 있어야 해요")
    where = (
        [Thread.id == thread_id]
        if thread_id is not None
        else [Thread.project_id == project_id, Thread.vendor_id == vendor_id]
    )
    q = (
        update(Thread)
        .where(*where, Thread.status == "open")
        .values(status="read_only", ro_reason=reason, closed_at=now_utc())
        .returning(Thread.id)
        .execution_options(synchronize_session=False)
    )
    return (await s.execute(q)).scalar_one_or_none()


async def find(s: AsyncSession, project_id: uuid.UUID, vendor_id: uuid.UUID) -> uuid.UUID | None:
    """(공사, 업체) 대화 id (없으면 None). 알림 링크 /chat/{tid}를 만들 때 쓴다."""
    q = select(Thread.id).where(Thread.project_id == project_id, Thread.vendor_id == vendor_id)
    return (await s.execute(q)).scalar_one_or_none()


async def notify_message(s: AsyncSession, thread_id: uuid.UUID, seq: int) -> None:
    """commit 뒤에 부른다: 대화 두 사람의 줄기에 msg {thread_id, seq}를 보낸다(시스템 카드를 넣은 뒤 등)."""
    got = await s.execute(
        select(Thread.customer_id, Thread.vendor_id).where(Thread.id == thread_id)
    )
    row = got.first()
    if row is not None:
        await realtime.push([row[0], row[1]], "msg", {"thread_id": str(thread_id), "seq": seq})


async def redact(s: AsyncSession, thread_id: uuid.UUID, *, now: datetime) -> bool:
    """보관 기간 정리(worker `thread_redact` 일, 부르는 쪽 트랜잭션 안): 닫힌 지 보관 기간이 지난 대화의
    고객 · 업체 글 본문을 지운다(redacted_at). L07: 기간이 None이라 지금은 아무것도 하지 않는다(False)."""
    if THREAD_CONTACT_RETENTION_DAYS is None:
        return False
    t = await s.get(Thread, thread_id)
    cutoff = now - timedelta(days=THREAD_CONTACT_RETENTION_DAYS)
    if t is None or t.status != "read_only" or t.closed_at is None or t.closed_at > cutoff:
        return False
    q = (
        update(ThreadMessage)
        .where(
            ThreadMessage.thread_id == thread_id,
            ThreadMessage.kind == "text",
            ThreadMessage.redacted_at.is_(None),
        )
        .values(body=None, redacted_at=now)
        .execution_options(synchronize_session=False)
    )
    return (await s.execute(q)).rowcount > 0


# ---- 관리자 · 탈퇴가 부르는 함수 (부르는 쪽 트랜잭션 안, 돌려준 Parties로 commit 뒤 push_parties) ----

Parties = list[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]]
_PARTIES = (Thread.id, Thread.customer_id, Thread.vendor_id, Thread.project_id)


async def close_for_user(s: AsyncSession, user: User) -> Parties:
    """탈퇴: 내 대화를 모두 읽기만(withdrawn)으로. 글 · 이름표는 남는다(C53). 이미 닫힌 것은 사유 그대로.
    돌려주는 값: 내 대화 모두 (상대 화면이 다시 읽게)."""
    col = Thread.customer_id if user.role == "customer" else Thread.vendor_id
    await s.execute(
        update(Thread)
        .where(col == user.id, Thread.status == "open")
        .values(status="read_only", ro_reason="withdrawn", closed_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    return [tuple(r) for r in (await s.execute(select(*_PARTIES).where(col == user.id))).all()]


async def mute_vendor(
    s: AsyncSession,
    *,
    at: datetime,
    thread_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
) -> Parties:
    """관리자 '채팅 쓰기 막기'(A02): 그 대화(또는 그 업체의 모든 대화)에서 업체 글쓰기를 막는다."""
    if thread_id is None and vendor_id is None:
        raise ValueError("thread_id 또는 vendor_id가 있어야 해요")
    where = [Thread.id == thread_id] if thread_id is not None else [Thread.vendor_id == vendor_id]
    q = (
        update(Thread)
        .where(*where, Thread.vendor_muted_at.is_(None))
        .values(vendor_muted_at=at)
        .returning(*_PARTIES)
        .execution_options(synchronize_session=False)
    )
    return [tuple(r) for r in (await s.execute(q)).all()]


async def close_for_vendor(s: AsyncSession, vendor_id: uuid.UUID, at: datetime) -> Parties:
    """관리자 업체 멈춤(진행 중도 닫기): 그 업체의 열린 대화를 읽기만(admin)으로."""
    q = (
        update(Thread)
        .where(Thread.vendor_id == vendor_id, Thread.status == "open")
        .values(status="read_only", ro_reason="admin", closed_at=at)
        .returning(*_PARTIES)
        .execution_options(synchronize_session=False)
    )
    return [tuple(r) for r in (await s.execute(q)).all()]


async def reopen_for_vendor(
    s: AsyncSession, vendor_id: uuid.UUID, live_visits: Collection[uuid.UUID]
) -> Parties:
    """업체 멈춤 풀기: 멈춤(admin)으로 닫았던 대화 중 그 요청(visit_id)이 아직 살아 있는 것만 다시 연다
    (live_visits, visit.service가 준다). 멈춤 때 닫힌 요청 · 그사이 끝난 요청의 대화는 읽기만 그대로(dev-05,
    점검 R4#4). 고객이 차단한 대화도 그대로."""
    if not live_visits:
        return []
    q = (
        update(Thread)
        .where(
            Thread.vendor_id == vendor_id,
            Thread.ro_reason == "admin",
            Thread.blocked_at.is_(None),
            Thread.visit_id.in_(list(live_visits)),
        )
        .values(status="open", ro_reason=None, closed_at=None)
        .returning(*_PARTIES)
        .execution_options(synchronize_session=False)
    )
    return [tuple(r) for r in (await s.execute(q)).all()]


async def push_parties(parties: Parties) -> None:
    """commit 뒤에 부른다: 바뀐 대화의 두 사람에게 state {kind: thread}. 업체에는 공사 id를 넣지 않는다."""
    for tid, customer_id, vendor_id, project_id in parties:
        await realtime.push_state([customer_id], "thread", tid, project_id)
        await realtime.push_state([vendor_id], "thread", tid, None)


async def thread_for_report(s: AsyncSession, user: User, thread_id: uuid.UUID) -> Thread | None:
    """신고: 내 대화인지 (아니면 None → 404)"""
    return await repo.thread_of(s, side_of(user), user.id, thread_id)


async def message_in(
    s: AsyncSession, thread_id: uuid.UUID, message_id: uuid.UUID
) -> ThreadMessage | None:
    """신고: 그 대화의 글 (없으면 None)"""
    m = await s.get(ThreadMessage, message_id)
    return m if m is not None and m.thread_id == thread_id else None


async def block_for_report(s: AsyncSession, user: User, thread_id: uuid.UUID) -> bool:
    """신고하면서 차단 (부르는 쪽 트랜잭션 안). 이미 차단했으면 False."""
    return await repo.block(s, thread_id, user.id, now_utc())


# ---- 화면 API ----


async def rows(s: AsyncSession, user: User) -> list[ThreadRowOut]:
    side = side_of(user)
    found = await repo.rows(s, side, user.id)
    last = await repo.last_messages(s, [(t.id, t.last_seq) for t, *_ in found if t.last_seq > 0])
    out = []
    for t, read_seq, v_status, day, half in found:
        m = last.get(t.id)
        out.append(
            ThreadRowOut(
                thread_id=t.id,
                title=t.vendor_label if side == "customer" else t.customer_label,
                visit_label=visit_label(v_status, day, half),
                last=ThreadLastOut(kind=m.kind, preview=_preview(m), at=m.created_at)
                if m is not None
                else None,
                unread=max(t.last_seq - int(read_seq), 0),
                status=t.status,
                ro_reason=t.ro_reason,
            )
        )
    return out


async def _mine(s: AsyncSession, user: User, thread_id: uuid.UUID) -> tuple[Side, Thread]:
    side = side_of(user)
    t = await repo.thread_of(s, side, user.id, thread_id)
    if t is None:
        raise _not_found()
    return side, t


async def _head(s: AsyncSession, user: User, side: Side, t: Thread) -> ThreadOut:
    v_status, open_change = await repo.visit_state(s, t.visit_id)
    deal_id = await repo.deal_of(s, t.visit_id)
    is_open = t.status == "open"
    customer = side == "customer"
    write = is_open and not (side == "vendor" and t.vendor_muted_at is not None)
    if customer:
        quote = f"/projects/{t.project_id}/quotes" if v_status in ("quoted", "chosen") else None
        project = f"/projects/{t.project_id}" if t.project_id else None
    else:
        quote = (
            f"/vendor/requests/{t.visit_id}/quote"
            if t.visit_id and v_status in ("visited", "quoted", "chosen")
            else None
        )
        if deal_id:
            project = f"/vendor/jobs/{deal_id}"
        else:
            project = f"/vendor/requests/{t.visit_id}" if t.visit_id else None
    return ThreadOut(
        thread_id=t.id,
        title=t.vendor_label if customer else t.customer_label,
        area_label=t.area_label,
        visit_id=t.visit_id,
        deal_id=deal_id,
        project_id=t.project_id if customer else None,
        status=t.status,
        ro_reason=t.ro_reason,
        blocked=customer and t.blocked_at is not None,
        last_seq=t.last_seq,
        read_seq=await repo.read_seq(s, t.id, user.id),
        can=ThreadCanOut(
            write=write,
            change_request=customer and is_open and v_status == "booked" and not open_change,
            cancel=customer and is_open and v_status == "booked",
            report=True,
        ),
        links=ThreadLinksOut(quote=quote, project=project),
    )


async def head(s: AsyncSession, user: User, thread_id: uuid.UUID) -> ThreadOut:
    side, t = await _mine(s, user, thread_id)
    return await _head(s, user, side, t)


async def messages(
    s: AsyncSession,
    user: User,
    thread_id: uuid.UUID,
    *,
    after_seq: int | None,
    before_seq: int | None,
    limit: int,
) -> list[MessageOut]:
    side, t = await _mine(s, user, thread_id)
    got = await repo.messages(s, t.id, after_seq=after_seq, before_seq=before_seq, limit=limit)
    return [message_out(m, user.id, side) for m in got]


async def _why_not(s: AsyncSession, side: Side, user: User, thread_id: uuid.UUID) -> AppError:
    """seq를 못 올린 까닭: 없어짐 404 · 읽기만 409 · 업체 쓰기 막힘 403"""
    t = await repo.thread_of(s, side, user.id, thread_id)
    if t is None:
        return _not_found()
    if t.status != "open":
        return app_error("read_only")
    return app_error("forbidden", MUTED)


async def post(
    s: AsyncSession, user: User, thread_id: uuid.UUID, data: MessageIn
) -> tuple[MessageOut, bool]:
    """글 보내기. 돌려주는 값: (글, 새로 넣었는지). 같은 client_key는 처음 글을 그대로 돌려준다."""
    me = user.id  # rollback은 세션의 모든 객체를 만료시켜서, 그 뒤에는 이 값만 쓴다
    side, t = await _mine(s, user, thread_id)
    old = await repo.message_by_key(s, t.id, me, data.client_key)
    if old is not None:
        return message_out(old, me, side), False
    if t.status != "open":
        raise app_error("read_only")
    if side == "vendor" and t.vendor_muted_at is not None:
        raise app_error("forbidden", MUTED)
    if data.kind == "photo" and not await repo.my_photo(s, user.id, data.file_id):
        raise app_error("invalid", "보낼 사진을 다시 골라 주세요.")
    other, tid, address_sent = _other(t, side), t.id, t.address_sent_at is not None
    now = now_utc()
    seq = await repo.next_seq(s, tid, side, me, now)  # 대화 행 잠금
    if seq is None:  # 그사이 닫힘 · 쓰기 막힘
        err = await _why_not(s, side, user, tid)
        await s.rollback()
        raise err
    text = data.body if data.kind == "text" else None
    msg = ThreadMessage(
        id=uuid7(),
        thread_id=tid,
        seq=seq,
        sender_role=side,
        sender_id=me,
        kind=data.kind,
        body=text,
        file_id=data.file_id if data.kind == "photo" else None,
        warn="offsite" if side == "vendor" and rules.offsite(text) else None,
        client_key=data.client_key,
        created_at=now,
    )
    try:  # 글 INSERT는 다음 문장 전에 나가므로(autoflush) 겹침 오류는 여기 어디서든 난다
        s.add(msg)
        await s.flush()
        if side == "customer" and not address_sent and rules.has_address(text):
            await repo.mark_address(s, tid, now)
        await repo.mark_read(s, tid, me, seq)  # 내 글은 읽은 것
        await s.commit()
    except IntegrityError:  # 같은 client_key가 동시에 두 번: 먼저 들어간 글을 돌려준다
        await s.rollback()
        old = await repo.message_by_key(s, tid, me, data.client_key)
        if old is None:
            raise
        return message_out(old, me, side), False
    await realtime.push([other, me], "msg", {"thread_id": str(tid), "seq": seq})
    return message_out(msg, me, side), True


async def read(s: AsyncSession, user: User, thread_id: uuid.UUID, seq: int) -> None:
    """여기까지 읽었어요(줄지 않음). 올랐으면 내 다른 기기에 read 이벤트."""
    _, t = await _mine(s, user, thread_id)
    before = await repo.read_seq(s, t.id, user.id)
    after = await repo.mark_read(s, t.id, user.id, min(seq, t.last_seq))
    await s.commit()
    if after > before:
        await realtime.push([user.id], "read", {"thread_id": str(t.id), "seq": after})


async def file_for(s: AsyncSession, user: User, thread_id: uuid.UUID, file_id: uuid.UUID) -> File:
    """채팅 사진: 대화 두 사람만, 그 대화에 붙은 사진만 (아니면 404)"""
    _, t = await _mine(s, user, thread_id)
    f = await repo.file_row(s, file_id) if await repo.has_file(s, t.id, file_id) else None
    if f is None:
        raise app_error("not_found", "사진을 볼 수 없어요.")
    return f


async def block(s: AsyncSession, user: User, thread_id: uuid.UUID) -> ThreadOut:
    """고객이 업체 차단(C31): 대화는 읽기만(blocked). 이미 차단했으면 409 already."""
    _, t = await _mine(s, user, thread_id)
    if not await repo.block(s, t.id, user.id, now_utc()):
        raise app_error("already", "이미 차단한 업체예요.")
    await s.commit()
    await push_parties([(t.id, t.customer_id, t.vendor_id, t.project_id)])
    return await head(s, user, thread_id)


async def unblock(s: AsyncSession, user: User, thread_id: uuid.UUID) -> ThreadOut:
    """차단 풀기: 차단 때문에 닫힌 대화만 다시 연다. 차단하지 않았으면 409 already."""
    _, t = await _mine(s, user, thread_id)
    if not await repo.unblock(s, t.id, user.id):
        raise app_error("already", "차단하지 않은 업체예요.")
    await s.commit()
    await push_parties([(t.id, t.customer_id, t.vendor_id, t.project_id)])
    return await head(s, user, thread_id)
