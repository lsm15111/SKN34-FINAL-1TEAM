"""v4 비서 표 (계약서 2장): 턴 장부(assistant_turns) · 대기 행동(assistant_actions).

- 턴: 대화(chats.kind='assistant') 한 번의 실행. running 행이 대화 잠금이다(부분 UNIQUE). 글은 chat_messages에
  있고 여기에는 카드 · 흔적(도구 이름 · 결과 크기 · 걸린 시간, 글 없음)만 둔다.
- 행동: 제안 도구가 만든 승인 대기 행. 사람이 승인해야 actions.execute가 기능 service를 부른다.
  target_id는 FK 없이 여러 표(공사 · 실측 · 확정 · 제안)를 가리킨다. 열린 제안은 (사람, 종류, 대상)마다 하나다.
  만료(expired)의 까닭(due · replaced)은 result.reason에 둔다(error_code는 실패에만, CHECK).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# chats · projects · visits 표(FK)를 metadata에 올린다(비서 표만 불러오는 worker · 시험용)
import app.chat.models
import app.project.models
import app.visit.models  # noqa: F401
from app.db import Base
from app.shared.ids import uuid7

SURFACES = ("customer", "vendor")
TURN_STATUSES = ("running", "done", "stopped", "failed")
MODES = ("llm", "free")
TOOL_MAX = 6  # 턴 하나의 도구 호출 상한(계약서 4장)

# 제안 도구와 1:1 (propose_<kind>)
ACTION_KINDS = (
    "home_info",
    "visit_request",
    "visit_slot",
    "vendor_confirm",
    "dates_accept",
    "delay_accept",
    "window_answer",
    "decline",
    "dates",
)
ACTION_STATUSES = ("proposed", "approved", "executed", "rejected", "expired", "failed")
ORIGINS = ("turn", "nudge")
TARGET_KINDS = ("project", "visit", "deal", "proposal")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class AssistantTurn(Base):
    __tablename__ = "assistant_turns"
    __table_args__ = (
        UniqueConstraint("user_id", "client_key", name="uq_assistant_turns_user_key"),
        # 대화 잠금: 대화마다 도는 턴은 하나(늦은 쪽은 409 turn_running)
        Index(
            "uq_assistant_turns_running",
            "chat_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_assistant_turns_chat_created", "chat_id", "created_at"),
        CheckConstraint(f"surface in {_in(SURFACES)}", name="surface"),
        CheckConstraint(f"status in {_in(TURN_STATUSES)}", name="status"),
        CheckConstraint(f"mode in {_in(MODES)}", name="mode"),
        CheckConstraint(f"tool_calls between 0 and {TOOL_MAX}", name="tool_calls"),
        CheckConstraint("cost_micros >= 0", name="cost"),
        CheckConstraint("char_length(client_key) between 8 and 64", name="client_key"),
        CheckConstraint("(status = 'failed') = (error_code is not null)", name="failed"),
        CheckConstraint("(status = 'running') = (ended_at is null)", name="ended"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    surface: Mapped[str] = mapped_column(String(10))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    client_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), default="running", server_default="running")
    mode: Mapped[str] = mapped_column(String(5), default="free", server_default="free")
    tool_calls: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40))
    # {rev, llm, tools: [{name, ok, size, ms}], actions: [id], stop, ms} (글 없음)
    trace: Mapped[dict] = mapped_column(JSONB(), default=dict, server_default=text("'{}'::jsonb"))
    # 이 턴에 보낸 카드(CardOut) 순서대로. 대화를 다시 열면 이것으로 그린다
    cards: Mapped[list] = mapped_column(JSONB(), default=list, server_default=text("'[]'::jsonb"))
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantAction(Base):
    __tablename__ = "assistant_actions"
    __table_args__ = (
        UniqueConstraint("user_id", "idem_key", name="uq_assistant_actions_user_idem"),
        # 대상마다 열린 제안은 하나(새로 만들면 옛 것은 expired · replaced)
        Index(
            "uq_assistant_actions_open",
            "user_id",
            "kind",
            "target_id",
            unique=True,
            postgresql_where=text("status = 'proposed'"),
        ),
        Index(
            "ix_assistant_actions_due", "expires_at", postgresql_where=text("status = 'proposed'")
        ),
        Index("ix_assistant_actions_user_created", "user_id", "created_at"),
        CheckConstraint(f"surface in {_in(SURFACES)}", name="surface"),
        CheckConstraint(f"origin in {_in(ORIGINS)}", name="origin"),
        CheckConstraint(f"kind in {_in(ACTION_KINDS)}", name="kind"),
        CheckConstraint(f"status in {_in(ACTION_STATUSES)}", name="status"),
        CheckConstraint(f"target_kind in {_in(TARGET_KINDS)}", name="target_kind"),
        CheckConstraint("char_length(idem_key) between 8 and 64", name="idem_key"),
        CheckConstraint("expires_at > created_at", name="expires"),
        CheckConstraint(
            "(status in ('proposed', 'expired')) = (decided_at is null)", name="decided"
        ),
        CheckConstraint("(status = 'executed') = (executed_at is not null)", name="executed"),
        CheckConstraint("(status = 'failed') = (error_code is not null)", name="failed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    surface: Mapped[str] = mapped_column(String(10))
    origin: Mapped[str] = mapped_column(String(10), default="turn", server_default="turn")
    kind: Mapped[str] = mapped_column(String(20))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    target_kind: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[uuid.UUID] = mapped_column()
    target_ver: Mapped[str | None] = mapped_column(String(40))
    # 실행할 값(코드가 ref를 풀어 넣은 id · 날짜). LLM 글은 넣지 않는다
    payload: Mapped[dict] = mapped_column(JSONB())
    # 무엇 · 얼마 · 어느 버전(ActionSummary). 금액 · 날짜는 계산 엔진 값
    summary: Mapped[dict] = mapped_column(JSONB())
    idem_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), default="proposed", server_default="proposed")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    # 실행 결과 {text, href, label} · 만료 까닭 {reason} · 새 판 {superseded_by} · 옛 판 {supersedes}
    result: Mapped[dict | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
