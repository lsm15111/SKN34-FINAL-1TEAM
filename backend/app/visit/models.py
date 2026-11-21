import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

# v3 (0026) 실측 일정 상태: 답 기다림 · 날짜 고를 차례 · 수락 기다림 · 다른 날 제안 옴 · 실측 확정 ·
# 실측 받음 · 견적서 옴 · 업체 확정 / 못 받음 · 기한 지남 · 취소 · 업체가 안 옴 · 닫힘
STATUSES = (
    "requested",
    "offered",
    "picked",
    "proposed",
    "booked",
    "visited",
    "quoted",
    "chosen",
    "declined",
    "expired",
    "cancelled",
    "no_show",
    "closed",
)
# 칸을 차지하는 살아 있는 상태 (공정마다 3곳까지). 지난 상태에서는 나가지 않는다
LIVE = ("requested", "offered", "picked", "proposed", "booked", "visited", "quoted", "chosen")
ENDED = ("declined", "expired", "cancelled", "no_show", "closed")
SLOTS = 3
ATTEMPTS_MAX = 2  # 같은 업체에 요청은 두 번까지 (service가 지킨다, C18)
DECLINE_CODES = ("full", "out_of_area", "other")  # 일정이 꽉 찼어요 · 지역 밖이에요 · 그 밖
CLOSE_REASONS = ("other_chosen", "reselected")  # 다른 업체를 확정 · 다시 고르기
EXPIRED_REASONS = ("reply", "pick")  # 업체 첫 답 48시간 · 고객 고르기 7일
# 실측 취소 이유: 일정이 바뀌었어요 · 다른 업체로 할래요 · 견적서가 늦어서 닫음 · 그 밖
CANCEL_CODES = ("changed", "other_vendor", "late_quote", "other")
HALVES = ("am", "pm")  # 오전 · 오후
WISH_SPAN_MAX = 62  # 희망 기간 · 업체 기간 최대 길이(일)
EXCLUDED_MAX = 31
# v4 반셀프: 요청에 남기는 직접 할 일 칩 키(project.diy.DIY와 같은 키, 0047 · 0053 CHECK)
DIY_KEYS = ("paint", "outlet", "light", "silicone", "handle", "clean", "paper_buy")
# 기록(visit_events.code) 값. CHECK는 두지 않는다(옛 값 full · out_of_area · resent · other_chosen · reselected)
EVENT_CODES = (
    "asked",
    "re_asked",
    "answered",
    "declined",
    "picked",
    "booked",
    "hold_released",
    "proposed",
    "proposal_picked",
    "repick",
    "change_requested",
    "change_accepted",
    "change_countered",
    "change_expired",
    "change_withdrawn",
    "cancelled",
    "visited",
    "no_show",
    "quote_sent",
    "expired",
    "closed",
    "requote",
)
# 담기(shortlists)
SHORTLIST_STATUSES = ("active", "removed")
REMOVED_CODES = ("customer", "expired", "declined", "cancelled", "no_show", "closed")
# 반나절 잡기(visit_holds): 잡아 둠(수락 기다림) · 확정
HOLD_KINDS = ("hold", "booked")
HOLD_STATUSES = ("active", "released")
# 다른 날 제안(visit_proposals)
PROPOSAL_REASONS = ("other_site", "no_crew", "other")  # 다른 현장 · 자재 · 사람이 안 돼요 · 그 밖
PROPOSAL_STATUSES = ("open", "picked", "repicked", "expired")
PROPOSAL_SLOTS_MAX = 3
# 일정 바꾸기 요청(visit_changes). countered(업체가 다른 날을 냄)도 고객 답을 기다리는 열린 상태
CHANGE_STATUSES = ("open", "accepted", "countered", "withdrawn", "expired")
CHANGE_OPEN = ("open", "countered")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_STATUS_SQL = _in(STATUSES)
_LIVE_SQL = f"status in {_in(LIVE)}"
_HALF_SQL = _in(HALVES)


class Shortlist(Base):
    """담기 한 칸 (공사 · 공종마다 3칸). 요청과 나눠 둔다(v3). 빼거나 요청이 끝나면 removed."""

    __tablename__ = "shortlists"
    __table_args__ = (
        Index(
            "uq_shortlists_vendor",
            "project_id",
            "trade",
            "vendor_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_shortlists_slot",
            "project_id",
            "trade",
            "slot",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("trade in ('dobae', 'mokgong')", name="trade"),
        CheckConstraint("slot between 1 and 3", name="slot"),
        CheckConstraint("status in ('active', 'removed')", name="status"),
        CheckConstraint(
            f"removed_code is null or removed_code in {_in(REMOVED_CODES)}", name="removed_code"
        ),
        CheckConstraint("(status = 'active') = (removed_code is null)", name="removed"),
        CheckConstraint("(status = 'removed') = (removed_at is not null)", name="removed_at"),
        CheckConstraint("grade is null or grade in ('economy', 'basic')", name="grade"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    trade: Mapped[str] = mapped_column(String(10))
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    slot: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(8), default="active", server_default="active")
    removed_code: Mapped[str | None] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # v3 (0034): 담을 때 고객이 고른 벽지(합지 economy · 실크 basic, C11). 비면 공사 벽지
    grade: Mapped[str | None] = mapped_column(String(10))


class Visit(Base):
    """실측 요청 한 건 (이 집 · 한 공종 · 한 업체 · 한 번째 시도). v3는 믿집이 반나절 날짜를 중계한다.

    요청할 때 업체 이름 · 가견적(확인한 단가 묶음과 합계) · 희망 기간 · 공사 희망일을 사본으로 고정한다.
    share_contact · consent_* · contact_until · message는 v2 칸이다(0031에서 지울 후보).
    """

    __tablename__ = "visits"
    __table_args__ = (
        Index(
            "uq_visits_slot",
            "project_id",
            "trade",
            "slot",
            unique=True,
            # 상수 튜플 LIVE로 만든 조건이라 사용자 입력이 들어가지 않는다(semgrep 오탐)
            postgresql_where=text(_LIVE_SQL),  # nosemgrep: avoid-sqlalchemy-text
        ),
        Index(
            "uq_visits_vendor",
            "project_id",
            "trade",
            "vendor_id",
            unique=True,
            # 상수 튜플 LIVE로 만든 조건이라 사용자 입력이 들어가지 않는다(semgrep 오탐)
            postgresql_where=text(_LIVE_SQL),  # nosemgrep: avoid-sqlalchemy-text
        ),
        UniqueConstraint("project_id", "trade", "vendor_id", "attempt", name="uq_visits_attempt"),
        CheckConstraint("trade in ('dobae', 'mokgong')", name="trade"),
        CheckConstraint("slot between 1 and 3", name="slot"),
        CheckConstraint(f"status in {_STATUS_SQL}", name="status"),
        CheckConstraint("share_contact = (consent_at is not null)", name="share_contact"),
        CheckConstraint("(consent_ver is null) = (consent_at is null)", name="consent"),
        CheckConstraint("message is null or length(btrim(message)) > 0", name="message"),
        CheckConstraint("estimate_total >= 0", name="estimate_total"),
        CheckConstraint("grade is null or grade in ('economy', 'basic')", name="grade"),
        CheckConstraint(
            "estimate_set_id is null or estimate_total is not null", name="estimate_set"
        ),
        CheckConstraint(
            "(status = 'declined') = (decline_code is not null)"
            " and (decline_code is null or decline_code in ('full', 'out_of_area', 'other'))",
            name="decline_code",
        ),
        CheckConstraint(
            "decline_note is null or (decline_code is not null"
            " and length(btrim(decline_note)) > 0)",
            name="decline_note",
        ),
        CheckConstraint(
            "(status = 'closed') = (close_reason is not null)"
            " and (close_reason is null or close_reason in"
            " ('other_chosen', 'reselected', 'vendor_stopped'))",
            name="close_reason",
        ),
        CheckConstraint("quote_ver >= 1", name="quote_ver"),
        CheckConstraint("attempt >= 1", name="attempt"),
        CheckConstraint(
            "(wish_start is null and wish_end is null)"
            " or (wish_start is not null and wish_end is not null"
            f" and wish_end >= wish_start and wish_end - wish_start <= {WISH_SPAN_MAX})",
            name="wish",
        ),
        CheckConstraint(
            "(booked_day is null) = (booked_half is null)"
            f" and (booked_half is null or booked_half in {_HALF_SQL})",
            name="booked",
        ),
        CheckConstraint(
            "(status = 'expired') = (expired_reason is not null)"
            " and (expired_reason is null or expired_reason in ('reply', 'pick'))",
            name="expired_reason",
        ),
        CheckConstraint(
            f"cancel_code is null or (status = 'cancelled' and cancel_code in {_in(CANCEL_CODES)})",
            name="cancel_code",
        ),
        CheckConstraint(
            "cancel_note is null or (cancel_code is not null and length(btrim(cancel_note)) > 0)",
            name="cancel_note",
        ),
        CheckConstraint(
            "diy <@ array[" + ", ".join(f"'{k}'" for k in DIY_KEYS) + "]::varchar[]", name="diy"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    trade: Mapped[str] = mapped_column(String(10))
    # 업체가 탈퇴해도 요청 기록은 남긴다 (이름은 사본으로)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="SET NULL"), index=True
    )
    vendor_name: Mapped[str] = mapped_column(String(100))
    slot: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(10), default="requested", server_default="requested")
    share_contact: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    consent_ver: Mapped[str | None] = mapped_column(String(20))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(String(300))
    # 요청 때의 가견적 사본. 가견적 없음이면 둘 다 비어 있다
    estimate_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendor_price_sets.id", ondelete="SET NULL")
    )
    estimate_total: Mapped[int | None] = mapped_column(BigInteger)
    decline_code: Mapped[str | None] = mapped_column(String(12))
    close_reason: Mapped[str | None] = mapped_column(String(16))  # vendor_stopped(0035)가 14자
    quote_ver: Mapped[int | None] = mapped_column(SmallInteger)  # 고객이 본 견적서 버전
    contact_until: Mapped[date | None] = mapped_column(Date)  # 확정 뒤 연락처가 보이는 마지막 날
    vendor_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ---- v3 (0026) ----
    shortlist_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shortlists.id", ondelete="SET NULL")
    )
    attempt: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    wish_start: Mapped[date | None] = mapped_column(Date)  # 고객 희망 기간 (보낼 때 고정)
    wish_end: Mapped[date | None] = mapped_column(Date)
    work_wish_on: Mapped[date | None] = mapped_column(Date)  # 공사 희망일 사본 (L04, 요청서 한 줄)
    # 보낸 때 + 48시간
    reply_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    booked_day: Mapped[date | None] = mapped_column(Date)  # 확정한 반나절 사본 (목록 · 채팅 띠)
    booked_half: Mapped[str | None] = mapped_column(String(2))
    # 실측일 + 3일 18:00
    quote_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_reason: Mapped[str | None] = mapped_column(String(8))
    cancel_code: Mapped[str | None] = mapped_column(String(12))
    cancel_note: Mapped[str | None] = mapped_column(String(100))
    decline_note: Mapped[str | None] = mapped_column(String(100))  # 못 받아요 '그 밖' 한 줄
    visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # '실측 받았어요'
    requote_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # '다시 받기'(D20)
    # v3 (0034): 요청 때 고객이 고른 벽지 사본(합지 economy · 실크 basic). 비면 공사 벽지
    grade: Mapped[str | None] = mapped_column(String(10))
    # v4 (0046): 요청 때 고객이 '업체에 알릴 것'으로 승인한 직접 할 일 칩 사본(project.diy 키). 비면 알린 것 없음
    diy: Mapped[list[str]] = mapped_column(ARRAY(String(10)), default=list, server_default="{}")


class VisitPhoto(Base):
    """실측 요청에 붙인 공간 사진 (0034). 파일은 files(kind photo), 업체는 요청서에서 본다."""

    __tablename__ = "visit_photos"
    __table_args__ = (
        UniqueConstraint("visit_id", "sort", name="uq_visit_photos_sort"),
        CheckConstraint("sort between 0 and 9", name="sort"),
        CheckConstraint("label is null or length(btrim(label)) > 0", name="label"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    sort: Mapped[int] = mapped_column(SmallInteger)
    label: Mapped[str | None] = mapped_column(String(20))  # 사진 이름표 (거실 벽 · 안방 천장)


class VisitEvent(Base):
    """실측 요청 상태 이력 (만들 때 없음 → requested). 상태가 그대로인 기록은 from = to로 남긴다.
    day · half · day_to는 기록 탭(C63 · I2)의 '12.13~12.18' · '12.15(화) 오전'을 그리는 칸이다."""

    __tablename__ = "visit_events"
    __table_args__ = (
        CheckConstraint(f"from_status is null or from_status in {_STATUS_SQL}", name="from_status"),
        CheckConstraint(f"to_status in {_STATUS_SQL}", name="to_status"),
        CheckConstraint(f"half is null or half in {_HALF_SQL}", name="half"),
        CheckConstraint("day_to is null or (day is not null and day_to >= day)", name="day_to"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(10))
    to_status: Mapped[str] = mapped_column(String(10))
    by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    code: Mapped[str | None] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    day: Mapped[date | None] = mapped_column(Date)
    half: Mapped[str | None] = mapped_column(String(2))
    day_to: Mapped[date | None] = mapped_column(Date)


class VisitWindow(Base):
    """업체가 되는 기간 (요청마다 답 하나): 기간 + 빼는 날 + 바로 확정. 고르기 기한 = 답 + 7일."""

    __tablename__ = "visit_windows"
    __table_args__ = (
        CheckConstraint(
            f"end_date >= start_date and end_date - start_date <= {WISH_SPAN_MAX}", name="dates"
        ),
        CheckConstraint(f"cardinality(excluded) <= {EXCLUDED_MAX}", name="excluded"),
        CheckConstraint("pick_due_at > answered_at", name="pick_due"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), primary_key=True
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # 기간 안인지는 service가 본다
    excluded: Mapped[list[date]] = mapped_column(ARRAY(Date), default=list, server_default="{}")
    instant: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    pick_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VisitHold(Base):
    """업체 달력의 반나절 한 칸 (잡아 둠 · 확정). 같은 업체 · 날 · 반나절 · 칸 번호에 살아 있는 잡기는 하나
    (L03: 반나절마다 vendors.visit_capacity개 칸). 늦은 쪽은 IntegrityError → 409 slot_taken."""

    __tablename__ = "visit_holds"
    __table_args__ = (
        Index(
            "uq_visit_holds_seat",
            "vendor_id",
            "day",
            "half",
            "seat",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_visit_holds_visit",
            "visit_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint(f"half in {_HALF_SQL}", name="half"),
        CheckConstraint("seat between 1 and 3", name="seat"),
        CheckConstraint("kind in ('hold', 'booked')", name="kind"),
        CheckConstraint("status in ('active', 'released')", name="status"),
        CheckConstraint("(kind = 'hold') = (until is not null)", name="until"),
        CheckConstraint("(status = 'released') = (released_at is not null)", name="released_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.user_id", ondelete="CASCADE"))
    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date)
    half: Mapped[str] = mapped_column(String(2))
    seat: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    kind: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(8), default="active", server_default="active")
    # 잡아 둔 기한 = 수락 기한
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VisitChange(Base):
    """확정 뒤 고객이 낸 일정 바꾸기 요청. 받기 전까지 원래 반나절 그대로(C28). 열린 요청은 하나."""

    __tablename__ = "visit_changes"
    __table_args__ = (
        Index(
            "uq_visit_changes_open",
            "visit_id",
            unique=True,
            postgresql_where=text("status in ('open', 'countered')"),
        ),
        CheckConstraint(f"from_half in {_HALF_SQL} and to_half in {_HALF_SQL}", name="halves"),
        CheckConstraint("(from_day, from_half) <> (to_day, to_half)", name="moved"),
        CheckConstraint(f"status in {_in(CHANGE_STATUSES)}", name="status"),
        CheckConstraint("(status in ('open', 'countered')) = (closed_at is null)", name="closed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    from_day: Mapped[date] = mapped_column(Date)
    from_half: Mapped[str] = mapped_column(String(2))
    to_day: Mapped[date] = mapped_column(Date)
    to_half: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 요청 + 48시간
    by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VisitProposal(Base):
    """업체가 낸 다른 날 제안(V07) 또는 바꾸기 요청에 낸 다른 날(V20, change_id). 열린 제안은 하나."""

    __tablename__ = "visit_proposals"
    __table_args__ = (
        Index(
            "uq_visit_proposals_open",
            "visit_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        CheckConstraint(
            f"reason_code is null or reason_code in {_in(PROPOSAL_REASONS)}", name="reason_code"
        ),
        # 처음 제안은 이유가 있고, 바꾸기 요청에 낸 다른 날은 이유 없이도 된다
        CheckConstraint("change_id is not null or reason_code is not null", name="reason"),
        CheckConstraint("note is null or length(btrim(note)) > 0", name="note"),
        CheckConstraint(f"status in {_in(PROPOSAL_STATUSES)}", name="status"),
        CheckConstraint("(status = 'open') = (closed_at is null)", name="closed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    change_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visit_changes.id", ondelete="SET NULL")
    )
    reason_code: Mapped[str | None] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 제안 + 48시간
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VisitProposalSlot(Base):
    """제안 한 건의 반나절 1~3개 (고객 희망 기간 안인지 · 개수는 service)"""

    __tablename__ = "visit_proposal_slots"
    __table_args__ = (CheckConstraint(f"half in {_HALF_SQL}", name="half"),)

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visit_proposals.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    half: Mapped[str] = mapped_column(String(2), primary_key=True)
