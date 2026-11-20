"""가견적: 업체가 확인한 단가 × 이 집 표준견적서 수량.

- 수량은 표준견적서 줄 수량을 그대로 쓴다. 합계에 들어가는 줄(포함 · 따로 계산)만 본다.
  실측 후 줄(철거 · 폐기물 · 짐 이동)은 업체 단가를 받지 않으니 처음부터 보지 않는다.
- 업체 단가는 부가세 빼고 적는다. '다른 줄에 포함'(included_in) 줄은 0원이다.
- 업체 단가가 없는 줄은 빼고 missing에 남긴다. 단가를 받는 표준 행이 아닌 줄(짐 있는 집 할증처럼
  수량이 없는 줄)은 left_out에 남긴다.
- 부가세는 공급가에 한 번만 붙인다(common.with_vat). 면세 업체는 0원.
- v3(dobae_v3, 1201~1208, dev-06): 업체 단가 × 계산 엔진 수량(QtyV3: 공급 평 · 벽지 평 · 품).
  받는 법은 단가 · 다른 줄에 포함(0원) · 빼기. 간이 · 면세 업체는 부가세 0(L02).
  표준견적서에 없는 줄(퍼티 · 식대 · 운송비)은 비교 %에서 뺀다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import COUNTED, Money, with_vat, won
from app.calc.dobae import GRADE_PAPER, QtyV3
from app.calc.quote_diff import percent_vs


@dataclass(frozen=True)
class PriceRow:
    """업체가 단가를 넣는 표준 행 (부가세 빼고, 단위당)"""

    key: str
    name: str
    unit: str


QtyKind = Literal["floor_py", "paper_py", "man_day", "one"]
PriceMode = Literal["price", "included", "excluded"]


@dataclass(frozen=True)
class PriceRowV3(PriceRow):
    """v3 단가표 한 줄. code는 화면 표시값(1201 …)이라 바뀌어도 저장 키는 그대로다(dev-06)."""

    code: str = ""
    qty: QtyKind = "one"  # 이 줄 수량 = QtyV3의 어느 값인지
    grade: str | None = None  # 도배지 줄: 이 벽지(economy 합지 · basic 실크)를 고른 집에만 쓴다
    in_standard: bool = True  # 표준견적서에 같은 일이 있는 줄. 아니면 비교 %에서 뺀다
    label: str = ""  # 고객 화면 이름(비면 name). 화면 · AI가 같은 말을 써요
    note: str = ""  # 고객 화면 줄 아래 짧은 뜻


# 단위는 refprice.vendor_baseline과 같다(테스트가 본다). 공급 평 = 내 집 평(공급 기준)
V3_ROWS: tuple[PriceRowV3, ...] = (
    PriceRowV3(
        "putty", "퍼티작업", "공급 평", "1201", "floor_py", None, False, note="사전퍼티 또는 밀작업"
    ),
    PriceRowV3("paper_hapji", "합지", "벽지 평", "1203", "paper_py", "economy", label="합지벽지"),
    PriceRowV3("paper_silk", "실크", "벽지 평", "1204", "paper_py", "basic", label="실크벽지"),
    PriceRowV3(
        "material", "부자재", "공급 평", "1205", "floor_py", note="풀 · 부직포 · 네바리 · 실리콘 등"
    ),
    PriceRowV3("labor", "인건비", "품", "1206", "man_day", note="품 = 1명이 하루 하는 일"),
    PriceRowV3("meal", "식대", "품", "1207", "man_day", None, False),
    PriceRowV3("truck", "운송비", "대", "1208", "one", None, False),
)
V3_BY_KEY: dict[str, PriceRowV3] = {r.key: r for r in V3_ROWS}

# 공정별로 업체 단가를 받는 표준 행. 키는 계산 엔진 줄 키와 같고, 도배지만 등급마다 따로 받는다
PRICE_ROWS: dict[str, tuple[PriceRow, ...]] = {
    "dobae": (
        PriceRow("wall", "벽 도배 시공 (풀 포함)", "㎡"),
        PriceRow("ceiling", "천장 도배 시공 (풀 포함)", "㎡"),
        *(PriceRow(f"paper_{g}", f"도배지 ({GRADE_PAPER[g]})", "㎡") for g in ("basic", "economy")),
        PriceRow("primer", "초배지", "㎡"),
    ),
    "mokgong": (
        PriceRow("frame", "천장 평탄화 · 경량천장틀", "㎡"),
        PriceRow("board", "천장 평탄화 · 석고보드 1겹", "㎡"),
        PriceRow("ceiling_mat", "천장틀 · 석고보드 자재", "㎡"),
        PriceRow("door", "방문 교체 (문틀 · 문짝)", "개"),
        PriceRow("casing", "문선 설치 (문 둘레 양면)", "m"),
        PriceRow("door_mat", "방문 자재 (ABS 문틀 · 문짝 · 문선)", "개"),
        PriceRow("molding", "천장 몰딩 설치", "m"),
        PriceRow("molding_mat", "몰딩 자재", "m"),
        PriceRow("base", "걸레받이 설치 (MDF)", "m"),
        PriceRow("base_mat", "걸레받이 자재", "m"),
    ),
    "dobae_v3": V3_ROWS,
}
PRICE_KEYS: dict[str, tuple[str, ...]] = {
    t: tuple(r.key for r in rows) for t, rows in PRICE_ROWS.items()
}


def price_key(line_key: str, grade: str | None) -> str:
    """표준견적서 줄 키 → 업체 단가 키. 도배지는 고객이 고른 등급의 단가를 쓴다."""
    return f"paper_{grade}" if line_key == "paper" and grade else line_key


@dataclass(frozen=True)
class StdLine:
    """표준견적서 줄에서 가견적에 쓰는 것"""

    key: str
    qty: Decimal | None
    state: str


@dataclass(frozen=True)
class VendorPrice:
    """업체 단가 한 줄: 단가(원, 부가세 빼고) 또는 다른 줄에 포함"""

    unit_price: int | None = None
    included_in: str | None = None

    def __post_init__(self) -> None:
        if (self.unit_price is None) == (self.included_in is None):
            raise ValueError("단가와 '다른 줄에 포함' 중 하나만 있어야 해요")
        if self.unit_price is not None and self.unit_price < 0:
            raise ValueError("단가는 0 이상이어야 해요")


@dataclass(frozen=True)
class EstimateLine:
    key: str  # 표준견적서 줄 키
    price_key: str  # 업체 단가 키 (도배지는 paper_basic · paper_economy)
    qty: Decimal
    unit_price: int | None  # 다른 줄에 포함이면 None
    included_in: str | None
    amount: int


@dataclass(frozen=True)
class Estimate:
    lines: tuple[EstimateLine, ...]
    supply: int
    vat: int
    total: int
    missing: tuple[str, ...]  # 업체 단가가 없어 뺀 표준 행
    left_out: tuple[str, ...]  # 업체 단가를 받지 않는 줄이라 뺀 것


def estimate(
    lines: Sequence[StdLine],
    prices: Mapping[str, VendorPrice],
    *,
    trade: str,
    grade: str | None = None,
    exempt: bool = False,
) -> Estimate:
    keys = PRICE_KEYS[trade]
    # 포함 대상은 이번 집에서 수량과 직접 단가로 실제 계산하는 줄이어야 한다.
    priced_keys = {
        price_key(ln.key, grade)
        for ln in lines
        if ln.state in COUNTED
        and ln.qty is not None
        and ln.qty > 0
        and price_key(ln.key, grade) in keys
        and (vp := prices.get(price_key(ln.key, grade))) is not None
        and vp.unit_price is not None
    }
    out: list[EstimateLine] = []
    missing: list[str] = []
    left_out: list[str] = []
    for ln in lines:
        if ln.state not in COUNTED:
            continue
        pk = price_key(ln.key, grade)
        if pk not in keys or ln.qty is None:
            left_out.append(ln.key)
            continue
        vp = prices.get(pk)
        if vp is None:
            missing.append(ln.key)
        elif vp.included_in is not None:
            if vp.included_in in priced_keys:
                out.append(EstimateLine(ln.key, pk, ln.qty, None, vp.included_in, 0))
            else:
                missing.append(ln.key)
        else:
            amount = won(ln.qty * vp.unit_price)
            out.append(EstimateLine(ln.key, pk, ln.qty, vp.unit_price, None, amount))
    supply = sum(x.amount for x in out)
    money = Money(supply, 0, supply) if exempt else with_vat(supply)
    return Estimate(
        tuple(out), money.supply, money.vat, money.total, tuple(missing), tuple(left_out)
    )


# ---- 가견적 v3 (dobae_v3, 1201~1208) ----


@dataclass(frozen=True)
class PriceV3:
    """업체 v3 단가 한 줄: 받는 법 + 단가(원, 부가세 빼고) · 포함 대상"""

    mode: PriceMode
    unit_price: int | None = None
    included_in: str | None = None

    def __post_init__(self) -> None:
        if (self.mode == "price") != (self.unit_price is not None):
            raise ValueError("단가 줄에만 단가가 있어야 해요")
        if (self.mode == "included") != (self.included_in is not None):
            raise ValueError("'다른 줄에 포함' 줄에만 포함 대상이 있어야 해요")
        if self.unit_price is not None and self.unit_price < 0:
            raise ValueError("단가는 0 이상이어야 해요")


@dataclass(frozen=True)
class EstimateV3Line:
    row: PriceRowV3
    qty: Decimal
    mode: PriceMode
    unit_price: int | None
    included_in: str | None
    amount: int  # 포함 · 빼기 줄은 0


@dataclass(frozen=True)
class EstimateV3:
    grade: str
    lines: tuple[EstimateV3Line, ...]
    supply: int
    vat: int
    total: int  # 고객이 낼 금액 (부가세 포함, 간이 · 면세는 공급가 그대로)
    compare_total: int  # 표준견적서에 있는 줄만 더한 금액(같은 부가세 방식). 비교 %에 쓴다
    vs_standard_pct: Decimal | None  # 표준견적서 대비 % (표준이 없으면 비움)
    paper_ok: bool  # 고객이 고른 벽지 줄이 '빼기'가 아님 (빼기면 '이 벽지는 안 해요')


def qty_of(row: PriceRowV3, q: QtyV3) -> Decimal:
    return {"floor_py": q.floor_py, "paper_py": q.paper_py, "man_day": q.man_day}.get(
        row.qty, Decimal(1)
    )


def row_amount(row: PriceRowV3, vp: PriceV3 | None, q: QtyV3) -> tuple[Decimal, int]:
    """한 줄의 (수량, 금액). 단가 줄만 단가 × 수량, 포함 · 빼기 · 아직 안 넣은 줄은 0원.
    업체 단가표 '공급 69.4㎡ 집이면' 열(D02)도 이 값이다."""
    n = qty_of(row, q)
    return n, (won(n * vp.unit_price) if vp is not None and vp.unit_price is not None else 0)


def estimate_v3(
    prices: Mapping[str, PriceV3],
    qty: QtyV3,
    *,
    grade: str,
    exempt: bool = False,
    standard_total: int | None = None,
) -> EstimateV3:
    """업체 v3 단가 × 계산 엔진 수량. 도배지는 고른 벽지 줄만, 단가가 없는 줄은 '빼기'로 본다.
    exempt면(간이 · 면세, L02) 부가세 0. 비교 %는 표준견적서에 없는 줄을 빼고 센다."""
    out: list[EstimateV3Line] = []
    for row in V3_ROWS:
        if row.grade is not None and row.grade != grade:
            continue
        vp = prices.get(row.key) or PriceV3("excluded")
        n, amount = row_amount(row, vp, qty)
        out.append(EstimateV3Line(row, n, vp.mode, vp.unit_price, vp.included_in, amount))
    supply = sum(x.amount for x in out)
    money = Money(supply, 0, supply) if exempt else with_vat(supply)
    same = sum(x.amount for x in out if x.row.in_standard)
    compare = same if exempt else with_vat(same).total
    pct = percent_vs(compare, standard_total) if standard_total else None
    paper_ok = all(x.mode != "excluded" for x in out if x.row.grade is not None)
    return EstimateV3(
        grade, tuple(out), money.supply, money.vat, money.total, compare, pct, paper_ok
    )
