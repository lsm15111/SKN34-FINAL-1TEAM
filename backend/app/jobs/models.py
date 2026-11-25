import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

# 기한 일 kind (architecture.md 6장 표). 처리 함수 표(kind → 함수)는 worker.py(조립 층)에 둔다
KINDS = (
    "visit_reply_due",  # 요청 + 48시간: 아직 requested면 expired(reply)
    "visit_pick_due",  # 업체 답 + 7일: 아직 offered면 expired(pick)
    "visit_accept_due",  # 고른 때 + 48시간: 아직 picked면 잡기 풀기 · offered (D12 최소 처리)
    "visit_proposal_due",  # 제안 + 48시간: 제안 expired · offered (D12 최소 처리)
    "visit_change_due",  # 바꾸기 요청 + 48시간: 요청 expired · 원래 일정 그대로
    "visit_reminder",  # 실측 전날 18:00: 양쪽 알림
    "visit_quote_due",  # 실측일 + 3일 18:00: 견적서가 없으면 고객 알림
    "quote_valid_soon",  # 유효기간 3일 · 1일 전: 고객 알림
    "deal_dates_due",  # 확정 + 2일 18:00: 공사 날짜가 없으면 양쪽 알림
    "deal_request_due",  # 다른 날짜 요청 + 48시간: 새 날짜가 없으면 양쪽 알림
    "deal_done_remind",  # 공사 끝 알림 + 4일: '3일 뒤 자동으로 끝나요'
    "deal_auto_done",  # 공사 끝 알림 + 7일: 아직 checking이면 done(자동)
    "thread_redact",  # 닫힌 대화 + 보관 기간: 글 본문 지우기 (보관 기간이 정해질 때까지 안 씀)
)
STATUSES = ("pending", "running", "done", "skipped", "failed", "cancelled")
FINISHED = ("done", "skipped", "failed", "cancelled")
ATTEMPTS_MAX = 5


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class Job(Base):
    """기한 일 한 줄 (D14 A). 상태를 바꾸는 service가 같은 트랜잭션에 넣고, worker가 1분마다 거둔다.

    ref_id는 FK 없이 여러 표를 가리킨다(대상이 지워졌으면 처리 함수가 skipped로 끝낸다).
    dedup_key가 같은 일은 한 번만 들어간다(jobs.service.key). last_error에는 오류 종류 이름만 둔다.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_due", "run_at", postgresql_where=text("status = 'pending'")),
        Index("ix_jobs_stuck", "locked_until", postgresql_where=text("status = 'running'")),
        CheckConstraint(f"kind in {_in(KINDS)}", name="kind"),
        CheckConstraint(f"status in {_in(STATUSES)}", name="status"),
        CheckConstraint("attempts between 0 and 10", name="attempts"),
        CheckConstraint("(status = 'running') = (locked_until is not null)", name="locked"),
        CheckConstraint(f"(status in {_in(FINISHED)}) = (done_at is not null)", name="done_at"),
        CheckConstraint("last_error is null or length(btrim(last_error)) > 0", name="last_error"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[uuid.UUID | None] = mapped_column()
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(60))
    dedup_key: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
