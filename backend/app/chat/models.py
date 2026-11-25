import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7


class Chat(Base):
    """대화방 하나. 고객 한 명이 여러 개 가질 수 있다.

    rev: 저장할 때마다 1씩 오르는 번호표. 질문을 시작할 때 본 번호와 저장할 때 번호가 다르면
    다른 질문이 먼저 저장된 것이라 늦은 쪽은 쓰지 않는다(409). 기한 잠금 대신 쓴다.
    """

    __tablename__ = "chats"
    __table_args__ = (
        CheckConstraint("rev >= 1", name="rev"),
        CheckConstraint(
            "waiting is null or waiting in ('orchestrator', 'trade', 'quote_explanation', 'schedule')",
            name="waiting",
        ),
        # 공사별 대화 목록(0034, B5 부탁): 같은 사람 · 같은 공사를 최근 순으로 거꾸로 읽는다
        Index("ix_chats_user_project", "user_id", "project_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # v3 (0034): AI 대화를 공사에 묶는다(없으면 공사 밖 가이드 대화). 공사가 지워지면 대화도 지운다
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    rev: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    waiting: Mapped[str | None] = mapped_column(String(30))  # 고객 답을 기다리는 담당
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """주고받은 말 한 줄. 한 번 저장할 때 고객 질문 · 답 두 줄이 같은 turn으로 쌓인다.

    관문 결과(라벨 · 신뢰도 · 출처)는 고객 질문 줄에만 남긴다. 의도 분류 재평가 재료.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        # 같은 턴을 두 번 저장하지 않는다
        UniqueConstraint("chat_id", "turn", "role", name="uq_chat_messages_chat_turn_role"),
        CheckConstraint("turn >= 1", name="turn"),
        CheckConstraint("role in ('user', 'assistant')", name="role"),
        CheckConstraint(
            "intent_label is null or intent_label in"
            " ('orchestrator', 'trade', 'quote_explanation', 'schedule', 'out_of_scope')",
            name="intent_label",
        ),
        CheckConstraint(
            "intent_confidence is null or intent_confidence between 0 and 1",
            name="intent_confidence",
        ),
        CheckConstraint(
            "intent_source is null or intent_source in ('rule', 'model', 'jev', 'button')",
            name="intent_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    turn: Mapped[int] = mapped_column(Integer)  # 저장할 때의 rev. 오래된 것부터 정렬하는 기준
    role: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    intent_label: Mapped[str | None] = mapped_column(String(30))
    intent_confidence: Mapped[float | None] = mapped_column(Float)
    intent_source: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
