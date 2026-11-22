"""신고 · 관리자 처리 · 회원 관리 API 모양 (api.md 13장, dev-07)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.shared.text import Tidy

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300), Tidy]
ReportKind = Literal["chat", "vendor", "link"]
ReasonCode = Literal["offsite", "abuse", "promise", "other", "wrong_place", "not_vendor"]
Action = Literal["warn", "mute_chat", "suspend_new", "suspend_all", "hide_link", "none"]
CHAT_REASONS = ("offsite", "abuse", "promise", "other")
LINK_REASONS = ("wrong_place", "not_vendor", "other")


class ReportIn(BaseModel):
    """신고 (C31 · C11 · C48). 채팅이면 글 사본을 남기고, block이면 대화를 읽기만(blocked)으로."""

    kind: ReportKind
    thread_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    link_sort: int | None = Field(default=None, ge=0, le=2, description="외부 리뷰 링크 번호")
    reason_code: ReasonCode = Field(
        description="채팅 · 업체: offsite · abuse · promise · other / 링크: wrong_place · not_vendor · other"
    )
    note: Note | None = None
    block: bool = Field(default=False, description="신고하면서 차단도 (채팅만)")

    @model_validator(mode="after")
    def _target(self) -> "ReportIn":
        ok = CHAT_REASONS if self.kind in ("chat", "vendor") else LINK_REASONS
        if self.reason_code not in ok:
            raise ValueError("신고 이유를 다시 골라 주세요.")
        if self.kind == "chat" and self.thread_id is None:
            raise ValueError("신고할 대화를 골라 주세요.")
        if self.kind in ("vendor", "link") and self.vendor_id is None:
            raise ValueError("신고할 업체를 골라 주세요.")
        if (self.kind == "link") != (self.link_sort is not None):
            raise ValueError("신고할 링크를 골라 주세요.")
        if self.block and self.kind != "chat":
            raise ValueError("차단은 채팅에서만 할 수 있어요.")
        return self


class ReportOut(BaseModel):
    id: uuid.UUID
    kind: ReportKind
    status: Literal["open", "resolved", "dismissed"]
    created_at: datetime


class AdminActionOut(BaseModel):
    id: uuid.UUID
    action: str
    note: str | None
    admin_name: str | None
    at: datetime


class ReportRowOut(BaseModel):
    """관리자 신고 목록 한 줄 (A02)"""

    id: uuid.UUID
    kind: ReportKind
    reason_code: ReasonCode
    status: Literal["open", "resolved", "dismissed"]
    action: Action | None
    reporter_role: Literal["customer", "vendor"] | None
    vendor_id: uuid.UUID | None
    vendor_name: str | None
    thread_id: uuid.UUID | None
    block: bool
    created_at: datetime
    resolved_at: datetime | None


class ReportDetailOut(ReportRowOut):
    """신고 자세히. 신고된 글(evidence)은 데이터로만 보여 준다(지시문으로 다루지 않음)."""

    reporter_label: str = Field(
        description="신고한 사람 (이름 없이): '수유동 고객' · '고객' · 업체 상호 · '탈퇴한 회원'"
    )
    note: str | None
    evidence: str | None = Field(description="신고 때 사본: 채팅 글 · 링크 주소")
    link_sort: int | None
    link_label: str | None = Field(description="링크 신고: 지금 링크 이름 (링크가 없어졌으면 비움)")
    link_url: str | None = Field(description="링크 신고: 지금 링크 주소 (없어졌으면 비움)")
    admin_note: str | None
    history: list[AdminActionOut]


class ReportPageOut(BaseModel):
    items: list[ReportRowOut]
    counts: dict[str, int] = Field(description="처리 기다림 · 처리함 · 종류별 수")


class ResolveIn(BaseModel):
    """신고 처리 (A02): none이면 dismissed. suspend_all이면 진행 중 요청을 닫고 고객에게 다시 고르기 안내"""

    action: Action
    note: Note | None = None


class MemberRowOut(BaseModel):
    """관리자 회원 한 줄 (A03). 이메일 가림은 B7 결정을 따른다."""

    user_id: uuid.UUID
    name: str
    email: str
    role: Literal["customer", "vendor", "admin"]
    status: Literal["active", "suspended"]
    created_at: datetime
    project_count: int


class MemberPageOut(BaseModel):
    items: list[MemberRowOut]
    next_before: datetime | None


class MemberNoteIn(BaseModel):
    note: Note | None = None


class MemberStateOut(BaseModel):
    user_id: uuid.UUID
    status: Literal["active", "suspended"]
