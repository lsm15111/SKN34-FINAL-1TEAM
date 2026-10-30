import re
import uuid

from pydantic import BaseModel, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL.match(v):
        raise ValueError("이메일 형식이 아니에요.")
    return v


def clean_name(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("이름을 적어 주세요.")
    return v


class SignupIn(BaseModel):
    """일반 회원가입"""

    name: str = Field(max_length=50)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    _email = field_validator("email")(normalize_email)
    _name = field_validator("name")(clean_name)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class MePatch(BaseModel):
    """내 정보 수정. 이메일은 로그인 아이디라 여기서 바꾸지 않는다."""

    name: str = Field(max_length=50)

    _name = field_validator("name")(clean_name)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    # 업체 회원만: pending(승인대기) · approved · rejected
    vendor_status: str | None = None
    vendor_reject_reason: str | None = None
