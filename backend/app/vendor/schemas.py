import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.auth.schemas import clean_name, normalize_email


class AreaIn(BaseModel):
    sido: str
    sgg: str


class VendorSignupIn(BaseModel):
    """업체 회원가입. 기본 회원정보만 받고, 사업자등록증 파일은 따로 받는다.

    상호 · 사업자번호 · 공정 · 지역 같은 업체 정보는 승인 뒤 업체 정보 관리에서 받는다.
    """

    name: str = Field(max_length=50, description="담당자 이름")
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    _email = field_validator("email")(normalize_email)
    _name = field_validator("name")(clean_name)


class RejectIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class VendorCard(BaseModel):
    """가견적 후보로 보여 줄 승인 업체. 연락처 · 담당자 이름은 넣지 않는다."""

    user_id: uuid.UUID
    name: str
    trades: list[str]
    site_url: str | None
    approved_at: datetime | None


class VendorAdminOut(BaseModel):
    """관리자 업체관리 · 가입 승인 화면용. 업체 정보 칸은 승인 뒤 채워진다."""

    user_id: uuid.UUID
    name: str
    email: str
    license_file_id: uuid.UUID
    status: str
    reject_reason: str | None
    created_at: datetime
    reviewed_at: datetime | None
    biz_name: str | None
    owner_name: str | None
    biz_no: str | None
    phone: str | None
    address: str | None
    site_url: str | None
    trades: list[str]
    areas: list[AreaIn]
    intro: str
