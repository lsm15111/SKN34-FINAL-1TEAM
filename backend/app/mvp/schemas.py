import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool

from app.calc.mvp_common import Grade
from app.calc.mvp_mokgong import DoorMode, MoldingType
from app.calc.plan_qty import SpaceKind

QTY_MAX = Decimal(10_000)  # 고객이 넣는 수량 한도 (㎡ · m · 개소)
Qty = Annotated[Decimal, Field(ge=0, le=QTY_MAX, max_digits=8, decimal_places=1)]


class MvpPlanBriefOut(BaseModel):
    id: str
    name: str
    region: str
    type: str
    supply_m2: Decimal
    excl_m2: Decimal | None
    supply_py: int
    rooms: int
    baths: int
    layout: str
    year: int | None
    stage: str | None
    src: str
    src_url: str
    img: str
    drawn: str
    has_ext: bool
    sup_note: str | None  # 공급면적 출처 글


class MvpPlanSpaceOut(BaseModel):
    id: str
    ko: str
    kind: str
    w_m: Decimal
    d_m: Decimal
    floor_m2: Decimal
    wall_m2: Decimal
    ceiling_m2: Decimal
    molding_m: Decimal
    base_m: Decimal
    own_door: bool
    papered: bool
    sure: str
    ext: bool
    plan_w_m: Decimal | None = None  # 도면 치수 (벽 가운데 기준, 확장 전)
    plan_d_m: Decimal | None = None


class MvpRollOut(BaseModel):
    kind: str
    ko: str
    size: str
    per_roll: int
    rolls: int


class MvpPlanEstOut(BaseModel):
    """평형으로 어림한 값 (v10 CALC9 est): 도면 수량과 비교용."""

    py: Decimal
    wall_m2: Decimal
    ceiling_m2: Decimal
    molding_m: Decimal
    base_m: Decimal


class MvpPlanQtyOut(BaseModel):
    plan_id: str
    rules_version: str
    expanded: bool
    ceiling: bool
    kinds: list[str] | None
    spaces: list[MvpPlanSpaceOut]
    wall_m2: Decimal
    ceiling_m2: Decimal
    paper_m2: Decimal
    primer_m2: Decimal
    rolls: list[MvpRollOut]
    molding_m: Decimal
    molding_pcs: int
    base_m: Decimal
    base_pcs: int
    doors: int
    casing_m: Decimal
    windows_m: Decimal
    low: list[str]
    assumptions: list[str]
    est: MvpPlanEstOut | None = None


class MvpProductOut(BaseModel):
    id: str
    kind: str
    name: str
    price: int
    why: str
    len_m: Decimal | None
    type: str | None
    per: str | None = None  # 한 개 단위: 짝 · 세트 (v10 MOK10.prod per)


class MvpExtraOut(BaseModel):
    key: str
    group: str
    ko: str
    what: str
    unit: str
    price: int
    basis: str
    src: str
    auto: str | None


class MvpGradeInitOut(BaseModel):
    molding_type: str
    molding: str
    base: str
    leaf: str
    door_set: str


class MvpMokFixedOut(BaseModel):
    """화면 문구에 쓰는 정해진 값 (v10 MOK10.fixed)."""

    minus_mult: Decimal  # 무몰딩 시공 배수
    hidden_mult: Decimal  # 히든 걸레받이 시공 배수
    molding_per_py: Decimal
    base_per_py: Decimal


class MvpMaterialsOut(BaseModel):
    version: str
    products: list[MvpProductOut]
    extras: list[MvpExtraOut]
    grades: dict[str, MvpGradeInitOut]
    fixed: MvpMokFixedOut | None = None


class MvpDoorIn(BaseModel):
    mode: DoorMode = "none"
    pick: str | None = Field(default=None, max_length=80)
    count: int | None = Field(default=None, ge=0, le=30)


class MvpCountIn(BaseModel):
    n: int = Field(default=0, ge=0, le=30)
    pick: str | None = Field(default=None, max_length=80)


class MvpMokSelIn(BaseModel):
    door: MvpDoorIn = MvpDoorIn()
    slide: MvpCountIn = MvpCountIn()
    hidden: MvpCountIn = MvpCountIn()
    molding_type: MoldingType = "none"
    molding: str | None = Field(default=None, max_length=80)
    base: str | None = Field(default=None, max_length=80)
    # 정해진 단가 항목: true면 자동 수량(도면 · 면적), 숫자면 넣은 수량
    extras: dict[Annotated[str, Field(max_length=40)], StrictBool | Qty] = Field(
        default={}, max_length=30
    )


class MvpPreviewIn(BaseModel):
    plan_id: str | None = Field(default=None, max_length=20)
    expanded: bool = True
    kinds: list[SpaceKind] | None = Field(default=None, max_length=9)
    grade: Grade | None = None  # 없으면 프로젝트 도배 등급
    mok: MvpMokSelIn | None = None  # 없으면 등급별 처음 자재


class MvpLineOut(BaseModel):
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: str
    source: str
    price_basis: str
    calc: str


class MvpStepOut(BaseModel):
    key: str
    name: str
    half_days: int


class MvpMarketLineOut(BaseModel):
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int
    note: str


class MvpGapStepOut(BaseModel):
    key: str
    name: str
    why: str
    d: int


class MvpMarketOut(BaseModel):
    version: str
    supply: int  # 부가세 별도
    lo: int
    hi: int
    band_lo: Decimal
    band_hi: Decimal
    n: int
    lines: list[MvpMarketLineOut]
    gap_start: int
    gap: list[MvpGapStepOut]


class MvpTradePreviewOut(BaseModel):
    trade: Literal["dobae", "mokgong"]
    version: str
    grade: str | None  # 도배: 실제 계산에 쓴 벽지 등급
    lines: list[MvpLineOut]
    supply: int
    vat: int
    total: int
    man_day: Decimal
    days: Decimal
    steps: list[MvpStepOut]
    notes: list[str]
    market: MvpMarketOut


class MvpPreviewOut(BaseModel):
    project_id: uuid.UUID
    project_rev: int
    area_m2: Decimal
    area_basis: str
    grade: Grade
    plan: MvpPlanBriefOut | None
    plan_qty: MvpPlanQtyOut | None
    trades: list[MvpTradePreviewOut]
    supply: int
    vat: int
    total: int
