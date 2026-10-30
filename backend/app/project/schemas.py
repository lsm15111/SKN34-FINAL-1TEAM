import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SizeBand = Literal["10", "20", "30", "40", "50"]
Budget = Literal["u300", "300-500", "500-700", "700-1000", "o1000", "undecided"]
MokItem = Literal["molding", "base", "door", "flatten"]
DobaeGrade = Literal["economy", "basic"]  # 저가형 · 기본형
MAX_PHOTOS_PER_SPACE = 10
MAX_PLANS = 5


class SpaceIn(BaseModel):
    key: str = Field(
        min_length=1,
        max_length=40,
        description="화면에서 붙인 임시 이름표. 공정 · 사진이 이걸로 공간을 가리킨다",
    )
    name: str = Field(max_length=20)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("공간 이름을 적어 주세요.")
        return v


class SizeIn(BaseModel):
    """평수: 10평대 · 20평대 … 중 하나(band), 또는 정확한 면적(basis + m2)"""

    band: SizeBand | None = None
    basis: Literal["supply", "exclusive"] | None = None
    m2: Decimal | None = Field(default=None, gt=10, lt=400, decimal_places=1)

    @model_validator(mode="after")
    def _one(self) -> "SizeIn":
        if (self.band is None) == (self.m2 is None) or (self.m2 is not None and self.basis is None):
            raise ValueError("평수를 고르거나, 공급 · 전용 면적을 ㎡로 적어 주세요.")
        if self.band is not None and self.basis is not None:
            raise ValueError("평수를 고르면 면적 기준은 비워 두세요.")
        return self


class WhenIn(BaseModel):
    kind: Literal["date", "movein", "months", "unknown"]
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _dates(self) -> "WhenIn":
        if self.kind in ("date", "movein") and self.start is None:
            raise ValueError("날짜를 골라 주세요.")
        if self.kind not in ("date", "movein") and (self.start or self.end):
            raise ValueError("이 시기에는 날짜를 넣지 않아요.")
        if self.end is not None and (
            self.kind != "date" or self.start is None or self.end < self.start
        ):
            raise ValueError("끝나는 날은 시작하는 날 뒤여야 해요.")
        return self


class TradeIn(BaseModel):
    spaces: list[str] = Field(min_length=1)


class DobaeIn(TradeIn):
    grade: DobaeGrade


class MokgongIn(TradeIn):
    items: list[MokItem] = Field(min_length=1)


class TradesIn(BaseModel):
    dobae: DobaeIn | None = None
    mokgong: MokgongIn | None = None

    @model_validator(mode="after")
    def _any(self) -> "TradesIn":
        if self.dobae is None and self.mokgong is None:
            raise ValueError("공정을 하나 이상 골라 주세요.")
        return self


class PhotoIn(BaseModel):
    space: str
    file_id: uuid.UUID


class ProjectCreate(BaseModel):
    """견적 받기 질문 흐름의 답 (FFW-03, FFW-04). 사진 · 도면은 먼저 POST /files로 올리고 id만 보낸다."""

    sido: str
    sgg: str
    house_type: Literal["apt"] = "apt"
    built_year: int | None = Field(default=None, ge=1900, le=2100)
    size: SizeIn
    balcony_ext: bool = False
    when: WhenIn
    occupied: bool
    budget: Budget | None = None
    spaces: list[SpaceIn] = Field(min_length=1, max_length=30)
    trades: TradesIn
    photos: list[PhotoIn] = Field(default=[], max_length=300)
    plans: list[uuid.UUID] = Field(default=[], max_length=MAX_PLANS)

    @model_validator(mode="after")
    def _refs(self) -> "ProjectCreate":
        keys = [s.key for s in self.spaces]
        if len(set(keys)) != len(keys):
            raise ValueError("공간 이름표가 겹쳐요.")
        names = [s.name for s in self.spaces]
        if len(set(names)) != len(names):
            raise ValueError("같은 이름의 공간이 있어요.")
        known = set(keys)
        for t in (self.trades.dobae, self.trades.mokgong):
            if t and not set(t.spaces) <= known:
                raise ValueError("공정에 없는 공간이 들어 있어요.")
            if t:
                t.spaces = list(dict.fromkeys(t.spaces))
        if self.trades.mokgong:
            self.trades.mokgong.items = list(dict.fromkeys(self.trades.mokgong.items))
        per: dict[str, int] = {}
        for p in self.photos:
            if p.space not in known:
                raise ValueError("사진에 없는 공간이 들어 있어요.")
            per[p.space] = per.get(p.space, 0) + 1
            if per[p.space] > MAX_PHOTOS_PER_SPACE:
                raise ValueError(f"공간마다 사진은 {MAX_PHOTOS_PER_SPACE}장까지예요.")
        ids = [p.file_id for p in self.photos] + list(self.plans)
        if len(set(ids)) != len(ids):
            raise ValueError("같은 파일이 두 번 들어 있어요.")
        return self


class SpaceOut(BaseModel):
    id: uuid.UUID
    name: str


class DobaeOut(BaseModel):
    spaces: list[uuid.UUID]
    grade: DobaeGrade | None  # 0003 전에 만든 프로젝트는 비어 있다


class MokgongOut(BaseModel):
    spaces: list[uuid.UUID]
    items: list[MokItem]


class TradesOut(BaseModel):
    dobae: DobaeOut | None = None
    mokgong: MokgongOut | None = None


class PhotoOut(BaseModel):
    file_id: uuid.UUID
    space_id: uuid.UUID


class ProjectOut(BaseModel):
    id: uuid.UUID
    sido: str
    sgg: str
    region: str
    house_type: str
    built_year: int | None
    size: SizeIn
    balcony_ext: bool
    when: WhenIn
    occupied: bool
    budget: str | None
    spaces: list[SpaceOut]
    trades: TradesOut
    photos: list[PhotoOut]
    plans: list[uuid.UUID]
    created_at: datetime


class ProjectListItem(BaseModel):
    id: uuid.UUID
    region: str
    size: SizeIn
    trades: list[str]
    created_at: datetime
