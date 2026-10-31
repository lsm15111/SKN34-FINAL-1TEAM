from pydantic import BaseModel, Field


class OptOutIn(BaseModel):
    """대신 연락 메시지의 수신거부 링크에 든 값"""

    token: str = Field(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class OptOutOut(BaseModel):
    done: bool
    message: str
