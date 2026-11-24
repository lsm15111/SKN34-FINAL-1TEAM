import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

TAGS = ("seam", "on_time", "kind", "tidy")  # 이음매 · 약속한 날 · 설명 친절 · 뒷정리
STATUSES = ("shown", "hidden")
# 공개한 내리는 기준(C49): 욕설 · 개인정보 · 공사와 상관없음 · 대가를 받고 씀
HIDDEN_CODES = ("abuse", "privacy", "unrelated", "paid")
BODY_MAX = 1000
PHOTOS_MAX = 5
# 탈퇴한 고객의 리뷰(L08): 글은 남기고 이름은 이 말로 보인다
WITHDRAWN_NAME = "탈퇴한 고객"


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class Review(Base):
    """공사 확정 한 건에 리뷰 하나 (deal_id UNIQUE). 탈퇴해도 남도록 공사 · 작성자 칸은 SET NULL(L08)."""

    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_vendor_created", "vendor_id", "created_at"),
        CheckConstraint("rating between 1 and 5", name="rating"),
        CheckConstraint("tags <@ array['seam', 'on_time', 'kind', 'tidy']::varchar[]", name="tags"),
        CheckConstraint("body is null or length(btrim(body)) > 0", name="body"),
        CheckConstraint("status in ('shown', 'hidden')", name="status"),
        CheckConstraint(
            f"hidden_code is null or hidden_code in {_in(HIDDEN_CODES)}", name="hidden_code"
        ),
        CheckConstraint("(status = 'hidden') = (hidden_code is not null)", name="hidden"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), unique=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.user_id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(12)), default=list, server_default="{}")
    body: Mapped[str | None] = mapped_column(String(BODY_MAX))
    context_label: Mapped[str] = mapped_column(String(60))  # '노원구 아파트 · 실크' 사본
    status: Mapped[str] = mapped_column(String(8), default="shown", server_default="shown")
    hidden_code: Mapped[str | None] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 있으면 '수정됨'


class ReviewPhoto(Base):
    """리뷰 사진 (files.kind = review_photo). 사진 하나는 한 리뷰에만 붙는다."""

    __tablename__ = "review_photos"
    __table_args__ = (CheckConstraint(f"sort between 0 and {PHOTOS_MAX - 1}", name="sort"),)

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True, unique=True
    )
    sort: Mapped[int] = mapped_column(SmallInteger)


class ReviewReply(Base):
    """업체 답글 (리뷰마다 하나, I4). 기본 키가 리뷰 id라 두 번째는 고치기다."""

    __tablename__ = "review_replies"
    __table_args__ = (CheckConstraint("length(btrim(body)) > 0", name="body"),)

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(String(BODY_MAX))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewHold(Base):
    """관리자가 숨긴 리뷰를 쓴 사람이 지운 공사(점검 R4#3). 그 공사에 다시 쓰면 숨긴 채(같은 기준)로 시작하고,
    관리자가 그 공사 리뷰를 다시 보이게 하면 지운다. 지우고 다시 써서 숨김을 푸는 길을 막는다."""

    __tablename__ = "review_holds"
    __table_args__ = (CheckConstraint(f"hidden_code in {_in(HIDDEN_CODES)}", name="hidden_code"),)

    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), primary_key=True
    )
    hidden_code: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
