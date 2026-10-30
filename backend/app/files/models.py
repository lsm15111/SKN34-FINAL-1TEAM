import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

# photo: 공간 사진 · plan: 아파트 도면 (고객) / license: 사업자등록증 · portfolio: 시공 사진 (업체)
KINDS = ("photo", "plan", "license", "portfolio")


class File(Base):
    """올린 파일 한 개. 내용은 저장소(files/storage.py)에, 여기에는 위치와 정보만 둔다."""

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("kind in ('photo', 'plan', 'license', 'portfolio')", name="kind"),
        CheckConstraint("size > 0", name="size"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    storage_key: Mapped[str] = mapped_column(String(100), unique=True)
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(50))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
