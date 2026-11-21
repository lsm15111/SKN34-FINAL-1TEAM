"""고객-업체 채팅 API 모양 (api.md 7장). 업체 쪽 응답에는 고객 이름 · 휴대폰 칸을 두지 않는다."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.shared.text import clean_input
from app.thread.models import BODY_MAX

# 제어 문자 · ANSI 색 코드 · 방향 바꾸기 글자는 길이 · 빈 글 검사 전에 지운다(NUL은 저장에서 500, 보안 L1 · L2)
Body = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=BODY_MAX),
    BeforeValidator(clean_input),
]
RoReason = Literal["other_chosen", "cancelled", "declined", "withdrawn", "blocked", "admin"]


class ThreadLastOut(BaseModel):
    kind: Literal["text", "photo", "system"]
    preview: str | None = Field(description="글 앞부분 · '사진' · 시스템 카드 말 (화면이 줄인다)")
    at: datetime


class ThreadRowOut(BaseModel):
    """채팅 목록 한 줄 (C24 · V19). 최근 순"""

    thread_id: uuid.UUID
    title: str = Field(description="고객 화면: 업체 상호 · 업체 화면: '상계동 고객'")
    visit_label: str | None = Field(description="실측 12.15(화) 오전 (화면 말)")
    last: ThreadLastOut | None
    unread: int
    status: Literal["open", "read_only"]
    ro_reason: RoReason | None


class ThreadCanOut(BaseModel):
    write: bool
    change_request: bool = Field(description="고객: 실측 일정 바꾸기 요청")
    cancel: bool = Field(description="고객: 실측 취소")
    report: bool


class ThreadLinksOut(BaseModel):
    quote: str | None = Field(description="견적서 보기 경로")
    project: str | None = Field(
        description="공사 보기 경로 (고객 /projects/{id} · 업체 /vendor/jobs/{did})"
    )


class ThreadOut(BaseModel):
    """대화 머리 (C25 · V09): 상대 이름표 · 공사 요약 · 단추"""

    thread_id: uuid.UUID
    title: str
    area_label: str = Field(description="노원구 상계동 69.4㎡")
    visit_id: uuid.UUID | None
    deal_id: uuid.UUID | None
    project_id: uuid.UUID | None = Field(description="고객에게만 (업체에는 비움)")
    status: Literal["open", "read_only"]
    ro_reason: RoReason | None
    blocked: bool = Field(description="고객이 차단함")
    last_seq: int
    read_seq: int = Field(description="내가 읽은 마지막 글")
    can: ThreadCanOut
    links: ThreadLinksOut


class MessageOut(BaseModel):
    """글 한 줄. warn(믿집 밖 거래 주의 줄)은 고객 화면에만 들어 있다(D05 A)."""

    model_config = ConfigDict(populate_by_name=True)

    seq: int
    id: uuid.UUID
    sender: Literal["me", "them", "system"] = Field(alias="from")
    kind: Literal["text", "photo", "system"]
    body: str | None
    file_id: uuid.UUID | None = Field(description="사진 (GET /threads/{tid}/files/{file_id})")
    system_code: str | None
    ref_id: uuid.UUID | None
    warn: Literal["offsite"] | None
    at: datetime


class MessageIn(BaseModel):
    """글 보내기. client_key가 같으면 저장하지 않고 처음 글을 200으로 돌려준다."""

    client_key: uuid.UUID
    kind: Literal["text", "photo"]
    body: Body | None = None
    file_id: uuid.UUID | None = Field(default=None, description="POST /files kind=chat_photo")

    @model_validator(mode="after")
    def _kind(self) -> "MessageIn":
        if self.kind == "text" and self.body is None:
            raise ValueError("보낼 글을 적어 주세요.")
        if self.kind == "photo" and self.file_id is None:
            raise ValueError("보낼 사진을 골라 주세요.")
        return self


class ReadIn(BaseModel):
    seq: int = Field(ge=0, description="읽은 마지막 글 (줄지 않는다)")
