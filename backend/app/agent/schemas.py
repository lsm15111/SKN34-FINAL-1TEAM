"""에이전트 입출력 모양. LLM 출력은 이 모델로 검사하고(Structured Outputs), 금액 · 수량 · 날짜는
숫자 대신 슬롯(⟦키⟧)으로만 쓴다. 숫자는 guards가 계산 엔진 값으로 채우고 검사한다(docs/agent/02-agents.md).
"""

from typing import Literal

from pydantic import BaseModel, Field

Route = Literal[
    "coach",
    "dobae",
    "mokgong",
    "both",
    "estimate",
    "schedule",
    "howto",
    "oos_trade",
    "oos_other",
    "chitchat",
    "abuse",
    "unclear",
]
ROUTES: tuple[str, ...] = Route.__args__
Trade = Literal["dobae", "mokgong"]


class GateResult(BaseModel):
    """입구 관문 결과. 답을 쓰지 않는다."""

    route: Route
    topic: str | None = None  # 주제 태그(guide.start …), 분석 · 가중치용
    confidence: float = Field(ge=0, le=1)
    method: Literal["rule", "model", "jev", "ask"]
    ask_choices: list[Route] = Field(default_factory=list, max_length=3)


class CheckQuestion(BaseModel):
    """이해 확인 질문. 버튼 2~3개, 건너뛰기 가능."""

    text: str = Field(max_length=80)
    choices: list[str] = Field(min_length=2, max_length=3)
    answer: int | None = None  # 정답 보기 번호. 의견을 묻는 질문이면 없음


class CoachReply(BaseModel):
    """코치: 답 → 이유 → 확인 질문 1개 → 다음 팁 1개(docs/agent/05-coaching.md 4절)."""

    lead: str = Field(max_length=200)
    why: str | None = Field(default=None, max_length=400)
    steps: list[str] = Field(default_factory=list, max_length=7)
    check_question: CheckQuestion | None = None
    next_tip: str | None = None  # 카드 key
    message_draft: str | None = Field(
        default=None, max_length=600
    )  # 업체 · 이웃에게 보낼 문구 초안
    out_of_scope_note: bool = False  # 범위 밖 공정 — 견적 · 공정표에 아직 없음을 덧붙임
    concepts_introduced: list[str] = Field(default_factory=list, max_length=3)
    cited_keys: list[str] = Field(default_factory=list)


class Question(BaseModel):
    slot: str
    text: str = Field(max_length=120)
    why: str = Field(max_length=120)  # 왜 묻는지 한 줄(가르치기)
    choices: list[str] = Field(default_factory=list, max_length=5)


class SlotUpdate(BaseModel):
    """제안일 뿐이다. 확정은 고객 버튼 또는 명확한 답일 때 chat.service가 한다."""

    slot: str
    value: str
    evidence: str = Field(max_length=120)  # 고객 말 중 근거


class RecipeExplain(BaseModel):
    steps: list[str] = Field(max_length=10)
    changes: list[str] = Field(
        default_factory=list, max_length=6
    )  # 기간 · 금액 · 다른 공정이 바뀌는 것
    ask_vendor: list[str] = Field(default_factory=list, max_length=4)


class Constraint(BaseModel):
    """말 → 공정표 제약. 날짜 계산은 계산 엔진이 한다."""

    kind: Literal[
        "no_weekend", "end_by", "start_after", "avoid_dates", "gap_after", "heating", "quiet_days"
    ]
    value: str  # 날짜(YYYY-MM-DD) · 공정 키 · 일 수


class TradeReply(BaseModel):
    """목공 · 도배 서브에이전트."""

    trade: Trade
    lead: str = Field(max_length=200)
    questions: list[Question] = Field(default_factory=list, max_length=4)
    cautions: list[str] = Field(default_factory=list, max_length=4)
    recipe: RecipeExplain | None = None
    slot_updates_proposed: list[SlotUpdate] = Field(default_factory=list)
    schedule_constraints: list[Constraint] = Field(default_factory=list)
    concepts_introduced: list[str] = Field(default_factory=list, max_length=3)
    cited_keys: list[str] = Field(default_factory=list)


class Note(BaseModel):
    key: str  # 줄 키 · 폭의 이유(qty:area …) · 차이 브리지 단계(vat · cond · qty · price · surcharge · rest)
    text: str = Field(max_length=200)


class QuoteExplain(BaseModel):
    """견적 설명: 금액을 만들지 않고 이유만 쓴다."""

    lead: str = Field(max_length=200)
    line_notes: list[Note] = Field(default_factory=list)
    range_why: list[Note] = Field(default_factory=list)
    bridge_notes: list[Note] = Field(default_factory=list)
    missing: list[Note] = Field(default_factory=list)
    ask_vendor: list[str] = Field(default_factory=list, max_length=4)
    cited_keys: list[str] = Field(default_factory=list)


class Impact(BaseModel):
    trade: str
    text: str = Field(max_length=200)


class ScheduleReply(BaseModel):
    lead: str = Field(max_length=200)
    constraints: list[Constraint] = Field(default_factory=list)
    impacts: list[Impact] = Field(default_factory=list)
    pending_request_id: str | None = None  # 일정 MCP가 만든 승인 대기 건(승인은 고객 버튼)
    notice_draft: str | None = Field(default=None, max_length=600)
    cited_keys: list[str] = Field(default_factory=list)


FindingKey = Literal[
    "ceiling_type",
    "molding_type",
    "baseboard",
    "existing_wallpaper",
    "mold_suspect",
    "lifting",
    "door_count",
    "clutter",
]


class Finding(BaseModel):
    key: FindingKey
    value: str  # 항목별 값 또는 unknown. 값 목록은 photo 쪽 코드가 검사
    confidence: Literal["low", "med", "high"]
    evidence: str = Field(max_length=120)  # 어느 사진 어디에서 봤는지
    needs_user_check: bool = True


class PhotoFindings(BaseModel):
    """사진 판독 초안. 고객이 확인한 값만 브리프에 들어간다(docs/agent/08-photo-docs.md)."""

    space: str
    items: list[Finding]
    retake: list[str] = Field(default_factory=list, max_length=3)
