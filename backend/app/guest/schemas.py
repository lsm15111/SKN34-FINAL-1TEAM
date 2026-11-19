"""로그인 전 표준견적서 계산 (dev-03). 입력은 project.schemas.HomeInfoIn(가입 뒤 POST /projects와 같은 칸)."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

LineState = Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]


class GuestLineOut(BaseModel):
    """표준견적서 줄 (계산 엔진). 합계에는 included · separate만 들어간다."""

    key: str
    name: str
    qty: Decimal | None
    unit: str = Field(description="㎡ · 벽지 평 · 품 · 식 (도배지 줄은 '벽지 평', D07 A)")
    unit_price: int | None
    amount: int | None
    state: LineState
    basis: Literal["public", "market", "assumed", "none"] = Field(
        description="공공 기준 · 시장 데이터 기준(도배지 시장 평균) · 팀 가정값 · 공공 단가 없음"
    )
    source: str = Field(description="출처 이름 (벽지 시장 평균 가격 2026.11 …)")


class RoomBandOut(BaseModel):
    """방 개수 기본값 한 칸: 이 면적(㎡) 이상이면 이 방 개수"""

    area_basis: Literal["supply", "exclusive"]
    min_m2: Decimal = Field(description="이 면적 이상 (㎡, 소수 한 자리 올림)")
    rooms: int


class RoomRuleOut(BaseModel):
    """방 개수 칸 (whole-house-area 방안 4). 화면은 면적으로 칸을 찾기만 하고 계산하지 않는다."""

    price_ver: str = Field(description="이 표가 든 도배 단가 판")
    share_ver: str = Field(description="방 개수별 공간 몫 표 판")
    min: int
    max: int
    fallback: int = Field(description="면적을 아직 안 넣었을 때 보이는 방 개수")
    bands: list[RoomBandOut] = Field(description="면적 기준별, 작은 면적부터")
    room_kinds: list[str] = Field(description="방 칩 순서 (방 1개 = 첫 칸, 5개 = 다섯 칸)")


class GuestStandardOut(BaseModel):
    """저장하지 않는 계산 결과. DB · 로그에 입력을 남기지 않는다."""

    formula_ver: str
    price_ver: str
    market_ver: str | None = Field(default=None, description="벽지 시장 평균 가격 판 (도배지 줄)")
    share_ver: str | None = Field(default=None, description="공간 몫 표 판 (부분 공사일 때만)")
    scope: Literal["full", "partial"]
    area_m2: Decimal
    area_basis: str
    pyeong: Decimal = Field(description="표시용 평 (계산 엔진)")
    rooms: int | None = Field(
        default=None, description="계산에 쓴 방 개수 (안 넣었으면 평형 기본값)"
    )
    lines: list[GuestLineOut]
    supply: int
    vat: int
    total: int = Field(description="부가세 포함")
    days: Decimal = Field(description="예상 공사 일수 (반나절 단위)")
    man_day: Decimal = Field(description="품 (0.5 단위 올림)")
    budget_fit: Literal["within", "over"] | None = Field(
        description="넣은 예산 안 · 밖 (예산을 안 넣었으면 비움)"
    )
    assumptions: list[str] = Field(description="계산에 쓴 가정 (화면 '이렇게 셌어요')")
