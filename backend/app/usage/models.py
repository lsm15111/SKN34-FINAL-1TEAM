import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

# 부른 목적. agent/llm.py의 Purpose와 같다(시험이 맞춰 본다)
PURPOSES = (
    "assistant",  # v4 비서 턴(고객 · 업체)
    "floorplan",  # v4 도면 자료 찾기(웹 검색)
    "nudge",  # v4 먼저 말 걸기: 부를지 판단 · 문장
    "memory",  # v4 기억 추출
    "v2_chat",  # v2 /v2/ask 도구 루프(chat_tools)
    "orchestrator",  # 여기부터 planner까지 v2 · v3 structured 역할
    "trade",
    "quote_explanation",
    "schedule",
    "composer",
    "general",
    "planner",
    "judge",  # 평가 판정(evaluation에서만)
    "check",  # 연결 확인
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class LlmUsage(Base):
    """유료 LLM 호출 한 번에 한 줄(계약서 2장). 토큰 · 비용 · 성공 여부만 두고 글은 넣지 않는다.

    cost_micros는 price_ver 가격표로 셈한 마이크로달러(정수). 상한(usage.service)은 이 합계를 센다.
    turn_id는 비서 턴(assistant_turns)을 FK 없이 가리킨다. error에는 오류 종류 이름만 둔다.
    """

    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_created", "created_at"),
        Index("ix_llm_usage_user_created", "user_id", "created_at"),
        CheckConstraint(f"purpose in {_in(PURPOSES)}", name="purpose"),
        CheckConstraint("char_length(btrim(model)) > 0", name="model"),
        CheckConstraint(
            "input_tokens >= 0 and cache_read_tokens >= 0 and cache_write_tokens >= 0"
            " and output_tokens >= 0",
            name="tokens",
        ),
        CheckConstraint("web_searches >= 0", name="web_searches"),
        CheckConstraint("cost_micros >= 0", name="cost"),
        CheckConstraint("latency_ms >= 0", name="latency"),
        CheckConstraint("ok = (error is null)", name="ok"),
        CheckConstraint("error is null or char_length(btrim(error)) > 0", name="error"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    turn_id: Mapped[uuid.UUID | None] = mapped_column()
    purpose: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    web_searches: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    price_ver: Mapped[str] = mapped_column(String(40))
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
