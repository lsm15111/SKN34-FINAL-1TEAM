import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidatorFunctionWrapHandler,
    WrapValidator,
    field_validator,
    model_validator,
)

from app.calc.space_share import rooms_needed
from app.shared.errors import app_error
from app.shared.regions import is_region

SizeBand = Literal["10", "20", "30", "40", "50"]
Budget = Literal["u300", "300-500", "500-700", "700-1000", "o1000", "undecided"]
MokItem = Literal["molding", "base", "door", "flatten"]
DobaeGrade = Literal["economy", "basic"]  # 저가형 · 기본형 (v3 화면 말: 합지 · 실크)
# v3 기본 정보
Scope = Literal["full", "partial"]  # 전체 · 부분 공사
Face = Literal["wall", "ceiling"]  # 벽 · 천장
# v4 철거 범위(모은 조건 demolition, calc.dobae.DEMOLITION): 전체 철거 · 부분 철거 · 철거 안 함
Demolition = Literal["full", "partial", "none"]
# 거실 · 주방 · 안방 · 작은방 1~4 · 복도 · 현관 · 드레스룸 (방 칩은 방 개수만큼: calc.space_share.room_kinds)
SpaceKind = Literal[
    "living", "kitchen", "master", "room1", "room2", "room3", "room4", "hall", "entry", "dress"
]
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
    """견적 받기 질문 흐름의 답. 사진 · 도면은 먼저 POST /files로 올리고 id만 보낸다."""

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


class HomeInfoIn(BaseModel):
    """v3 기본 정보 (C02 · D11). 로그인 전 손님 계산(POST /guest/standard)과 가입 뒤 공사 만들기
    (POST /projects, 머리 Idempotency-Key = 기기 답의 key)가 같은 칸을 쓴다. 금액은 서버 계산 엔진이 다시 센다."""

    model_config = ConfigDict(extra="forbid")

    trade: Literal["dobae"] = "dobae"
    scope: Scope = "full"
    spaces: list[SpaceKind] = Field(
        default=[], max_length=10, description="부분 공사일 때 켠 공간 칩 (전체면 비움)"
    )
    rooms: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="방 개수 1~5. 비우면 평형 기본값(GET /guest/room-rule)으로 센다",
    )
    faces: list[Face] = Field(
        default=["wall", "ceiling"], min_length=1, max_length=2, description="전체는 벽 + 천장"
    )
    housing: Literal["apt"] = Field(
        default="apt", description="아파트만 (나머지는 화면에서 '준비 중')"
    )
    sido: str = Field(min_length=1, max_length=20)
    sgg: str = Field(min_length=1, max_length=20)
    emd: str | None = Field(
        default=None,
        max_length=20,
        description="읍면동 (옛 화면 호환). 지금 화면은 시 · 군 · 구까지만 받아 비워 둬요",
    )
    area_m2: Decimal = Field(gt=10, lt=400, decimal_places=1, description="㎡ (평은 화면 도움)")
    area_basis: Literal["supply", "exclusive"]
    occupied: bool = Field(description="짐이 있는 집")
    grade: DobaeGrade = Field(description="합지(economy) · 실크(basic)")
    budget_won: int | None = Field(
        default=None,
        ge=100_000,
        le=10_000_000_000,
        multiple_of=10_000,
        description="예산(원, 만 원 단위). 비우면 '아직 몰라요'",
    )
    start_date: date | None = Field(default=None, description="공사 시작 희망일 (모르면 비움)")
    demolition: Demolition | None = Field(
        default=None,
        description="철거 범위(모은 조건 demolition): full 전체 철거 · partial 부분 · none 안 함. "
        "전체 철거면 표준견적서가 리모델링 기준이에요. 고치기에서 안 보내면 그대로, null이면 지워요",
    )

    @field_validator("emd")
    @classmethod
    def _emd(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @model_validator(mode="after")
    def _scope(self) -> "HomeInfoIn":
        if len(set(self.spaces)) != len(self.spaces) or len(set(self.faces)) != len(self.faces):
            raise ValueError("같은 공간 · 면을 두 번 골랐어요.")
        if self.scope == "full" and (self.spaces or set(self.faces) != {"wall", "ceiling"}):
            raise ValueError("전체 공사는 공간을 고르지 않고 벽 · 천장을 모두 해요.")
        if self.scope == "partial" and not self.spaces:
            raise ValueError("부분 공사할 공간을 골라 주세요.")
        if self.rooms is not None and rooms_needed(self.spaces) > self.rooms:
            raise ValueError("방 개수보다 많은 방을 골랐어요.")
        return self


def check_home(data: HomeInfoIn, today: date) -> None:
    """모양 검사로 못 보는 것: 있는 시 · 군 · 구인지, 시작 희망일(오늘 ~ 2년 안).
    서비스 지역 · 동은 보지 않는다. 표준견적서는 모든 시 · 군 · 구에서 나오고, 업체는 업체 고르기에서
    시공 지역으로 거른다. 틀리면 422 invalid + 칸(fields). 손님 계산과 공사 만들기 · 고치기가 같이 쓴다.
    입력값은 오류에 넣지 않는다."""

    def bad(loc: str, msg: str):
        return app_error("invalid", msg, fields=[{"loc": [loc], "msg": msg}])

    if not is_region(data.sido, data.sgg):
        raise bad("sgg", "지역을 다시 골라 주세요.")
    if data.start_date is not None:
        if data.start_date < today:
            raise bad("start_date", "오늘 이후 날짜를 골라 주세요.")
        if data.start_date > date(today.year + 2, today.month, min(today.day, 28)):
            raise bad("start_date", "2년 안의 날짜를 골라 주세요.")


# v3에만 있는 칸. 하나라도 있으면 v3 몸통(HomeInfoIn)으로, 아니면 지금 화면 몸통(ProjectCreate)으로 본다
V3_ONLY_KEYS = frozenset(HomeInfoIn.model_fields) - frozenset(ProjectCreate.model_fields)


def _one_shape(v: Any, _: ValidatorFunctionWrapHandler) -> "ProjectCreate | HomeInfoIn":
    """두 모양 중 하나만 검사한다. 그래서 422 fields의 loc는 지금처럼 칸 이름만 있다(모양 이름이 붙지 않음)."""
    if isinstance(v, ProjectCreate | HomeInfoIn):
        return v
    if isinstance(v, dict) and V3_ONLY_KEYS & v.keys():
        return HomeInfoIn.model_validate(v)
    return ProjectCreate.model_validate(v)


# POST · PATCH /projects 몸통 (contract 3.2). OpenAPI에는 두 모양이 anyOf로 다 보인다
ProjectBody = Annotated[ProjectCreate | HomeInfoIn, WrapValidator(_one_shape)]


class HomeInfoOut(BaseModel):
    """저장한 v3 기본 정보 (넣은 그대로). v2로 만든 공사는 비어 있다."""

    trade: str
    scope: Scope
    spaces: list[SpaceKind]
    faces: list[Face]
    rooms: int | None = Field(default=None, description="넣은 방 개수 (옛 공사는 비어 있음)")
    housing: str
    sido: str
    sgg: str
    emd: str | None
    area_m2: Decimal
    area_basis: str
    occupied: bool
    grade: DobaeGrade | None
    budget_won: int | None
    start_date: date | None
    demolition: Demolition | None = Field(default=None, description="철거 범위(모은 조건)")


class EmdOut(BaseModel):
    """읍면동 한 줄 (B6 자료)"""

    name: str = Field(description="상계동")
    code: str | None = Field(default=None, description="행정동 코드 (있을 때만)")


class ProjectOut(BaseModel):
    id: uuid.UUID
    code: str
    rev: int
    locked: bool  # 실측을 요청해 집 정보를 더 고칠 수 없음
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
    # ---- v3 (1단계에서 채움) ----
    source: Literal["v2", "guest", "member"] = Field(
        default="v2", description="만든 길: 옛 v2 · 손님 답 옮김 · 가입 뒤 바로"
    )
    emd: str | None = Field(default=None, description="읍면동")
    budget_won: int | None = Field(default=None, description="예산(원)")
    home: HomeInfoOut | None = Field(default=None, description="v3 기본 정보 (넣은 그대로)")


class ProjectListItem(BaseModel):
    id: uuid.UUID
    code: str
    region: str
    size: SizeIn
    trades: list[str]
    created_at: datetime


class ProjectBrief(BaseModel):
    """다른 기능(실측 요청)이 업체 쪽 화면에 쓰는 집 요약. 고객 이름 · 휴대폰 · 동 · 호수는
    보여도 되는지 부르는 쪽(visit.service)이 정한다."""

    id: uuid.UUID
    code: str
    owner_id: uuid.UUID
    owner_name: str
    owner_phone: str | None
    sido: str
    sgg: str
    region: str
    occupied: bool
    when: WhenIn
    apt_name: str | None
    dong: str | None
    ho: str | None


class ConditionOut(BaseModel):
    """AI 상담으로 모은 조건 한 칸(맥락 L3). 화면 칩은 'label: value'예요"""

    trade: str
    key: str
    label: str
    value: str


class ProjectCheckOut(BaseModel):
    """공사 전에 할 일 한 줄"""

    key: str
    label: str
    done: bool
    done_at: datetime | None


class ProjectCheckIn(BaseModel):
    done: bool
