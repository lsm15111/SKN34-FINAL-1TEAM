"""AI 칸 도구: 기능 service 공개 함수로 프로젝트 사실(ProjectFacts)을 읽어 에이전트에 넘긴다.

- 에이전트(app.agent)는 기능 service를 import하지 않는다. 여기(chat)가 읽어서 넘긴다.
- 숫자 · 날짜는 계산 엔진이 이미 만든 값만 옮긴다(표준견적서 · 공정표 · 실측 초안). 여기서 계산하지 않는다.
- 남의 프로젝트는 기능 service가 404로 막는다(project.service.get_for). 동 · 호 · 연락처는 옮기지 않는다.
- 부르는 함수는 B1a 계약(docs/v3/contract.md 5장)만: project.get_for · quote.standard_for · schedule.plan_for ·
  schedule.overview_for · visit.vendors_for · visit.draft_for · visit.pick_view(날짜 고르기 화면, context.ids의 실측 id) ·
  visit.vendor_detail(업체 자세히 화면, context.ids의 업체 id → 화면 사실).
  1단계 함수가 아직 없거나 그 칸이 비면 그 사실을 비운다
  (답은 '계산 없음' 정해 둔 글로). 업체끼리 줄 차이는 계산 엔진 함수가 생기기 전까지 넘기지 않는다(여기서 빼기 계산 안 함).
"""

import re
import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.v3.schemas import (
    EstimateFacts,
    GeneralFacts,
    PlanBlockFact,
    PlanFacts,
    ProjectFacts,
    ScreenFacts,
    ScreenLineFact,
    SizeCalcFact,
    StandardFacts,
    StandardLineFact,
    VendorPickFact,
    VendorRangeFact,
    VendorScreenFacts,
    VisitDraftFacts,
    VisitRecommendFact,
)
from app.agent.v3.templates import md
from app.auth.models import User
from app.shared.clock import now_utc
from app.shared.errors import AppError

STATES = {"included", "bundled", "separate", "optional", "after_visit", "excluded"}
TRADES = {"dobae", "mokgong"}
# overview_for phase → 에이전트 단계(다음 할 일 버튼)
PHASE = {"estimate": "standard", "progress": "visit", "work": "construction", "done": "done"}


async def project_facts(
    s: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    today: date,
    ids: Sequence[str] = (),
    view: str | None = None,
) -> ProjectFacts:
    """프로젝트 사실. 남의 것 · 없는 것은 404(AppError)를 그대로 올린다.
    ids(보던 실측 id)가 있으면 업체가 답한 기간 · 추천 반나절도 옮긴다(날짜 고르기 화면).
    view가 업체 자세히(vendor)면 ids의 업체 가견적 줄을 화면 사실로 옮긴다(화면과 같은 계산 엔진 값)."""
    from app.project import service as project_service

    p = await project_service.get_for(s, user, project_id)
    trades = [t for t in ("dobae", "mokgong") if getattr(p.trades, t, None) is not None]
    dobae = getattr(p.trades, "dobae", None)
    facts = ProjectFacts(
        stage="visit" if getattr(p, "locked", False) else "standard",
        area_m2=float(p.size.m2) if p.size.m2 is not None else None,
        area_basis=p.size.basis,
        trades=trades,  # type: ignore[arg-type]
        grade=getattr(dobae, "grade", None),
        living="living" if getattr(p, "occupied", False) else "vacant",
        start_wish=p.when.start if p.when else None,
    )
    facts.calc_m2, facts.calc_basis = _calc_area(p)
    facts.standard = await _standard(s, user, project_id)
    facts.plan = await _plan(s, user, project_id, today)
    facts.visit_draft = await _visit_draft(s, user, project_id, today)
    picked = await _visit_pick(s, user, project_id, ids)
    if picked is not None:
        d = facts.visit_draft or VisitDraftFacts()
        d.ranges, d.recommend = picked[0], picked[1]
        d.basis_start = d.basis_start or picked[2]
        facts.visit_draft = d
    facts.estimates = await _estimates(s, user, project_id)
    facts.vendors = await _vendor_picks(
        s, user, project_id, "dobae" if dobae else trades[0] if trades else "dobae"
    )
    stage = await _stage(s, user, project_id, today)
    if stage:
        facts.stage = stage  # type: ignore[assignment]
    # 모은 조건(맥락 L3): 고객이 되묻기에 답한 칸은 다시 묻지 않아요(answer.slot_known)
    facts.brief = await project_service.conditions(s, project_id)
    if view is not None:
        facts.screen = ScreenFacts(view=view)  # type: ignore[arg-type]
        if view == "vendor" and ids and dobae is not None:
            facts.screen.vendor = await _vendor_screen(s, user, project_id, ids[0], today)
    seen = facts.screen.vendor if facts.screen else None
    if seen is not None:  # 보는 업체의 따로 받는 줄(표준견적서에 없는 줄)을 가견적 칸에도 적어요
        for e in facts.estimates:
            if e.vendor == seen.vendor and not e.separate:
                e.separate = [x.name for x in seen.lines if not x.in_standard and x.amount > 0]
    return facts


async def _vendor_screen(
    s: AsyncSession, user: User, project_id: uuid.UUID, raw: str, today: date
) -> VendorScreenFacts | None:
    """업체 자세히 화면의 가견적(도배 v3). 업체 id가 아니거나 고를 수 없는 업체면 비워요(404는 올리지 않음)."""
    from app.visit import service as visit_service

    try:
        d = await visit_service.vendor_detail(
            s, user, project_id, uuid.UUID(str(raw)), "dobae", today
        )
    except (ValueError, AppError):
        return None
    return vendor_screen(d)


def vendor_screen(d) -> VendorScreenFacts | None:
    """VendorDetailOut → 화면 사실. 값은 옮기기만 해요(셈 없음). 보여 준 벽지가 아닌 도배지 줄은 화면처럼 빼요."""
    from app.refprice.vendor_baseline import VENDOR_BASE_2026_11

    e = d.estimate_v3
    if e is None:
        return None
    other = "paper_hapji" if e.grade == "basic" else "paper_silk"
    lines = []
    for ln in e.lines:
        if ln.key == other or ln.mode == "excluded":
            continue
        base = VENDOR_BASE_2026_11.get(ln.code)
        lines.append(
            ScreenLineFact(
                key=ln.key,
                name=ln.name,
                qty=float(ln.qty),
                unit=ln.unit,
                unit_price=ln.unit_price,
                amount=ln.amount,
                in_standard=ln.in_standard,
                included_in=ln.included_in,
                basis=base.unit_ko.removesuffix("당").strip() if base else "",
            )
        )
    pct = e.vs_standard_pct
    return VendorScreenFacts(
        vendor=d.profile.biz_name or "", grade=e.grade, total=e.total, supply=e.supply, vat=e.vat,
        vs_standard=None if pct is None else float(pct), grade_diff=d.grade_diff, lines=lines,
    )  # fmt: skip


async def _stage(s: AsyncSession, user: User, project_id: uuid.UUID, today: date) -> str | None:
    from app.schedule import service as schedule_service

    try:
        o = await schedule_service.overview_for(s, user, project_id, today)
    except AppError:
        return None
    return PHASE.get(getattr(o, "phase", ""))


async def _estimates(s: AsyncSession, user: User, project_id: uuid.UUID) -> list[EstimateFacts]:
    """담은 업체(없으면 이 구 업체 앞 3곳)의 가견적 합계. 합계 · 표준 대비 %는 계산 엔진 값 그대로."""
    from app.visit import service as visit_service

    try:
        lst = await visit_service.vendors_for(s, user, project_id, "dobae")
    except AppError:
        return []
    cards = [*lst.local, *lst.nearby]
    picked = [c for c in cards if c.shortlisted] or cards[:3]
    return [
        EstimateFacts(
            vendor=c.name,
            total=c.estimate_total,
            vs_standard=None if c.vs_standard_pct is None else int(c.vs_standard_pct),
        )
        for c in picked[:3]
        if c.estimate_total is not None
    ]


async def _vendor_picks(
    s: AsyncSession, user: User, project_id: uuid.UUID, trade: str
) -> list[VendorPickFact]:
    """업체 추천(코드): 업체 고르기 화면과 같은 카드(이 구 · 가까운 구)에서 계산 엔진 점수로 3곳.
    별점 · 공사 수 · 가견적 · 표준 대비 %는 화면 값 그대로 옮기고, 고르기는 calc.vendor_pick이 한다."""
    from app.calc import vendor_pick
    from app.visit import service as visit_service

    try:
        lst = await visit_service.vendors_for(s, user, project_id, trade)
    except AppError:
        return []
    cands = [
        vendor_pick.Candidate(
            vendor_id=str(c.vendor_id),
            name=c.name,
            local=local,
            estimate_total=c.estimate_total,
            vs_standard_pct=None if c.vs_standard_pct is None else int(c.vs_standard_pct),
            rating=None if c.rating is None else float(c.rating),  # 화면 값은 Decimal이라 float으로
            review_count=c.review_count or 0,
            done_count=c.done_count or 0,
            instant=bool(c.instant_badge),
        )
        for local, cards in ((True, lst.local), (False, lst.nearby))
        for c in cards
    ]
    out = []
    for p in vendor_pick.pick(cands):
        c = p.c
        out.append(
            VendorPickFact(
                vendor_id=c.vendor_id,
                name=c.name,
                local=c.local,
                estimate_total=c.estimate_total,
                vs_standard_pct=c.vs_standard_pct,
                rating=c.rating,
                review_count=c.review_count,
                done_count=c.done_count,
                instant=c.instant,
                score=p.score,
                reasons=vendor_pick.reasons(p),
            )
        )
    return out


# 질문에 나온 평수 · ㎡(가정 계산). 공백 반복에 상한을 둬요(CodeQL ReDoS)
PYEONG = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d)?)\s{0,2}평")
SQM = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d{1,2})?)\s{0,2}(?:㎡|m2|m²|제곱미터|평방미터|헤베)")
PY_M2 = 3.3058  # 1평 = 3.3058㎡ (표시 · 가정 계산용 환산)
EXAMPLE_PY = (24, 34, 44)


def asked_area(text: str) -> tuple[float, str, str] | None:
    """질문에 나온 면적 → (㎡, 기준, 화면 이름). 'N평'은 공급 평형으로, '㎡'는 '공급'이라고 쓰지 않으면 전용으로 봐요
    (84㎡ · 59㎡처럼 ㎡로 말하는 건 보통 전용면적이에요). 공급 10~80평(33~265㎡) 밖은 None."""
    t = text or ""
    m = PYEONG.search(t)
    if m:
        py = float(m.group(1))
        if not 10 <= py <= 80:
            return None
        return round(py * PY_M2, 1), "supply", f"{m.group(1)}평"
    m = SQM.search(t)
    if not m:
        return None
    v = float(m.group(1))
    if not 33 <= v <= 265:
        return None
    basis = "supply" if "공급" in t else "exclusive"
    return v, basis, f"{'공급' if basis == 'supply' else '전용'} {m.group(1)}㎡"


def _size_calc(m2v: float, basis: str, label: str) -> SizeCalcFact:
    """면적 하나를 도배 · 목공 계산 엔진으로 센다(빈집 · 벽 + 천장 · 전체 · 방 개수는 평형 기본값)."""
    from decimal import Decimal

    from app.calc import dobae, mokgong
    from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
    from app.refprice.book import DOBAE_V3_2026_11, MOKGONG_2026H2
    from app.refprice.house import HOUSE_2026H2
    from app.refprice.wallpaper_market import paper_market

    m2 = Decimal(str(m2v)).quantize(Decimal("0.1"))

    def std(grade: str, occupied: bool):
        h = dobae.HomeV3(m2, basis, grade, occupied)  # type: ignore[arg-type]
        return dobae.standard_v3(
            h, DOBAE_V3_2026_11, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2
        )

    basic, eco, occ = std("basic", False), std("economy", False), std("basic", True)
    mk = mokgong.quote(mokgong.MokgongInput(m2, basis, ("molding", "base"), False), MOKGONG_2026H2)  # type: ignore[arg-type]
    return SizeCalcFact(
        label=label, pyeong=float(basic.pyeong), area_m2=float(m2), area_basis=basis,  # type: ignore[arg-type]
        rooms=basic.rooms or 0, dobae_total=basic.quote.total,
        dobae_total_economy=eco.quote.total, dobae_days=float(basic.quote.days),
        dobae_days_occupied=float(occ.quote.days), mokgong_total=mk.total,
        mokgong_days=float(mk.days),
    )  # fmt: skip


# 시작 날짜: '12월 1일' · '12/1부터' · '내일' · '모레' · '다음 주 월요일'. 길이에 상한을 둬요(ReDoS)
MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s{0,2}월\s{0,2}(\d{1,2})\s{0,2}일")
SLASH_DAY = re.compile(
    r"(?<![\d./])(\d{1,2})/(\d{1,2})(?![\d./])\s{0,2}(?:일\s{0,2})?(?:부터|에|시작)"
)
# 화면이 쓰는 꼴 '12.1(화)'. '2.5일' 같은 기간을 날짜로 읽지 않게 요일 괄호를 요구해요
DOT_DAY = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\s{0,1}\([월화수목금토일]\)")
REL_DAY = re.compile(r"내일|모레|(이번|다음)\s{0,2}주\s{0,2}([월화수목금토일])요일")
WEEKDAY_KO = "월화수목금토일"


def asked_start(text: str, today: date) -> date | None:
    """질문에 나온 시작 날짜. 지난 월 · 일이면 다음 해로 봐요. 없거나 잘못된 날짜면 None."""
    from datetime import timedelta

    t = text or ""
    m = MONTH_DAY.search(t) or SLASH_DAY.search(t) or DOT_DAY.search(t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        for y in (today.year, today.year + 1):
            try:
                got = date(y, mo, d)
            except ValueError:
                return None
            if got >= today:
                return got
        return None
    r = REL_DAY.search(t)
    if not r:
        return None
    if r.group(0) == "내일":
        return today + timedelta(days=1)
    if r.group(0) == "모레":
        return today + timedelta(days=2)
    want = WEEKDAY_KO.index(r.group(2))
    monday = today - timedelta(days=today.weekday())
    if r.group(1) == "다음":
        monday += timedelta(days=7)
    got = monday + timedelta(days=want)
    return got if got >= today else None


def _with_dates(x: SizeCalcFact, start: date) -> SizeCalcFact:
    """시작 날짜부터 일하는 날(주말 · 공휴일 빼고)에 빈집 기준 일을 놓는다(계산 엔진 schedule.span)."""
    from datetime import timedelta

    from app.calc import schedule
    from app.refprice.holidays import days_off

    off = days_off(start, start + timedelta(days=60))
    d0, d1, _ = schedule.span(start, x.dobae_days, off)
    up = {"dobae_dates": (d0, d1)}
    if x.mokgong_days:
        m0, m1, _ = schedule.span(start, x.mokgong_days, off)
        up["mokgong_dates"] = (m0, m1)
    up["pair"] = _pair_plan(x, start, off)
    return x.model_copy(update=up)


def _pair_plan(x: SizeCalcFact, start: date, off) -> PlanFacts | None:
    """목공(몰딩 · 걸레받이) 다음 도배(기본형 · 빈집)를 시작 날짜부터 이어 놓은 일정.
    공사 공정표와 같은 계산 엔진(schedule.lay_out)이 단계 반나절로 셈해요. 못 세면 None."""
    from decimal import Decimal

    from app.calc import dobae, mokgong, schedule
    from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
    from app.refprice.book import DOBAE_V3_2026_11, MOKGONG_2026H2
    from app.refprice.house import HOUSE_2026H2
    from app.refprice.wallpaper_market import paper_market

    m2 = Decimal(str(x.area_m2)).quantize(Decimal("0.1"))
    try:
        h = dobae.HomeV3(m2, x.area_basis, "basic", False)
        std = dobae.standard_v3(
            h, DOBAE_V3_2026_11, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2
        )
        mk = mokgong.quote(
            mokgong.MokgongInput(m2, x.area_basis, ("molding", "base"), False), MOKGONG_2026H2
        )
        p = schedule.lay_out(
            [
                schedule.TradePlan("mokgong", mk.steps, MOKGONG_2026H2.crew),
                schedule.TradePlan("dobae", std.quote.steps, DOBAE_V3_2026_11.crew),
            ],
            start,
            off,
        )
    except ValueError:
        return None
    ko = {"mokgong": "목공", "dobae": "도배"}
    blocks = [
        PlanBlockFact(trade=b.trade, ko=ko[b.trade], start=b.start, end=b.end)  # type: ignore[arg-type]
        for b in p.blocks
        if b.trade in ko
    ]
    if not blocks:
        return None
    last = blocks[-1].end
    after = " · ".join(b.label for b in p.blocks if b.trade is None and b.start > last and b.label)
    return PlanFacts(start=p.start, end=p.end, work_days=p.work_days, blocks=blocks, after=after)


def _calc_area(p) -> tuple[float | None, str | None]:
    """표준견적서와 같은 면적(평형대면 대표 평형의 공급면적). 못 세면 (None, None)."""
    from app.calc.standard_quote import house_area
    from app.refprice.house import HOUSE_2026H2

    try:
        m2, basis = house_area(p.size.band, p.size.m2, p.size.basis, HOUSE_2026H2)
    except (ValueError, KeyError):
        return None, None
    return float(m2), basis


def house_size(facts: ProjectFacts | None) -> SizeCalcFact | None:
    """이 집 면적으로 센 계산 엔진 값(공사에 없는 공종을 물을 때 씀). 면적을 모르면 None."""
    if facts is None:
        return None
    m2 = facts.calc_m2 or facts.area_m2
    if not m2:
        return None
    return _size_calc(m2, facts.calc_basis or facts.area_basis or "supply", "이 집")


def with_said(g: GeneralFacts, area, start: date | None, today: date) -> GeneralFacts:
    """이번 질문에 없으면 앞 턴에 말한 집 크기(SaidArea) · 시작 날짜(대화 상태)로 계산 엔진 값을 다시 세요.
    질문에 있으면 그 값을 써요(새로 말한 것이 이겨요). 오늘보다 앞선 날짜는 이어받지 않아요."""
    asked = g.asked
    if asked is None and area is not None:
        asked = _size_calc(area.m2, area.basis, area.label)
    begin = g.start if g.start is not None else (start if start and start >= today else None)
    if begin is None:
        return g.model_copy(update={"asked": asked})
    if begin != g.start:  # 날짜를 이어받았어요: 질문 평수 · 예시 평수에 그 날짜를 새로 놓아요
        examples = [_with_dates(x, begin) for x in g.examples]
        asked = _with_dates(asked, begin) if asked is not None else None
        return g.model_copy(update={"asked": asked, "examples": examples, "start": begin})
    if asked is not None and asked is not g.asked:  # 날짜는 이번 질문에, 평수만 이어받았어요
        asked = _with_dates(asked, begin)
    return g.model_copy(update={"asked": asked})


def general_facts(text: str, today: date | None = None) -> GeneralFacts:
    """질문만 보고 센 계산 엔진 값(DB 없음, 순수 계산). 질문 평수 · 예시 평수 3개 · 방문 1개.
    today를 주면 질문의 시작 날짜('12월 1일부터')로 끝나는 날도 센다."""
    from decimal import Decimal

    from app.calc import mokgong
    from app.refprice.book import DOBAE_V3_2026_11, MOKGONG_2026H2

    area = asked_area(text)
    one = Decimal("79.3")  # 방문 값은 집 크기와 상관없어서 24평 집으로 센다(폐기물 등 최소 줄 포함)

    def door(frame: bool) -> int:
        q = mokgong.quote(
            mokgong.MokgongInput(one, "supply", ("door",), False, doors=1, door_frame=frame),
            MOKGONG_2026H2,
        )
        return q.total

    asked = _size_calc(*area) if area else None
    examples = [_size_calc(round(x * PY_M2, 1), "supply", f"{x}평") for x in EXAMPLE_PY]
    start = asked_start(text, today) if today else None
    if start is not None:
        asked = _with_dates(asked, start) if asked else None
        examples = [_with_dates(x, start) for x in examples]
    return GeneralFacts(
        asked=asked,
        examples=examples,
        door_set=door(True),
        door_leaf=door(False),
        price_ver=DOBAE_V3_2026_11.version,
        start=start,
    )


async def _standard(s: AsyncSession, user: User, project_id: uuid.UUID) -> StandardFacts | None:
    from app.quote import service as quote_service

    try:
        st = await quote_service.standard_for(s, user, project_id)
    except AppError:
        return None
    lines = [
        StandardLineFact(
            key=ln.key,
            name=ln.name,
            state=ln.state,  # type: ignore[arg-type]
            qty=float(ln.qty) if ln.qty is not None else None,
            unit=ln.unit,
            unit_price=ln.unit_price,
            amount=ln.amount,
            trade=t.trade,  # type: ignore[arg-type]
        )
        for t in st.trades
        if t.trade in TRADES
        for ln in t.lines
        if ln.state in STATES
    ]
    trades = {t.trade: t.total for t in st.trades if t.trade in TRADES}
    return StandardFacts(total=st.total, supply=st.supply, vat=st.vat, trades=trades, lines=lines)


async def _plan(
    s: AsyncSession, user: User, project_id: uuid.UUID, today: date
) -> PlanFacts | None:
    from app.schedule import service as schedule_service

    try:
        p = await schedule_service.plan_for(s, user, project_id, today)
    except AppError:
        return None
    blocks = [
        PlanBlockFact(trade=b.trade, ko=b.label, start=b.start, end=b.end)  # type: ignore[arg-type]
        for b in p.blocks
        if b.trade in TRADES
    ]
    kind = "final" if p.kind == "final" else "expected"
    return PlanFacts(kind=kind, start=p.start, end=p.end, work_days=p.work_days, blocks=blocks)


async def _visit_draft(
    s: AsyncSession, user: User, project_id: uuid.UUID, today: date
) -> VisitDraftFacts | None:
    """B1a `visit.service.draft_for`(GET /projects/{id}/visits/draft와 같은 값, 1단계)가 생기면 그대로 옮긴다.

    산식 글은 계산 엔진 상수(calc.slots)로 적는다(날짜를 새로 계산하지 않음)."""
    from app.calc import slots
    from app.visit import service as visit_service

    fn = getattr(visit_service, "draft_for", None)
    if fn is None:
        return None
    try:
        d = await fn(s, user, project_id, "dobae", today)
    except AppError:
        return None
    vendors = [getattr(v, "name", "") for v in getattr(d, "vendors", []) or []]
    return VisitDraftFacts(
        wish_start=getattr(d, "wish_start", None),
        wish_end=getattr(d, "wish_end", None),
        basis_start=getattr(d, "basis_start", None),
        formula=f"공사 시작 희망일 − {slots.DRAFT_FROM_DAYS}일 ~ − {slots.DRAFT_TO_DAYS}일",
        vendors=[v for v in vendors if v],
    )


def pick_facts(pick) -> tuple[list[VendorRangeFact], VisitRecommendFact, date | None] | None:
    """날짜 고르기 화면 값(visit.service.pick_view) → 초안 재료. 기간 · 추천일 · 기준 날은 계산 엔진 값 그대로
    옮기고, 산식 글은 그 값과 계산 엔진 상수(calc.slots)로 적기만 한다."""
    from app.calc import slots

    w, rec = getattr(pick, "window", None), getattr(pick, "recommend", None)
    name = getattr(pick, "vendor_name", "") or ""
    if w is None or rec is None or not name:
        return None
    wish = getattr(pick, "work_wish_on", None)
    if rec.basis == "start_minus_20" and wish is not None:
        basis = f"{md(wish)} − {slots.RECOMMEND_BEFORE_DAYS}일 = {md(rec.target)}"
    else:
        basis = "업체가 된다고 한 날 중 가장 이른 반나절"
    return (
        [VendorRangeFact(vendor=name, start=w.start, end=w.end)],
        VisitRecommendFact(vendor=name, day=rec.day, half=rec.half, basis=basis),
        wish,
    )


async def _visit_pick(
    s: AsyncSession, user: User, project_id: uuid.UUID, ids: Sequence[str]
) -> tuple[list[VendorRangeFact], VisitRecommendFact, date | None] | None:
    """보던 실측 하나(앞에서부터)의 업체 기간 · 추천. 실측 id가 아니거나 남의 것이면 건너뛴다(404는 올리지 않음)."""
    from app.visit import service as visit_service

    for raw in ids:
        try:
            vid = uuid.UUID(str(raw))
        except ValueError:
            continue
        try:
            pick = await visit_service.pick_view(s, user, project_id, vid, now_utc())
        except AppError:
            continue
        got = pick_facts(pick)
        if got is not None:
            return got
    return None
