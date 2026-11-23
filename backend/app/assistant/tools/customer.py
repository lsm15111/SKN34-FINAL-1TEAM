"""고객 비서 읽기 도구 (계약서 5장): get_home · get_standard_quote · recommend_vendors · vendor_free_slots ·
compare_quotes · get_schedule · today_tasks · show_card · compare_grades(벽지 두 종류 견주기) · market_range(시세 범위) ·
offer_choices(물은 갈래를 고르기 칩으로).

공사는 세션이 정한 project_id만 쓴다(남의 것은 기능 service가 404). 카드 · 모델용 값은 cards.py가 만든다.
"""

import re
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.assistant import policy
from app.assistant.tools import ToolCtx, ToolError, ToolOut, cards, obj, tool
from app.db import SessionLocal

Trade = Literal["dobae", "mokgong"]
TRADE = {
    "type": "string",
    "enum": ["dobae", "mokgong"],
    "description": "공정: dobae 도배 · mokgong 목공",
}
REF = {"type": "string", "description": "도구 결과에 나온 이름표"}


def pid_of(tc: ToolCtx) -> uuid.UUID:
    if tc.project_id is None:
        raise ToolError("no_project", "공사를 먼저 골라 주세요.")
    return tc.project_id


def dobae_only(trade: str) -> None:
    """업체 연결(추천 · 실측 요청 · 견적 비교 · 확정)은 아직 도배만이다. 목공이면 ToolError(dobae_only)."""
    if trade != "dobae":
        raise ToolError("dobae_only", policy.DOBAE_ONLY)


REGION_HINT = (
    "sgg는 시 · 군 · 구 이름이에요(예 노원구 · 성남시). 같은 이름이 여러 시 · 도에 있으면 '부산 중구'처럼 시 · 도를 "
    "앞에 붙이고, 동 이름(상계동)은 넣지 않아요"
)


def _sido_id(word: str | None) -> str | None:
    """'서울' · '서울특별시' · 'seoul' → 'seoul'. 모르면 None."""
    from app.shared.regions import SIDO

    w = (word or "").strip()
    return next((k for k, (short, full, _) in SIDO.items() if w in (k, short, full)), None)


def region_of(text: str | None, home_sido: str | None) -> tuple[str, str]:
    """도구가 받은 지역 글('노원구' · '서울 노원구' · '노원') → (시 · 도 id, 시 · 군 · 구). 시 · 도가 앞에 없으면 집
    시 · 도에서 먼저 찾고, 없으면 그 이름이 하나뿐인 시 · 도. 끝 글자(구 · 시 · 군)가 빠져도 찾고 끝의 동 이름은 뗀다.
    모르거나 여러 시 · 도에 있으면 ToolError."""
    from app.shared.regions import SIDO, is_region

    words = (text or "").split()
    sid = _sido_id(words[0]) if len(words) > 1 else None
    words = words[1:] if sid else words
    if words and words[-1].endswith(("동", "읍", "면")) and len(words) > 1:
        words = words[:-1]  # '노원구 상계동' → 구까지
    name = "".join(words)
    if not name:
        raise ToolError("need_region", "어느 시 · 군 · 구인지 알려 주세요.", hint=REGION_HINT)
    names = [name, *(name + x for x in ("구", "시", "군") if not name.endswith(x))]
    for n in names:
        if sid:
            if is_region(sid, n):
                return sid, n
            continue
        if home_sido and is_region(home_sido, n):
            return home_sido, n
        hits = [k for k in SIDO if is_region(k, n)]
        if len(hits) == 1:
            return hits[0], n
        if hits:
            raise ToolError("need_sido", "어느 시 · 도의 지역인지 알려 주세요.", hint=REGION_HINT)
    raise ToolError("bad_region", "지역을 다시 확인해 주세요.", hint=REGION_HINT)


class NoArgs(BaseModel):
    pass


class TradeIn(BaseModel):
    trade: Trade = "dobae"


@tool(
    "get_home",
    surface="customer",
    kind="read",
    status="집 정보를 보고 있어요",
    description="이 공사의 집 정보(지역 · 면적 · 평 · 살면서 공사 · 벽지 · 방 · 공사 시작 희망 · 직접 할 일 · 잠김)를 읽고 "
    "집 정보 카드를 보여 줘요. 고객이 집 정보를 바꾸겠다 · 보여 달라고 하면(무엇을 바꿀지 아직 말하지 않았어도) 글로만 "
    "되묻지 말고 먼저 이 도구로 카드를 보여 준 뒤 고칠 칸을 물어요. 고칠 값을 말하면 propose_home_info예요.",
    model=NoArgs,
    schema=obj({}),
)
async def get_home(tc: ToolCtx, _: NoArgs) -> ToolOut:
    async with SessionLocal() as s:
        card, model = await cards.home(s, tc.user, pid_of(tc))
    return ToolOut(data=model, cards=[card])


@tool(
    "get_standard_quote",
    surface="customer",
    kind="read",
    status="표준견적서를 보고 있어요",
    description="공공 기준 단가로 믿집이 계산한 표준견적서(부가세 포함 합계 · 큰 줄 · 예상 일수)를 읽어요. "
    "total은 부가세 포함이고, 줄 금액은 칸 이름처럼 공급가(부가세 별도)라 total과 더하거나 빼지 않아요. "
    "도배면 paper 칸에 롤 수(계산 엔진, 여분 따로)와 벽지 값(부가세 포함) · 벽지를 넣은/뺀 합계가 있어요. "
    "줄 text는 수량 × 단가, excluded는 합계 밖 줄(선택 · 실측 후 · 안 함)이에요. how는 평수 · 도배 면적 · 벽지 평 · "
    "품 · 기간 · 식대를 어떻게 셌는지(계산 엔진 글, 업체 가견적 수량도 같은 값)라 '수량 · 품은 어떻게 나왔어요?'에 "
    "그대로 근거로 써요. save는 벽지 종류는 그대로 두고 줄이는 길(바꾸면 합계 · 줄어드는 돈, 부가세 포함)이에요.",
    model=TradeIn,
    schema=obj({"trade": TRADE}),
)
async def get_standard_quote(tc: ToolCtx, a: TradeIn) -> ToolOut:
    async with SessionLocal() as s:
        card, model = await cards.standard(s, tc.user, pid_of(tc), a.trade)
    return ToolOut(data=model, cards=[card])


@tool(
    "compare_grades",
    surface="customer",
    kind="read",
    status="벽지 두 종류를 견주고 있어요",
    description="지금 집 조건으로 도배 표준견적서를 합지(저가형) · 실크(기본형) 두 벽지로 함께 계산해 두 합계(부가세 "
    "포함) · 차액(실크 − 합지) · 금액이 달라지는 줄(벽지 값 · 시공 …, 공급가)과 벽지마다 롤 수를 보여 줘요. "
    "벽지 직접 구매면 두 합계 모두 벽지 값을 뺀 값이고, 업체에 벽지까지 맡길 때의 합계는 paper 칸에 있어요. "
    "저장하지 않는 계산이라 지금 표준견적서와 고른 벽지는 그대로예요. 실크와 합지 중 고민할 때 쓰고, 바꾸고 싶다고 "
    "하면 propose_home_info(grade)로 승인 카드를 만들어요(실측 요청 전만). 표준견적서 대비 %는 없어요.",
    model=NoArgs,
    schema=obj({}),
)
async def compare_grades(tc: ToolCtx, _: NoArgs) -> ToolOut:
    async with SessionLocal() as s:
        try:
            card, model = await cards.grade_compare(s, tc.user, pid_of(tc))
        except ValueError as e:  # 도배가 없거나 계산할 수 없는 집 정보
            raise ToolError("no_dobae", "이 공사는 두 벽지를 견줄 도배 계산이 없어요.") from e
    return ToolOut(data=model, cards=[card])


@tool(
    "market_range",
    surface="customer",
    kind="read",
    status="시세 범위를 보고 있어요",
    description="'보통 얼마' · '시세'를 물을 때 이 집 조건(면적 · 벽지 · 천장 · 사는 중, 목공은 고른 항목)의 시세 범위"
    "(부가세 포함, 만 원 단위)와 근거 실견적 수 · 출처 한 줄을 읽어요. 믿집 계산 엔진이 모은 실견적으로 낸 가운데 "
    "절반 범위이고 원자료는 없어요. 범위를 말할 때 출처(source)를 같이 말해요. found가 false면 범위를 지어내지 말고 "
    "까닭(note)을 말해요. 표준견적서 금액은 get_standard_quote예요.",
    model=TradeIn,
    schema=obj({"trade": TRADE}),
)
async def market_range(tc: ToolCtx, a: TradeIn) -> ToolOut:
    async with SessionLocal() as s:
        card, model = await cards.market_range(s, tc.user, pid_of(tc), a.trade)
    return ToolOut(data=model, cards=[card] if card is not None else [])


class RecommendIn(BaseModel):
    trade: Trade = "dobae"
    sgg: str | None = Field(default=None, max_length=30)  # 다른 구 업체 읽기만(집 정보는 그대로)


# 고객이 고르기를 맡길 때(리드 결정 11-22, QA r3 s4): 코드 점수 1위를 서버가 넣는다(AGENTS.md 4장 '업체 추천은
# 에이전트가 아니다'). 모델에는 누가 1위인지와 까닭 틀을 준다
LEFT_NOTE = (
    "picks는 믿집 점수(별점 · 끝낸 공사 · 가견적) 순이에요. 고객이 골라 달라고 맡기면: {name}(믿집 점수 1위 · {why}). "
    "그때는 propose_visit_request를 pick=top으로 불러요(믿집이 점수 1위를 넣어요)."
)


def left_to_us(model: dict) -> None:
    """추천 모델 값에 '맡기시면 이 곳'(점수 1위 · 까닭 틀)을 더한다. picks가 비면 그대로."""
    if not model.get("picks"):
        return
    top = model["picks"][0]
    why = " · ".join([*top.get("reasons", []), f"가견적 {top['estimate_won']:,}원"])
    note = LEFT_NOTE.format(name=top["name"], why=why)
    model["note"] = " ".join(x for x in (model.get("note"), note) if x)


@tool(
    "recommend_vendors",
    surface="customer",
    kind="read",
    status="업체를 고르고 있어요",
    description="이 집 조건에 맞는 업체 3곳(v1~v3)을 믿집 점수(별점 · 끝낸 공사 · 가견적)로 골라요. picks는 점수 "
    "순(첫째가 1위)이에요. 가견적은 업체가 확인한 단가 × 믿집 수량이에요. 업체 연결은 아직 도배(dobae)만이에요. "
    "고객이 집 지역과 다른 구를 말하면 sgg(시 · 군 · 구, 예 노원구)로 그 구 업체를 읽기만으로 볼 수 있어요: 집 "
    "정보는 그대로이고 그 업체들에는 요청할 수 없어요(실측 요청은 집 지역 업체에만). 믿집 밖 조사보다 먼저 써요.",
    model=RecommendIn,
    schema=obj(
        {
            "trade": TRADE,
            "sgg": {
                "type": "string",
                "description": "집 지역이 아닌 시 · 군 · 구 업체를 읽기만으로 볼 때 그 이름(예 노원구, 같은 이름이 여러 "
                "시 · 도에 있으면 '부산 중구'). 비우면 집 지역",
            },
        },
        required=["trade"],
    ),
)
async def recommend_vendors(tc: ToolCtx, a: RecommendIn) -> ToolOut:
    from app.project import service as project_service

    dobae_only(a.trade)
    pid = pid_of(tc)
    async with SessionLocal() as s:
        if a.sgg:
            p = await project_service.get_for(s, tc.user, pid)
            region = region_of(a.sgg, p.sido)
            if region != (p.sido, p.sgg):
                return await _elsewhere(s, tc, p, a.trade, *region)
        card, model = await cards.vendor_picks(s, tc.user, pid, a.trade, tc.refs)
        if not model["picks"]:
            return await no_picks(s, tc, pid, model)
    left_to_us(model)
    return ToolOut(data=model, cards=[card])


# 추천할 곳이 0곳(QA r6 c3 H1: 0곳 카드를 다섯 번 내고 '두 업체 카드를 다시 보여 드렸어요'라고 함): 빈 카드를 보내지
# 않고 까닭(why, cards.vendor_picks) · 다음 할 일(next) 하나를 모델에 준다. 진행 중인 실측 요청이 있으면 그 다음 일과
# 작업 카드, 없으면 믿집 밖 조사(이미 맡겼으면 그 결과)
NONE_NOTE = (
    "추천할 업체가 0곳이라 업체 추천 카드는 보이지 않았어요(카드를 보였다고 말하지 마요). 까닭(why)과 다음 할 일"
    "(next) 하나를 짧게 말해요."
)
NEXT_LIVE = "진행 중인 실측 요청을 이어 가요: {steps}"
NEXT_OUTSIDE = "믿집 밖 공개 페이지에서 찾아볼지 한 번 물어요(start_research). 고객이 말하지 않은 다른 지역은 먼저 권하지 않아요"
NEXT_LOOKED = "믿집 밖 업체 조사를 이미 맡겼어요(진행 · 결과는 get_research)"


async def no_picks(s, tc: ToolCtx, pid: uuid.UUID, model: dict) -> ToolOut:
    """0곳 업체 추천의 도구 결과: 카드 없이 까닭 · 다음 할 일(진행 중인 요청이 있으면 작업 카드도)."""
    from app.assistant import research
    from app.schedule import service as schedule_service

    o = await schedule_service.overview_for(s, tc.user, pid, tc.today)
    steps = cards.visits_next(o)
    if steps:
        nxt = NEXT_LIVE.format(steps=steps)
    elif await research.outside_lately(s, tc.user.id, pid, tc.now):
        nxt = NEXT_LOOKED
    else:
        nxt = NEXT_OUTSIDE
    note = " ".join(x for x in (model.get("note"), NONE_NOTE) if x)
    task = cards.visit_task(pid, o, tc.now) if steps else None
    return ToolOut(data={**model, "next": nxt, "note": note}, task=task)


ELSEWHERE_NOTE = (
    "집 지역({home})이 아닌 {there} 업체를 읽기만 했어요. 이 업체들에는 지금 실측 요청을 보낼 수 없어요(실측 요청은 집 "
    "지역 업체에만). 고객이 집 지역을 바꾸려 하면 propose_home_info의 sgg로 승인 카드를 만들어요."
)
ELSEWHERE_LOCKED = {
    "live": " 지금은 실측 요청이 진행 중이라 집 정보가 잠겨 있어요. 보낸 요청을 모두 취소하면 지역을 바꿀 수 있어요.",
    "quoted": " 업체 견적서가 온 뒤라 집 지역은 바꿀 수 없어요.",
}


async def _elsewhere(s, tc: ToolCtx, p, trade: str, sido: str, sgg: str) -> ToolOut:
    """다른 구 업체 읽기만(리드 결정 11-22, QA r3 s1 B1 · B5): 그 구 업체를 이 집 조건 · 같은 점수(calc.vendor_pick)로
    3곳 고른다. 이름표를 주지 않고(요청할 수 없게), 카드는 보기만(카드 id의 '@' = 지난 카드 꼴, 단추 없음)."""
    from app.assistant.schemas import CardOut, VendorPick, VendorPicksData
    from app.calc import vendor_pick
    from app.shared.regions import region_label
    from app.visit import service as visit_service

    got = await visit_service.vendors_elsewhere(s, tc.user, p.id, trade, sido, sgg)
    live, quoted = await visit_service.lock_hold(s, p.id) if p.locked else (0, False)
    by_id = {c.vendor_id: c for c in (*got["local"], *got["nearby"])}
    cands = [
        vendor_pick.Candidate(
            vendor_id=str(c.vendor_id),
            name=c.name,
            local=local,
            estimate_total=c.estimate_total,
            vs_standard_pct=None if c.vs_standard_pct is None else int(c.vs_standard_pct),
            rating=None if c.rating is None else float(c.rating),
            review_count=c.review_count or 0,
            done_count=c.done_count or 0,
            instant=bool(c.instant_badge),
        )
        for local, rows in ((True, got["local"]), (False, got["nearby"]))
        for c in rows
        if c.state == "ok"
    ]
    there = region_label(sido, sgg)
    picks = []
    for i, x in enumerate(vendor_pick.pick(cands), 1):
        c = by_id[uuid.UUID(x.c.vendor_id)]
        picks.append(
            VendorPick(
                ref=f"{sgg}-{i}",  # 이 대화 이름표가 아니에요(요청 단추 없음)
                vendor_id=c.vendor_id,
                name=c.name,
                rating=None if c.rating is None else float(c.rating),
                reviews=c.review_count or 0,
                done_jobs=c.done_count or 0,
                estimate_won=c.estimate_total or 0,
                reasons=[r for r in vendor_pick.reasons(x) if "표준" not in r],
                badge="바로 확정" if c.instant_badge else None,
                picked=False,
                href=cards.href(p.id, "/vendors"),
            )
        )
    basis = [f"{sgg}에서 일하고 이 공정을 해요", *cards.PICK_BASIS[1:]]
    data = VendorPicksData(
        area_name=sgg, picks=picks, basis=basis, more_href=cards.href(p.id, "/vendors")
    )
    card = CardOut(
        card_id=f"picks-{trade}@{sgg}",  # '@' 카드는 화면이 보기만(고르기 · 요청 단추 없음)으로 그려요
        kind="vendor_picks",
        data=data.model_dump(mode="json"),
        say=f"{sgg} 업체예요. 집 지역이 아니라서 보기만 할 수 있어요." if picks else None,
    )
    lock = "quoted" if quoted else "live" if live else None
    note = ELSEWHERE_NOTE.format(home=p.region, there=there) + ELSEWHERE_LOCKED.get(lock or "", "")
    model = {
        "area": sgg,
        "region": there,
        "trade": trade,
        "state": "보기만 해요",
        "basis": basis,
        "picks": [
            {
                "name": x.name,
                "rating": x.rating,
                "reviews": x.reviews,
                "done_jobs": x.done_jobs,
                "estimate_won": x.estimate_won,
                "reasons": x.reasons,
                "instant": x.badge is not None,
            }
            for x in picks
        ],
        "count": len(picks),
        "note": note,
    } | cards.estimate_range(picks)
    return ToolOut(data=model, cards=[card] if picks else [])


class SlotsIn(BaseModel):
    ref: str  # 업체 이름표(v…, 요청 전) 또는 실측 요청 이름표(m…, 업체가 기간을 답한 뒤)
    prefer: Literal["any", "am", "pm"] = "any"
    days: Literal["any", "weekday", "weekend"] = "any"
    more: bool = False  # 다른 시간: 이 대화에서 이미 보인 반나절은 빼고 남은 자리에서


MORE_NONE = "이 대화에서 이미 보인 후보 말고는 업체 기간에 남은 반나절이 없어요."
MORE_NOTE = "이 대화에서 이미 보인 반나절은 빼고 남은 자리에서 골랐어요."


def shown_halves(tc: ToolCtx, visit_id: str) -> frozenset[tuple[date, str]]:
    """이 대화에서 이미 보인 그 요청의 반나절 후보(이름표 s…의 날 · 반나절, 먼저 말 걸기 카드 포함)."""
    return frozenset(
        (date.fromisoformat(str(it["day"])), str(it["half"]))
        for it in tc.refs.items.values()
        if it.get("kind") == "slot" and str(it.get("visit_id")) == visit_id
    )


@tool(
    "vendor_free_slots",
    surface="customer",
    kind="read",
    status="실측 시간을 찾고 있어요",
    description="실측 시간 후보를 찾아요. ref는 꼭 넣어요: 요청 전에는 업체 이름표(v1…, recommend_vendors 결과)로 "
    "희망 기간 후보(r1~r2), 업체가 기간을 답한 뒤에는 실측 요청 이름표(m1…, today_tasks · compare_quotes 결과)로 "
    "반나절 후보(s1~s3). prefer는 고객이 말한 편한 반나절, days는 평일 · 주말이에요. 고객이 다른 시간 · 다른 날을 "
    "더 보고 싶어 하면 more=true: 이 대화에서 이미 보인 반나절은 빼고 업체 기간에 남은 자리(오후 포함)에서 골라요.",
    model=SlotsIn,
    schema=obj(
        {
            "ref": {"type": "string", "description": "업체 이름표 v… 또는 실측 요청 이름표 m…"},
            "prefer": {"type": "string", "enum": ["any", "am", "pm"]},
            "days": {"type": "string", "enum": ["any", "weekday", "weekend"]},
            "more": {
                "type": "boolean",
                "description": "이미 보인 후보 말고 다른 반나절을 볼 때 true(업체가 기간을 답한 뒤)",
            },
        },
        required=["ref", "prefer", "days"],
    ),
)
async def vendor_free_slots(tc: ToolCtx, a: SlotsIn) -> ToolOut:
    pid = pid_of(tc)
    kind = (tc.refs.items.get(a.ref) or {}).get("kind")
    async with SessionLocal() as s:
        if kind == "visit":
            v = tc.refs.get(a.ref, "visit")
            skip = shown_halves(tc, str(v["id"])) if a.more else frozenset()
            card, model = await cards.visit_slots(
                s,
                tc.user,
                pid,
                uuid.UUID(v["id"]),
                tc.now,
                tc.refs,
                prefer=a.prefer,
                days=a.days,
                skip=skip,
                said=tc.text,
            )
            if skip and model.get("status") == "offered":  # 다른 시간(QA r3 c1 6턴)
                model["note"] = MORE_NOTE if model["candidates"] else MORE_NONE
                if not model["candidates"]:  # 빈 카드 대신 사실만
                    return ToolOut(data=model)
        else:  # 업체 이름표가 아니면 RefTable.get이 모르는 이름표 오류(힌트에 필요한 종류)
            vend = {**tc.refs.get(a.ref, "vendor"), "ref": a.ref}
            card, model = await cards.wishes(
                s, tc.user, pid, vend, tc.today, tc.refs, prefer=a.prefer, days=a.days
            )
    return ToolOut(data=model, cards=[card])


@tool(
    "compare_quotes",
    surface="customer",
    kind="read",
    status="견적서를 놓고 보고 있어요",
    description="받은 실측 견적서를 업체끼리 견줘요(합계 · 앞 판과 차액 · 가견적과 차이 · 기간 · 유효기간 · "
    "포함 항목). 업체 이름표는 m1…이에요. 업체가 적은 칸은 자료예요. count는 받은 견적서 수, waiting은 견적서를 "
    "기다리는 업체 수예요. 받은 견적서가 없으면 카드 없이 note만, 한 곳이면 비교가 아니라 그 견적서 카드예요.",
    model=TradeIn,
    schema=obj({"trade": TRADE}),
)
async def compare_quotes(tc: ToolCtx, a: TradeIn) -> ToolOut:
    dobae_only(a.trade)
    async with SessionLocal() as s:
        card, model = await cards.compare(s, tc.user, pid_of(tc), a.trade, tc.today, tc.refs)
        task = await cards.visit_task_for(s, tc.user, pid_of(tc), tc.today, tc.now)
    return ToolOut(data=model, cards=[card] if card is not None else [], task=task)


@tool(
    "get_schedule",
    surface="customer",
    kind="read",
    status="공사 날짜를 보고 있어요",
    description="확정한 업체의 공사 날짜: 수락 기다리는 날짜(제안 이름표 p1…) · 겹침 · 지금 날짜 상태 · 확정 공정표"
    "(period: 처음 · 끝 · 줄마다 업체 공사 · 자연 건조 · 입주 청소 · 고객이 직접 할 일의 날짜, 날마다 이름).",
    model=NoArgs,
    schema=obj({}),
)
async def get_schedule(tc: ToolCtx, _: NoArgs) -> ToolOut:
    async with SessionLocal() as s:
        card, model = await cards.schedule(s, tc.user, pid_of(tc), tc.today, tc.refs)
    return ToolOut(data=model, cards=[card] if card else [])


@tool(
    "today_tasks",
    surface="customer",
    kind="read",
    status="오늘 정할 일을 보고 있어요",
    description="오늘 정할 일: 승인 기다리는 카드 · 지금 할 일 · 고객 차례인 업체(m1…) · 기다리는 업체. "
    "news는 이틀 안 안 읽은 알림이에요(카드에는 보이지 않고 종 알림에 있어요).",
    model=NoArgs,
    schema=obj({}),
)
async def today_tasks(tc: ToolCtx, _: NoArgs) -> ToolOut:
    async with SessionLocal() as s:
        card, model = await cards.today(s, tc.user, pid_of(tc), tc.today, tc.now, tc.refs)
        task = await cards.visit_task_for(s, tc.user, pid_of(tc), tc.today, tc.now)
    # 빈 카드는 보내지 않아요(QA r3 s6 B3). 새 알림(news)은 카드에 보이지 않아서 세지 않아요(2026-11-23 사용자)
    if not any(card.data.get(k) for k in ("todo", "waiting", "know")):
        return ToolOut(data={**model, "note": TODAY_EMPTY}, task=task)
    return ToolOut(data=model, cards=[card], task=task)


TODAY_EMPTY = "오늘 정할 일 · 기다리는 일이 없어요(빈 카드는 보이지 않았어요)."


ShowKind = Literal[
    "home_info", "standard_quote", "vendor_picks", "quote_compare", "schedule", "today"
]


class ShowIn(BaseModel):
    kind: ShowKind


@tool(
    "show_card",
    surface="customer",
    kind="read",
    status="카드를 불러오고 있어요",
    description="화면 카드 하나를 다시 보여 줘요(집 정보 · 표준견적서 · 업체 추천 · 견적서 비교 · 공사 날짜 · 오늘). "
    "결과는 지금 다시 센 카드의 핵심 값이에요(업체 추천이면 몇 곳 · 어느 업체). 말은 이 값으로 해요. 보일 것이 없으면(업체 "
    "0곳 · 받은 견적서 없음) 카드 없이 까닭만 와요.",
    model=ShowIn,
    schema=obj(
        {
            "kind": {
                "type": "string",
                "enum": [
                    "home_info",
                    "standard_quote",
                    "vendor_picks",
                    "quote_compare",
                    "schedule",
                    "today",
                ],
            }
        }
    ),
)
async def show_card(tc: ToolCtx, a: ShowIn) -> ToolOut:
    pid = pid_of(tc)
    async with SessionLocal() as s:
        if a.kind == "home_info":
            card, model = await cards.home(s, tc.user, pid)
        elif a.kind == "standard_quote":
            card, model = await cards.standard(s, tc.user, pid)
        elif a.kind == "vendor_picks":
            card, model = await cards.vendor_picks(s, tc.user, pid, "dobae", tc.refs)
            if not model["picks"]:  # 0곳: 빈 카드 대신 까닭 · 다음 할 일(QA r6 c3 H1)
                out = await no_picks(s, tc, pid, model)
                return ToolOut(data={"shown": None, **out.data}, task=out.task)
        elif a.kind == "quote_compare":
            card, model = await cards.compare(s, tc.user, pid, "dobae", tc.today, tc.refs)
            if card is None:  # 받은 견적서가 없으면 빈 카드 대신 사실(기다리는 업체 수)
                return ToolOut(data={"shown": None, **model})
        elif a.kind == "schedule":
            card, model = await cards.schedule(s, tc.user, pid, tc.today, tc.refs)
        else:
            card, model = await cards.today(s, tc.user, pid, tc.today, tc.now, tc.refs)
    if card is None:
        raise ToolError("no_card", "보여 줄 카드가 아직 없어요.")
    return ToolOut(data=shown_of(a.kind, model), cards=[card])


# show_card가 모델에 돌려줄 보인 카드의 핵심 값(카드 종류마다 칸, QA r6 c3 H1: {"shown": kind}만 받아 0곳 카드를
# '두 업체 카드'로 말함). 값은 카드를 만든 그대로(계산 엔진 · DB)이고, 큰 칸(표준견적서 줄 · 근거 글)은 뺀다
SHOWN: dict[str, tuple[str, ...]] = {
    "home_info": ("facts", "locked"),
    "standard_quote": ("trades", "total", "days"),
    "vendor_picks": ("area", "count", "estimate_low_won", "estimate_high_won", "note"),
    "quote_compare": ("count", "waiting", "gap_won", "note"),
    "schedule": ("final_version", "deals", "period"),
    "today": ("todo", "waiting", "news"),
}
SHOWN_ROWS: dict[str, tuple[str, tuple[str, ...]]] = {
    "vendor_picks": ("picks", ("ref", "name", "estimate_won", "instant", "proposed")),
    "quote_compare": ("cols", ("ref", "vendor_name", "status", "version", "total")),
}


def shown_of(kind: str, model: dict) -> dict:
    """보인 카드의 핵심 값: {"shown": 종류, 칸…}. 목록 칸(업체 · 견적서)은 줄마다 이름표 · 이름 · 금액만."""
    got: dict = {"shown": kind}
    got |= {k: model[k] for k in SHOWN.get(kind, ()) if model.get(k) not in (None, "", [], {})}
    if kind in SHOWN_ROWS:
        key, cols = SHOWN_ROWS[kind]
        got[key] = [{c: row[c] for c in cols if c in row} for row in model.get(key) or []]
    return got


# ---- 물은 갈래를 고르기 칩으로(QA r6 c1 M12: 'A부터 볼까요, B부터 볼까요?'라고 물어도 누를 칩이 없었어요) ----

# 칩 글에 넣지 않는 것: 숫자(금액 · 날짜는 카드 값으로만) · 영어(이름표 · 도구 이름)
CHOICE_BAD = re.compile(r"[0-9A-Za-z]")
CHOICES_SAID = "고르기 칩을 보였어요. 고객이 누르면 그 말(say)이 와요. 칩을 다시 늘어놓지 말고 묻는 말 하나로 맺어요."


class ChoiceOpt(BaseModel):
    label: str = Field(min_length=1, max_length=20)  # 단추 글
    say: str = Field(min_length=1, max_length=40)  # 누르면 비서에게 보낼 고객 말


class ChoicesIn(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    options: list[ChoiceOpt] = Field(min_length=2, max_length=4)


@tool(
    "offer_choices",
    surface="customer",
    kind="read",
    status="고를 것을 준비하고 있어요",
    description="고객에게 둘 이상의 갈래 중 하나를 고르게 물을 때(예: '견적 금액부터 볼까요, 벽지부터 볼까요?') 그 갈래를 "
    "누를 칩으로 같이 보여 줘요. title은 묻는 말(짧게), options는 2~4개: label은 단추 글(10자 안팎), say는 누르면 "
    "비서에게 갈 고객 말('견적 금액부터 볼래요'). 숫자 · 영어는 넣지 않아요. 승인 카드가 아니라 말만 보내요. 고를 "
    "갈래를 묻지 않는 답에는 쓰지 않아요.",
    model=ChoicesIn,
    schema=obj(
        {
            "title": {"type": "string", "description": "묻는 말(40자 안)"},
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": obj(
                    {
                        "label": {"type": "string", "description": "단추 글(20자 안)"},
                        "say": {"type": "string", "description": "누르면 보낼 고객 말(40자 안)"},
                    }
                ),
            },
        }
    ),
)
async def offer_choices(tc: ToolCtx, a: ChoicesIn) -> ToolOut:
    """모델이 정한 갈래를 고르기 칩 카드로(cards.options_card, 한 턴에 한 장: 다시 부르면 바꿔 끼워요). 칩 글은 모델이
    썼으니 숫자 · 영어를 받지 않고 개인정보는 가려요(누르면 고객 말로 다시 검사를 지나요)."""
    texts = [a.title, *(x for o in a.options for x in (o.label, o.say))]
    if any(CHOICE_BAD.search(t) for t in texts):
        raise ToolError(
            "bad_input",
            "고를 것에 넣을 수 없는 글이 있어요.",
            hint="칩 글(title · label · say)에서 숫자 · 영어를 빼고 다시 불러요",
        )
    opts = [(policy.mask_in(o.label), policy.mask_in(o.say), None) for o in a.options]
    if any(not x or not y for x, y, _ in opts):
        raise ToolError(
            "bad_input", "고를 것에 넣을 수 없는 글이 있어요.", hint="칩 글을 다시 써요"
        )
    card = cards.options_card(f"choices-{tc.turn_id}", policy.mask_in(a.title), opts)
    return ToolOut(
        data={"shown": "options", "count": len(opts), "note": CHOICES_SAID}, cards=[card]
    )
