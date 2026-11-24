"""신고 · 관리자 처리 · 업체 멈춤 · 회원 정지 · 리뷰 숨김 (dev-07, A02 · A03 · D26).

- 신고: 대상이 내 대화 · 볼 수 있는 업체 · 보이는 링크인지 확인. 채팅이면 그 글 사본(evidence)을 남기고,
  block이면 대화를 읽기만(blocked)으로. 신고된 글은 관리자 화면에 데이터로만 보인다.
- 처리: 열린 신고만 한 번(조건부 UPDATE, 아니면 409 already) → 조치 실행 → admin_actions → 알림(신고한 사람 ·
  업체) → commit → 줄기. 경고 · 쓰기 막기 · 업체 멈춤 · 링크 숨김 · 문제없음.
- 업체 멈춤(D26): 새 요청만(new) · 진행 중도(all). all은 그 업체의 열린 대화를 읽기만(admin)으로 닫는다.
  진행 중 실측 요청 닫기 · 고객 다시 고르기 안내는 visit.service.close_for_vendor, 업체 멈춤 칸 · 외부 링크
  상태는 vendor.service(suspend · unsuspend · set_review_link_status)가 바꾼다(다른 기능은 그 service로).
- 관리자 화면에도 고객 이름 · 연락처를 보이지 않는다(신고한 사람 = '수유동 고객').
"""

import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.account import service as account_service
from app.auth.models import User
from app.notify import catalog
from app.notify import service as notify
from app.realtime import service as realtime
from app.report import repository as repo
from app.report.models import Report
from app.report.schemas import (
    AdminActionOut,
    MemberPageOut,
    MemberRowOut,
    MemberStateOut,
    ReportDetailOut,
    ReportIn,
    ReportOut,
    ReportPageOut,
    ReportRowOut,
    ResolveIn,
)
from app.review import service as review_service
from app.review.schemas import ReviewStateOut
from app.shared.clock import now_utc
from app.shared.errors import AppError, app_error
from app.shared.ids import uuid7
from app.thread import service as thread_service
from app.vendor import service as vendor_service
from app.vendor.schemas import LinkCheckIn, ReviewLinkAdminOut, VendorSuspendOut
from app.visit import service as visit_service

GONE = "탈퇴한 회원"
VENDOR_ACTIONS = ("warn", "mute_chat", "suspend_new", "suspend_all")
DUPLICATE = "이미 신고한 글이에요. 믿집이 확인하고 있어요."


def _not_found(what: str) -> AppError:
    return app_error("not_found", f"{what} 찾을 수 없어요.")


# ---- 신고 (고객 · 업체) ----


async def create(s: AsyncSession, user: User, data: ReportIn) -> ReportOut:
    vendor_id: uuid.UUID | None = None
    thread_id = message_id = None
    evidence: str | None = None
    parties: thread_service.Parties = []
    if data.kind == "chat":
        t = await thread_service.thread_for_report(s, user, data.thread_id)
        if t is None:
            raise _not_found("대화를")
        thread_id = t.id
        if user.role == "customer":
            vendor_id = t.vendor_id
        if data.message_id is not None:
            m = await thread_service.message_in(s, t.id, data.message_id)
            if m is None:
                raise _not_found("글을")
            if m.sender_role == "system" or m.sender_id == user.id:
                raise app_error("invalid", "상대가 보낸 글만 신고할 수 있어요.")
            if await repo.open_on_message(s, user.id, m.id):
                raise app_error("already", DUPLICATE)
            message_id = m.id
            evidence = (m.body if m.kind == "text" else "(사진)") if not m.redacted_at else None
        if data.block:
            if user.role != "customer":
                raise app_error("forbidden", "차단은 고객만 할 수 있어요.")
            if await thread_service.block_for_report(s, user, t.id):
                parties = [(t.id, t.customer_id, t.vendor_id, t.project_id)]
    else:
        if user.role != "customer":
            raise app_error("forbidden", "업체 · 링크 신고는 고객만 할 수 있어요.")
        v = await repo.vendor(s, data.vendor_id)
        if v is None or v.status != "approved":
            raise _not_found("업체를")
        vendor_id = v.user_id
        if data.kind == "link":
            link = await repo.link(s, v.user_id, data.link_sort)
            if link is None or link.status != "shown":
                raise _not_found("링크를")
            evidence = link.url
    now = now_utc()
    r = Report(
        id=uuid7(),
        kind=data.kind,
        reporter_id=user.id,
        vendor_id=vendor_id,
        thread_id=thread_id,
        message_id=message_id,
        link_sort=data.link_sort if data.kind == "link" else None,
        reason_code=data.reason_code,
        note=data.note,
        evidence=evidence[:1000] if evidence else None,
        block=bool(data.block),
        status="open",
        created_at=now,
    )
    s.add(r)
    try:
        await s.commit()
    except IntegrityError as exc:  # 같은 글을 처리 전에 동시에 또 신고
        await s.rollback()
        raise app_error("already", DUPLICATE) from exc
    await thread_service.push_parties(parties)
    return ReportOut(id=r.id, kind=r.kind, status=r.status, created_at=r.created_at)


# ---- 관리자 신고 목록 · 자세히 · 처리 (A02) ----


def _row(r: Report, vendor_name: str | None, reporter_role: str | None) -> dict:
    return {
        "id": r.id,
        "kind": r.kind,
        "reason_code": r.reason_code,
        "status": r.status,
        "action": r.action,
        "reporter_role": reporter_role if reporter_role in ("customer", "vendor") else None,
        "vendor_id": r.vendor_id,
        "vendor_name": vendor_name,
        "thread_id": r.thread_id,
        "block": r.block,
        "created_at": r.created_at,
        "resolved_at": r.resolved_at,
    }


async def page(s: AsyncSession, status: str, kind: str | None) -> ReportPageOut:
    rows = await repo.page(s, status, kind)
    return ReportPageOut(
        items=[ReportRowOut(**_row(r, name, role)) for r, name, role in rows],
        counts=await repo.counts(s, status),
    )


async def _reporter_label(s: AsyncSession, r: Report, role: str | None) -> str:
    """이름 없이: 채팅이면 대화 이름표('수유동 고객' · 상호), 아니면 '동 고객' · 상호"""
    if role is None:
        return GONE
    labels = await repo.thread_labels(s, r.thread_id)
    if role == "customer":
        if labels is not None:
            return labels[0]
        area = await repo.latest_area(s, r.reporter_id)
        return f"{area} 고객" if area else "고객"
    if labels is not None:
        return labels[1]
    return await repo.biz_name(s, r.reporter_id) or "업체"


async def detail(s: AsyncSession, report_id: uuid.UUID) -> ReportDetailOut:
    r = await repo.report(s, report_id)
    if r is None:
        raise _not_found("신고를")
    role, _ = await repo.names(s, r.reporter_id)
    link = (
        await repo.link(s, r.vendor_id, r.link_sort)
        if r.kind == "link" and r.vendor_id is not None and r.link_sort is not None
        else None
    )
    history = [
        AdminActionOut(id=a.id, action=a.action, note=a.note, admin_name=name, at=a.at)
        for a, name in await repo.history(s, r.id)
    ]
    return ReportDetailOut(
        **_row(r, await repo.biz_name(s, r.vendor_id), role),
        reporter_label=await _reporter_label(s, r, role),
        note=r.note,
        evidence=r.evidence,
        link_sort=r.link_sort,
        link_label=link.label if link else None,
        link_url=link.url if link else None,
        admin_note=r.admin_note,
        history=history,
    )


async def _tell_vendor(s: AsyncSession, vendor_id: uuid.UUID, kind: str, key: str) -> None:
    await notify.add(
        s,
        user_id=vendor_id,
        kind=kind,
        body=catalog.KINDS[kind].example,
        link=catalog.link(kind),
        dedup_key=f"{kind}:{key}",
    )


async def _suspend(
    s: AsyncSession,
    admin: User,
    vendor_id: uuid.UUID,
    scope: str,
    note: str | None,
    at: datetime,
    report_id: uuid.UUID | None = None,
) -> tuple[VendorSuspendOut, thread_service.Parties]:
    if await repo.vendor(s, vendor_id) is None:
        raise _not_found("업체를")
    got = await vendor_service.suspend(s, vendor_id, scope, at)
    if got is None:
        raise app_error("already", "이미 멈춘 업체예요.")
    closed, parties = 0, []
    if scope == "all":
        # 잠금 순서(프로젝트 → 요청 → 대화): 실측 요청을 먼저 닫고 대화를 닫는다
        closed = await visit_service.close_for_vendor(s, vendor_id, at)
        parties = await thread_service.close_for_vendor(s, vendor_id, at)
    action = repo.add_action(
        s,
        admin_id=admin.id,
        action="suspend_vendor",
        at=at,
        target_user_id=vendor_id,
        report_id=report_id,
        note=note,
    )
    await _tell_vendor(s, vendor_id, "vendor_suspended", str(action.id))
    out = VendorSuspendOut(
        vendor_id=vendor_id, suspended_at=got[0], suspend_scope=got[1], closed_visits=closed
    )
    return out, parties


async def _hide_reported(
    s: AsyncSession, admin: User, vendor_id: uuid.UUID, url: str | None, now: datetime
) -> None:
    """링크 신고 '링크 숨김': 신고한 주소(evidence)의 링크만 숨긴다. 그사이 업체가 링크를 빼거나 고쳐 다른 링크가
    그 자리로 당겨져도 그 링크는 숨기지 않고, 신고한 주소를 다른 자리로 옮겼으면 거기서 숨긴다(점검 R3#4).
    숨긴 링크가 없으면 되돌리고 409(신고는 열린 채 — 다른 처리를 고른다)."""
    rows = await repo.links_by_url(s, vendor_id, url) if url else []
    already = any(x.status == "hidden" for x in rows)
    changed = False
    for x in rows:
        got = await vendor_service.set_review_link_status(
            s, vendor_id, x.sort, "hidden", by=admin.id, at=now, url=x.url
        )
        changed = changed or got is not None
    if changed:
        return
    await s.rollback()
    if already:
        raise app_error("already", "신고한 링크는 이미 숨겼어요. 다른 처리를 골라 주세요.")
    raise app_error(
        "stale", "그사이 업체가 신고한 링크를 빼거나 고쳤어요. 다른 처리를 골라 주세요."
    )


async def resolve(
    s: AsyncSession, admin: User, report_id: uuid.UUID, data: ResolveIn
) -> ReportDetailOut:
    r = await repo.report(s, report_id)
    if r is None:
        raise _not_found("신고를")
    if r.status != "open":
        raise app_error("already", "이미 처리한 신고예요.")
    if data.action == "hide_link" and r.kind != "link":
        raise app_error("invalid", "링크 신고에서만 링크를 숨길 수 있어요.")
    if data.action in VENDOR_ACTIONS and r.vendor_id is None:
        raise app_error("invalid", "업체가 없는 신고에는 할 수 없는 처리예요.")
    now = now_utc()
    if not await repo.close(s, r.id, action=data.action, note=data.note, by=admin.id, at=now):
        await s.rollback()
        raise app_error("already", "이미 처리한 신고예요.")
    parties: thread_service.Parties = []
    vendor_id = r.vendor_id
    key = str(r.id)

    def record(action: str) -> None:
        repo.add_action(
            s,
            admin_id=admin.id,
            action=action,
            at=now,
            target_user_id=vendor_id,
            report_id=r.id,
            note=data.note,
        )

    if data.action == "warn":
        record("warn_vendor")
        await _tell_vendor(s, vendor_id, "vendor_warned", key)
    elif data.action == "mute_chat":
        if r.thread_id is not None:
            parties = await thread_service.mute_vendor(s, at=now, thread_id=r.thread_id)
        else:
            parties = await thread_service.mute_vendor(s, at=now, vendor_id=vendor_id)
        record("mute_vendor")
        await _tell_vendor(s, vendor_id, "vendor_muted", key)
    elif data.action in ("suspend_new", "suspend_all"):
        scope = "new" if data.action == "suspend_new" else "all"
        _, parties = await _suspend(s, admin, vendor_id, scope, data.note, now, r.id)
    elif data.action == "hide_link":
        if vendor_id is not None and r.link_sort is not None:
            await _hide_reported(s, admin, vendor_id, r.evidence, now)
            record("link_hidden")
            await _tell_vendor(s, vendor_id, "link_checked", key)
        else:
            record("dismiss_report")
    else:
        record("dismiss_report")
    if r.reporter_id is not None:
        await notify.add(
            s,
            user_id=r.reporter_id,
            kind="report_resolved",
            body=catalog.KINDS["report_resolved"].example,
            link=catalog.link("report_resolved"),
            dedup_key=f"report_resolved:{r.id}",
        )
    await s.commit()
    await visit_service.flush_later(s)  # 업체 멈춤으로 닫은 실측 요청의 화면 신호
    await notify.push_unread(s, [r.reporter_id, vendor_id])
    await thread_service.push_parties(parties)
    return await detail(s, r.id)


# ---- 관리자 업체 멈춤 (신고 없이도, D26) ----


async def suspend_vendor(
    s: AsyncSession, admin: User, vendor_id: uuid.UUID, scope: str, note: str
) -> VendorSuspendOut:
    out, parties = await _suspend(s, admin, vendor_id, scope, note, now_utc())
    await s.commit()
    await visit_service.flush_later(s)  # 닫은 실측 요청의 화면 신호(고객 · 업체)
    await notify.push_unread(s, [vendor_id])
    await thread_service.push_parties(parties)
    return out


async def unsuspend_vendor(
    s: AsyncSession, admin: User, vendor_id: uuid.UUID, note: str | None
) -> VendorSuspendOut:
    if await repo.vendor(s, vendor_id) is None:
        raise _not_found("업체를")
    if not await vendor_service.unsuspend(s, vendor_id):
        raise app_error("already", "멈추지 않은 업체예요.")
    live = await visit_service.live_ids_of_vendor(s, vendor_id)
    parties = await thread_service.reopen_for_vendor(s, vendor_id, live)
    repo.add_action(
        s,
        admin_id=admin.id,
        action="unsuspend_vendor",
        at=now_utc(),
        target_user_id=vendor_id,
        note=note,
    )
    await s.commit()
    await thread_service.push_parties(parties)
    return VendorSuspendOut(
        vendor_id=vendor_id, suspended_at=None, suspend_scope=None, closed_visits=0
    )


# ---- 관리자 외부 리뷰 링크 확인 (A01, vendor-01) ----


async def check_link(
    s: AsyncSession, admin: User, vendor_id: uuid.UUID, sort: int, data: LinkCheckIn
) -> ReviewLinkAdminOut:
    """외부 리뷰 링크 보여요 · 숨김. 관리자가 본 주소(url)를 주면 그 주소일 때만 바꾼다(그사이 업체가
    고쳤으면 409 stale). 이미 그 상태면 409 already. 업체 알림 · admin_actions 기록."""
    if await repo.vendor(s, vendor_id) is None:
        raise _not_found("업체를")
    before = await repo.link(s, vendor_id, sort)
    if before is None:
        raise _not_found("링크를")
    now = now_utc()
    got = await vendor_service.set_review_link_status(
        s, vendor_id, sort, data.status, by=admin.id, at=now, note=data.note, url=data.url
    )
    if got is None:
        await s.rollback()
        now_row = await repo.link(s, vendor_id, sort)
        if now_row is None:
            raise _not_found("링크를")
        if data.url is not None and now_row.url != data.url:
            raise app_error("stale", "그사이 업체가 링크를 고쳤어요. 새 주소를 다시 확인해 주세요.")
        raise app_error("already", "이미 그렇게 둔 링크예요.")
    action = repo.add_action(
        s,
        admin_id=admin.id,
        action="link_shown" if data.status == "shown" else "link_hidden",
        at=now,
        target_user_id=vendor_id,
        note=data.note,
    )
    await _tell_vendor(s, vendor_id, "link_checked", str(action.id))
    await s.commit()
    await notify.push_unread(s, [vendor_id])
    return got


# ---- 관리자 회원 (A03) ----


async def members(
    s: AsyncSession, *, q: str | None, status: str | None, before: datetime | None
) -> MemberPageOut:
    rows = await repo.members(s, q=q, status=status, before=before)
    items = [
        MemberRowOut(
            user_id=u.id,
            name=u.name,
            email=u.email,
            role=u.role,
            status=u.status,
            created_at=u.created_at,
            project_count=n,
        )
        for u, n in rows
    ]
    more = len(rows) == repo.MEMBERS_PAGE
    return MemberPageOut(items=items, next_before=rows[-1][0].created_at if more else None)


async def set_member(
    s: AsyncSession, admin: User, user_id: uuid.UUID, status: str, note: str | None
) -> MemberStateOut:
    """정지(suspended) · 풀기(active). 관리자 계정은 403, 이미 그 상태면 409 already."""
    target = await repo.member(s, user_id)
    if target is None:
        raise _not_found("회원을")
    if target.role == "admin":
        raise app_error("forbidden", "관리자 계정은 정지할 수 없어요.")
    if not await account_service.set_status(s, user_id, status):
        raise app_error(
            "already",
            "이미 정지한 회원이에요." if status == "suspended" else "정지하지 않은 회원이에요.",
        )
    repo.add_action(
        s,
        admin_id=admin.id,
        action="suspend_user" if status == "suspended" else "unsuspend_user",
        at=now_utc(),
        target_user_id=user_id,
        note=note,
    )
    await s.commit()
    return MemberStateOut(user_id=user_id, status=status)


# ---- 관리자 리뷰 숨김 · 다시 보이기 (C49 기준 코드만) ----


async def set_review(
    s: AsyncSession, admin: User, review_id: uuid.UUID, code: str | None, note: str | None
) -> ReviewStateOut:
    """code가 있으면 숨김, None이면 다시 보이기. 없으면 404, 이미 그 상태면 409 already."""
    if await review_service.exists(s, review_id) is None:
        raise _not_found("리뷰를")
    if code is not None:
        vendor_id = await review_service.set_hidden(s, review_id, code)
    else:
        vendor_id = await review_service.set_shown(s, review_id)
    if vendor_id is None:
        raise app_error("already", "이미 숨긴 리뷰예요." if code else "이미 보이는 리뷰예요.")
    repo.add_action(
        s,
        admin_id=admin.id,
        action="hide_review" if code else "show_review",
        at=now_utc(),
        target_user_id=vendor_id,
        review_id=review_id,
        note=note,
    )
    await s.commit()
    await realtime.push_state([vendor_id], "review", review_id)
    return ReviewStateOut(id=review_id, status="hidden" if code else "shown", hidden_code=code)
