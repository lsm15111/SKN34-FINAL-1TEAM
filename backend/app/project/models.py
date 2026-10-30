import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

SIZE_BANDS = ("10", "20", "30", "40", "50")  # 10평대 … 50평 이상 (공급 기준)
BUDGETS = ("u300", "300-500", "500-700", "700-1000", "o1000", "undecided")
MOK_ITEMS = ("molding", "base", "door", "flatten")  # 천장 몰딩 · 걸레받이 · 방문 교체 · 천장 평탄화
DOBAE_GRADES = ("economy", "basic")  # 저가형 · 기본형


class Project(Base):
    """고객이 견적 받기로 만든 인테리어 프로젝트 (기본정보). 동 · 호수는 실측 요청 때만 받는다."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("house_type = 'apt'", name="house_type"),
        CheckConstraint(
            "built_year is null or built_year between 1900 and 2100", name="built_year"
        ),
        CheckConstraint(
            "size_band is null or size_band in ('10', '20', '30', '40', '50')", name="size_band"
        ),
        CheckConstraint(
            "area_basis is null or area_basis in ('supply', 'exclusive')", name="area_basis"
        ),
        CheckConstraint("area_m2 is null or area_m2 > 0", name="area_m2"),
        CheckConstraint(
            "(size_band is not null and area_m2 is null and area_basis is null)"
            " or (size_band is null and area_m2 is not null and area_basis is not null)",
            name="size",
        ),
        CheckConstraint("start_kind in ('date', 'movein', 'months', 'unknown')", name="start_kind"),
        CheckConstraint(
            "(start_kind in ('date', 'movein')) = (start_date is not null)", name="start_date"
        ),
        CheckConstraint(
            "end_date is null or (start_kind = 'date' and end_date >= start_date)", name="end_date"
        ),
        CheckConstraint(
            "budget is null or budget in ('u300', '300-500', '500-700', '700-1000', 'o1000', 'undecided')",
            name="budget",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    sido: Mapped[str] = mapped_column(String(20))
    sgg: Mapped[str] = mapped_column(String(20))
    house_type: Mapped[str] = mapped_column(String(10), default="apt", server_default="apt")
    built_year: Mapped[int | None] = mapped_column(SmallInteger)
    size_band: Mapped[str | None] = mapped_column(String(2))
    area_basis: Mapped[str | None] = mapped_column(String(10))
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(7, 1))
    balcony_ext: Mapped[bool] = mapped_column(Boolean, default=False)
    start_kind: Mapped[str] = mapped_column(String(10))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    occupied: Mapped[bool] = mapped_column(Boolean)
    budget: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectSpace(Base):
    """고객이 넣은 공간 (거실, 방 2, 주방 2 …)"""

    __tablename__ = "project_spaces"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_spaces_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(20))
    sort: Mapped[int] = mapped_column(SmallInteger)


class ProjectTrade(Base):
    """프로젝트에서 고른 공정. 도배는 유형(grade), 목공은 항목(items)도 둔다."""

    __tablename__ = "project_trades"
    __table_args__ = (
        CheckConstraint("trade in ('dobae', 'mokgong')", name="trade"),
        CheckConstraint("trade = 'mokgong' or cardinality(items) = 0", name="items"),
        CheckConstraint(
            "items <@ array['molding', 'base', 'door', 'flatten']::varchar[]", name="item_keys"
        ),
        CheckConstraint("grade is null or grade in ('economy', 'basic')", name="grade"),
        CheckConstraint("trade = 'dobae' or grade is null", name="grade_trade"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    trade: Mapped[str] = mapped_column(String(10), primary_key=True)
    items: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list, server_default="{}")
    # 도배 유형. 0002로 만든 행에는 없어서 DB에서는 비워 둘 수 있고, 새 요청은 API가 꼭 받는다.
    grade: Mapped[str | None] = mapped_column(String(10))


class ProjectTradeSpace(Base):
    """공정마다 고른 공간"""

    __tablename__ = "project_trade_spaces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "trade"],
            ["project_trades.project_id", "project_trades.trade"],
            ondelete="CASCADE",
            name="fk_project_trade_spaces_trade",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    trade: Mapped[str] = mapped_column(String(10), primary_key=True)
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_spaces.id", ondelete="CASCADE"), primary_key=True
    )


class ProjectFile(Base):
    """프로젝트에 붙인 공간 사진과 도면. 파일 하나는 한 프로젝트에만 붙는다."""

    __tablename__ = "project_files"
    __table_args__ = (
        CheckConstraint("role in ('photo', 'plan')", name="role"),
        CheckConstraint("(role = 'photo') = (space_id is not null)", name="space"),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    space_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_spaces.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(10))
    sort: Mapped[int] = mapped_column(SmallInteger)
