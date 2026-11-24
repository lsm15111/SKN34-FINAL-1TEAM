"""신고 · 처리 기록 · 회원 목록 DB. 업체 멈춤 칸(vendors.suspended_at · suspend_scope)과 외부 리뷰 링크
숨김(vendor_review_links.status)은 vendor 기능에 쓰는 함수가 아직 없어 여기서 바꾼다(b1b.md 부탁:
vendor.service에 함수가 생기면 그것을 부른다). 그 밖의 다른 기능 표는 읽기만 한다."""

import uuid
from datetime import datetime

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.project.models import Project
from app.report.models import AdminAction, Report
from app.shared.ids import uuid7
from app.thread.models import Thread
from app.vendor.models import Vendor, VendorReviewLink

LIST_MAX = 200
MEMBERS_PAGE = 50
DONE = ("resolved", "dismissed")


def _status_filter(q: Select, status: str) -> Select:
    return (
        q.where(Report.status == "open") if status == "open" else q.where(Report.status.in_(DONE))
    )


async def open_on_message(s: AsyncSession, reporter_id: uuid.UUID, message_id: uuid.UUID) -> bool:
    q = select(Report.id).where(
        Report.reporter_id == reporter_id,
        Report.message_id == message_id,
        Report.status == "open",
    )
    return (await s.execute(q)).first() is not None


async def report(s: AsyncSession, report_id: uuid.UUID) -> Report | None:
    q = select(Report).where(Report.id == report_id).execution_options(populate_existing=True)
    return (await s.execute(q)).scalar_one_or_none()


async def page(s: AsyncSession, status: str, kind: str | None) -> list[tuple]:
    """(신고, 업체 상호, 신고한 사람 역할) 최근 순"""
    q = (
        select(Report, Vendor.biz_name, User.role)
        .outerjoin(Vendor, Vendor.user_id == Report.vendor_id)
        .outerjoin(User, User.id == Report.reporter_id)
    )
    q = _status_filter(q, status)
    if kind is not None:
        q = q.where(Report.kind == kind)
    q = q.order_by(Report.created_at.desc(), Report.id.desc()).limit(LIST_MAX)
    return [tuple(r) for r in (await s.execute(q)).all()]


async def counts(s: AsyncSession, status: str) -> dict[str, int]:
    """처리 기다림 · 처리함 수 + 고른 탭(status)의 종류별 수"""
    q = select(Report.status, func.count()).group_by(Report.status)
    by_status = {k: int(v) for k, v in (await s.execute(q)).all()}
    out = {"open": by_status.get("open", 0), "done": sum(by_status.get(x, 0) for x in DONE)}
    q = _status_filter(select(Report.kind, func.count()), status).group_by(Report.kind)
    kinds = dict((await s.execute(q)).all())
    out.update({k: int(kinds.get(k, 0)) for k in ("chat", "vendor", "link")})
    return out


async def names(s: AsyncSession, user_id: uuid.UUID | None) -> tuple[str | None, str | None]:
    """(역할, 이름) — 관리자 이름 · 신고한 사람 역할"""
    if user_id is None:
        return None, None
    row = (await s.execute(select(User.role, User.name).where(User.id == user_id))).first()
    return (row[0], row[1]) if row else (None, None)


async def biz_name(s: AsyncSession, vendor_id: uuid.UUID | None) -> str | None:
    if vendor_id is None:
        return None
    q = select(Vendor.biz_name).where(Vendor.user_id == vendor_id)
    return (await s.execute(q)).scalar_one_or_none()


async def thread_labels(s: AsyncSession, thread_id: uuid.UUID | None) -> tuple[str, str] | None:
    """(고객 이름표, 업체 이름표) — '수유동 고객' · 상호"""
    if thread_id is None:
        return None
    q = select(Thread.customer_label, Thread.vendor_label).where(Thread.id == thread_id)
    row = (await s.execute(q)).first()
    return (row[0], row[1]) if row else None


async def latest_area(s: AsyncSession, owner_id: uuid.UUID) -> str | None:
    """고객의 최근 공사 동(없으면 구). 이름 대신 '상계동 고객'으로 보이려고"""
    q = (
        select(Project.emd, Project.sgg)
        .where(Project.owner_id == owner_id)
        .order_by(Project.created_at.desc())
        .limit(1)
    )
    row = (await s.execute(q)).first()
    return (row[0] or row[1]) if row else None


async def history(s: AsyncSession, report_id: uuid.UUID) -> list[tuple[AdminAction, str | None]]:
    q = (
        select(AdminAction, User.name)
        .outerjoin(User, User.id == AdminAction.admin_id)
        .where(AdminAction.report_id == report_id)
        .order_by(AdminAction.at, AdminAction.id)
    )
    return [tuple(r) for r in (await s.execute(q)).all()]


async def close(
    s: AsyncSession,
    report_id: uuid.UUID,
    *,
    action: str,
    note: str | None,
    by: uuid.UUID,
    at: datetime,
) -> bool:
    """열린 신고만 처리함(resolved) · 문제없음(dismissed)으로. 이미 처리했으면 False"""
    q = (
        update(Report)
        .where(Report.id == report_id, Report.status == "open")
        .values(
            status="dismissed" if action == "none" else "resolved",
            action=action,
            admin_note=note,
            resolved_by=by,
            resolved_at=at,
        )
        .returning(Report.id)
        .execution_options(synchronize_session=False)
    )
    return (await s.execute(q)).scalar_one_or_none() is not None


def add_action(
    s: AsyncSession,
    *,
    admin_id: uuid.UUID,
    action: str,
    at: datetime,
    target_user_id: uuid.UUID | None = None,
    report_id: uuid.UUID | None = None,
    review_id: uuid.UUID | None = None,
    note: str | None = None,
) -> AdminAction:
    row = AdminAction(
        id=uuid7(),  # 알림 dedup_key에 쓰려고 미리 만든다
        admin_id=admin_id,
        action=action,
        target_user_id=target_user_id,
        report_id=report_id,
        review_id=review_id,
        note=note,
        at=at,
    )
    s.add(row)
    return row


# ---- 업체 (보기 · 링크 읽기. 멈춤 · 링크 상태 바꾸기는 vendor.service) ----


async def vendor(s: AsyncSession, vendor_id: uuid.UUID) -> Vendor | None:
    q = select(Vendor).where(Vendor.user_id == vendor_id).execution_options(populate_existing=True)
    return (await s.execute(q)).scalar_one_or_none()


async def link(s: AsyncSession, vendor_id: uuid.UUID, sort: int) -> VendorReviewLink | None:
    q = select(VendorReviewLink).where(
        VendorReviewLink.vendor_id == vendor_id, VendorReviewLink.sort == sort
    )
    return (await s.execute(q)).scalar_one_or_none()


async def links_by_url(s: AsyncSession, vendor_id: uuid.UUID, url: str) -> list[VendorReviewLink]:
    """그 업체 링크 중 이 주소인 것(신고한 주소를 업체가 다른 자리로 옮겼어도 찾는다)"""
    q = (
        select(VendorReviewLink)
        .where(VendorReviewLink.vendor_id == vendor_id, VendorReviewLink.url == url)
        .order_by(VendorReviewLink.sort)
    )
    return list((await s.execute(q.execution_options(populate_existing=True))).scalars())


# ---- 회원 (A03) ----


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def members(
    s: AsyncSession, *, q: str | None, status: str | None, before: datetime | None
) -> list[tuple[User, int]]:
    """고객 · 업체 회원 (관리자는 빼요), 가입 최근 순. (회원, 공사 수)"""
    projects = (
        select(func.count())
        .select_from(Project)
        .where(Project.owner_id == User.id)
        .scalar_subquery()
    )
    sel = select(User, projects).where(User.role.in_(("customer", "vendor")))
    if q:
        pat = _like(q.strip().lower())
        sel = sel.where(
            or_(func.lower(User.name).like(pat, escape="\\"), User.email.like(pat, escape="\\"))
        )
    if status is not None:
        sel = sel.where(User.status == status)
    if before is not None:
        sel = sel.where(User.created_at < before)
    sel = sel.order_by(User.created_at.desc(), User.id.desc()).limit(MEMBERS_PAGE)
    return [(u, int(n)) for u, n in (await s.execute(sel)).all()]


async def member(s: AsyncSession, user_id: uuid.UUID) -> User | None:
    q = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    return (await s.execute(q)).scalar_one_or_none()
