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
    Integer,
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

# 제안 도구와 1:1 (propose_<kind>). date_change는 0044에서 더함(고객 공사 날짜 바꾸기 요청)
ACTION_KINDS = (
    "home_info",
    "visit_request",
    "visit_slot",
    "vendor_confirm",
    "dates_accept",
    "delay_accept",
    "date_change",
    "window_answer",
    "decline",
    "dates",
    # 07 자동화: 추가 금액 답 · 공사 끝 확인 · 한 번 더 요청(0044)
    "extra_answer",
    "work_check",
    "visit_again",
    # 보낸 실측 요청 취소(0051, visit.service.cancel)
    "visit_cancel",
    # 희망 예산(0059, 집 정보 '예산' 칸 project.service.set_budget)
    "budget",
    # 도배 전 앞 공사 답(0060, project.prework.set_prework). 제안 도구 없이 점검 카드 단추(choices)로만 만들어요
    "prework",
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
    # 이어 하기(0054, follow.py): 사람이 누른 카드 뒤 코드가 바로 내미는 다음 카드
    "follow_up",
)  # fmt: skip
NUDGE_CHANNELS = ("feed", "notify")
NUDGE_STATUSES = ("pending", "held", "sent", "opened", "dismissed", "expired")
NUDGE_SOURCES = ("ai", "guide")  # 문장을 쓴 쪽: Haiku · 정해 둔 틀
# 기억 키(계약서 2장). 사람마다 키 하나에 한 줄(새 말로 덮어씀, 목록 칸은 더함), 모두 MEMORY_MAX개까지.
# move_in(이사 · 입주 때)은 0048에서 더함
MEMORY_KEYS = (
    "avail_days", "avail_half", "living", "style", "material", "priority", "pet", "diy", "move_in",
)  # fmt: skip
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
        # 보이는 줄의 due_at = 정리가 마지막으로 본 때(proactive._settle_rows가 오래 안 본 줄부터 읽는다, 0051)
        Index(
            "ix_assistant_nudges_shown_due",
            "due_at",
            "id",
            postgresql_where=text("status in ('sent', 'opened')"),
        ),
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


class AssistantMemoryMark(Base):
    """기억 칸(사람, 키)마다 마지막으로 바뀐 때: 그 값을 말한 때 · 고객이 지운 때 · 칩으로 줄인 때(0055). 늘기만 하고
    기억 줄을 지워도 남는다. 값 · 글은 두지 않는다.

    기억 뽑기 일은 그 말을 한 때가 이 값보다 앞이면 그 칸을 건드리지 않는다: 미뤘다 뽑거나 다시 하는 옛 말이 나중
    말을 덮거나, 지운 기억이 지우기 전에 한 말로 다시 생기지 않게(R1b #8 · #9).
    """

    __tablename__ = "assistant_memory_marks"
    __table_args__ = (CheckConstraint(f"key in {_in(MEMORY_KEYS)}", name="key"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(12), primary_key=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssistantRefTop(Base):
    """비서 대화 이름표 머리글자(v · m · s …)마다 쓴 가장 큰 번호(runtime.RefTable). 늘기만 한다.

    이름표 표 · 번호 기록은 Redis(지워져도 되는 값)에 있어, 모두 지워지면 번호를 1부터 다시 매겨 지난 카드 단추의
    이름표가 새 대상을 가리킬 수 있었다(QA edge P3). 새 번호를 쓴 표를 저장할 때 여기 번호보다 크지 않으면 그 이름을
    버려(모르는 이름표 → 카드를 새로 불러옴) 같은 이름이 다른 대상을 가리키지 않게 한다.
    """

    __tablename__ = "assistant_ref_tops"
    __table_args__ = (
        CheckConstraint("prefix ~ '^[a-z]$'", name="prefix"),
        CheckConstraint("top >= 1", name="top"),
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    prefix: Mapped[str] = mapped_column(String(1), primary_key=True)
    top: Mapped[int] = mapped_column(Integer)


# 조사 담당(리서처, docs/v4/09-research.md). 종류 · 상태 · 진행 단계
RESEARCH_KINDS = ("outside_vendors", "materials", "general")
RESEARCH_STATUSES = ("queued", "running", "done", "failed", "stopped")
RESEARCH_LIVE = ("queued", "running")  # 도는 조사(공사마다 하나)
RESEARCH_STEPS = ("search", "read", "write")


class AssistantResearch(Base):
    """조사 하나(09-research). 비서 도구(start_research)가 대기 줄을 넣고, worker가 Claude 웹 검색 · 가져오기로 돌린다.

    - 상태는 assistant/research.py 한 곳에서 조건부 UPDATE로 바꾼다: queued → running → done · stopped · failed,
      queued → stopped(시작 전 멈춤) · failed(멈춘 조사). 공사마다 도는 조사(queued · running)는 하나다(부분 UNIQUE).
    - goal은 가린 글(구 · 동 · 평형 · 도배 조건), steps는 진행 단계 · 상태 기록, notes는 바꾸기 메모(가린 글),
      notes_used는 worker가 다음 왕복에 넣은 메모 수, stop_at은 멈춤 요청 때다.
    - result는 그 고객 것만(요약 · 링크 · 확인하는 곳). 다른 고객에게 다시 쓰지 않고, 30일 지나면 지워도 된다.
    """

    __tablename__ = "assistant_research"
    __table_args__ = (
        Index(
            "uq_assistant_research_live",
            "project_id",
            unique=True,
            postgresql_where=text("status in ('queued', 'running')"),
        ),
        Index("ix_assistant_research_project_created", "project_id", "created_at"),
        Index("ix_assistant_research_user_created", "user_id", "created_at"),
        CheckConstraint(f"kind in {_in(RESEARCH_KINDS)}", name="kind"),
        CheckConstraint(f"status in {_in(RESEARCH_STATUSES)}", name="status"),
        CheckConstraint(f"step is null or step in {_in(RESEARCH_STEPS)}", name="step"),
        CheckConstraint("char_length(btrim(title)) between 1 and 40", name="title"),
        CheckConstraint("char_length(btrim(goal)) between 1 and 200", name="goal"),
        CheckConstraint("calls between 0 and 20", name="calls"),
        CheckConstraint("notes_used >= 0", name="notes_used"),
        CheckConstraint("cost_micros >= 0", name="cost"),
        CheckConstraint("(status in ('queued', 'running')) = (ended_at is null)", name="ended"),
        CheckConstraint("status <> 'running' or started_at is not null", name="started"),
        CheckConstraint("(status = 'failed') = (error_code is not null)", name="failed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    turn_id: Mapped[uuid.UUID | None] = mapped_column()  # 시작한 비서 턴(FK 없음, 흔적)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(40))
    goal: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued")
    step: Mapped[str | None] = mapped_column(String(10))
    # [{step | event, at}] 진행 단계 · 상태 기록(글 없음)
    steps: Mapped[list] = mapped_column(JSONB(), default=list, server_default=text("'[]'::jsonb"))
    # [{text, at}] 바꾸기 메모(가린 글)
    notes: Mapped[list] = mapped_column(JSONB(), default=list, server_default=text("'[]'::jsonb"))
    notes_used: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    stop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # {summary, links, checks, note, partial, outside} (research.ResearchData 결과 칸)
    result: Mapped[dict | None] = mapped_column(JSONB())
    calls: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
