import re
import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.auth.schemas import clean_name, normalize_email
from app.shared.regions import is_region
from app.vendor.models import MAX_PORTFOLIO_URLS, TRADES

MAX_AREAS = 50  # 일하는 지역(시 · 군 · 구) 수. 실제로 가는 곳만 고르게 한다
_URL_MAX = 300
_BLANK = re.compile(r"[\s\x00-\x1f\x7f]")


class AreaIn(BaseModel):
    sido: str
    sgg: str


def clean_url(v: str) -> str:
    """http · https 주소만. 앞말(https)만 소문자로 맞추고 나머지는 적은 그대로 둔다."""
    v = v.strip()
    try:
        parts = urlsplit(v)
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("http:// 또는 https://로 시작하는 주소를 넣어 주세요.")
    if _BLANK.search(v):
        raise ValueError("주소에 빈칸이 들어 있어요.")
    if len(v) > _URL_MAX:
        raise ValueError(f"주소는 {_URL_MAX}자까지예요.")
    return parts.scheme + v[len(parts.scheme) :]


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
    portfolio_urls: list[str] = []
    approved_at: datetime | None


class VendorProfileIn(BaseModel):
    """업체 정보 관리. 통째로 바꾼다. 공정 · 지역이 있어야 고객 가견적 후보에 나온다."""

    biz_name: str = Field(max_length=100, description="상호 (가견적 후보에 보이는 이름)")
    site_url: str | None = Field(default=None, max_length=_URL_MAX, description="홈페이지")
    trades: list[str] = Field(min_length=1, max_length=len(TRADES), description="맡는 공정 키")
    areas: list[AreaIn] = Field(
        min_length=1, max_length=MAX_AREAS, description="일하는 지역 (시 · 도 id + 시 · 군 · 구)"
    )
    portfolio_urls: list[str] = Field(
        default=[], max_length=MAX_PORTFOLIO_URLS, description="시공 사례 링크 (http · https)"
    )

    @field_validator("biz_name")
    @classmethod
    def _biz_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("상호를 적어 주세요.")
        return v

    @field_validator("site_url")
    @classmethod
    def _site_url(cls, v: str | None) -> str | None:
        return clean_url(v) if v and v.strip() else None

    @field_validator("trades")
    @classmethod
    def _trades(cls, v: list[str]) -> list[str]:
        if not set(v) <= set(TRADES):
            raise ValueError("모르는 공정이 있어요.")
        return [t for t in TRADES if t in v]  # 정한 순서로, 겹치면 하나만

    @field_validator("areas")
    @classmethod
    def _areas(cls, v: list[AreaIn]) -> list[AreaIn]:
        if not all(is_region(a.sido, a.sgg) for a in v):
            raise ValueError("모르는 지역이 있어요. 다시 골라 주세요.")
        return [AreaIn(sido=a, sgg=b) for a, b in dict.fromkeys((a.sido, a.sgg) for a in v)]

    @field_validator("portfolio_urls")
    @classmethod
    def _portfolio_urls(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(clean_url(u) for u in v))


class VendorProfileOut(BaseModel):
    """업체 정보 관리 화면. 승인 직후에는 모두 비어 있다."""

    biz_name: str | None
    site_url: str | None
    trades: list[str]
    areas: list[AreaIn]
    portfolio_urls: list[str]


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
