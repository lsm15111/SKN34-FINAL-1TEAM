"""MVP 목공: 고른 자재(문 · 천장 몰딩 · 걸레받이)와 정해진 단가 항목으로 목공 금액을 낸다.

팀 목공 계산(mokgong.quote)과 같은 Quote 모양을 낸다. 시공 품 · 하루 목수 수는 팀 MokgongPrices를 쓰고,
자재값 · 정해진 단가는 refprice.mvp_materials의 MokBook을 쓴다.
금액은 원 정수(won), 길이 · 면적은 소수 한 자리(m2), 자재 개수는 올림, 품은 0.5 단위로 올린다.
도면 수량(PlanQty)이 있으면 몰딩 · 걸레받이 길이와 천장 넓이를 도면에서 읽는다.
"""

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from app.calc.common import COUNTED, PYEONG_M2, AreaBasis, Line, Step, half_days, half_up, m2, won
from app.calc.mokgong import MokgongPrices
from app.calc.mvp_common import Grade, MvpLine, PriceBasis, num, team_basis
from app.calc.plan_qty import PlanQty

ProductKind = Literal["door_set", "door_leaf", "slide", "hidden", "molding", "base"]
DoorMode = Literal["none", "replace", "overlay", "leaf"]  # 안 함 · 문틀까지 · 문틀 덧방 · 문짝만
MoldingType = Literal["flat", "step", "minus", "none"]

MOLDING_KO = {"flat": "평몰딩", "step": "계단몰딩", "minus": "무몰딩(마이너스)"}


@dataclass(frozen=True)
class Product:
    kind: ProductKind
    name: str
    price: int  # 공급가 원 (한 짝 · 한 세트 · 한 개)
    why: str  # 어떤 값인지 (판매가 · 규격)
    len_m: Decimal | None = None  # 몰딩 · 걸레받이 한 개 길이
    type: str | None = None  # 몰딩 종류 · 히든 걸레받이


@dataclass(frozen=True)
class Price:
    price: int
    basis: PriceBasis
    src: str


@dataclass(frozen=True)
class MokFixed:
    """문 · 몰딩 시공처럼 고르지 않는 단가와 가정값."""

    door_install: Price
    leaf_install: Price
    overlay_frame: Price
    casing: Price
    casing_mat: Price  # 문 하나 문선 자재
    handle: Price
    slide_install: Price
    hidden_install: Price
    molding: Price
    base: Price
    minus_mult: Decimal  # 무몰딩 시공 배수
    hidden_mult: Decimal  # 히든 걸레받이 시공 배수
    molding_loss: Decimal
    base_loss: Decimal
    molding_per_py: Decimal  # 도면이 없을 때 공급 1평당 길이
    base_per_py: Decimal
    supply_per_floor: Decimal  # 도면이 없을 때 천장 넓이 = 공급면적 ÷ 이 값
    doors_by_py: tuple[int, ...]  # 도면이 없을 때 방문 수: 평 경계
    doors_count: tuple[int, ...]  # 경계마다 방 + 욕실 수


@dataclass(frozen=True)
class Extra:
    key: str
    group: str
    ko: str
    what: str
    unit: str
    price: int
    basis: PriceBasis
    src: str
    auto: Literal["ceiling", "windows"] | None = None  # 수량을 자동으로 채울 수 있는 항목


@dataclass(frozen=True)
class GradeInit:
    """등급별 처음 고른 자재. 문은 처음에 '안 함'이라 작업 방식을 고르면 쓴다."""

    molding_type: MoldingType
    molding: str
    base: str
    leaf: str
    door_set: str


@dataclass(frozen=True)
class MokBook:
    version: str
    products: dict[str, Product]
    fixed: MokFixed
    extras: tuple[Extra, ...]
    init: dict[Grade, GradeInit]


@dataclass(frozen=True)
class DoorSel:
    mode: DoorMode = "none"
    pick: str | None = None
    count: int | None = None  # 없으면 도면에서 센 문, 그것도 없으면 입력 doors


@dataclass(frozen=True)
class CountSel:
    n: int = 0
    pick: str | None = None


@dataclass(frozen=True)
class MokSel:
    door: DoorSel = DoorSel()
    slide: CountSel = CountSel()
    hidden: CountSel = CountSel()
    molding_type: MoldingType = "none"
    molding: str | None = None
    base: str | None = None
    # 정해진 단가 항목: True면 자동 수량(auto가 있는 항목만), 숫자면 고객이 넣은 수량
    extras: dict[str, bool | Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class MvpMokgongInput:
    area_m2: Decimal
    sel: MokSel
    area_basis: AreaBasis = "supply"
    occupied: bool = False
    doors: int = 0  # 도면이 없을 때 방문 수. 0이면 평형으로 어림 (방 + 욕실)
    plan: PlanQty | None = None
    plan_name: str = ""


@dataclass(frozen=True)
class MvpMokgongQuote:
    version: str
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal
    steps: list[Step]
    days: Decimal
    assumptions: list[str]
    doors: int
    molding_m: Decimal
    base_m: Decimal
    extra_amount: int  # 정해진 단가 항목 합 (시장 기준 범위에 같은 금액을 더할 때 씀)


def _up(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def _product(book: MokBook, pid: str | None, kinds: tuple[ProductKind, ...]) -> Product:
    p = book.products.get(pid or "")
    if p is None or p.kind not in kinds:
        raise ValueError("고른 자재를 다시 골라 주세요")
    return p


def doors_by_pyeong(book: MokBook, py: Decimal) -> int:
    """도면이 없을 때 방문 수 (방 + 욕실)."""
    f = book.fixed
    return next(
        (n for b, n in zip(f.doors_by_py, f.doors_count, strict=False) if py < b), f.doors_count[-1]
    )


def supply_area(inp: "MvpMokgongInput", mg: MokgongPrices) -> Decimal:
    if inp.area_basis == "supply":
        return inp.area_m2
    return m2(inp.area_m2 * mg.supply_per_exclusive)


def default_sel(book: MokBook, grade: Grade) -> MokSel:
    i = book.init[grade]
    return MokSel(molding_type=i.molding_type, molding=i.molding, base=i.base)


def default_door_pick(book: MokBook, grade: Grade, mode: DoorMode) -> str | None:
    i = book.init[grade]
    return None if mode == "none" else i.door_set if mode == "replace" else i.leaf


def quote(inp: MvpMokgongInput, book: MokBook, mg: MokgongPrices) -> MvpMokgongQuote | None:
    """고른 것이 하나도 없으면 None."""
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    f, sel, plan = book.fixed, inp.sel, inp.plan
    area = supply_area(inp, mg)
    py = area / PYEONG_M2
    lines: list[Line] = []
    md_door = md_trim = md_ceil = Decimal(0)

    def add(key, name, qty, unit, price, amount, basis: PriceBasis, src, calc="", state="included"):
        lines.append(
            MvpLine(key, name, qty, unit, price, amount, state, src, team_basis(basis), basis, calc)
        )

    def add_price(key, name, n: int, p: Price, calc):
        add(key, name, Decimal(n), "개", p.price, n * p.price, p.basis, p.src, calc)

    def add_pick(key, name, n: int, p: Product, calc):
        add(key, name, Decimal(n), "개", p.price, n * p.price, "pick", f"고른 자재 · {p.why}", calc)

    # 문
    d = sel.door
    if d.count is not None:
        n = d.count
    elif plan and plan.doors:
        n = plan.doors
    else:
        n = inp.doors or doors_by_pyeong(book, py)
    n = max(0, n)
    doors = 0
    if d.mode != "none" and n > 0:
        doors = n
        dp = _product(book, d.pick, ("door_set",) if d.mode == "replace" else ("door_leaf",))
        each = f"방문 {n}개"
        if d.mode == "replace":
            add_price("door", "방문 교체 설치 (문틀 · 문짝)", n, f.door_install, each)
            add_pick("door_mat", f"방문 자재 · {dp.name}", n, dp, each)
            md_door += n * mg.md_door
        elif d.mode == "overlay":
            add_price("door_frame", "문틀 덧방 (시공 + 덧방 문틀)", n, f.overlay_frame, each)
            add_price("door", "문짝 설치", n, f.leaf_install, each)
            add_pick("door_mat", f"문짝 자재 · {dp.name}", n, dp, each)
            md_door += n * mg.md_door
        else:
            add_price("door", "문짝 교체 설치", n, f.leaf_install, each)
            add_pick("door_mat", f"문짝 자재 · {dp.name}", n, dp, each)
            md_door += n * mg.md_door / 2
        add_price("handle", "손잡이 (기본)", n, f.handle, each)
        if d.mode != "leaf":
            cas = m2(mg.casing_per_door * n)
            add(
                "casing",
                "문선 설치 (문 둘레 양면)",
                cas,
                "m",
                f.casing.price,
                won(cas * f.casing.price),
                f.casing.basis,
                f.casing.src,
                f"문 하나에 양면 {num(mg.casing_per_door)}m × {n}개",
            )
            add_price("casing_mat", "문선 자재 (기본)", n, f.casing_mat, each)
            md_door += cas * mg.md_casing
    for key, ko, s, inst in (
        ("slide", "슬라이딩 도어", sel.slide, f.slide_install),
        ("hidden", "히든도어", sel.hidden, f.hidden_install),
    ):
        if s.n <= 0:
            continue
        sp = _product(book, s.pick, (key,))
        add_price(key, f"{ko} 설치", s.n, inst, f"{ko} {s.n}개")
        add_pick(f"{key}_mat", f"{ko} 자재 · {sp.name}", s.n, sp, f"{ko} {s.n}개")
        md_door += s.n * mg.md_door * Decimal("1.5")

    # 천장 몰딩 · 걸레받이: 도면이 있으면 도면 길이, 없으면 평형 가정값
    trims = []
    if sel.molding_type != "none":
        mp = _product(book, sel.molding, ("molding",))
        if mp.type != sel.molding_type:
            raise ValueError("몰딩 종류와 자재가 맞지 않아요")
        mult = f.minus_mult if sel.molding_type == "minus" else Decimal(1)
        name = f"천장 몰딩 설치 · {MOLDING_KO[sel.molding_type]}"
        why = "무몰딩은 석고 마감 손이 더 가요"
        trims.append(("molding", name, "천장 몰딩", mp, mult, why, f.molding, f.molding_loss))
    if sel.base is not None:
        bp = _product(book, sel.base, ("base",))
        mult = f.hidden_mult if bp.type == "hidden" else Decimal(1)
        why = "히든은 벽 석고보드와 함께 묻어요"
        trims.append(("base", "걸레받이 설치", "걸레받이", bp, mult, why, f.base, f.base_loss))
    lens = {"molding": Decimal(0), "base": Decimal(0)}
    for key, name, ko, p, mult, why, inst, loss in trims:
        per_py = f.molding_per_py if key == "molding" else f.base_per_py
        if plan:
            length = plan.molding_m if key == "molding" else plan.base_m
            where = "천장 둘레" if key == "molding" else "바닥 둘레(문 · 큰 창 뺌)"
            how = f"도면 {inp.plan_name}에서 잰 {where}"
        else:
            length, how = m2(py * per_py), f"공급 {num(m2(py))}평 × {num(per_py)}m"
        lens[key] = length
        lp = won(inst.price * mult)
        src = f"{inst.src} × {num(mult)}({why} · 팀 가정값)" if mult > 1 else inst.src
        basis: PriceBasis = "assumed" if mult > 1 else inst.basis
        add(key, name, length, "m", lp, won(length * lp), basis, src, how)
        if p.len_m is None:
            raise ValueError("고른 자재를 다시 골라 주세요")
        pcs = _up(length * loss / p.len_m)
        calc = f"{ko.removeprefix('천장 ')} {num(length)}m × {num(loss)} ÷ {num(p.len_m)}m"
        add_pick(f"{key}_mat", f"{ko} 자재 · {p.name}", pcs, p, calc)
        md_trim += length * (mg.md_molding if key == "molding" else mg.md_base) * mult

    # 정해진 단가 항목
    ceiling = plan.ceiling_m2 if plan else m2(area / f.supply_per_floor)
    windows = plan.windows_m if plan else Decimal(0)
    known = {x.key: x for x in book.extras}
    if not set(sel.extras) <= set(known):
        raise ValueError("목공 항목을 다시 골라 주세요")
    extra = 0
    for x in book.extras:
        v = sel.extras.get(x.key)
        if v is None or v is False:
            continue
        if v is True:
            if x.auto is None:
                raise ValueError("이 항목은 수량을 넣어 주세요")
            q = ceiling if x.auto == "ceiling" else windows
            if x.auto == "windows":
                how = "도면에서 잰 창 폭 합계"
            else:
                how = "도면에서 잰 천장 넓이" if plan else "전용면적(바닥 × 1.0)"
        else:
            q, how = v, "고객이 넣은 수량"
        q = m2(max(Decimal(0), q))
        if not q:
            continue
        a = won(q * x.price)
        extra += a
        add(x.key, x.ko, q, x.unit, x.price, a, x.basis, x.src, how)
        if x.key == "flatten_overlay":
            md_ceil += q * mg.md_board
        elif x.key == "ceiling_redo":
            md_ceil += q * (mg.md_frame + mg.md_board)
    if not lines:
        return None

    # 실측 후 정하는 줄
    def after(key, name):
        src = "공공 단가가 없어 업체 견적에서 확인해요"
        add(key, name, None, "식", None, None, "none", src, state="after_visit")

    if d.mode in ("replace", "overlay") and doors:
        after("remove_door", "기존 방문 · 문틀 철거")
    if trims:
        after("remove_trim", "기존 몰딩 · 걸레받이 철거")
    if sel.extras.get("ceiling_redo"):
        after("remove_ceiling", "기존 천장 철거")
    after("waste", "폐기물 처리")
    if inp.occupied:
        after("moving", "짐 이동 · 보양")

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * mg.vat_rate)
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    if md_trim or md_ceil:
        steps.append(Step("remove", "철거 · 바탕 정리", 1))
    if md_ceil:
        steps.append(Step("ceiling", "천장 석고보드", half_days(md_ceil, mg.crew)))
    if md_door:
        steps.append(Step("door", "문 교체", half_days(md_door, mg.crew)))
    if md_trim:
        steps.append(Step("trim", "몰딩 · 걸레받이", half_days(md_trim, mg.crew)))
    steps.append(Step("finish", "정리 · 청소", 1))

    notes = [
        (
            "문 · 천장 몰딩 · 걸레받이는 고른 자재값에 공공 시공 단가를 더했어요. "
            "나머지 목공은 정해진 단가예요."
        )
    ]
    if plan:
        notes.append(
            f"몰딩 · 걸레받이 길이는 도면 {inp.plan_name}에서 방마다 잰 둘레예요. 실측 때 다시 재요."
        )
    else:
        notes.append(
            f"몰딩은 공급 1평에 {num(f.molding_per_py)}m, 걸레받이는 {num(f.base_per_py)}m로 "
            "집 전체를 잡았어요. 실측 때 다시 재요."
        )
    if any(isinstance(ln, MvpLine) and ln.price_basis == "assumed" for ln in lines):
        notes.append(
            "'팀 가정값' 줄은 공개 단가가 없어 팀이 정한 값이에요. 업체 견적에서 꼭 확인해 주세요."
        )
    if extra and any(k not in ("flatten_overlay", "ceiling_redo") for k in sel.extras):
        notes.append("우물천장 · 가벽 같은 항목은 기간 계산에 넣지 않았어요. 업체가 일정을 정해요.")
    notes.append(f"하루 목수 {mg.crew}명이 들어가는 것으로 기간을 잡았어요.")

    return MvpMokgongQuote(
        version=book.version,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md_door + md_trim + md_ceil),
        steps=steps,
        days=Decimal(sum(s.half_days for s in steps)) / 2,
        assumptions=notes,
        doors=doors,
        molding_m=lens["molding"],
        base_m=lens["base"],
        extra_amount=extra,
    )
