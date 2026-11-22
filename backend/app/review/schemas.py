"""리뷰 · 답글 API 모양 (api.md 12장, dev-07). 별점 요약 모양은 vendor.schemas.RatingOut."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.review.models import BODY_MAX, PHOTOS_MAX
from app.shared.text import Tidy
from app.vendor.schemas import RatingOut, ReviewLinkOut

ReviewTag = Literal["seam", "on_time", "kind", "tidy"]  # 이음매 · 약속한 날 · 설명 친절 · 뒷정리
HiddenCode = Literal["abuse", "privacy", "unrelated", "paid"]
Body = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BODY_MAX), Tidy
]
HideNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300), Tidy]


class ReviewWriteIn(BaseModel):
    """리뷰 쓰기 (C39): 공사가 끝난(done) 그 공사의 고객만, 공사마다 한 번"""

    rating: int = Field(ge=1, le=5)
    tags: list[ReviewTag] = Field(default_factory=list, max_length=4)
    body: Body | None = None
    photo_file_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=PHOTOS_MAX, description="POST /files kind=review_photo"
    )

    @model_validator(mode="after")
    def _distinct(self) -> "ReviewWriteIn":
        if len(set(self.tags)) != len(self.tags) or len(set(self.photo_file_ids)) != len(
            self.photo_file_ids
        ):
            raise ValueError("같은 것을 두 번 골랐어요.")
        return self


class ReviewEditIn(BaseModel):
    """리뷰 고치기 (보낸 칸만 바꾼다, '수정됨'이 붙는다)"""

    rating: int | None = Field(default=None, ge=1, le=5)
    tags: list[ReviewTag] | None = Field(default=None, max_length=4)
    body: Body | None = None
    photo_file_ids: list[uuid.UUID] | None = Field(default=None, max_length=PHOTOS_MAX)


class ReplyIn(BaseModel):
    body: Body


class ReplyOut(BaseModel):
    body: str
    created_at: datetime
    edited_at: datetime | None


class ReviewItemOut(BaseModel):
    """리뷰 한 줄 (C48 · V24). 탈퇴한 고객은 이름이 '탈퇴한 고객'(L08)"""

    id: uuid.UUID
    rating: int
    tags: list[ReviewTag]
    body: str | None
    author_label: str = Field(description="김○○ · 탈퇴한 고객")
    context_label: str = Field(description="노원구 아파트 · 실크 (만든 때 사본)")
    photos: list[uuid.UUID]
    created_at: datetime
    edited: bool = Field(description="'수정됨'")
    reply: ReplyOut | None


class ReviewPageOut(BaseModel):
    """업체 리뷰 전체 (C48): 숨긴 리뷰는 빠진다"""

    vendor_id: uuid.UUID
    rating: RatingOut
    items: list[ReviewItemOut]
    next_before: datetime | None = Field(description="다음 쪽 커서 (없으면 끝)")
    links: list[ReviewLinkOut] = Field(description="외부 리뷰 링크 (보여요만)")


class VendorReviewRowOut(ReviewItemOut):
    deal_id: uuid.UUID | None
    waiting_reply: bool = Field(description="답글을 기다려요")
    hidden: bool = Field(description="관리자가 숨김 (업체에게는 보인다)")


class VendorReviewsOut(BaseModel):
    """업체 리뷰 · 답글 (V24)"""

    rating: RatingOut
    waiting: int = Field(description="답글 기다리는 리뷰 수")
    items: list[VendorReviewRowOut]


class ReviewHideIn(BaseModel):
    """관리자 숨김: 공개한 기준 코드만 (C49)"""

    code: HiddenCode
    note: HideNote | None = None


class ReviewStateOut(BaseModel):
    id: uuid.UUID
    status: Literal["shown", "hidden"]
    hidden_code: HiddenCode | None
