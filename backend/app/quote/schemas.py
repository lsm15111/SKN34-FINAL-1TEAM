import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.quote.sourcing import CostKind, Route


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


class SourcingOut(BaseModel):
    project_id: uuid.UUID
    region: str
    trades: list[str]
    facts: list[str] = Field(description="업체에 건넬 집 정보 (코드가 만든 것, 복사용)")
    candidates: list[CandidateOut]
    proxy_enabled: bool
    notice: str | None = None
    prompt_version: str | None = None
