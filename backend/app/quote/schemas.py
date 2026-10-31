import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.quote.sourcing import CostKind, Route

_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


class ContactRequestIn(BaseModel):
    """외부 업체에 믿집이 대신 보낼 가견적 요청. 고객이 받는 업체와 보낼 글에 동의해야 한다."""

    project_id: uuid.UUID
    trade: str = Field(min_length=1, max_length=10)
    vendor_id: uuid.UUID = Field(description="외부 업체 id")
    body: str = Field(max_length=800, description="업체에 보낼 글 (10자 이상, 링크 없이)")
    consent: Literal[True] = Field(
        description="받는 업체 · 보낼 글 · 믿집이 대신 보내는 것에 동의 (true만 받는다)"
    )

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("요청 내용을 10자 이상 적어 주세요.")
        if _LINK.search(v):
            raise ValueError("링크는 넣을 수 없어요.")
        return v


class ContactRequestOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    trade: str
    vendor_id: uuid.UUID
    channel: Literal["sms", "email", "form"]
    status: Literal["draft", "queued", "sending", "sent", "test_sent", "failed", "blocked"] = Field(
        description="test_sent = 시험 발송(기록만, 실제로 보내지 않음). sent는 실제 발송만"
    )
    send_enabled: bool
    notice: str


class CostOut(BaseModel):
    kind: CostKind
    amount: int | None = Field(description="원. 업체가 공지한 출장비일 때만")
    label: str


class SourceOut(BaseModel):
    kind: Literal["app", "sangga", "kiscon", "seed"]
    label: str
    fetched_at: datetime | None = Field(description="모은 날 (앱 업체는 승인한 날)")


class LinksOut(BaseModel):
    homepage: str | None = None
    portfolio: list[str] = []
    quote: str | None = Field(default=None, description="공개 견적 · 문의 창구")
    place: str | None = Field(default=None, description="카카오맵 장소 페이지")


class RequestStateOut(BaseModel):
    trade: str
    status: str
    label: str


class CandidateOut(BaseModel):
    id: uuid.UUID
    kind: Literal["app", "ext"]
    name: str
    trades: list[str]
    region: str
    near: bool = Field(description="프로젝트와 같은 시 · 군 · 구")
    route: Route
    route_label: str
    cost: CostOut
    source: SourceOut
    links: LinksOut
    registration: str | None = Field(description="등록 정보 (예: 실내건축공사업 등록)")
    biz_status: str | None = Field(description="국세청 사업자 상태")
    phone: str | None = Field(description="공공 등록 정보에 나온 사무실 번호")
    proxy_off: bool = Field(description="대신 요청을 쓸 수 있는 업체지만 기능이 꺼져 있음")
    checklist: list[str] = Field(description="전화로 물어볼 것 (phone 길일 때)")
    why: str | None = Field(
        default=None, description="이 업체를 고른 이유 한 줄 (LLM, 실패하면 비움)"
    )
    draft: str | None = Field(default=None, description="요청문 초안 (LLM, 실패하면 비움)")
    requests: list[RequestStateOut] = []


class QuoteRequestIn(BaseModel):
    trade: str = Field(min_length=1, max_length=10)
    vendor_id: uuid.UUID
    message: str = Field(default="", max_length=1000, description="업체에 남길 말 (선택)")


class QuoteRequestOut(BaseModel):
    id: uuid.UUID
    trade: str
    vendor_id: uuid.UUID
    status: Literal["requested", "viewed"]
    created_at: datetime


class InboxItemOut(BaseModel):
    """업체 받은편지함 한 줄. 고객 이름 · 연락처 · 동 · 호수는 없다."""

    id: uuid.UUID
    trade: str
    trade_label: str
    status: Literal["requested", "viewed"]
    status_label: str
    region: str
    facts: list[str]
    message: str
    created_at: datetime
    viewed_at: datetime | None


class SourcingOut(BaseModel):
    project_id: uuid.UUID
    region: str
    trades: list[str]
    facts: list[str] = Field(description="업체에 건넬 집 정보 (코드가 만든 것, 복사용)")
    candidates: list[CandidateOut]
    proxy_enabled: bool
    notice: str | None = None
    prompt_version: str | None = None
