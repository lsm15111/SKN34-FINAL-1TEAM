"""v2 인테리어 한 건 저장 · 목록 입출력."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.shared.text import Tidy
from app.v2.schemas import V2PlanIn, V2QuoteIn

Title = Field(min_length=1, max_length=40)


class V2CaseSaveIn(BaseModel):
    """state: 화면이 고른 값(사진 · 올린 파일은 빼고). quote_in · plan_in이 있으면 서버가 다시 계산해 남긴다."""

    title: Annotated[str, Field(min_length=1, max_length=40), Tidy] | None = None
    state: dict[str, Any]
    quote_in: V2QuoteIn | None = None
    plan_in: V2PlanIn | None = None


class V2CaseTitleIn(BaseModel):
    title: Annotated[str, Tidy] = Title


class V2CaseItemOut(BaseModel):
    id: uuid.UUID
    title: str
    style: str | None
    pyeong: float | None
    region: str
    picks: int
    far: int
    quote_total: int | None
    quote_code: str | None
    cost_lo: int | None  # 예상 공사비 (부가세 포함, 견적서 요약과 같은 값)
    cost_hi: int | None
    trades: int  # 견적에 든 공정 수
    plan_start: date | None
    plan_end: date | None
    work_days: int | None
    created_at: datetime
    updated_at: datetime


class V2CaseOut(V2CaseItemOut):
    state: dict[str, Any]
    quote: dict[str, Any] | None
    plan: dict[str, Any] | None
