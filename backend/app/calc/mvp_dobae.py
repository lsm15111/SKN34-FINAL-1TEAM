"""MVP 도배: 팀 도배 계산(dobae.quote)과 같은 공공 기준에 도면 면적과 줄마다 수량 풀이를 더한다.

단가 · 가정값은 팀 DobaePrices를 그대로 쓴다. 도면(PlanQty)이 있으면 벽 · 천장 면적을 도면에서 읽고,
없으면 팀 계산과 같이 평형에서 어림한다. 프리미엄 등급은 벽지가 실크라 basic 단가로 계산한다.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.calc.common import (
    BASIS_LABEL,
    COUNTED,
    AreaBasis,
    Line,
    Step,
    half_days,
    half_up,
    m2,
    won,
)
from app.calc.dobae import GRADE_PAPER, DobaePrices
from app.calc.dobae import Grade as PaperGrade
from app.calc.mvp_common import Grade, MvpLine, PriceBasis, num, team_basis
from app.calc.plan_qty import PlanQty


@dataclass(frozen=True)
class MvpDobaeInput:
    area_m2: Decimal
    grade: Grade
    area_basis: AreaBasis = "supply"
    include_ceiling: bool = True
    occupied: bool = False
    balcony_ext: bool = False  # 도면이 있으면 도면 면적에 이미 들어 있어 쓰지 않는다
    plan: PlanQty | None = None
    plan_name: str = ""


@dataclass(frozen=True)
class MvpDobaeQuote:
    version: str
    paper_grade: PaperGrade  # 실제 계산에 쓴 벽지 (economy = 합지, basic = 실크)
    paper_m2: Decimal
    wall_m2: Decimal
    ceiling_m2: Decimal
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def paper_grade(grade: Grade) -> PaperGrade:
    return "economy" if grade == "economy" else "basic"


def quote(inp: MvpDobaeInput, p: DobaePrices) -> MvpDobaeQuote:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    g, src, plan = paper_grade(inp.grade), p.sources, inp.plan
    f = p.area_factor[inp.area_basis]
    gross = inp.area_m2 * f
    if inp.balcony_ext:
        gross *= p.balcony_factor
    ceiling = m2(gross * p.ceiling_share)
    wall = m2(gross) - ceiling
    if plan:
        wall, ceiling = plan.wall_m2, plan.ceiling_m2
    ceil_used = ceiling if inp.include_ceiling else Decimal(0)
    paper_area = wall + ceil_used
    paper_qty = m2(paper_area * p.paper_ratio)
    primer_qty = m2(wall * p.primer_wall_ratio + ceil_used * p.primer_ceiling_ratio)
    wall_amt, ceil_amt = won(wall * p.labor_wall), won(ceiling * p.labor_ceiling)
    lines: list[Line] = []

    def add(key, name, qty, unit, price, amount, state, s, basis: PriceBasis = "public", calc=""):
        lines.append(
            MvpLine(key, name, qty, unit, price, amount, state, s, team_basis(basis), basis, calc)
        )

    if plan:
        wall_calc = f"도면 {inp.plan_name}에서 방마다 잰 벽 면적(문 · 창 뺌)"
        ceil_calc = f"도면 {inp.plan_name}에서 잰 천장 면적"
    else:
        where = "공급" if inp.area_basis == "supply" else "전용"
        bal = f" × {num(p.balcony_factor)}" if inp.balcony_ext else ""
        wall_calc = (
            f"벽 면적 = 도배 면적 {num(m2(gross))}㎡ − 천장 {num(ceiling)}㎡ "
            f"(도배 면적 = {where} {num(inp.area_m2)}㎡ × {num(f)}{bal})"
        )
        ceil_calc = f"천장 = 도배 면적 × {num(p.ceiling_share)}"
    add(
        "wall",
        "벽 도배 시공 (풀 포함)",
        wall,
        "㎡",
        p.labor_wall,
        wall_amt,
        "included",
        src["wall"],
        calc=wall_calc,
    )
    add(
        "ceiling",
        "천장 도배 시공 (풀 포함)",
        ceiling,
        "㎡",
        p.labor_ceiling,
        ceil_amt if inp.include_ceiling else None,
        "included" if inp.include_ceiling else "excluded",
        src["ceiling"],
        calc=ceil_calc,
    )
    add(
        "paper",
        f"도배지 ({GRADE_PAPER[g]})",
        paper_qty,
        "㎡",
        p.paper[g],
        won(paper_qty * p.paper[g]),
        "included",
        src[f"paper_{g}"],
        "assumed" if g == "economy" else "public",
        f"바를 면적 {num(paper_area)}㎡ × 소요량 {num(p.paper_ratio)}",
    )
    add(
        "primer",
        "초배지",
        primer_qty,
        "㎡",
        p.primer,
        won(primer_qty * p.primer),
        "included",
        src["primer"],
        calc=f"벽 {num(wall)}㎡ × {num(p.primer_wall_ratio)} + "
        f"천장 {num(ceil_used)}㎡ × {num(p.primer_ceiling_ratio)}",
    )
    if inp.occupied:
        labor = wall_amt + (ceil_amt if inp.include_ceiling else 0)
        extra = won(labor * p.labor_ratio * (1 / p.occupied_output - 1))
        calc = (
            f"시공 노무비 {labor:,}원 × 노무 비율 {num(p.labor_ratio)} × "
            f"(1 ÷ {num(p.occupied_output)} − 1)"
        )
        add(
            "occupied",
            "짐 있는 집 작업 할증",
            None,
            "식",
            None,
            extra,
            "included",
            src["occupied"],
            calc=calc,
        )
    add(
        "removal",
        "기존 벽지 철거",
        paper_area,
        "㎡",
        p.removal,
        won(paper_area * p.removal),
        "after_visit",
        src["removal"],
        calc=f"벽지 떼내기 ㎡당 {p.removal:,}원",
    )
    add("waste", "폐기물 처리", None, "식", None, None, "after_visit", src["none"], "none")
    if inp.occupied:
        add("moving", "짐 이동 · 보양", None, "식", None, None, "after_visit", src["none"], "none")

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * p.vat_rate)
    md = wall * p.md_wall + ceil_used * p.md_ceiling
    if inp.occupied:
        md = md / p.occupied_output
    man_days = half_up(md)
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    name = "벽지 바르기 (벽 · 천장)" if inp.include_ceiling else "벽지 바르기 (벽)"
    steps.append(Step("paper", name, half_days(man_days, p.crew)))
    steps.append(Step("finish", "마감 · 확인 · 청소", 1))

    if plan:
        notes = [
            (
                f"벽 · 천장 면적은 도면 {inp.plan_name}에서 방마다 재서 더했어요(문 · 창 뺌). "
                "실측 전 어림이라 실측 때 다시 재요."
            )
        ]
    else:
        notes = [
            (
                f"도배 면적은 {BASIS_LABEL[inp.area_basis]} × {num(f)}로 추정했어요. "
                "실측 때 방마다 다시 재요."
            ),
            f"천장은 도배 면적의 {int(p.ceiling_share * 100)}%로 잡았어요.",
        ]
    notes.append(f"하루 도배공 {p.crew}명이 들어가는 것으로 기간을 잡았어요.")
    if inp.balcony_ext and not plan:
        notes.append(f"발코니 확장은 도배 면적을 {num(p.balcony_factor)}배로 잡았어요.")

    return MvpDobaeQuote(
        version=p.version,
        paper_grade=g,
        paper_m2=paper_area,
        wall_m2=wall,
        ceiling_m2=ceiling,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=man_days,
        steps=steps,
        days=Decimal(sum(s.half_days for s in steps)) / 2,
        assumptions=notes,
    )
