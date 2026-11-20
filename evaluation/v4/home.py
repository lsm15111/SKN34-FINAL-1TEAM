"""v4 평가에 넣는 집 사실 한 벌. v2 · v3 답 파이프라인에 같은 집 조건을 넣어요(DB 없음).

맞춘 방법(2026-11-21)
- 전에는 두 평가가 다른 집을 넣었어요.
  - v2 답 평가(`evaluation/answer/run.py`): 32평 · 도배 + 목공 · 스탠다드(거주 칸 없음)
  - v3 평가(`evaluation/v3/coverage_check.FACTS`): 69.4㎡(공급, 약 21평)에 옛 계산 값을 손으로 적음
    (합계 1,974,069원 · 가견적 '표준 대비 6%'). 지금 계산 엔진으로 69.4㎡ 도배는 1,802,374원이라 값도 낡았어요
- 이제 집 조건(HOMES)만 한 곳에 적고, 금액 · 기간 · 날짜는 각 파이프라인이 자기 계산 엔진 길로 만들어요.
  - 두 쪽에 같게: 32평 = 공급 105.8㎡(32 × 3.3058, calc.common.pyeong_to_m2) · 도배 기본형(실크) + 목공(몰딩 · 걸레받이)
    · 빈집 · 오늘 2026-11-19
  - v2: V2QuoteIn(pyeong 32 · wallpaper + carpentry · tier · grade basic · vacant) + V2AskProfile(v2 화면이 보내는 글:
    빈집 · 도배, 목공 · 스탠다드 · quote 단계). 금액은 price_reference 도구가 service.quote로 세요
  - v3: ProjectFacts(105.8㎡ supply · dobae + mokgong · basic · vacant · 시작 희망 2027-01-04) + 표준견적서 · 예상 공정표를
    chat.tools와 같은 계산 함수(dobae.standard_v3 · mokgong.quote · schedule.lay_out)로 여기서 세요
  - 넣지 않는 것: 업체 추천 · 가견적 · 실측 초안(v2에는 넣을 칸이 없어요), 표준 대비 %(사용자 결정 2026-11-21)
- 남는 차이
  - 계산 길이 달라 같은 집도 금액이 달라요(32평 도배 + 목공 합계: v2 4,274,531원 · v3 4,072,840원, 2026-11-21 코드).
    그래서 판정의 '숫자 일치'는 그 답이 받은 계산 값(facts_given)과 견줘요
  - v2 채팅에는 공사 시작 희망일 · 공정표 칸이 없어요. run_compare --same-only면 v3에서도 빼요
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

KO_TRADE = {"dobae": "도배", "mokgong": "목공"}
KO_GRADE = {"basic": "기본형(실크)", "economy": "저가형(합지)"}
KO_MOK = {"molding": "몰딩", "base": "걸레받이", "door": "방문", "flatten": "평탄화"}


@dataclass(frozen=True)
class Home:
    id: str
    pyeong: int  # 공급 평
    area_m2: float  # 공급 ㎡ = pyeong × 3.3058(소수 한 자리)
    area_basis: str
    trades: tuple[str, ...]
    grade: str
    mokgong: tuple[str, ...]  # 목공 범위
    living: str  # vacant | living
    start_wish: date
    today: date

    def text(self, with_start: bool = True) -> str:
        """판정기 · 사람이 읽는 집 사실 한 줄(두 답이 같이 받은 조건)."""
        trades = " + ".join(
            f"도배 {KO_GRADE[self.grade]}"
            if t == "dobae"
            else f"목공({' · '.join(KO_MOK[x] for x in self.mokgong)})"
            for t in self.trades
        )
        parts = [
            f"{self.pyeong}평(공급 {self.area_m2}㎡) 아파트",
            trades,
            "빈집" if self.living == "vacant" else "살면서 공사",
        ]
        if with_start:
            parts.append(f"공사 시작 희망 {self.start_wish.isoformat()}")
        parts.append(f"오늘 {self.today.isoformat()}")
        return " · ".join(parts) + " (지역 · 예산은 정하지 않음)"


HOMES = {
    "H32": Home(
        id="H32",
        pyeong=32,
        area_m2=105.8,
        area_basis="supply",
        trades=("dobae", "mokgong"),
        grade="basic",
        mokgong=("molding", "base"),
        living="vacant",
        start_wish=date(2027, 1, 4),
        today=date(2026, 11, 19),
    )
}
NO_HOME = "집 정보 없음(프로젝트 없이 물음)"


# ---- v2 입력 ----
def v2_inputs(h: Home):
    """(V2QuoteIn, V2AskProfile). profile 글은 v2 화면(components/v2/ai/context.ts)이 보내는 값 그대로예요."""
    from app.v2 import schemas as v2

    cats = [{"dobae": "wallpaper", "mokgong": "carpentry"}[t] for t in h.trades]
    quote = v2.V2QuoteIn(
        pyeong=Decimal(h.pyeong), living=h.living, cats=cats, tier=h.grade, grade=h.grade
    )
    profile = v2.V2AskProfile(
        pyeong=Decimal(h.pyeong),
        living={"vacant": "빈집", "living": "살면서 공사"}[h.living],
        scope=", ".join(KO_TRADE[t] for t in h.trades),
        tier={"basic": "스탠다드", "economy": "베이직"}[h.grade],
        step="quote",
    )
    return quote, profile


def won(x) -> str:
    return f"{x:,}원" if isinstance(x, int) else "-"


def v2_digest(h: Home) -> str:
    """v2 LLM이 받는 계산 값: price_reference 도구 결과(service.quote)를 같은 숫자 그대로 줄글로."""
    from app.v2 import ask

    quote, _ = v2_inputs(h)
    ref = ask._price_reference(quote, h.today)
    if "error" in ref:
        return "(없음)"
    lines = [f"평형 {ref['평형']}평"]
    for t in ref["공정"]:
        lo, hi = t["보통범위_부가세별도"]
        why = " / ".join(f"{s['이유']} {s['금액']:+,}원({s['설명']})" for s in t["차이_이유"])
        lines.append(
            f"{t['공정']}: 표준견적서(부가세 포함) {won(t['표준견적서_부가세포함'])} · 기간 {t['기간_일']}일"
            f" · 시장 기준(부가세 별도) {won(t['시장기준_부가세별도'])} · 보통 범위 {won(lo)}~{won(hi)}"
            f"(실견적 {t['확인한_실견적_건수']}건) · 차이 이유: {why}"
        )
    lo, hi = ref["참고_공정_범위_부가세포함"]
    lines.append(f"참고 공정 범위(부가세 포함) {won(lo)}~{won(hi)}")
    return "\n".join(lines)


# ---- v3 입력 ----
def v3_facts(h: Home, *, with_plan: bool = True):
    """ProjectFacts: 운영(chat.tools.project_facts)이 DB에서 읽는 칸을 같은 계산 함수로 여기서 세요."""
    from app.agent.v3.schemas import (
        PlanBlockFact,
        PlanFacts,
        ProjectFacts,
        StandardFacts,
        StandardLineFact,
    )
    from app.calc import dobae, mokgong, schedule
    from app.calc.common import pyeong_to_m2, sum_won
    from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
    from app.refprice.book import DOBAE_V3_2026_11, MOKGONG_2026H2
    from app.refprice.holidays import days_off
    from app.refprice.house import HOUSE_2026H2
    from app.refprice.wallpaper_market import paper_market

    m2 = Decimal(str(h.area_m2))
    if h.area_basis == "supply" and pyeong_to_m2(Decimal(h.pyeong)) != m2:
        raise ValueError(f"{h.id}: {h.pyeong}평과 {h.area_m2}㎡가 맞지 않아요")
    occupied = h.living == "living"
    try:
        home = dobae.HomeV3(m2, h.area_basis, h.grade, occupied)  # type: ignore[arg-type]
        std = dobae.standard_v3(
            home,
            DOBAE_V3_2026_11,
            paper_market(home.grade),
            SPACE_SHARE_ROOMS_2026_11,
            HOUSE_2026H2,
        )
        mk = mokgong.quote(
            mokgong.MokgongInput(m2, h.area_basis, h.mokgong, occupied),  # type: ignore[arg-type]
            MOKGONG_2026H2,
        )
    except TypeError as e:  # 계산 엔진 함수 모양이 바뀌면 여기부터 맞춰요(feat-v4-calc 병합 뒤)
        raise RuntimeError("계산 엔진 함수가 바뀌었어요. home.v3_facts를 맞춰 주세요") from e
    quotes = {"mokgong": mk, "dobae": std.quote}  # 운영 standard_for와 같은 순서(목공 → 도배)
    order = [t for t in ("mokgong", "dobae") if t in h.trades]
    lines = [
        StandardLineFact(
            key=ln.key, name=ln.name, state=ln.state, qty=float(ln.qty) if ln.qty is not None else None,
            unit=ln.unit, unit_price=ln.unit_price, amount=ln.amount, trade=t,  # type: ignore[arg-type]
        )
        for t in order
        for ln in quotes[t].lines
    ]  # fmt: skip
    standard = StandardFacts(
        total=sum_won(quotes[t].total for t in order),
        supply=sum_won(quotes[t].subtotal for t in order),
        vat=sum_won(quotes[t].vat for t in order),
        trades={t: quotes[t].total for t in order},
        lines=lines,
    )
    plan = None
    if with_plan:
        crews = {"mokgong": MOKGONG_2026H2.crew, "dobae": DOBAE_V3_2026_11.crew}
        off = days_off(h.start_wish, h.start_wish + timedelta(days=60))
        p = schedule.lay_out(
            [schedule.TradePlan(t, quotes[t].steps, crews[t]) for t in order], h.start_wish, off
        )
        ko = {"mokgong": "목공", "dobae": "도배"}
        blocks = [
            PlanBlockFact(trade=b.trade, ko=ko[b.trade], start=b.start, end=b.end)  # type: ignore[arg-type]
            for b in p.blocks
            if b.trade in ko
        ]
        last = blocks[-1].end if blocks else p.end
        after = " · ".join(
            b.label for b in p.blocks if b.trade is None and b.start > last and b.label
        )
        plan = PlanFacts(
            start=p.start, end=p.end, work_days=p.work_days, blocks=blocks, after=after
        )
    return ProjectFacts(
        stage="standard",
        area_m2=h.area_m2,
        area_basis=h.area_basis,  # type: ignore[arg-type]
        calc_m2=h.area_m2,
        calc_basis=h.area_basis,  # type: ignore[arg-type]
        trades=list(h.trades),  # type: ignore[arg-type]
        grade=h.grade,  # type: ignore[arg-type]
        living=h.living,  # type: ignore[arg-type]
        start_wish=h.start_wish if with_plan else None,
        standard=standard,
        plan=plan,
    )


STATE_KO = {"included": "포함", "bundled": "묶음 포함", "separate": "따로 계산", "optional": "선택",
            "after_visit": "실측 후", "excluded": "안 함"}  # fmt: skip


def _size_line(x) -> str:
    """SizeCalcFact 한 줄(질문 평수 · 이 집 · 예시 평수)."""
    parts = [
        f"{x.label}({x.pyeong:g}평 · {x.area_m2:g}㎡ {'공급' if x.area_basis == 'supply' else '전용'} · 방 {x.rooms})",
        f"도배 기본형 {won(x.dobae_total)} · 저가형 {won(x.dobae_total_economy)}",
        f"도배 {x.dobae_days:g}일(살면서 {x.dobae_days_occupied:g}일)",
    ]
    if x.mokgong_total is not None:
        parts.append(f"목공(몰딩 · 걸레받이) {won(x.mokgong_total)} · {x.mokgong_days:g}일")
    if x.dobae_dates:
        parts.append(f"도배 날짜 {x.dobae_dates[0]}~{x.dobae_dates[1]}")
    if x.mokgong_dates:
        parts.append(f"목공 날짜 {x.mokgong_dates[0]}~{x.mokgong_dates[1]}")
    if x.pair is not None:
        parts.append(
            f"목공 → 도배 이어서 {x.pair.start}~{x.pair.end}(일하는 날 {x.pair.work_days}일)"
        )
    return " · ".join(parts)


def v3_digest(facts, general) -> str:
    """v3가 받은 계산 값(판정기의 숫자 일치용): 프로젝트 표준견적서 · 공정표 + 질문으로 센 값을 같은 숫자 그대로 줄글로."""
    lines: list[str] = []
    if facts is not None and facts.standard is not None:
        s = facts.standard
        trades = " · ".join(f"{KO_TRADE.get(t, t)} {won(v)}" for t, v in s.trades.items())
        lines.append(
            f"표준견적서(부가세 포함) 합계 {won(s.total)} · 공급가 {won(s.supply)} · 부가세 {won(s.vat)} · {trades}"
        )
        rows = []
        for x in s.lines:
            qty = (
                f" {x.qty:g}{x.unit} × {won(x.unit_price)}"
                if x.qty is not None and x.unit_price is not None
                else ""
            )
            amt = f" = {won(x.amount)}" if x.amount is not None else ""
            rows.append(f"{x.name}{qty}{amt}({STATE_KO.get(x.state, x.state)})")
        lines.append("줄: " + " / ".join(rows))
    if facts is not None and facts.plan is not None:
        p = facts.plan
        blocks = " · ".join(f"{b.ko} {b.start}~{b.end}" for b in p.blocks)
        after = f" · 뒤: {p.after}" if p.after else ""
        lines.append(f"예상 공정표 {p.start}~{p.end}(일하는 날 {p.work_days}일) · {blocks}{after}")
    if facts is not None and facts.start_wish:
        lines.append(f"공사 시작 희망 {facts.start_wish}")
    if general is not None:
        if general.here is not None:
            lines.append("이 집: " + _size_line(general.here))
        if general.asked is not None:
            lines.append("질문 평수: " + _size_line(general.asked))
        if facts is None:  # 프로젝트가 없을 때만 예시 평수(24 · 34 · 44평)를 답에 써요
            lines += ["예시: " + _size_line(x) for x in general.examples]
        if general.door_set is not None:
            lines.append(
                f"방문 1개: 문틀까지 {won(general.door_set)} · 문짝만 {won(general.door_leaf)}"
            )
        if general.start is not None:
            lines.append(f"질문의 시작 날짜 {general.start}")
    return "\n".join(lines) or "(없음)"
