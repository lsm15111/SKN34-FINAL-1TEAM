"""고객 비서 읽기 도구 (계약서 5장): get_home · get_standard_quote · recommend_vendors · vendor_free_slots ·
compare_quotes · get_schedule · today_tasks · show_card · compare_grades(벽지 두 종류 견주기) · market_range(시세 범위).

공사는 세션이 정한 project_id만 쓴다(남의 것은 기능 service가 404). 카드 · 모델용 값은 cards.py가 만든다.
"""

import uuid
from typing import Literal

from pydantic import BaseModel

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


class NoArgs(BaseModel):
    pass


class TradeIn(BaseModel):
    trade: Trade = "dobae"


@tool(
    "get_home",
    surface="customer",
    kind="read",
    status="집 정보를 보고 있어요",
    description="이 공사의 집 정보(지역 · 면적 · 평 · 살면서 공사 · 벽지 · 방 · 공사 시작 희망 · 직접 할 일 · 잠김)를 읽어요.",
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
    description="공공 기준 단가로 믿집이 계산한 표준견적서(부가세 포함 합계 · 큰 줄 · 예상 일수)를 읽어요.",
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
    "포함) · 차액(실크 − 합지) · 금액이 달라지는 줄(벽지 값 · 시공 …)을 보여 줘요. 저장하지 않는 계산이라 지금 "
    "표준견적서와 고른 벽지는 그대로예요. 실크와 합지 중 고민할 때 쓰고, 바꾸고 싶다고 하면 propose_home_info"
    "(grade)로 승인 카드를 만들어요(실측 요청 전만). 표준견적서 대비 %는 없어요.",
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


@tool(
    "recommend_vendors",
    surface="customer",
    kind="read",
    status="업체를 고르고 있어요",
    description="이 집 조건에 맞는 업체 3곳(v1~v3)을 믿집 점수(별점 · 끝낸 공사 · 가견적)로 골라요. "
    "가견적은 업체가 확인한 단가 × 믿집 수량이에요. 업체 연결은 아직 도배(dobae)만이에요.",
    model=TradeIn,
    schema=obj({"trade": TRADE}),
)
async def recommend_vendors(tc: ToolCtx, a: TradeIn) -> ToolOut:
    dobae_only(a.trade)
    async with SessionLocal() as s:
        card, model = await cards.vendor_picks(s, tc.user, pid_of(tc), a.trade, tc.refs)
    return ToolOut(data=model, cards=[card])


class SlotsIn(BaseModel):
    ref: str  # 업체 이름표(v…, 요청 전) 또는 실측 요청 이름표(m…, 업체가 기간을 답한 뒤)
    prefer: Literal["any", "am", "pm"] = "any"
    days: Literal["any", "weekday", "weekend"] = "any"


@tool(
    "vendor_free_slots",
    surface="customer",
    kind="read",
    status="실측 시간을 찾고 있어요",
    description="실측 시간 후보를 찾아요. ref는 꼭 넣어요: 요청 전에는 업체 이름표(v1…, recommend_vendors 결과)로 "
    "희망 기간 후보(r1~r2), 업체가 기간을 답한 뒤에는 실측 요청 이름표(m1…, today_tasks · compare_quotes 결과)로 "
    "반나절 후보(s1~s3). prefer는 고객이 말한 편한 반나절, days는 평일 · 주말이에요.",
    model=SlotsIn,
    schema=obj(
        {
            "ref": {"type": "string", "description": "업체 이름표 v… 또는 실측 요청 이름표 m…"},
            "prefer": {"type": "string", "enum": ["any", "am", "pm"]},
            "days": {"type": "string", "enum": ["any", "weekday", "weekend"]},
        },
    ),
)
async def vendor_free_slots(tc: ToolCtx, a: SlotsIn) -> ToolOut:
    pid = pid_of(tc)
    kind = (tc.refs.items.get(a.ref) or {}).get("kind")
    async with SessionLocal() as s:
        if kind == "visit":
            v = tc.refs.get(a.ref, "visit")
            card, model = await cards.visit_slots(
                s, tc.user, pid, uuid.UUID(v["id"]), tc.now, tc.refs, prefer=a.prefer, days=a.days
            )
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
    description="오늘 정할 일: 승인 기다리는 카드 · 지금 할 일 · 고객 차례인 업체(m1…) · 기다리는 업체 · 새 소식.",
    model=NoArgs,
    schema=obj({}),
)
async def today_tasks(tc: ToolCtx, _: NoArgs) -> ToolOut:
    async with SessionLocal() as s:
        card, model = await cards.today(s, tc.user, pid_of(tc), tc.today, tc.now, tc.refs)
        task = await cards.visit_task_for(s, tc.user, pid_of(tc), tc.today, tc.now)
    return ToolOut(data=model, cards=[card], task=task)


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
    description="화면 카드 하나를 다시 보여 줘요(집 정보 · 표준견적서 · 업체 추천 · 견적서 비교 · 공사 날짜 · 오늘).",
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
            card, _ = await cards.home(s, tc.user, pid)
        elif a.kind == "standard_quote":
            card, _ = await cards.standard(s, tc.user, pid)
        elif a.kind == "vendor_picks":
            card, _ = await cards.vendor_picks(s, tc.user, pid, "dobae", tc.refs)
        elif a.kind == "quote_compare":
            card, model = await cards.compare(s, tc.user, pid, "dobae", tc.today, tc.refs)
            if card is None:  # 받은 견적서가 없으면 빈 카드 대신 사실(기다리는 업체 수)
                return ToolOut(data={"shown": None, **model})
        elif a.kind == "schedule":
            card, _ = await cards.schedule(s, tc.user, pid, tc.today, tc.refs)
        else:
            card, _ = await cards.today(s, tc.user, pid, tc.today, tc.now, tc.refs)
    if card is None:
        raise ToolError("no_card", "보여 줄 카드가 아직 없어요.")
    return ToolOut(data={"shown": a.kind}, cards=[card])
