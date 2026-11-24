"""리뷰 · 답글 (dev-07, I4). 공사가 끝난(done) 그 공사의 고객만, 공사마다 한 번.

- 업체 화면에는 쓴 사람 이름을 보내지 않는다('고객'). 고객 화면은 '김○○', 탈퇴한 고객은 '탈퇴한 고객'(L08).
- 숨긴 리뷰(관리자)는 고객 화면 · 별점에서 빠지고, 업체에게는 '숨김'으로 보인다.
- 관리자 숨김 · 다시 보이기는 report.service가 set_hidden · set_shown을 부른다(처리 기록 admin_actions와 같이).
"""

import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.calc import rating as rating_calc
from app.calc.dobae import GRADE_PAPER
from app.files.models import File
from app.notify import catalog
from app.notify import service as notify
from app.realtime import service as realtime
from app.review import repository as repo
from app.review.models import PHOTOS_MAX, WITHDRAWN_NAME, Review, ReviewReply
from app.review.schemas import (
    ReplyIn,
    ReplyOut,
    ReviewEditIn,
    ReviewItemOut,
    ReviewPageOut,
    ReviewWriteIn,
    VendorReviewRowOut,
    VendorReviewsOut,
)
from app.shared.clock import now_utc
from app.shared.errors import AppError, app_error
from app.shared.ids import uuid7
from app.vendor.schemas import RatingOut, ReviewLinkOut

TAGS_ORDER = ("seam", "on_time", "kind", "tidy")


def _not_found(what: str = "리뷰를") -> AppError:
    return app_error("not_found", f"{what} 찾을 수 없어요.")


def masked(name: str | None) -> str:
    """'김하늘' → '김○○' (고객 화면). 이름이 없으면 탈퇴한 고객"""
    if not name:
        return WITHDRAWN_NAME
    return name[0] + "○" * max(len(name) - 1, 1)


def context_label(sgg: str, trade: str, grade: str | None) -> str:
    """'노원구 아파트 · 실크' (쓸 때 사본)"""
    what = GRADE_PAPER.get(grade or "", "도배") if trade == "dobae" else "목공"
    return f"{sgg} 아파트 · {what}"[:60]


async def rating_of(s: AsyncSession, vendor_id: uuid.UUID) -> RatingOut:
    """별점 요약. 업체 카드 · 자세히(visit.service.rating_of)와 같은 계산 엔진 함수로 센다."""
    total, count, tags, done = await repo.rating(s, vendor_id)
    x = rating_calc.summary(total, count, done, tags)
    return RatingOut(avg=x.avg, count=x.count, done_count=x.done_count, tags=x.tags)


def _reply_out(r: ReviewReply | None) -> ReplyOut | None:
    return ReplyOut(body=r.body, created_at=r.created_at, edited_at=r.edited_at) if r else None


async def _items(
    s: AsyncSession, rows: list[Review], *, for_vendor: bool
) -> list[tuple[Review, dict]]:
    ids = [r.id for r in rows]
    photos = await repo.photos_of(s, ids)
    replies = await repo.replies_of(s, ids)
    names = {} if for_vendor else await repo.names_of(s, [r.author_id for r in rows])
    out = []
    for r in rows:
        if r.author_id is None:
            label = WITHDRAWN_NAME
        else:
            label = "고객" if for_vendor else masked(names.get(r.author_id))
        out.append(
            (
                r,
                {
                    "id": r.id,
                    "rating": r.rating,
                    "tags": [t for t in TAGS_ORDER if t in (r.tags or [])],
                    "body": r.body,
                    "author_label": label,
                    "context_label": r.context_label,
                    "photos": photos.get(r.id, []),
                    "created_at": r.created_at,
                    "edited": r.edited_at is not None,
                    "reply": _reply_out(replies.get(r.id)),
                },
            )
        )
    return out


async def item(s: AsyncSession, r: Review) -> ReviewItemOut:
    ((_, fields),) = await _items(s, [r], for_vendor=False)
    return ReviewItemOut(**fields)


async def for_customer(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    vendor_id: uuid.UUID,
    *,
    sort: str,
    before: datetime | None,
    limit: int,
) -> ReviewPageOut:
    """업체 리뷰 전체(C48): 그 공사의 고객만, 숨긴 리뷰 빼고. 최신순은 before 커서, 낮은 별점부터는 한 쪽만."""
    if await repo.project_of(s, user.id, project_id) is None:
        raise _not_found("공사를")
    if not await repo.vendor_listed(s, vendor_id):
        raise _not_found("업체를")
    rows = await repo.page(s, vendor_id, shown_only=True, sort=sort, before=before, limit=limit)
    items = [ReviewItemOut(**f) for _, f in await _items(s, rows, for_vendor=False)]
    more = sort == "latest" and len(rows) == limit
    links = [
        ReviewLinkOut(sort=x.sort, label=x.label, url=x.url, status=x.status)
        for x in await repo.shown_links(s, vendor_id)
    ]
    return ReviewPageOut(
        vendor_id=vendor_id,
        rating=await rating_of(s, vendor_id),
        items=items,
        next_before=rows[-1].created_at if more else None,
        links=links,
    )


async def _check_photos(s: AsyncSession, user: User, file_ids: list[uuid.UUID]) -> None:
    if len(file_ids) > PHOTOS_MAX:
        raise app_error("invalid", f"사진은 {PHOTOS_MAX}장까지 올릴 수 있어요.")
    if await repo.free_photos(s, user.id, file_ids) != len(file_ids):
        raise app_error("invalid", "올린 리뷰 사진만 붙일 수 있어요.")


async def write(
    s: AsyncSession, user: User, project_id: uuid.UUID, deal_id: uuid.UUID, data: ReviewWriteIn
) -> ReviewItemOut:
    """리뷰 쓰기(C39). 공사가 안 끝났으면 403 · 두 번째 409 already. 업체에 알림."""
    project = await repo.project_of(s, user.id, project_id)
    deal = await repo.deal_in(s, project_id, deal_id) if project else None
    if project is None or deal is None or deal.vendor_id is None:
        raise _not_found("공사를")
    if deal.status != "done":
        raise app_error("forbidden", "공사가 끝난 뒤에 리뷰를 쓸 수 있어요.")
    if await repo.by_deal(s, deal_id) is not None:
        raise app_error("already", "이 공사의 리뷰는 이미 썼어요.")
    await _check_photos(s, user, data.photo_file_ids)
    now = now_utc()
    grade = await repo.grade_of(s, project_id, deal.trade)
    # 관리자가 숨긴 리뷰를 지운 공사면 다시 써도 숨긴 채(같은 기준)로 시작해요. 관리자가 보고 다시 보이게 해요(점검 R4#3)
    held = await repo.held_code(s, deal_id)
    r = Review(
        id=uuid7(),
        deal_id=deal_id,
        vendor_id=deal.vendor_id,
        project_id=project_id,
        author_id=user.id,
        rating=data.rating,
        tags=list(data.tags),
        body=data.body,
        context_label=context_label(project.sgg, deal.trade, grade),
        status="hidden" if held else "shown",
        hidden_code=held,
        created_at=now,
    )
    try:
        s.add(r)
        await repo.set_photos(s, r.id, data.photo_file_ids, replace=False)
        await notify.add(
            s,
            user_id=deal.vendor_id,
            kind="review_written",
            body=catalog.KINDS["review_written"].example,
            link=catalog.link("review_written"),
            dedup_key=f"review_written:{r.id}",
        )
        await s.commit()
    except IntegrityError as exc:  # 같은 공사에 동시에 두 번 · 같은 사진을 동시에
        await s.rollback()
        raise app_error("already", "이 공사의 리뷰는 이미 썼어요.") from exc
    await notify.push_unread(s, [deal.vendor_id])
    await realtime.push_state([deal.vendor_id], "review", r.id)
    return await item(s, r)


async def _mine(s: AsyncSession, user: User, review_id: uuid.UUID) -> Review:
    r = await repo.review(s, review_id)
    if r is None or r.author_id != user.id:
        raise _not_found()
    return r


async def edit(
    s: AsyncSession, user: User, review_id: uuid.UUID, data: ReviewEditIn
) -> ReviewItemOut:
    """내 리뷰 고치기: 보낸 칸만 바꾸고 '수정됨'(edited_at)"""
    r = await _mine(s, user, review_id)
    sent = data.model_fields_set
    if "rating" in sent and data.rating is not None:
        r.rating = data.rating
    if "tags" in sent and data.tags is not None:
        if len(set(data.tags)) != len(data.tags):
            raise app_error("invalid", "같은 것을 두 번 골랐어요.")
        r.tags = list(data.tags)
    if "body" in sent:
        r.body = data.body
    if "photo_file_ids" in sent and data.photo_file_ids is not None:
        ids = list(data.photo_file_ids)
        if len(set(ids)) != len(ids):
            raise app_error("invalid", "같은 것을 두 번 골랐어요.")
        current = (await repo.photos_of(s, [r.id]))[r.id]
        await _check_photos(s, user, [i for i in ids if i not in current])
        await repo.set_photos(s, r.id, ids, replace=True)
    r.edited_at = now_utc()
    try:
        await s.commit()
    except IntegrityError as exc:
        await s.rollback()
        raise app_error("invalid", "올린 리뷰 사진만 붙일 수 있어요.") from exc
    if r.vendor_id is not None:
        await realtime.push_state([r.vendor_id], "review", r.id)
    return await item(s, await _mine(s, user, review_id))


async def remove(s: AsyncSession, user: User, review_id: uuid.UUID) -> None:
    r = await _mine(s, user, review_id)
    vendor_id = r.vendor_id
    if r.status == "hidden" and r.hidden_code and r.deal_id is not None:
        # 관리자가 숨긴 리뷰: 지우고 다시 써서 숨김을 푸는 길을 막아요(점검 R4#3)
        await repo.hold(s, r.deal_id, r.hidden_code)
    await s.delete(r)
    await s.commit()
    await realtime.push_state([vendor_id], "review", review_id)


async def for_vendor(s: AsyncSession, vendor: User, *, waiting_only: bool) -> VendorReviewsOut:
    """업체 리뷰 · 답글(V24). 숨긴 리뷰도 '숨김'으로 보인다. 쓴 사람 이름은 없다."""
    rows = await repo.page(s, vendor.id, shown_only=waiting_only, waiting_only=waiting_only)
    items = []
    for r, f in await _items(s, rows, for_vendor=True):
        waiting = f["reply"] is None and r.status == "shown"
        items.append(
            VendorReviewRowOut(
                **f, deal_id=r.deal_id, waiting_reply=waiting, hidden=r.status == "hidden"
            )
        )
    return VendorReviewsOut(
        rating=await rating_of(s, vendor.id),
        waiting=await repo.waiting_count(s, vendor.id),
        items=items,
    )


async def reply(
    s: AsyncSession, vendor: User, review_id: uuid.UUID, data: ReplyIn
) -> tuple[ReplyOut, bool]:
    """답글 달기 · 고치기(I4, 리뷰마다 하나). 돌려주는 값: (답글, 처음인지). 처음이면 쓴 고객에게 알림."""
    r = await repo.review(s, review_id)
    if r is None or r.vendor_id != vendor.id:
        raise _not_found()
    # rollback은 세션의 모든 객체를 만료시켜서, 그 뒤에는 이 값만 쓴다
    author_id, project_id, me = r.author_id, r.project_id, vendor.id
    now = now_utc()
    found = await repo.reply_of(s, review_id)
    created = found is None
    try:  # 답글 INSERT는 다음 문장 전에 나가므로(autoflush) 겹침 오류는 여기 어디서든 난다
        if found is None:
            found = ReviewReply(review_id=review_id, vendor_id=me, body=data.body, created_at=now)
            s.add(found)
            await s.flush()
            if author_id is not None and project_id is not None:
                await notify.add(
                    s,
                    user_id=author_id,
                    kind="review_replied",
                    body=catalog.KINDS["review_replied"].example,
                    link=catalog.link("review_replied", pid=project_id),
                    dedup_key=f"review_replied:{review_id}",
                    project_id=project_id,
                )
        else:
            found.body = data.body
            found.edited_at = now
        await s.commit()
    except IntegrityError:  # 처음 답글이 동시에 두 번: 뒤의 것은 고치기로
        await s.rollback()
        found = await repo.reply_of(s, review_id)
        if found is None:
            raise
        found.body, found.edited_at, created = data.body, now, False
        await s.commit()
    if created and author_id is not None:
        await notify.push_unread(s, [author_id])
    await realtime.push_state([author_id], "review", review_id, project_id)
    return _reply_out(found), created


async def photo_for(s: AsyncSession, user: User, review_id: uuid.UUID, file_id: uuid.UUID) -> File:
    """리뷰 사진: 보이는 리뷰는 로그인한 고객 누구나, 숨긴 리뷰는 쓴 사람 · 그 업체 · 관리자만.
    업체는 자기 리뷰의 사진만 본다(남의 업체 리뷰 404)."""
    r = await repo.review(s, review_id)
    if r is None or not await repo.has_photo(s, review_id, file_id):
        raise _not_found("사진을")
    if user.role == "admin" or r.author_id == user.id:
        ok = True
    elif user.role == "vendor":
        ok = r.vendor_id == user.id
    else:
        ok = r.status == "shown"
    f = await repo.file_row(s, file_id) if ok else None
    if f is None:
        raise _not_found("사진을")
    return f


async def set_hidden(s: AsyncSession, review_id: uuid.UUID, code: str) -> uuid.UUID | None:
    """관리자 숨김 (부르는 쪽 트랜잭션 안). 돌려주는 값: 업체 id (없거나 이미 숨김이면 None)"""
    return await repo.set_status(s, review_id, hidden_code=code)


async def set_shown(s: AsyncSession, review_id: uuid.UUID) -> uuid.UUID | None:
    """관리자 다시 보이기 (부르는 쪽 트랜잭션 안). 돌려주는 값: 업체 id (없거나 이미 보임이면 None).
    관리자가 그 공사 리뷰를 다시 봤으니 '숨긴 리뷰를 지운 공사' 표시도 지운다."""
    vendor_id = await repo.set_status(s, review_id, hidden_code=None)
    if vendor_id is not None:
        await repo.drop_hold_of(s, review_id)
    return vendor_id


async def exists(s: AsyncSession, review_id: uuid.UUID) -> Review | None:
    return await repo.review(s, review_id)
