"""v4 비서 표 (계약서 2장): 턴 장부 · 대기 행동 · 먼저 말 걸기(assistant_nudges) · 기억(assistant_memory).

- 턴: 대화(chats.kind='assistant') 한 번의 실행. running 행이 대화 잠금이다(부분 UNIQUE). 글은 chat_messages에
  있고 여기에는 카드 · 흔적(도구 이름 · 결과 크기 · 걸린 시간, 글 없음)만 둔다.
- 행동: 제안 도구가 만든 승인 대기 행. 사람이 승인해야 actions.execute가 기능 service를 부른다.
  target_id는 FK 없이 여러 표(공사 · 실측 · 확정 · 제안)를 가리킨다. 열린 제안은 (사람, 종류, 대상)마다 하나다.
  만료(expired)의 까닭(due · replaced)은 result.reason에 둔다(error_code는 실패에만, CHECK).
- 먼저 말 걸기: 상태 전이 알림 · 시간 · 무응답에서 코드가 만든 제안 한 줄. ref_id는 FK 없이 대상(실측 · 제안 ·
  확정 · 공사)을 가리킨다. (사람, dedup_key)는 한 줄이다. 보낸 뒤 열기 · 닫기는 사람이 한다.
- 기억: 고객이 한 말에서만 뽑은 조건 · 선호. 근거 메시지(chat_messages)가 지워지면 같이 지운다.
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
    # 07 자동화: 추가 금액 답 · 공사 끝 확인 · 한 번 더 요청(0044)
    "extra_answer",
    "work_check",
    "visit_again",
)
ACTION_STATUSES = ("proposed", "approved", "executed", "rejected", "expired", "failed")
ORIGINS = ("turn", "nudge")
TARGET_KINDS = ("project", "visit", "deal", "proposal", "extra")  # extra: 추가 금액(0044)

# 먼저 말 걸기 트리거(계약서 6장 표, proactive.TRIGGERS와 같다)
NUDGE_TRIGGERS = (
    "visit_offered", "quote_sent", "dates_proposed", "work_eve", "no_pick",
    "visit_requested", "visit_picked", "deal_confirmed",
    # 07 자동화(0044, aftercare.TRIGGERS)
    "vendor_out", "extra_added", "work_done", "prep_week", "dates_requested", "quote_due",
)  # fmt: skip
NUDGE_CHANNELS = ("feed", "notify")
NUDGE_STATUSES = ("pending", "held", "sent", "opened", "dismissed", "expired")
NUDGE_SOURCES = ("ai", "guide")  # 문장을 쓴 쪽: Haiku · 정해 둔 틀
# 기억 키(계약서 2장). 사람마다 키 하나에 한 줄(새 말로 덮어씀), 모두 MEMORY_MAX개까지
MEMORY_KEYS = ("avail_days", "avail_half", "living", "style", "material", "priority", "pet", "diy")
MEMORY_MAX = 12


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


class AssistantNudge(Base):
    """먼저 말 걸기 한 줄(계약서 2장 · 6장). 코드가 트리거 · 대상 · 점수를 정하고, 문장(body)만 Haiku가 쓴다.

    pending(기다림) → sent(feed에 보임 · notify면 알림도 씀) → opened · dismissed, 또는 held(기록만) · expired(상태가
    바뀜 · 새 제안에 밀림). 까닭(reason)은 held · expired의 이름이다. card는 보낼 때 만든 카드(CardOut) 통째다.
    """

    __tablename__ = "assistant_nudges"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_assistant_nudges_user_dedup"),
        Index("ix_assistant_nudges_due", "due_at", postgresql_where=text("status = 'pending'")),
        Index("ix_assistant_nudges_user_sent", "user_id", "sent_at"),
        CheckConstraint(f"surface in {_in(SURFACES)}", name="surface"),
        CheckConstraint(f"trigger in {_in(NUDGE_TRIGGERS)}", name="trigger"),
        CheckConstraint(f"channel in {_in(NUDGE_CHANNELS)}", name="channel"),
        CheckConstraint(f"status in {_in(NUDGE_STATUSES)}", name="status"),
        CheckConstraint(f"src is null or src in {_in(NUDGE_SOURCES)}", name="src"),
        CheckConstraint("score between 0 and 100", name="score"),
        CheckConstraint("char_length(dedup_key) between 8 and 80", name="dedup_key"),
        CheckConstraint("body is null or char_length(btrim(body)) between 1 and 200", name="body"),
        CheckConstraint(
            "status not in ('sent', 'opened', 'dismissed')"
            " or (sent_at is not null and body is not null and src is not null)",
            name="sent",
        ),
        CheckConstraint(
            "status not in ('opened', 'dismissed') or acted_at is not null", name="acted"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    surface: Mapped[str] = mapped_column(String(10))
    # 고객 제안만 공사를 적는다(업체 제안은 비움: 업체는 고객 공사 id를 받지 않는다)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    trigger: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[uuid.UUID] = mapped_column()
    dedup_key: Mapped[str] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    score: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    body: Mapped[str | None] = mapped_column(String(200))
    src: Mapped[str | None] = mapped_column(String(5))
    reason: Mapped[str | None] = mapped_column(String(20))
    card: Mapped[dict | None] = mapped_column(JSONB())
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assistant_actions.id", ondelete="SET NULL")
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantMemory(Base):
    """기억 한 줄(계약서 2장 · 7장). 고객 메시지 한 줄에서 Haiku가 뽑고 코드가 검사한 값만 둔다.

    값(value)은 근거 인용(evidence_quote) 안에 있고, 인용은 근거 메시지 글 안에 있다. 기억 쓰기 도구는 없다.
    """

    __tablename__ = "assistant_memory"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_assistant_memory_user_key"),
        CheckConstraint(f"key in {_in(MEMORY_KEYS)}", name="key"),
        CheckConstraint("char_length(btrim(value)) between 1 and 60", name="value"),
        CheckConstraint(
            "char_length(btrim(evidence_quote)) between 1 and 200", name="evidence_quote"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(12))
    value: Mapped[str] = mapped_column(String(60))
    evidence_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    evidence_quote: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
