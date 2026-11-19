"""계산 엔진 값으로 쓰는 답 문장 · 상자 (기간 · 비용 · 업체 추천). LLM 없음, 숫자를 새로 만들지 않는다.

- 숫자는 모두 ProjectFacts(이 집 표준견적서 · 예상 공정표 · 가견적 · 추천 업체)나
  GeneralFacts(질문 평수 · 예시 평수 · 방문 1개를 chat.tools가 계산 엔진으로 센 값)에서 옮긴다.
- 문장에 쓴 숫자가 출력 검사(check.section)를 지나도록, 같은 숫자를 담은 글(allowed · calc_text)을 함께 돌려준다.
- 금액 글은 만 원 반올림('약 286만 원')만 쓰고, 정확한 값은 계산 상자에 둔다.
- 더하기 · 빼기 같은 새 계산을 하지 않는다(목공 + 도배 합친 기간은 공정표가 있을 때만 공정표 값으로).
"""

from dataclasses import dataclass, field

from app.agent.v3.schemas import (
    CalcBox,
    Choice,
    GeneralFacts,
    ProjectFacts,
    SizeCalcFact,
    UiCard,
)
from app.agent.v3.templates import josa, md


@dataclass
class Lines:
    lines: list[str] = field(default_factory=list)
    boxes: list[CalcBox] = field(default_factory=list)
    cards: list[UiCard] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)  # 검사에 넘길 숫자 글(계산 엔진 값)

    @property
    def calc_text(self) -> str:
        return " ".join(self.numbers)

    def add(self, other: "Lines") -> None:
        self.lines += other.lines
        self.boxes += other.boxes
        self.cards += other.cards
        self.numbers += other.numbers


def man(won: int) -> str:
    """만 원 반올림 글: 2,859,232 → '286만 원' (검사는 만 원 반올림 값도 허용해요)"""
    return f"{round(won / 10_000):,}만 원"


def days(v: float) -> str:
    """반나절 단위 일수 글: 2.0 → '2일', 2.5 → '2.5일'"""
    return f"{int(v)}일" if float(v).is_integer() else f"{v:g}일"


def _size_numbers(x: SizeCalcFact) -> list[str]:
    return [
        x.label, str(x.dobae_total), str(x.dobae_total_economy), days(x.dobae_days),
        days(x.dobae_days_occupied), str(x.mokgong_total or ""), days(x.mokgong_days or 0),
        str(x.rooms),
    ]  # fmt: skip


def _area_far(facts: ProjectFacts | None, x: SizeCalcFact | None) -> bool:
    """질문 평수가 이 집 면적과 10% 넘게 다른가(다르면 질문 평수로도 센다)."""
    if x is None or facts is None or not facts.area_m2:
        return x is not None
    same_basis = (facts.area_basis or "supply") == x.area_basis
    return not same_basis or abs(x.area_m2 - facts.area_m2) / facts.area_m2 > 0.10


# ---- 기간 ----
def period(trade: str, facts: ProjectFacts | None, general: GeneralFacts | None) -> Lines:
    """'며칠 걸려요'. 이 집 공정표 → 질문 평수 → 예시 평수 순으로 숫자를 준다(도배 · 목공만)."""
    out = Lines()
    plan = facts.plan if facts else None
    if plan is not None:
        out.lines.append(
            f"이 집 예상 공정표로는 {md(plan.start)} ~ {md(plan.end)}, 일하는 날 {plan.work_days}일이에요."
        )
        out.numbers += [md(plan.start), md(plan.end), f"{plan.work_days}일"]
        for b in plan.blocks:
            if b.trade == trade or (trade == "common" and b.trade in ("dobae", "mokgong")):
                out.lines.append(f"{josa(b.ko, '은', '는')} {md(b.start)} ~ {md(b.end)}에 해요.")
                out.numbers += [md(b.start), md(b.end)]
        out.boxes.append(
            CalcBox(
                label="예상 공정표",
                ref="plan.range",
                qty=plan.work_days,
                unit="일",
                note=f"{md(plan.start)} ~ {md(plan.end)}",
            )
        )
    g = general
    asked = g.asked if g else None
    if g is not None and (plan is None or _area_far(facts, asked)):
        if asked is not None:
            out.add(_period_size(trade, asked, lead=plan is None))
        elif plan is None:
            out.add(_period_examples(trade, g))
    if plan is None and asked is None:
        out.lines.append("평수를 알려 주시면 그 집으로 다시 계산해 드려요.")
        out.cards.append(
            UiCard(kind="next_step", choices=[Choice(text="기본 정보 넣기", action="start")])
        )
    return out


def _period_size(trade: str, x: SizeCalcFact, lead: bool) -> Lines:
    out = Lines(numbers=_size_numbers(x))
    head = f"믿집 계산으로 {x.label}" if lead else f"물어보신 {x.label}이면 믿집 계산으로"
    if trade == "mokgong" and x.mokgong_days is not None:
        out.lines.append(f"{head} 몰딩 · 걸레받이 목공은 약 {days(x.mokgong_days)}이에요.")
        out.boxes.append(
            CalcBox(
                label=f"{x.label} 목공 기간",
                ref="general.asked.mokgong_days",
                qty=x.mokgong_days,
                unit="일",
                note="몰딩 · 걸레받이 · 빈집 기준",
            )
        )
        return out
    out.lines.append(
        f"{head} 도배는 빈집이면 약 {days(x.dobae_days)}, 살면서 하면 약 {days(x.dobae_days_occupied)}이에요."
    )
    out.lines.append(
        "벽 + 천장 전체를 반나절 단위로 센 작업 일수예요. 실측 뒤 업체가 정확히 정해요."
    )
    out.boxes.append(
        CalcBox(
            label=f"{x.label} 도배 기간",
            ref="general.asked.dobae_days",
            qty=x.dobae_days,
            unit="일",
            note=f"빈집 · 벽 + 천장 · 살면서 {days(x.dobae_days_occupied)}",
        )
    )
    return out


def _period_examples(trade: str, g: GeneralFacts) -> Lines:
    out = Lines()
    for x in g.examples:
        out.numbers += _size_numbers(x)
    if trade == "mokgong":
        parts = [f"{x.label} 약 {days(x.mokgong_days or 0)}" for x in g.examples]
        out.lines.append(
            f"믿집 계산으로 몰딩 · 걸레받이 목공은 {', '.join(parts)}이에요(빈집 기준)."
        )
    else:
        parts = [f"{x.label} 약 {days(x.dobae_days)}" for x in g.examples]
        out.lines.append(f"믿집 계산으로 도배(벽 + 천장 · 빈집)는 {', '.join(parts)}이에요.")
        occ = [f"{x.label} 약 {days(x.dobae_days_occupied)}" for x in g.examples]
        out.lines.append(f"살면서 하면 짐을 옮기며 해서 {', '.join(occ)}이에요.")
    for x in g.examples:
        q = x.mokgong_days if trade == "mokgong" else x.dobae_days
        out.boxes.append(
            CalcBox(
                label=f"{x.label} {'목공' if trade == 'mokgong' else '도배'} 기간",
                ref=f"general.examples.{x.label}",
                qty=q,
                unit="일",
                note="빈집 기준",
            )
        )
    return out


# ---- 비용 ----
def price(
    trade: str, facts: ProjectFacts | None, general: GeneralFacts | None, text: str = ""
) -> Lines:
    """'얼마예요'. 이 집 표준견적서 → 질문 평수 → 예시 평수. 방문 질문이면 방문 1개 값."""
    out = Lines()
    g = general
    if g is not None and trade in ("mokgong", "common") and _door_question(text) and g.door_set:
        out.lines.append(
            f"믿집 목공 계산으로 방문 1개는 문틀까지 바꾸면 약 {man(g.door_set)}, 문짝만 바꾸면 약 {man(g.door_leaf or 0)}이에요."
        )
        out.lines.append(
            "자재 · 시공 · 폐기물을 넣은 부가세 포함 참고 금액이에요. 문 크기 · 문턱은 실측 때 정해요."
        )
        out.numbers += [str(g.door_set), str(g.door_leaf or 0), "1개"]
        out.boxes += [
            CalcBox(
                label="방문 1개 · 문틀까지",
                ref="general.door_set",
                amount=g.door_set,
                note="부가세 포함",
            ),
            CalcBox(
                label="방문 1개 · 문짝만",
                ref="general.door_leaf",
                amount=g.door_leaf,
                note="부가세 포함",
            ),
        ]
        return out
    st = facts.standard if facts else None
    grade_q = _grade_question(text)
    if st is not None and grade_q and facts and facts.grade:
        ko = GRADE_KO[facts.grade]
        out.lines.append(
            f"이 집 표준견적서는 {ko}로 계산했고 합계는 부가세 포함 약 {man(st.total)}이에요."
        )
        out.lines.append(
            "실크 · 합지를 바꿔 보려면 표준견적서에서 '조건 바꾸기'를 눌러요. 바꾸면 바로 다시 계산해요."
        )
        out.numbers += [str(st.total), str(st.supply), str(st.vat)]
        out.boxes.append(
            CalcBox(
                label="표준견적서 합계",
                ref="standard.total",
                amount=st.total,
                note=f"부가세 포함 · {ko}",
            )
        )
    elif st is not None:
        out.lines.append(f"이 집 표준견적서 합계는 부가세 포함 약 {man(st.total)}이에요.")
        out.lines.append(
            "업체 견적이 아니라 공공 기준 단가로 계산한 참고 금액이에요. 실측 뒤 정하는 줄(철거 등)은 합계에 없어요."
        )
        out.numbers += [str(st.total), str(st.supply), str(st.vat)]
        out.boxes.append(
            CalcBox(
                label="표준견적서 합계", ref="standard.total", amount=st.total, note="부가세 포함"
            )
        )
    asked = g.asked if g else None
    if g is not None and (st is None or _area_far(facts, asked)):
        if asked is not None:
            out.add(_price_size(trade, asked, lead=st is None))
        elif st is None:
            out.add(_price_examples(trade, g, both=grade_q))
    if st is None:
        out.cards.append(
            UiCard(kind="next_step", choices=[Choice(text="내 집으로 계산하기", action="start")])
        )
    return out


DOOR = (
    "방문",
    "문짝",
    "문틀",
    "화장실 문",
    "욕실 문",
    "욕실문",
    "화장실문",
    "현관문",
    "문 교체",
    "도어",
)


def _door_question(text: str) -> bool:
    return any(w in (text or "") for w in DOOR)


def _price_size(trade: str, x: SizeCalcFact, lead: bool) -> Lines:
    out = Lines(numbers=_size_numbers(x))
    head = (
        f"믿집 표준견적서 계산으로 {x.label}" if lead else f"물어보신 {x.label}이면 믿집 계산으로"
    )
    if trade == "mokgong" and x.mokgong_total:
        out.lines.append(
            f"{head} 몰딩 · 걸레받이 목공은 부가세 포함 약 {man(x.mokgong_total)}이에요."
        )
        out.boxes.append(CalcBox(label=f"{x.label} 몰딩 · 걸레받이", ref="general.asked.mokgong_total",
                                 amount=x.mokgong_total, note="부가세 포함 · 빈집"))  # fmt: skip
        return out
    out.lines.append(
        f"{head} 전체 도배는 실크(기본형) 약 {man(x.dobae_total)}, 합지(저가형) 약 {man(x.dobae_total_economy)}이에요."
    )
    out.lines.append(
        "부가세 포함 · 빈집 · 벽 + 천장 기준이고, 철거처럼 실측 뒤 정하는 줄은 빠져 있어요."
    )
    out.boxes += [
        CalcBox(label=f"{x.label} 도배 · 실크(기본형)", ref="general.asked.dobae_total",
                amount=x.dobae_total, note="부가세 포함"),
        CalcBox(label=f"{x.label} 도배 · 합지(저가형)", ref="general.asked.dobae_total_economy",
                amount=x.dobae_total_economy, note="부가세 포함"),
    ]  # fmt: skip
    return out


GRADE_KO = {"economy": "합지(저가형)", "basic": "실크(기본형)"}
GRADE_WORDS = ("실크", "합지", "저가형", "기본형")


def _grade_question(text: str) -> bool:
    return any(w in (text or "") for w in GRADE_WORDS)


def _price_examples(trade: str, g: GeneralFacts, both: bool = False) -> Lines:
    out = Lines()
    for x in g.examples:
        out.numbers += _size_numbers(x)
    if trade == "mokgong":
        parts = [f"{x.label} 약 {man(x.mokgong_total or 0)}" for x in g.examples]
        out.lines.append(
            f"믿집 계산으로 몰딩 · 걸레받이 목공은 {', '.join(parts)}이에요(부가세 포함)."
        )
    else:
        parts = [f"{x.label} 약 {man(x.dobae_total)}" for x in g.examples]
        out.lines.append(
            f"믿집 표준견적서 계산으로 실크 전체 도배는 {', '.join(parts)}이에요(부가세 포함 · 빈집)."
        )
        if both:
            eco = [f"{x.label} 약 {man(x.dobae_total_economy)}" for x in g.examples]
            out.lines.append(f"합지로 하면 {', '.join(eco)}이에요.")
    out.lines.append("평수를 알려 주시거나 기본 정보를 넣으면 그 집으로 계산해 드려요.")
    return out


# ---- 업체 추천 (코드가 고른 업체) ----
CRITERIA = (
    "고른 기준: 이 구에서 일하고 단가를 확인한 업체 중 별점(리뷰 수 반영) · 믿집 공사 수 · "
    "가견적(표준견적서 대비) 점수 순이에요. 광고로 순서를 바꾸지 않아요."
)


def vendors(facts: ProjectFacts | None) -> Lines:
    out = Lines()
    picks = facts.vendors if facts else []
    if not picks:
        if facts is None:
            out.lines.append("기본 정보를 넣으면 이 집 지역과 공사에 맞는 업체 3곳을 골라 드려요.")
            out.cards.append(
                UiCard(kind="next_step", choices=[Choice(text="기본 정보 넣기", action="start")])
            )
        else:
            out.lines.append(
                "아직 이 집 조건에 맞춰 단가를 확인한 업체가 없어요. 업체 고르기에서 새로 들어오는 업체를 볼 수 있어요."
            )
            out.cards.append(
                UiCard(kind="next_step", choices=[Choice(text="업체 보기", action="vendors")])
            )
        return out
    out.lines.append(
        f"이 집 조건에 맞는 업체 {len(picks)}곳을 골라 봤어요. 고르는 건 고객님이에요."
    )
    out.lines.append(
        f"고른 기준으로 점수가 가장 높은 곳은 {josa(picks[0].name, '이에요', '예요')}."
    )
    for p in picks:
        out.numbers += [p.name, *p.reasons, str(p.estimate_total or "")]
    out.cards.append(UiCard(kind="vendor_reco", title="추천 업체", text=CRITERIA, vendors=list(picks),
                            choices=[Choice(text="업체 모두 보기", action="vendors")]))  # fmt: skip
    return out


# ---- 목공 + 도배 같이 (오케스트레이터가 부름) ----
def pair_period(facts: ProjectFacts | None, general: GeneralFacts | None) -> Lines:
    """'도배랑 몰딩 같이 하면 며칠'. 공정표가 있으면 공정표 값만, 없으면 평수별 목공 · 도배 일수를 따로(더하지 않음)."""
    out = Lines()
    plan = facts.plan if facts else None
    if plan is not None:
        out.lines.append(
            f"이 집 예상 공정표로는 {md(plan.start)} ~ {md(plan.end)}, 일하는 날 {plan.work_days}일이에요."
        )
        out.numbers += [md(plan.start), md(plan.end), f"{plan.work_days}일"]
        for b in plan.blocks:
            out.lines.append(f"{josa(b.ko, '은', '는')} {md(b.start)} ~ {md(b.end)}에 해요.")
            out.numbers += [md(b.start), md(b.end)]
        out.boxes.append(
            CalcBox(
                label="예상 공정표",
                ref="plan.range",
                qty=plan.work_days,
                unit="일",
                note=f"{md(plan.start)} ~ {md(plan.end)}",
            )
        )
        return out
    if general is None:
        return out
    sizes = [general.asked] if general.asked else general.examples
    for x in sizes:
        out.numbers += _size_numbers(x)
    parts = [
        f"{x.label} 목공 약 {days(x.mokgong_days or 0)} · 도배 약 {days(x.dobae_days)}"
        for x in sizes
    ]
    out.lines.append(f"믿집 계산으로 몰딩 · 걸레받이 목공과 도배는 {', '.join(parts)}이에요(빈집).")
    out.lines.append(
        "목공을 먼저 끝내고 도배를 해요. 기본 정보를 넣으면 두 공정을 이어 붙인 예상 공정표 날짜로 잡아 드려요."
    )
    out.cards.append(
        UiCard(kind="next_step", choices=[Choice(text="기본 정보 넣기", action="start")])
    )
    return out
