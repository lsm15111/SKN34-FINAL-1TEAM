"""리뷰 DB 읽기 · 쓰기. 공사 · 프로젝트 · 업체 · 파일 표는 읽기 조인으로만 본다."""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.files.models import File
from app.project.models import Project, ProjectTrade
from app.review.models import Review, ReviewHold, ReviewPhoto, ReviewReply
from app.schedule.models import Deal
from app.vendor.models import Vendor, VendorReviewLink


async def project_of(s: AsyncSession, owner_id: uuid.UUID, project_id: uuid.UUID) -> Project | None:
    q = select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    return (await s.execute(q)).scalar_one_or_none()


async def deal_in(s: AsyncSession, project_id: uuid.UUID, deal_id: uuid.UUID) -> Deal | None:
    q = select(Deal).where(Deal.id == deal_id, Deal.project_id == project_id)
    return (await s.execute(q)).scalar_one_or_none()


async def grade_of(s: AsyncSession, project_id: uuid.UUID, trade: str) -> str | None:
    q = select(ProjectTrade.grade).where(
        ProjectTrade.project_id == project_id, ProjectTrade.trade == trade
    )
    return (await s.execute(q)).scalar_one_or_none()


async def vendor_listed(s: AsyncSession, vendor_id: uuid.UUID) -> bool:
    q = select(Vendor.user_id).where(Vendor.user_id == vendor_id, Vendor.status == "approved")
    return (await s.execute(q)).first() is not None


async def shown_links(s: AsyncSession, vendor_id: uuid.UUID) -> list[VendorReviewLink]:
    q = (
        select(VendorReviewLink)
        .where(VendorReviewLink.vendor_id == vendor_id, VendorReviewLink.status == "shown")
        .order_by(VendorReviewLink.sort)
    )
    return list((await s.execute(q)).scalars())


async def review(s: AsyncSession, review_id: uuid.UUID) -> Review | None:
    q = select(Review).where(Review.id == review_id).execution_options(populate_existing=True)
    return (await s.execute(q)).scalar_one_or_none()


async def by_deal(s: AsyncSession, deal_id: uuid.UUID) -> Review | None:
    return (await s.execute(select(Review).where(Review.deal_id == deal_id))).scalar_one_or_none()


async def free_photos(s: AsyncSession, owner_id: uuid.UUID, file_ids: list[uuid.UUID]) -> int:
    """내가 올린 리뷰 사진 중 아직 다른 리뷰에 붙지 않은 것의 수"""
    if not file_ids:
        return 0
    used = select(ReviewPhoto.file_id).where(ReviewPhoto.file_id.in_(file_ids))
    q = (
        select(func.count())
        .select_from(File)
        .where(
            File.id.in_(file_ids),
            File.owner_id == owner_id,
            File.kind == "review_photo",
            File.id.not_in(used),
        )
    )
    return int((await s.execute(q)).scalar_one())


async def set_photos(
    s: AsyncSession, review_id: uuid.UUID, file_ids: list[uuid.UUID], *, replace: bool
) -> None:
    if replace:
        await s.execute(delete(ReviewPhoto).where(ReviewPhoto.review_id == review_id))
    for i, fid in enumerate(file_ids):
        s.add(ReviewPhoto(review_id=review_id, file_id=fid, sort=i))


async def photos_of(s: AsyncSession, review_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    out: dict[uuid.UUID, list] = {rid: [] for rid in review_ids}
    if not review_ids:
        return out
    q = (
        select(ReviewPhoto.review_id, ReviewPhoto.file_id)
        .where(ReviewPhoto.review_id.in_(review_ids))
        .order_by(ReviewPhoto.review_id, ReviewPhoto.sort)
    )
    for rid, fid in (await s.execute(q)).all():
        out[rid].append(fid)
    return out


async def replies_of(s: AsyncSession, review_ids: list[uuid.UUID]) -> dict[uuid.UUID, ReviewReply]:
    if not review_ids:
        return {}
    q = select(ReviewReply).where(ReviewReply.review_id.in_(review_ids))
    return {r.review_id: r for r in (await s.execute(q)).scalars()}


async def names_of(s: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = [u for u in user_ids if u is not None]
    if not ids:
        return {}
    q = select(User.id, User.name).where(User.id.in_(ids))
    return dict((await s.execute(q)).all())


async def page(
    s: AsyncSession,
    vendor_id: uuid.UUID,
    *,
    shown_only: bool,
    sort: str = "latest",
    before: datetime | None = None,
    waiting_only: bool = False,
    limit: int | None = None,
) -> list[Review]:
    q = select(Review).where(Review.vendor_id == vendor_id)
    if shown_only:
        q = q.where(Review.status == "shown")
    if waiting_only:
        replied = select(ReviewReply.review_id)
        q = q.where(Review.id.not_in(replied))
    if sort == "low":
        q = q.order_by(Review.rating, Review.created_at.desc(), Review.id.desc())
    else:
        if before is not None:
            q = q.where(Review.created_at < before)
        q = q.order_by(Review.created_at.desc(), Review.id.desc())
    if limit is not None:
        q = q.limit(limit)
    return list((await s.execute(q)).scalars())


async def rating(s: AsyncSession, vendor_id: uuid.UUID) -> tuple[int, int, dict[str, int], int]:
    """(별점 합, 리뷰 수, 칩별 수, 믿집에서 끝낸 공사 수). 숨긴 리뷰는 뺀다."""
    total, count = (
        await s.execute(
            select(func.coalesce(func.sum(Review.rating), 0), func.count()).where(
                Review.vendor_id == vendor_id, Review.status == "shown"
            )
        )
    ).one()
    tag = func.unnest(Review.tags).label("tag")
    tags_q = select(tag).where(Review.vendor_id == vendor_id, Review.status == "shown").subquery()
    tags = dict((await s.execute(select(tags_q.c.tag, func.count()).group_by(tags_q.c.tag))).all())
    done = (
        await s.execute(
            select(func.count())
            .select_from(Deal)
            .where(Deal.vendor_id == vendor_id, Deal.status == "done")
        )
    ).scalar_one()
    return int(total), int(count), {k: int(v) for k, v in tags.items()}, int(done)


async def waiting_count(s: AsyncSession, vendor_id: uuid.UUID) -> int:
    replied = select(ReviewReply.review_id)
    q = (
        select(func.count())
        .select_from(Review)
        .where(
            Review.vendor_id == vendor_id,
            Review.status == "shown",
            Review.id.not_in(replied),
        )
    )
    return int((await s.execute(q)).scalar_one())


async def has_photo(s: AsyncSession, review_id: uuid.UUID, file_id: uuid.UUID) -> bool:
    q = select(ReviewPhoto.file_id).where(
        ReviewPhoto.review_id == review_id, ReviewPhoto.file_id == file_id
    )
    return (await s.execute(q)).first() is not None


async def file_row(s: AsyncSession, file_id: uuid.UUID) -> File | None:
    return await s.get(File, file_id)


async def reply_of(s: AsyncSession, review_id: uuid.UUID) -> ReviewReply | None:
    q = (
        select(ReviewReply)
        .where(ReviewReply.review_id == review_id)
        .execution_options(populate_existing=True)
    )
    return (await s.execute(q)).scalar_one_or_none()


async def set_status(
    s: AsyncSession, review_id: uuid.UUID, *, hidden_code: str | None
) -> uuid.UUID | None:
    """숨김(hidden_code) · 다시 보이기(None). 이미 그 상태면 None. 돌려주는 값: 업체 id"""
    if hidden_code is None:
        where, values = Review.status == "hidden", {"status": "shown", "hidden_code": None}
    else:
        where, values = Review.status == "shown", {"status": "hidden", "hidden_code": hidden_code}
    q = (
        update(Review)
        .where(Review.id == review_id, where)
        .values(**values)
        .returning(Review.vendor_id)
        .execution_options(synchronize_session=False)
    )
    return (await s.execute(q)).scalar_one_or_none()


async def hold(s: AsyncSession, deal_id: uuid.UUID, hidden_code: str) -> None:
    """숨긴 리뷰를 지운 공사로 남긴다(이미 있으면 기준만 바꾼다)"""
    q = (
        insert(ReviewHold)
        .values(deal_id=deal_id, hidden_code=hidden_code)
        .on_conflict_do_update(
            index_elements=[ReviewHold.deal_id], set_={"hidden_code": hidden_code}
        )
    )
    await s.execute(q)


async def held_code(s: AsyncSession, deal_id: uuid.UUID) -> str | None:
    """그 공사에 다시 쓴 리뷰가 숨긴 채로 시작할 기준(없으면 None)"""
    q = select(ReviewHold.hidden_code).where(ReviewHold.deal_id == deal_id)
    return (await s.execute(q)).scalar_one_or_none()


async def drop_hold_of(s: AsyncSession, review_id: uuid.UUID) -> None:
    """관리자가 다시 보이게 한 리뷰의 공사 표시를 지운다"""
    deal = select(Review.deal_id).where(Review.id == review_id).scalar_subquery()
    await s.execute(delete(ReviewHold).where(ReviewHold.deal_id == deal))
