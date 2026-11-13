"""v2 화면(/v2, v10 이식) API 모양. 응답 키 이름은 v10 JS 결과와 같다.

스키마 이름은 모두 V2 접두어(팀 스키마 이름과 겹치면 OpenAPI가 덮어쓴다).
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StrictBool

from app.calc.plan_qty import SpaceKind
from app.calc.precise_mokgong import DoorMode, MoldingType

Id = Annotated[str, Field(max_length=80)]


def _real_day(v: str) -> str:
    """모양(YYYY-MM-DD)만 맞고 달력에 없는 날짜(2월 30일 · 13월)는 422로 막는다."""
    if v:
        try:
            date.fromisoformat(v if len(v) == 10 else f"{v}-01")
        except ValueError as e:
            raise ValueError("달력에 없는 날짜예요") from e
    return v


Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$"), AfterValidator(_real_day)]
DayOrEmpty = Annotated[str, Field(pattern=r"^(\d{4}-\d{2}-\d{2})?$"), AfterValidator(_real_day)]
# 입주 희망: 연-월 또는 연-월-일
MoveDay = Annotated[str, Field(pattern=r"^(\d{4}-\d{2}(-\d{2})?)?$"), AfterValidator(_real_day)]
Qty = Annotated[Decimal, Field(ge=0, le=10_000, max_digits=8, decimal_places=1)]
Cat = Literal[
    "wallpaper",
    "floor",
    "tile",
    "bath",
    "furniture",
    "carpentry",
    "film",
    "paint",
    "middoor",
    "light",
    "window",
    "finish",
]
Trade = Annotated[str, Field(max_length=20)]


# ---- 입력: 견적 ----
class V2DoorIn(BaseModel):
    mode: DoorMode = "none"
    pick: Id | None = None
    count: int | None = Field(default=None, ge=0, le=30)


class V2CountIn(BaseModel):
    n: int = Field(default=0, ge=0, le=30)
    pick: Id | None = None


class V2MoldingIn(BaseModel):
    type: MoldingType = "none"
    pick: Id | None = None


class V2BaseIn(BaseModel):
    pick: Id | None = None


class V2MokIn(BaseModel):
    """v10 S.mok10 (frontend store.ts MokSt)."""

    door: V2DoorIn = V2DoorIn()
    slide: V2CountIn = V2CountIn()
    hidden: V2CountIn = V2CountIn()
    molding: V2MoldingIn = V2MoldingIn()
    base: V2BaseIn = V2BaseIn()
    # 정해진 단가 항목: true면 자동 수량, 숫자면 넣은 수량
    extras: dict[Annotated[str, Field(max_length=40)], StrictBool | Qty] = Field(
        default={}, max_length=30
    )


class V2PlanSelIn(BaseModel):
    id: str = Field(max_length=20)
    expanded: bool = True
    kinds: list[SpaceKind] | None = Field(default=None, max_length=9)
    spaces: list[Literal["room", "kitchen", "bath", "entry", "window"]] | None = Field(
        default=None, max_length=5
    )


class V2QuoteIn(BaseModel):
    pyeong: Decimal | None = Field(default=None, ge=0, le=300, max_digits=6, decimal_places=2)
    living: Literal["living", "vacant"] | None = None
    cats: list[Cat] = Field(default=[], max_length=12)
    picks: dict[Annotated[str, Field(max_length=20)], Id] = Field(default={}, max_length=20)
    plan: V2PlanSelIn | None = None
    balcony: bool = False
    mok: V2MokIn | None = None
    tier: Literal["economy", "basic", "premium"] = "basic"


# ---- 출력: 견적 ----
class V2LineOut(BaseModel):
    key: str
    name: str
    qty: float | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: str
    source: str
    basis: str
    calc: str


class V2StepOut(BaseModel):
    key: str
    name: str
    half_days: int


class V2MarketLineOut(BaseModel):
    key: str
    name: str
    qty: float | None
    unit: str
    unit_price: int | None
    amount: int
    note: str


class V2BandRatioOut(BaseModel):
    lo: float
    hi: float
    lo80: float
    hi80: float
    n: int | None


class V2MarketOut(BaseModel):
    trade: str
    grade: str | None  # 도배: silk · hapji
    lines: list[V2MarketLineOut]
    supply: int
    lo: int
    hi: int
    band: V2BandRatioOut
    version: str


class V2BandOut(BaseModel):
    lo: int
    hi: int
    n: int
    p: list[float]
    mk: V2MarketOut


class V2GapStepOut(BaseModel):
    key: str
    name: str
    why: str
    d: int


class V2GapOut(BaseModel):
    model_config = {"populate_by_name": True}

    from_: int = Field(alias="from", serialization_alias="from")
    steps: list[V2GapStepOut]
    to: int


class V2PreciseOut(BaseModel):
    trade: Literal["dobae", "mokgong"]
    ko: str
    lines: list[V2LineOut]
    supply: int
    vat: int
    total: int
    man_days: float
    md_raw: float
    crew: int
    steps: list[V2StepOut]
    days: float
    notes: list[str]
    grade: str | None
    extra_amount: int | None
    ver: str | None
    band: V2BandOut
    gap: V2GapOut


class V2PubOut(BaseModel):
    unit_price: int
    amount: int
    source: str


class V2RefLineOut(BaseModel):
    key: str
    name: str
    qty: float
    unit: str
    lo: int | None
    hi: int | None
    state: str
    basis: str
    source: str
    calc: str
    pub: V2PubOut | None
    note: str | None


class V2RefOut(BaseModel):
    cat: str
    ko: str
    level: str
    lines: list[V2RefLineOut]
    lo: int
    hi: int
    vlo: int
    vhi: int
    tlo: int  # 부가세 포함
    thi: int
    days: float
    crew: int
    steps: list[V2StepOut]
    notes: list[str]


class V2MeasuredOut(BaseModel):
    name: str
    wall_m2: float
    ceiling_m2: float
    molding_m: float
    base_m: float
    doors: int


class V2DoorsAutoOut(BaseModel):
    n: int
    how: str


class V2InpOut(BaseModel):
    py: float
    area_m2: float
    measured: V2MeasuredOut | None
    occupied: bool
    balcony: bool
    grade: str
    mok: list[str]
    doors: int
    doors_auto: V2DoorsAutoOut
    assumed: list[str]


class V2SumOut(BaseModel):
    lo: int
    hi: int


class V2QuoteOut(BaseModel):
    inp: V2InpOut
    precise: list[V2PreciseOut]
    ref: list[V2RefOut]
    missing: list[str]
    supply: int
    vat: int
    total: int
    rlo: int
    rhi: int
    all_lo: int
    all_hi: int
    code: str
    at: str
    band: V2SumOut | None
    formula_version: str  # 산식 버전 (v10 CALC.FORMULA_VERSION)
    price_ver: str  # 공공 단가 버전 (v10 CALC.PRICE_VER)


class V2MarketExtraOut(BaseModel):
    key: str
    name: str
    per: Literal["곳", "식"]
    lo: int
    hi: int
    n: int


# ---- 공정표 ----
class V2ConsIn(BaseModel):
    weekendWork: bool = False
    endBy: DayOrEmpty = ""
    startAfter: DayOrEmpty = ""
    avoid: list[Day] = Field(default=[], max_length=60)


class V2PropIn(BaseModel):
    start: Day
    end: Day
    crew: int | None = Field(default=None, ge=1, le=20)


class V2AcceptedIn(BaseModel):
    start: Day
    end: Day


class V2TrialIn(BaseModel):
    trade: Trade
    start: Day
    end: Day


class V2PlanIn(BaseModel):
    quote: V2QuoteIn
    move: MoveDay = ""
    cons: V2ConsIn = V2ConsIn()
    props: dict[Trade, V2PropIn] = Field(default={}, max_length=12)
    accepted: dict[Trade, V2AcceptedIn] = Field(default={}, max_length=12)
    trial: V2TrialIn | None = None


class V2BlockOut(BaseModel):
    trade: str
    ko: str
    kind: Literal["work", "dry", "clean"]
    start: str
    end: str
    days: int
    crew: int | None
    state: str


class V2DayItemOut(BaseModel):
    trade: str
    ko: str
    todo: list[str]


class V2DayOut(BaseModel):
    date: str
    off: bool
    holiday: str | None
    items: list[V2DayItemOut]


class V2FixedOut(BaseModel):
    start: str


class V2PlanTradeOut(BaseModel):
    trade: str
    ko: str
    steps: list[V2StepOut]
    crew: int
    fixed: V2FixedOut | None
    state: Literal["expected", "pending", "confirmed"]
    need: float


class V2MovedOut(BaseModel):
    trade: str
    ko: str
    start: str


class V2TrialOut(BaseModel):
    trade: str
    start: str
    end: str
    moved: list[V2MovedOut]
    clash: bool
    error: str | None
    work_days: int
    need: float | None
    short: bool


class V2WeekOut(BaseModel):
    n: int
    start: str
    end: str
    blocks: list[V2BlockOut]


class V2PlanOut(BaseModel):
    start: str
    end: str
    work_days: int
    blocks: list[V2BlockOut]
    days: list[V2DayOut]
    trades: list[V2PlanTradeOut]
    warn: list[str]
    today: str
    tomorrow: str
    due_next: str
    weeks: list[V2WeekOut]
    trial: V2TrialOut | None


# ---- 받은 견적 맞춰 보기 ----
class V2CheckScopeIn(BaseModel):
    ceiling: bool = True
    removal: bool = False
    moving: bool = False
    casing9: bool = False
    etc: bool = False
    extras: dict[Annotated[str, Field(max_length=20)], int] = Field(default={}, max_length=12)


class V2CheckIn(BaseModel):
    quote: V2QuoteIn
    trade: Literal["dobae", "mokgong"]
    amount: Decimal = Field(ge=-1, le=10_000_000_000, max_digits=14, decimal_places=2)
    mode: Literal["unknown", "excluded", "included"] = "unknown"
    scope: V2CheckScopeIn = V2CheckScopeIn()


class V2BarOut(BaseModel):
    band_left: float
    band_width: float
    me: float


class V2CheckOut(BaseModel):
    warn: str | None
    trade: str | None = None
    supply: int | None = None
    lo: int | None = None
    hi: int | None = None
    where: Literal["low", "in", "high"] | None = None
    pct: float | None = None
    head: str | None = None
    notes: list[str] = []
    why: list[str] = []
    vat_unknown: bool = False
    bar: V2BarOut | None = None


# ---- 업체 가견적 · 실측 견적서 요약 칸 ----
Won = Annotated[Decimal, Field(ge=0, le=100_000_000_000, max_digits=14, decimal_places=2)]


class V2EstLineIn(BaseModel):
    key: Annotated[str, Field(max_length=40)]
    name: Annotated[str, Field(max_length=200)]
    qty: Qty | None
    state: Annotated[str, Field(max_length=20)]


class V2EstimateIn(BaseModel):
    trade: Literal["dobae", "mokgong"]
    grade: Literal["economy", "basic"] | None = None
    lines: list[V2EstLineIn] = Field(max_length=60)
    prices: dict[Annotated[str, Field(max_length=40)], Won | None] = Field(
        default={}, max_length=60
    )
    std_total: int = Field(ge=0, le=100_000_000_000)


class V2EstimateOut(BaseModel):
    ok: bool
    supply: int | None = None
    vat: int | None = None
    total: int | None = None
    pct: float | None = None
    why: str | None = None


class V2EnteredIn(BaseModel):
    amount: int = Field(ge=0, le=100_000_000_000)
    mode: Literal["excluded", "included", "exempt"]
    std_total: int | None = Field(default=None, ge=0, le=100_000_000_000)


class V2EnteredOut(BaseModel):
    supply: int
    vat: int
    total: int
    pct: float | None


# ---- 셀프 계산기 ----
Len = Annotated[float, Field(ge=0, le=1000)]
Pos = Annotated[float, Field(gt=0, le=1000)]


class V2Calc7In(BaseModel):
    """v10 CALC7 입력 그대로 (+ kind). 빈 칸 기본값은 v10 calcCard처럼 화면이 넣는다."""

    kind: Literal["wallpaper", "trim", "paint"]
    w: Len = 0
    d: Len = 0
    hgt: Pos = 2.3
    doors: Len = 0
    windows: Len = 0
    ceiling: bool = False
    rollW: Pos = 0.53
    rollLen: Pos = 12.5
    repeat: Len = 0
    loss: Len = 10
    doorW: Len = 0.9
    pieceLen: Pos = 2.4
    coats: Len = 2
    cover: Pos = 10


class V2WallOut(BaseModel):
    wall_m2: float
    ceiling_m2: float
    strips: int
    cStrips: int
    per_roll: int
    rolls_raw: float
    rolls: int


class V2TrimOut(BaseModel):
    molding_m: float
    molding_pcs: int
    base_m: float
    base_pcs: int


class V2PaintOut(BaseModel):
    area_m2: float
    liters: float
    n18: int
    n4: int


# ---- 추가 항목 범위 ----
class V2CasingIn(BaseModel):
    doors: int = Field(ge=0, le=30)
    with_door: bool = False


class V2ExtrasIn(BaseModel):
    picks: dict[Annotated[str, Field(max_length=20)], int] = Field(default={}, max_length=12)
    casing: V2CasingIn | None = None


class V2ExtrasOut(BaseModel):
    lo: int
    hi: int
    notes: list[str]


# ---- AI 상담 (/v2/ask) ----
# 지시문 · 도구 정의는 서버가 정한다. 화면은 질문 · 고객 상태 · 자료(데이터)만 보낸다.
IMAGE_MAX = 600_000  # base64 글자 수: 긴 변 1280px jpeg 한 장이 넉넉히 들어간다
AskKind = Literal["chat", "quote_explanation", "schedule"]
Short = Annotated[str, Field(max_length=200)]
B64 = Annotated[str, Field(max_length=IMAGE_MAX, pattern=r"^[A-Za-z0-9+/=]*$")]


class V2AskProfile(BaseModel):
    """화면이 보여 주는 고객 상태(글). 금액 계산에는 쓰지 않는다 (금액은 quote로 서버가 계산)."""

    style: Short = ""
    pyeong: Decimal | None = Field(default=None, ge=0, le=300, max_digits=6, decimal_places=2)
    region: Short = ""
    living: Short = ""
    scope: Short = ""
    budget_manwon: int | None = Field(default=None, ge=0, le=1_000_000)
    tier: Short = ""
    step: Short = ""
    picks: list[Short] = Field(default=[], max_length=20)
    photos: int = Field(default=0, ge=0, le=50)
    ref_photos: int = Field(default=0, ge=0, le=50)
    plan_name: Short = ""


class V2AskMaterial(BaseModel):
    id: Id
    cat: Short = ""
    tier: Short = ""
    rank: int | None = Field(default=None, ge=0, le=1000)
    brand: Short = ""
    name: Short = ""
    spec: Annotated[str, Field(max_length=120)] = ""
    price: Short = ""
    tags: list[Annotated[str, Field(max_length=20)]] = Field(default=[], max_length=8)


class V2AskIn(BaseModel):
    kind: AskKind = "chat"
    message: str = Field(min_length=1, max_length=1_000)
    profile: V2AskProfile = V2AskProfile()
    quote: V2QuoteIn | None = None  # 금액 도구 · 견적 설명이 서버에서 다시 계산한다
    plan: V2PlanIn | None = None  # 공정표 상담
    materials: list[V2AskMaterial] = Field(default=[], max_length=24)
    images: list[B64] = Field(default=[], max_length=2)


class V2AskResultIn(BaseModel):
    id: str = Field(max_length=100)
    content: str = Field(max_length=20_000)


class V2AskResumeIn(BaseModel):
    results: list[V2AskResultIn] = Field(min_length=1, max_length=12)


class V2ToolCallOut(BaseModel):
    id: str
    name: str
    arguments: dict


class V2IntentOut(BaseModel):
    label: str
    confidence: float
    source: str


class V2AskSource(BaseModel):
    """답에 붙은 근거 조각. 서버 지식 자료에서 이번 턴에 보여 준 것만"""

    ref: str
    source_type: str
    title: str
    publisher: str
    date: str
    section: str
    url: str
    official: bool  # 공공 · 표준 · 제조사 · 협회 자료


class V2AskSuggest(BaseModel):
    """입력창 위 버튼으로 보일 이어 물을 질문. 서버가 답할 수 있는지 검색해 본 것만"""

    text: str
    ref: str | None = None  # 질문 은행 질문이 묶인 조각


class V2AskOut(BaseModel):
    done: bool
    turn: str | None = None  # 화면 도구를 실행하고 /v2/ask/{turn}로 결과를 보낸다
    tool_calls: list[V2ToolCallOut] = []
    text: str = ""  # 숫자 검사를 마친 답. done일 때만 채운다
    failed: bool = False
    gate: Literal["out"] | None = None  # 범위 밖이라 AI를 부르지 않았다
    intent: V2IntentOut | None = None
    dropped: list[str] = []  # 숫자 검사로 뺀 문장의 이유
    cons: V2ConsIn | None = None  # 공정표 상담이 바꾼 조건
    sources: list[V2AskSource] = []  # 답에 남은 [K번호] 근거
    cites_dropped: int = 0  # 보여 주지 않았거나 문장과 맞지 않아 뗀 [K번호] 수
    suggest: list[V2AskSuggest] = []  # 이어 물을 질문 0~3개 (일반 상담만)


class V2AskHealthOut(BaseModel):
    ok: bool
    live: bool
