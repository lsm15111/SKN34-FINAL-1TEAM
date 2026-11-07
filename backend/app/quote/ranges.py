"""표준견적서 · 가견적의 예상 범위: 저장한 줄 금액 + 이 집을 얼마나 아는지 + '실측 후' 줄 → calc.price_range.

- 정밀도는 지금 집 정보로 정한다: 면적을 넣었으면 area, 평형대만 골랐으면 band. 천장 평탄화 · 방문 개수는 가정값(guess).
- 일부 공간만 고르면 '고른 공간 몫'도 가정값이라 그 σ(RANGE.share_sigma)를 더하고, 철거 · 폐기물 같은
  한 번(식) 금액도 공사 크기만큼 줄인다(조건 줄 min_scale).
- '실측 후' 줄은 고객이 아직 모르는 것으로 보고(open) 할 확률만큼 섞는다.
- 범위는 저장하지 않고 볼 때마다 계산한다. 입력이 같으면 늘 같은 값이다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.calc.common import COUNTED
from app.calc.price_range import (
    LADDER,
    CondState,
    Precision,
    PriceRange,
    RangeInput,
    price_range,
    price_range_total,
)
from app.calc.spaces import SpacePick
from app.project.schemas import ProjectOut
from app.quote.schemas import RangeOut, RangePartOut
from app.refprice.market import RANGE

# 공정 → 고른 공간 몫이 곱해지는 수량 근거(calc.price_range.QTY_DRIVER의 근거 이름)
SHARE_DRIVER = {"dobae": "area", "mokgong": "edge"}
# 조건 줄 수량을 다른 줄에서 가져오는 것: 방문 철거 개수 = 방문 줄 수량
COND_QTY_FROM = {("mokgong", "remove_door"): "door"}


class LineLike(Protocol):
    key: str
    qty: Decimal | None
    amount: int | None
    state: str


@dataclass(frozen=True)
class Known:
    """이 집 수량을 얼마나 아는지 (범위 입력에 쓰는 것만)"""

    precision: Precision  # 집 크기: band(평형대) · area(면적 입력)
    pick: SpacePick
    spaces: int  # 그 공정에 고른 공간 수


def size_precision(p: ProjectOut) -> Precision:
    return "area" if p.size.band is None and p.size.m2 is not None else "band"


def _precision(trade: str, base: Precision) -> dict[str, Precision]:
    if trade == "dobae":
        return {"area": base}
    return {"edge": base, "flat": "guess", "door": "guess"}


def _share_sigma(trade: str, k: Known) -> dict[str, Decimal]:
    if k.pick.whole:
        return {}
    sig = RANGE.share_sigma.get(str(min(k.spaces, 3)), Decimal(0))
    return {SHARE_DRIVER[trade]: sig} if sig else {}


def _job_share(trade: str, pick: SpacePick) -> Decimal:
    return pick.paper if trade == "dobae" else pick.edge


def range_input(
    trade: str,
    grade: str | None,
    lines: Sequence[LineLike],
    k: Known,
    *,
    amounts: Mapping[str, int] | None = None,
    vendor_priced: bool = False,
    exempt: bool = False,
) -> RangeInput:
    """저장한 표준견적서 줄로 범위 입력을 만든다. amounts를 주면(가견적) 그 금액을 쓴다."""
    rules = RANGE.conds.get(trade, {})
    qty = {ln.key: ln.qty for ln in lines}
    conds: dict[str, CondState] = {}
    cond_qty: dict[str, Decimal] = {}
    for ln in lines:
        if ln.state != "after_visit" or ln.key not in rules:
            continue
        conds[ln.key] = "open"
        if rules[ln.key].per == "qty":
            q = ln.qty if ln.qty is not None else qty.get(COND_QTY_FROM.get((trade, ln.key), ""))
            if q is None:
                del conds[ln.key]  # 수량을 모르는 조건 줄은 범위에 넣지 않는다
                continue
            cond_qty[ln.key] = q
    if amounts is None:
        amounts = {
            ln.key: ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None
        }
    return RangeInput(
        trade=trade,
        amounts=dict(amounts),
        precision=_precision(trade, k.precision),
        grade=grade,
        conds=conds,
        cond_qty=cond_qty,
        vendor_priced=vendor_priced,
        exempt=exempt,
        share_sigma=_share_sigma(trade, k),
        job_share=_job_share(trade, k.pick),
    )


def out(r: PriceRange, k: Known | None, *, whole: bool | None = None) -> RangeOut:
    return RangeOut(
        version=r.version,
        low=r.low,
        mid=r.mid,
        high=r.high,
        extra_max=r.extra_max,
        precision=k.precision if k else "band",
        whole=k.pick.whole if k else bool(whole),
        parts=[
            RangePartOut(
                driver=p.driver,
                share=p.share,
                better=p.better,
                low_if=p.low_if,
                high_if=p.high_if,
                low_if_no=p.low_if_no,
                high_if_no=p.high_if_no,
            )
            for p in r.parts
        ],
        notes=list(r.notes),
    )


def trade_range(inp: RangeInput, k: Known, *, explain: bool = True) -> RangeOut:
    return out(price_range(inp, RANGE, explain=explain), k)


def total_range(inps: list[RangeInput], ks: list[Known]) -> RangeOut:
    r = price_range_total(inps, RANGE)
    o = out(r, None, whole=all(k.pick.whole for k in ks))
    return o.model_copy(update={"precision": min((k.precision for k in ks), key=LADDER.index)})
