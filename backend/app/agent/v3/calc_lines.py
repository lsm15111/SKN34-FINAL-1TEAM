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
    table: list[list[str]] = field(default_factory=list)  # 평수별 값 같은 2열 표(첫 표만 써요)

    @property
    def calc_text(self) -> str:
        return " ".join(self.numbers)

    def add(self, other: "Lines") -> None:
        self.lines += other.lines
        self.boxes += other.boxes
        self.cards += other.cards
        self.numbers += other.numbers
        if other.table and not self.table:
            self.table = other.table


def man(won: int) -> str:
    """만 원 반올림 글: 2,859,232 → '286만 원' (검사는 만 원 반올림 값도 허용해요)"""
    return f"{round(won / 10_000):,}만 원"


def days(v: float) -> str:
    """반나절 단위 일수 글: 2.0 → '2일', 2.5 → '2.5일'"""
    return f"{int(v)}일" if float(v).is_integer() else f"{v:g}일"


def span_days(vals: list[float]) -> str:
    """여러 평수 일수의 범위 글: [2, 2.5, 3] → '2~3일', 모두 같으면 '2일'"""
    lo, hi = min(vals), max(vals)
    return days(lo) if lo == hi else f"{days(lo)[:-1]}~{days(hi)}"


def span_man(vals: list[int]) -> str:
    """여러 평수 금액의 범위 글(만 원 반올림): '224만~373만 원'"""
    lo, hi = man(min(vals)), man(max(vals))
    return lo if lo == hi else f"{lo[:-2]}~{hi}"


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


# 계산 엔진 도배 일수는 바르기 · 마감(살면서면 짐 정리)만 세요. 기존 벽지 철거는 실측 후 줄이에요(calc.dobae)
REMOVAL = "기존 벽지를 뜯는 시간은 들어 있지 않아요. 실측 뒤 업체가 정해요."


# ---- 기간 ----
def period(trade: str, facts: ProjectFacts | None, general: GeneralFacts | None) -> Lines:
    """'며칠 걸려요'. 이 집 공정표 · 질문 평수 · 예시 평수로 숫자를 준다(도배 · 목공만).
    질문 평수가 이 집과 다르면 질문 평수 줄을 먼저, 이 집 공정표는 '참고로'로 뒤에 둬요."""
    out = Lines()
    plan = facts.plan if facts else None
    g = general
    asked = g.asked if g else None
    far = asked is not None and (plan is None or _area_far(facts, asked))
    mine = Lines()  # 이 집 예상 공정표
    missing = (
        plan is not None
        and trade in ("dobae", "mokgong")
        and bool(plan.blocks)
        and all(b.trade != trade for b in plan.blocks)
    )
    if missing:  # 공사에 없는 공종: 공정표 줄 대신 '들어 있지 않아요' + 이 집 크기로 센 일수
        mine = _period_missing(trade, g.here if g else None)
    elif plan is not None:
        pre = "참고로 " if far else ""
        mine.lines.append(
            f"{pre}이 집 예상 공정표로는 {md(plan.start)} ~ {md(plan.end)}, 일하는 날 {plan.work_days}일이에요."
        )
        mine.numbers += [md(plan.start), md(plan.end), f"{plan.work_days}일"]
        for b in plan.blocks:
            if b.trade == trade or (trade == "common" and b.trade in ("dobae", "mokgong")):
                mine.lines.append(f"{josa(b.ko, '은', '는')} {md(b.start)} ~ {md(b.end)}에 해요.")
                mine.numbers += [md(b.start), md(b.end)]
        mine.boxes.append(
            CalcBox(
                label="예상 공정표",
                ref="plan.range",
                qty=plan.work_days,
                unit="일",
                note=f"{md(plan.start)} ~ {md(plan.end)}",
            )
        )
        mine.cards.append(
            UiCard(kind="next_step", choices=[Choice(text="공정표 보기", action="plan")])
        )
    ask = Lines()  # 질문 평수 · 예시 평수
    if g is not None and far:
        ask.add(_period_size(trade, asked, lead=plan is None))  # type: ignore[arg-type]
        if g.start is not None:
            ask.add(_period_dates(trade, g))
    elif g is not None and plan is None:
        ask.add(_period_examples(trade, g))  # 시작 날짜가 있으면 표에 끝나는 날까지
    for part in (ask, mine) if far else (mine, ask):
        out.add(part)
    if out.lines and trade in ("dobae", "common") and (plan is None or plan.kind == "expected"):
        out.lines.append(REMOVAL)  # 한 번만(계산 엔진 일수는 바르기 · 마감만)
    if plan is None and asked is None:
        out.lines.append(
            "평수를 알려 주시면 그 집으로 다시 계산해 드려요."
            if g is not None and g.start is not None
            else "평수와 시작 날짜를 알려 주시면 끝나는 날짜까지 계산해 드려요."
        )
        out.cards.append(
            UiCard(kind="next_step", choices=[Choice(text="기본 정보 넣기", action="start")])
        )
    return out


def _period_dates(trade: str, g: GeneralFacts) -> Lines:
    """질문의 시작 날짜부터 일하는 날에 놓은 날짜(계산 엔진 schedule.span 결과, tools가 셈)."""
    out = Lines()
    start = g.start
    key = "mokgong_dates" if trade == "mokgong" else "dobae_dates"
    ko = "목공" if trade == "mokgong" else "도배"
    rows = [g.asked] if g.asked is not None else list(g.examples)
    rows = [x for x in rows if getattr(x, key) is not None]
    if start is None or not rows:
        return out
    if len(rows) == 1:
        d0, d1 = getattr(rows[0], key)
        out.lines.append(
            f"{md(start)}에 시작하면 {rows[0].label} {josa(ko, '은', '는')} {md(d0)} ~ {md(d1)}이에요(빈집 · 주말 · 공휴일 빼고)."
        )
        out.numbers += [md(d0), md(d1)]
    else:
        parts = [f"{x.label} {md(getattr(x, key)[1])}" for x in rows]
        out.lines.append(
            f"{md(start)}에 시작하면 {josa(ko, '은', '는')} {', '.join(parts)}에 끝나요(빈집 · 주말 · 공휴일 빼고)."
        )
        out.numbers += [md(getattr(x, key)[1]) for x in rows]
    out.numbers.append(md(start))
    return out


def _period_missing(trade: str, here: SizeCalcFact | None) -> Lines:
    """공사에 없는 공종의 기간: 공정표에 날짜가 없다고 먼저 말하고, 이 집 크기로 센 일수를 붙여요."""
    ko = "목공" if trade == "mokgong" else "도배"
    out = Lines(
        lines=[f"이 공사에는 {josa(ko, '이', '가')} 들어 있지 않아서 공정표에 {ko} 날짜는 없어요."]
    )
    if here is None:
        return out
    if trade == "mokgong" and here.mokgong_days is not None:
        out.lines.append(
            f"이 집 크기로 세면 몰딩 · 걸레받이 목공은 약 {days(here.mokgong_days)}이에요."
        )
        out.numbers.append(days(here.mokgong_days))
        out.boxes.append(
            CalcBox(label="이 집 목공 기간", ref="general.here.mokgong_days", qty=here.mokgong_days,
                    unit="일", note="몰딩 · 걸레받이 · 빈집 기준")
        )  # fmt: skip
    elif trade == "dobae":
        out.lines.append(
            f"이 집 크기로 세면 도배는 빈집이면 약 {days(here.dobae_days)}, "
            f"살면서 하면 약 {days(here.dobae_days_occupied)}이에요."
        )
        out.numbers += [days(here.dobae_days), days(here.dobae_days_occupied)]
        out.boxes.append(
            CalcBox(label="이 집 도배 기간", ref="general.here.dobae_days", qty=here.dobae_days,
                    unit="일", note=f"빈집 · 벽 + 천장 · 살면서 {days(here.dobae_days_occupied)}")
        )  # fmt: skip
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
    out.lines.append("벽 + 천장 전체를 반나절 단위로 센 바르는 일수예요.")
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
    """평수를 모를 때: 결론 한 줄(범위) + 평수별 2열 표. 시작 날짜가 있으면 표에 끝나는 날을 넣어요."""
    out = Lines()
    for x in g.examples:
        out.numbers += _size_numbers(x)
    mk = trade == "mokgong"
    ko = "몰딩 · 걸레받이 목공" if mk else "도배(벽 + 천장)"
    vals = [(x.mokgong_days or 0) if mk else x.dobae_days for x in g.examples]
    if g.start is not None:
        key = "mokgong_dates" if mk else "dobae_dates"
        rows = [x for x in g.examples if getattr(x, key)]
        out.lines.append(
            f"{md(g.start)}에 시작하면 빈집 {ko}는 평수에 따라 이렇게 끝나요(주말 · 공휴일 빼고)."
        )
        for x, v in zip(g.examples, vals, strict=True):
            if x in rows:
                d0, d1 = getattr(x, key)
                out.table.append([x.label, f"{md(d0)} ~ {md(d1)} · 약 {days(v)}"])
                out.numbers += [md(d0), md(d1)]
        out.numbers.append(md(g.start))
        if not mk:
            out.lines.append("살면서 하면 짐을 옮기며 해서 더 걸려요.")
    else:
        out.lines.append(f"믿집 계산으로 빈집 {ko}는 평수에 따라 약 {span_days(vals)}이에요.")
        for x, v in zip(g.examples, vals, strict=True):
            cell = (
                f"약 {days(v)}"
                if mk
                else f"빈집 약 {days(v)} · 살면서 약 {days(x.dobae_days_occupied)}"
            )
            out.table.append([x.label, cell])
        out.numbers.append(span_days(vals))
    for x, v in zip(g.examples, vals, strict=True):
        out.boxes.append(
            CalcBox(
                label=f"{x.label} {'목공' if mk else '도배'} 기간",
                ref=f"general.examples.{x.label}",
                qty=v,
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
    asked = g.asked if g else None
    far = asked is not None and (st is None or _area_far(facts, asked))
    pre = "참고로 " if far else ""
    mine = Lines()  # 이 집 표준견적서
    own = st.trades.get(trade) if st is not None and len(st.trades) > 1 else None
    if st is not None and grade_q and facts and facts.grade:
        ko = GRADE_KO[facts.grade]
        mine.lines.append(
            f"{pre}이 집 표준견적서는 {ko}로 계산했고 합계는 부가세 포함 약 {man(st.total)}이에요."
        )
        mine.lines.append(
            "실크 · 합지를 바꿔 보려면 표준견적서에서 '조건 바꾸기'를 눌러요. 바꾸면 바로 다시 계산해요."
        )
        mine.numbers += [str(st.total), str(st.supply), str(st.vat)]
        mine.boxes.append(
            CalcBox(
                label="표준견적서 합계",
                ref="standard.total",
                amount=st.total,
                note=f"부가세 포함 · {ko}",
            )
        )
    elif st is not None:
        if own is not None:  # 도배 질문엔 도배 합계(공정별 합계는 계산 엔진 값)
            ko = BY_TRADE_KO.get(trade, "")
            mine.lines.append(
                f"{pre}이 집 표준견적서의 {ko} 합계는 부가세 포함 약 {man(own)}이에요(전체 약 {man(st.total)})."
            )
            mine.numbers += [str(own)]
        else:
            mine.lines.append(f"{pre}이 집 표준견적서 합계는 부가세 포함 약 {man(st.total)}이에요.")
        if not far:  # 빠진 줄 안내는 한 번만(질문 평수 줄이 따로 말해요)
            mine.lines.append(
                "업체 견적이 아니라 공공 기준 단가로 계산한 참고 금액이에요. 실측 뒤 정하는 줄(철거 등)은 합계에 없어요."
            )
        mine.numbers += [str(st.total), str(st.supply), str(st.vat)]
        mine.boxes.append(
            CalcBox(
                label="표준견적서 합계", ref="standard.total", amount=st.total, note="부가세 포함"
            )
        )
    ask = Lines()
    if g is not None and far:
        ask.add(_price_size(trade, asked, lead=st is None))  # type: ignore[arg-type]
    elif g is not None and st is None:
        ask.add(_price_examples(trade, g))
    for part in (ask, mine) if far else (mine, ask):
        out.add(part)
    if st is None:
        out.cards.append(
            UiCard(kind="next_step", choices=[Choice(text="내 집으로 계산하기", action="start")])
        )
    return out


BY_TRADE_KO = {"dobae": "도배", "mokgong": "목공"}


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


def _price_examples(trade: str, g: GeneralFacts) -> Lines:
    """평수를 모를 때: 결론 한 줄(범위) + 평수별 2열 표(도배는 실크 · 합지 둘 다)."""
    out = Lines()
    for x in g.examples:
        out.numbers += _size_numbers(x)
    if trade == "mokgong":
        vals = [x.mokgong_total or 0 for x in g.examples]
        out.lines.append(
            f"믿집 계산으로 몰딩 · 걸레받이 목공은 평수에 따라 약 {span_man(vals)}이에요(부가세 포함)."
        )
        out.table = [[x.label, f"약 {man(v)}"] for x, v in zip(g.examples, vals, strict=True)]
        out.numbers.append(span_man(vals))
    else:
        vals = [x.dobae_total for x in g.examples]
        out.lines.append(
            f"믿집 표준견적서 계산으로 실크 전체 도배는 평수에 따라 약 {span_man(vals)}이에요(부가세 포함 · 빈집)."
        )
        out.table = [
            [x.label, f"실크 약 {man(x.dobae_total)} · 합지 약 {man(x.dobae_total_economy)}"]
            for x in g.examples
        ]
        out.numbers.append(span_man(vals))
    out.lines.append("평수를 알려 주시거나 기본 정보를 넣으면 그 집으로 계산해 드려요.")
    return out


# ---- 업체 추천 (코드가 고른 업체) ----
def criteria() -> str:
    """화면에 적는 고른 기준. 무게는 계산 엔진 상수에서 바로 읽어, 보인 기준과 실제 계산이 늘 같아요(전자상거래법 제21조).
    가견적 점수는 같은 일 줄 금액으로 세지만, 표준견적서와 견주는 말은 쓰지 않아요(사용자 결정 2026-11-21)."""
    from app.calc import vendor_pick as vp

    return (
        f"고른 기준: 이 구(3곳보다 적으면 가까운 구까지)에서 가견적이 있는 업체를 별점(리뷰 수 반영) {vp.W_RATING:.0%} · "
        f"믿집 공사 수 {vp.W_DONE:.0%} · 가견적(같은 일 금액이 낮을수록 높게) {vp.W_PRICE:.0%}로 센 점수에 이 구 업체 덤을 더해 높은 순으로 골라요. "
        "광고로 순서를 바꾸지 않아요. 가견적은 부가세 포함이고, 철거처럼 실측 뒤 정하는 비용은 빠져 있어요. 계약은 업체와 직접 해요."
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
    out.cards.append(UiCard(kind="vendor_reco", title="추천 업체", text=criteria(), vendors=list(picks),
                            choices=[Choice(text="업체 모두 보기", action="vendors")]))  # fmt: skip
    return out


# ---- 목공 + 도배 같이 (오케스트레이터가 부름) ----
PAIR_ORDER = "목공을 먼저 끝내고 도배를 해요."


def _pair_dates(start, rows: list[SizeCalcFact]) -> Lines:
    """시작 날짜부터 목공 다음 도배를 이어 놓은 날짜(tools가 schedule.lay_out으로 셈). 평수 하나면 문장, 여럿이면 표."""
    out = Lines(numbers=[md(start)])
    for x in rows:
        p = x.pair
        out.numbers += [md(b.start) for b in p.blocks] + [md(b.end) for b in p.blocks]  # type: ignore[union-attr]
        out.numbers += [md(p.end), f"{p.work_days}일"]  # type: ignore[union-attr]
    tail = "(빈집 · 주말 · 공휴일 빼고)"
    if len(rows) == 1:
        x, p = rows[0], rows[0].pair
        parts = ", ".join(f"{josa(b.ko, '은', '는')} {md(b.start)} ~ {md(b.end)}" for b in p.blocks)  # type: ignore[union-attr]
        out.lines.append(
            f"믿집 계산으로 {josa(x.label, '을', '를')} {md(start)}에 시작하면 {parts}이에요{tail}."
        )
        if p.after:  # type: ignore[union-attr]
            out.lines.append(f"{p.after}까지 넣으면 {md(p.end)}에 끝나요.")  # type: ignore[union-attr]
        note = f"{md(p.start)} ~ {md(p.end)}" + (f" · {p.after} 포함" if p.after else "")  # type: ignore[union-attr]
        out.boxes.append(
            CalcBox(label=f"{x.label} 목공 · 도배 일정", ref="general.asked.pair",
                    qty=p.work_days, unit="일", note=note)  # type: ignore[union-attr]
        )  # fmt: skip
        return out
    out.lines.append(f"믿집 계산으로 {md(start)}에 시작하면 목공 · 도배를 이 날짜에 해요{tail}.")
    out.table = [
        [x.label, " · ".join([*(f"{b.ko} {md(b.start)} ~ {md(b.end)}" for b in x.pair.blocks),  # type: ignore[union-attr]
                              *([f"끝 {md(x.pair.end)}"] if x.pair.after else [])])]  # type: ignore[union-attr]
        for x in rows
    ]  # fmt: skip
    if any(x.pair.after for x in rows):  # type: ignore[union-attr]
        out.lines.append(f"끝 날짜는 {rows[0].pair.after}까지 넣은 날이에요.")  # type: ignore[union-attr]
    return out


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
        have = {b.trade for b in plan.blocks}
        for trade in (
            "mokgong",
            "dobae",
        ):  # 공사에 없는 공종은 없다고 말하고 이 집 크기로 센 일수를 붙여요
            if have and trade not in have:
                out.add(_period_missing(trade, general.here if general else None))
        return out
    if general is None:
        return out
    sizes = [general.asked] if general.asked else general.examples
    for x in sizes:
        out.numbers += _size_numbers(x)
    dated = [x for x in sizes if x.pair is not None and x.pair.blocks]
    if general.start is not None and dated:
        out.add(_pair_dates(general.start, dated))  # 시작 날짜를 알면 끝나는 날까지(계산 엔진 일정)
    else:
        out.lines.append("믿집 계산으로 몰딩 · 걸레받이 목공과 도배는 빈집 기준 이만큼 걸려요.")
        out.table = [
            [x.label, f"목공 약 {days(x.mokgong_days or 0)} · 도배 약 {days(x.dobae_days)}"]
            for x in sizes
        ]
    out.lines.append(
        f"{PAIR_ORDER} 기본 정보를 넣으면 두 공정을 이어 붙인 예상 공정표 날짜로 잡아 드려요."
    )
    out.cards.append(
        UiCard(kind="next_step", choices=[Choice(text="기본 정보 넣기", action="start")])
    )
    return out
