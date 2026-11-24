import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

SIZE_BANDS = ("10", "20", "30", "40", "50")  # 10평대 … 50평 이상 (공급 기준)
BUDGETS = ("u300", "300-500", "500-700", "700-1000", "o1000", "undecided")
MOK_ITEMS = ("molding", "base", "door", "flatten")  # 천장 몰딩 · 걸레받이 · 방문 교체 · 천장 평탄화
DOBAE_GRADES = ("economy", "basic")  # 저가형 · 기본형 (v3 화면 말: 합지 · 실크)
# v3: 공사 범위(전체 · 부분) · 면(벽 · 천장) · 공간 종류 · 손님 답을 옮겼는지
SCOPES = ("full", "partial")
FACES = ("wall", "ceiling")
# 거실 · 주방 · 안방 · 작은방 1~4 · 복도 · 현관 · 드레스룸 (공간 몫은 calc.space_share 표에서 kind로)
SPACE_KINDS = (
    "living",
    "kitchen",
    "master",
    "room1",
    "room2",
    "room3",
    "room4",
    "hall",
    "entry",
    "dress",
)
# v3 부분 공사 공간을 project_spaces에 넣을 때 쓰는 이름 (화면 말)
SPACE_NAMES = {
    "living": "거실",
    "kitchen": "주방",
    "master": "안방",
    "room1": "작은방 1",
    "room2": "작은방 2",
    "room3": "작은방 3",
    "room4": "작은방 4",
    "hall": "복도",
    "entry": "현관",
    "dress": "드레스룸",
}
SOURCES = ("v2", "guest", "member")
BUDGET_WON_MIN = 100_000
BUDGET_WON_MAX = 10_000_000_000
BUDGET_WON_UNIT = 10_000  # 예산은 만 원 단위(CHECK budget_won)
_FACES_SQL = "array['wall', 'ceiling']::varchar[]"
_SPACE_KINDS_SQL = (
    "('living', 'kitchen', 'master', 'room1', 'room2', 'room3', 'room4', 'hall', 'entry', 'dress')"
)
# 직접 할 일 칸(project/diy.py DIY 키 + 없어요). 칩 키를 더하면 이 줄 · migration도 같이 바꾼다
_DIY_SQL = (
    "key not like 'diy.%' or (value = 'self' and key in ('diy.paint', 'diy.outlet', 'diy.light',"
    " 'diy.silicone', 'diy.handle', 'diy.clean', 'diy.paper_buy', 'diy.none'))"
)
# 도배 전 앞 공사 답 칸(project/prework.py 공정 · 단추 값). 공정을 더하면 이 줄 · migration도 같이 바꾼다
_PREWORK_SQL = (
    "key not like 'prework.%' or (key in ('prework.mokgong', 'prework.electric', 'prework.film',"
    " 'prework.floor') and value in ('done', 'todo', 'none'))"
)


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
        CheckConstraint("rev >= 1", name="rev"),
        CheckConstraint(
            "budget is null or budget in ('u300', '300-500', '500-700', '700-1000', 'o1000', 'undecided')",
            name="budget",
        ),
        CheckConstraint(
            "budget_won is null or (budget_won between 100000 and 10000000000"
            " and budget_won % 10000 = 0)",
            name="budget_won",
        ),
        CheckConstraint("source in ('v2', 'guest', 'member')", name="source"),
        CheckConstraint("rooms is null or rooms between 1 and 5", name="rooms"),
        # 손님 답 옮기기 멱등 키: 같은 키로 두 번 오면 만든 공사를 돌려준다 (NULL끼리는 겹치지 않는다)
        UniqueConstraint("owner_id", "client_key", name="uq_projects_client_key"),
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
    # 요청 번호(MJ-2611-0142). 표준견적서 번호 · 실측 요청 문구에 쓴다
    code: Mapped[str] = mapped_column(String(16), unique=True)
    # 집 정보를 고칠 때마다 1씩 오른다. 표준견적서 · 공정표가 만든 때의 값을 남긴다
    rev: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    # 첫 실측 요청 때 찍는다. 그 뒤로는 집 정보를 고치지 않는다
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 아파트 이름 · 동 · 호수: 고객이 업체에 연락처를 보내기로 할 때만 받는다
    apt_name: Mapped[str | None] = mapped_column(String(40))
    dong: Mapped[str | None] = mapped_column(String(10))
    ho: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # v3 (0024): 읍면동 · 예산(원) · 만든 길 · 손님 답 옮기기 멱등 키
    emd: Mapped[str | None] = mapped_column(String(20))  # 상계동. 업체에는 구 · 동까지만 간다
    budget_won: Mapped[int | None] = mapped_column(BigInteger)  # 비면 '아직 몰라요'
    source: Mapped[str] = mapped_column(String(8), default="v2", server_default="v2")
    client_key: Mapped[uuid.UUID | None] = mapped_column()
    # v3 (0036): 방 개수 1~5. 비면(옛 공사 · v2) 평형 기본값으로 센다(calc.dobae.rooms_of)
    rooms: Mapped[int | None] = mapped_column(SmallInteger)


class ProjectSpace(Base):
    """고객이 넣은 공간 (거실, 방 2, 주방 2 …). v3는 공간 종류(kind)로 고른다."""

    __tablename__ = "project_spaces"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_spaces_name"),
        CheckConstraint(f"kind is null or kind in {_SPACE_KINDS_SQL}", name="kind"),
        Index(
            "uq_project_spaces_kind",
            "project_id",
            "kind",
            unique=True,
            postgresql_where=text("kind is not null"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(20))
    sort: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[str | None] = mapped_column(String(12))  # v3 공간 종류 (SPACE_KINDS)


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
        CheckConstraint("scope in ('full', 'partial')", name="scope"),
        CheckConstraint(
            f"faces <@ {_FACES_SQL} and cardinality(faces) between 1 and 2", name="faces"
        ),
        # 전체 공사는 벽 + 천장
        CheckConstraint(f"scope <> 'full' or faces @> {_FACES_SQL}", name="full_faces"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    trade: Mapped[str] = mapped_column(String(10), primary_key=True)
    items: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list, server_default="{}")
    # 도배 유형. 0002로 만든 행에는 없어서 DB에서는 비워 둘 수 있고, 새 요청은 API가 꼭 받는다.
    grade: Mapped[str | None] = mapped_column(String(10))
    # v3 (0024): 전체 · 부분 공사와 면. 부분 공사 공간은 project_trade_spaces를 그대로 쓴다
    scope: Mapped[str] = mapped_column(String(8), default="full", server_default="full")
    faces: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)),
        default=lambda: ["wall", "ceiling"],
        server_default=text("'{wall,ceiling}'"),
    )


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


# 공사 전에 할 일 (판 WSchedule · WPlanDone). 항목을 더하면 CHECK · migration도 같이 바꾼다
CHECK_KEYS = ("office_report",)
CHECK_LABELS = {"office_report": "관리사무소에 공사 신고를 했어요"}


class ProjectCheck(Base):
    """고객이 켠 공사 전 체크 한 줄 (끄면 행을 지운다)"""

    __tablename__ = "project_checks"
    __table_args__ = (CheckConstraint("key in ('office_report')", name="key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(30), primary_key=True)
    done_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProjectCondition(Base):
    """AI 상담으로 모은 조건(맥락 L3, agent-context.md 3절). 화면 이름 '모은 조건'.

    고객이 되묻기에 답하거나 단추로 고른 값만 둔다(LLM 추측은 넣지 않는다). 칸(key)은 TradeSpec 칸 이름
    (예: dobae.grade)이고 공사 · 칸마다 하나다. 다음 턴부터 에이전트가 같은 칸을 다시 묻지 않는다.
    v4 철거 범위(demolition)는 코드 값(full · partial · none)만 받는다(0043, 전체 철거면 리모델링 기준).
    v4 직접 할 일(diy.<키>)은 project/diy.py 칩 키와 '없어요'(diy.none)만, 값은 self만 받는다(0046).
    v4 도배 전 앞 공사 답(prework.<공정>)은 project/prework.py 공정과 단추 값(done · todo · none)만 받는다(0060).
    """

    __tablename__ = "project_conditions"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_project_conditions_key"),
        CheckConstraint("char_length(key) between 3 and 40", name="key"),
        CheckConstraint("char_length(btrim(value)) between 1 and 40", name="value"),
        CheckConstraint(
            "key <> 'demolition' or value in ('full', 'partial', 'none')", name="demolition"
        ),
        CheckConstraint(_DIY_SQL, name="diy"),
        CheckConstraint(_PREWORK_SQL, name="prework"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    trade: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
