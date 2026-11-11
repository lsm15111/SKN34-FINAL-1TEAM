"""v2 화면(/v2, 커스텀 MVP v10 이식) API 모양. 응답 키 이름은 v10 JS 결과와 같다.

스키마 이름은 모두 MvpV2 접두어(팀 스키마 이름과 겹치면 OpenAPI가 덮어쓴다).
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool

from app.calc.mvp_mokgong import DoorMode, MoldingType
from app.calc.plan_qty import SpaceKind

Id = Annotated[str, Field(max_length=80)]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
DayOrEmpty = Annotated[str, Field(pattern=r"^(\d{4}-\d{2}-\d{2})?$")]
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
class MvpV2DoorIn(BaseModel):
    mode: DoorMode = "none"
    pick: Id | None = None
    count: int | None = Field(default=None, ge=0, le=30)


class MvpV2CountIn(BaseModel):
    n: int = Field(default=0, ge=0, le=30)
    pick: Id | None = None


class MvpV2MoldingIn(BaseModel):
    type: MoldingType = "none"
    pick: Id | None = None


class MvpV2BaseIn(BaseModel):
    pick: Id | None = None


class MvpV2MokIn(BaseModel):
    """v10 S.mok10 (frontend store.ts MokSt)."""

    door: MvpV2DoorIn = MvpV2DoorIn()
    slide: MvpV2CountIn = MvpV2CountIn()
    hidden: MvpV2CountIn = MvpV2CountIn()
    molding: MvpV2MoldingIn = MvpV2MoldingIn()
    base: MvpV2BaseIn = MvpV2BaseIn()
    # 정해진 단가 항목: true면 자동 수량, 숫자면 넣은 수량
    extras: dict[Annotated[str, Field(max_length=40)], StrictBool | Qty] = Field(
        default={}, max_length=30
    )


class MvpV2PlanSelIn(BaseModel):
    id: str = Field(max_length=20)
    expanded: bool = True
    kinds: list[SpaceKind] | None = Field(default=None, max_length=9)
    spaces: list[Literal["room", "kitchen", "bath", "entry", "window"]] | None = Field(
        default=None, max_length=5
    )


class MvpV2QuoteIn(BaseModel):
    pyeong: Decimal | None = Field(default=None, ge=0, le=300, max_digits=6, decimal_places=2)
    living: Literal["living", "vacant"] | None = None
    cats: list[Cat] = Field(default=[], max_length=12)
    picks: dict[Annotated[str, Field(max_length=20)], Id] = Field(default={}, max_length=20)
    plan: MvpV2PlanSelIn | None = None
    balcony: bool = False
    mok: MvpV2MokIn | None = None
    tier: Literal["economy", "basic", "premium"] = "basic"


# ---- 출력: 견적 ----
class MvpV2LineOut(BaseModel):
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


class MvpV2StepOut(BaseModel):
    key: str
    name: str
    half_days: int


class MvpV2MarketLineOut(BaseModel):
    key: str
    name: str
    qty: float | None
    unit: str
    unit_price: int | None
    amount: int
    note: str


class MvpV2BandRatioOut(BaseModel):
    lo: float
    hi: float
    lo80: float
    hi80: float
    n: int | None


class MvpV2MarketOut(BaseModel):
    trade: str
    grade: str | None  # 도배: silk · hapji
    lines: list[MvpV2MarketLineOut]
    supply: int
    lo: int
    hi: int
    band: MvpV2BandRatioOut
    version: str


class MvpV2BandOut(BaseModel):
    lo: int
    hi: int
    n: int
    p: list[float]
    mk: MvpV2MarketOut


class MvpV2GapStepOut(BaseModel):
    key: str
    name: str
    why: str
    d: int


class MvpV2GapOut(BaseModel):
    model_config = {"populate_by_name": True}

    from_: int = Field(alias="from", serialization_alias="from")
    steps: list[MvpV2GapStepOut]
    to: int


class MvpV2PreciseOut(BaseModel):
    trade: Literal["dobae", "mokgong"]
    ko: str
    lines: list[MvpV2LineOut]
    supply: int
    vat: int
    total: int
    man_days: float
    md_raw: float
    crew: int
    steps: list[MvpV2StepOut]
    days: float
    notes: list[str]
    grade: str | None
    extra_amount: int | None
    ver: str | None
    band: MvpV2BandOut
    gap: MvpV2GapOut


class MvpV2PubOut(BaseModel):
    unit_price: int
    amount: int
    source: str


class MvpV2RefLineOut(BaseModel):
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
    pub: MvpV2PubOut | None
    note: str | None


class MvpV2RefOut(BaseModel):
    cat: str
    ko: str
    level: str
    lines: list[MvpV2RefLineOut]
    lo: int
    hi: int
    vlo: int
    vhi: int
    days: float
    crew: int
    steps: list[MvpV2StepOut]
    notes: list[str]


class MvpV2MeasuredOut(BaseModel):
    name: str
    wall_m2: float
    ceiling_m2: float
    molding_m: float
    base_m: float
    doors: int


class MvpV2DoorsAutoOut(BaseModel):
    n: int
    how: str


class MvpV2InpOut(BaseModel):
    py: float
    area_m2: float
    measured: MvpV2MeasuredOut | None
    occupied: bool
    balcony: bool
    grade: str
    mok: list[str]
    doors: int
    doors_auto: MvpV2DoorsAutoOut
    assumed: list[str]


class MvpV2SumOut(BaseModel):
    lo: int
    hi: int


class MvpV2QuoteOut(BaseModel):
    inp: MvpV2InpOut
    precise: list[MvpV2PreciseOut]
    ref: list[MvpV2RefOut]
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
    band: MvpV2SumOut | None
    formula_version: str  # 산식 버전 (v10 CALC.FORMULA_VERSION)
    price_ver: str  # 공공 단가 버전 (v10 CALC.PRICE_VER)


class MvpV2MarketExtraOut(BaseModel):
    key: str
    name: str
    per: Literal["곳", "식"]
    lo: int
    hi: int
    n: int


# ---- 공정표 ----
class MvpV2ConsIn(BaseModel):
    weekendWork: bool = False
    endBy: DayOrEmpty = ""
    startAfter: DayOrEmpty = ""
    avoid: list[Day] = Field(default=[], max_length=60)


class MvpV2PropIn(BaseModel):
    start: Day
    end: Day
    crew: int | None = Field(default=None, ge=1, le=20)


class MvpV2AcceptedIn(BaseModel):
    start: Day
    end: Day


class MvpV2TrialIn(BaseModel):
    trade: Trade
    start: Day
    end: Day


class MvpV2PlanIn(BaseModel):
    quote: MvpV2QuoteIn
    move: str = Field(default="", pattern=r"^(\d{4}-\d{2}(-\d{2})?)?$")
    cons: MvpV2ConsIn = MvpV2ConsIn()
    props: dict[Trade, MvpV2PropIn] = Field(default={}, max_length=12)
    accepted: dict[Trade, MvpV2AcceptedIn] = Field(default={}, max_length=12)
    trial: MvpV2TrialIn | None = None


class MvpV2BlockOut(BaseModel):
    trade: str
    ko: str
    kind: Literal["work", "dry", "clean"]
    start: str
    end: str
    days: int
    crew: int | None
    state: str


class MvpV2DayItemOut(BaseModel):
    trade: str
    ko: str
    todo: list[str]


class MvpV2DayOut(BaseModel):
    date: str
    off: bool
    holiday: str | None
    items: list[MvpV2DayItemOut]


class MvpV2FixedOut(BaseModel):
    start: str


class MvpV2PlanTradeOut(BaseModel):
    trade: str
    ko: str
    steps: list[MvpV2StepOut]
    crew: int
    fixed: MvpV2FixedOut | None
    state: Literal["expected", "pending", "confirmed"]
    need: float


class MvpV2MovedOut(BaseModel):
    trade: str
    ko: str
    start: str


class MvpV2TrialOut(BaseModel):
    trade: str
    start: str
    end: str
    moved: list[MvpV2MovedOut]
    clash: bool
    error: str | None
    work_days: int
    need: float | None
    short: bool


class MvpV2WeekOut(BaseModel):
    n: int
    start: str
    end: str
    blocks: list[MvpV2BlockOut]


class MvpV2PlanOut(BaseModel):
    start: str
    end: str
    work_days: int
    blocks: list[MvpV2BlockOut]
    days: list[MvpV2DayOut]
    trades: list[MvpV2PlanTradeOut]
    warn: list[str]
    today: str
    tomorrow: str
    due_next: str
    weeks: list[MvpV2WeekOut]
    trial: MvpV2TrialOut | None


# ---- 받은 견적 맞춰 보기 ----
class MvpV2CheckScopeIn(BaseModel):
    ceiling: bool = True
    removal: bool = False
    moving: bool = False
    casing9: bool = False
    etc: bool = False
    extras: dict[Annotated[str, Field(max_length=20)], int] = Field(default={}, max_length=12)


class MvpV2CheckIn(BaseModel):
    quote: MvpV2QuoteIn
    trade: Literal["dobae", "mokgong"]
    amount: Decimal = Field(ge=-1, le=10_000_000_000, max_digits=14, decimal_places=2)
    mode: Literal["unknown", "excluded", "included"] = "unknown"
    scope: MvpV2CheckScopeIn = MvpV2CheckScopeIn()


class MvpV2BarOut(BaseModel):
    band_left: float
    band_width: float
    me: float


class MvpV2CheckOut(BaseModel):
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
    bar: MvpV2BarOut | None = None


# ---- 업체 가견적 · 실측 견적서 요약 칸 ----
Won = Annotated[Decimal, Field(ge=0, le=100_000_000_000, max_digits=14, decimal_places=2)]


class MvpV2EstLineIn(BaseModel):
    key: Annotated[str, Field(max_length=40)]
    name: Annotated[str, Field(max_length=200)]
    qty: Qty | None
    state: Annotated[str, Field(max_length=20)]


class MvpV2EstimateIn(BaseModel):
    trade: Literal["dobae", "mokgong"]
    grade: Literal["economy", "basic"] | None = None
    lines: list[MvpV2EstLineIn] = Field(max_length=60)
    prices: dict[Annotated[str, Field(max_length=40)], Won | None] = Field(
        default={}, max_length=60
    )
    std_total: int = Field(ge=0, le=100_000_000_000)


class MvpV2EstimateOut(BaseModel):
    ok: bool
    supply: int | None = None
    vat: int | None = None
    total: int | None = None
    pct: float | None = None
    why: str | None = None


class MvpV2EnteredIn(BaseModel):
    amount: int = Field(ge=0, le=100_000_000_000)
    mode: Literal["excluded", "included", "exempt"]
    std_total: int | None = Field(default=None, ge=0, le=100_000_000_000)


class MvpV2EnteredOut(BaseModel):
    supply: int
    vat: int
    total: int
    pct: float | None


# ---- 셀프 계산기 ----
Len = Annotated[float, Field(ge=0, le=1000)]
Pos = Annotated[float, Field(gt=0, le=1000)]


class MvpV2Calc7In(BaseModel):
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


class MvpV2WallOut(BaseModel):
    wall_m2: float
    ceiling_m2: float
    strips: int
    cStrips: int
    per_roll: int
    rolls_raw: float
    rolls: int


class MvpV2TrimOut(BaseModel):
    molding_m: float
    molding_pcs: int
    base_m: float
    base_pcs: int


class MvpV2PaintOut(BaseModel):
    area_m2: float
    liters: float
    n18: int
    n4: int


# ---- 추가 항목 범위 ----
class MvpV2CasingIn(BaseModel):
    doors: int = Field(ge=0, le=30)
    with_door: bool = False


class MvpV2ExtrasIn(BaseModel):
    picks: dict[Annotated[str, Field(max_length=20)], int] = Field(default={}, max_length=12)
    casing: MvpV2CasingIn | None = None


class MvpV2ExtrasOut(BaseModel):
    lo: int
    hi: int
    notes: list[str]


# ---- AI ----
IMAGE_MAX = 1_500_000  # base64 글자 수


class MvpV2TextPart(BaseModel):
    type: Literal["text"]
    text: str = Field(max_length=60_000)


class MvpV2ImagePart(BaseModel):
    type: Literal["image"]
    data: str = Field(max_length=IMAGE_MAX, pattern=r"^[A-Za-z0-9+/=]*$")


class MvpV2ToolCallIn(BaseModel):
    id: str = Field(max_length=100)
    name: str = Field(max_length=64)
    arguments: dict = {}


class MvpV2MessageIn(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: (
        Annotated[str, Field(max_length=60_000)]
        | Annotated[
            list[Annotated[MvpV2TextPart | MvpV2ImagePart, Field(discriminator="type")]],
            Field(max_length=12),
        ]
    )
    tool_calls: list[MvpV2ToolCallIn] | None = Field(default=None, max_length=12)
    tool_call_id: str | None = Field(default=None, max_length=100)


class MvpV2ToolIn(BaseModel):
    name: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    description: str = Field(default="", max_length=2_000)
    parameters: dict = {}


class MvpV2LlmIn(BaseModel):
    system: str = Field(default="", max_length=60_000)
    messages: list[MvpV2MessageIn] = Field(min_length=1, max_length=30)
    tools: list[MvpV2ToolIn] = Field(default=[], max_length=12)


class MvpV2ToolCallOut(BaseModel):
    id: str
    name: str
    arguments: dict


class MvpV2LlmOut(BaseModel):
    text: str
    tool_calls: list[MvpV2ToolCallOut]
    stop: Literal["tool_calls", "stop", "refusal"]


class MvpV2LlmHealthOut(BaseModel):
    ok: bool
    live: bool
