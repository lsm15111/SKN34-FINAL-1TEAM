import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.shared.text import strip_controls, visible

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(v: str) -> str:
    v = v.strip().lower()
    # 제어 · 보이지 않는 글자가 든 주소는 받지 않는다(NUL은 저장 · 조회에서 500, 보안 QA r2 N2)
    if not _EMAIL.match(v) or not v.isprintable():
        raise ValueError("이메일 형식이 아니에요.")
    return v


_PHONE = re.compile(r"^01[0-9]{8,9}$")


def normalize_phone(v: str) -> str:
    """010-1234-5678 · 01012345678 · 010 1234 5678 → 01012345678"""
    digits = re.sub(r"[\s-]", "", v)
    if not _PHONE.match(digits):
        raise ValueError("휴대폰 번호를 확인해 주세요. 예: 010-1234-5678")
    return digits


def clean_name(v: str) -> str:
    """제어 문자 · ANSI 색 코드 · 방향 바꾸기 글자를 지우고(NUL은 저장에서 500) 빈칸을 한 칸으로.
    보이지 않는 글자(한글 채움 U+3164 등)만 남으면 빈 이름이에요(보안 QA r2 N4)."""
    v = " ".join(strip_controls(v).split())
    if not visible(v):
        raise ValueError("이름을 적어 주세요.")
    return v


class SignupIn(BaseModel):
    """일반 회원가입. 휴대폰은 넣지 않아도 돼요(9판 C05 '휴대폰 (선택)', 업체에는 가지 않음 · security.md 7.1)."""

    name: str = Field(max_length=50)
    phone: str | None = Field(default=None, max_length=20, description="비우면 저장하지 않아요")
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    _email = field_validator("email")(normalize_email)
    _name = field_validator("name")(clean_name)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return None if v is None or not v.strip() else normalize_phone(v)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return strip_controls(v).strip().lower()  # NUL은 조회에서 500(보안 QA r2 N2)


class MePatch(BaseModel):
    """내 정보 수정. 보낸 칸만 바꾼다. 이메일은 로그인 아이디라 여기서 바꾸지 않는다."""

    name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else clean_name(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return None if v is None else normalize_phone(v)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    phone: str | None = None
    role: str
    created_at: datetime  # 가입한 때 (내 정보 화면)
    # 업체 회원만: pending(심사 중) · needs_info(보완 요청) · approved · rejected. 승인 전에는 업체 기능이 잠긴다
    vendor_status: str | None = None
    vendor_review_code: str | None = None  # 보완 요청 · 거절 사유 코드
    vendor_review_note: str | None = None  # 관리자가 업체에 보낸 말
    vendor_reject_reason: str | None = None  # 예전 칸 (거절일 때 vendor_review_note와 같다)
