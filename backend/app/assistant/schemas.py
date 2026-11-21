"""v4 비서 API 모양 (계약서 3장). 사용자 · 공사 · 실측은 서버가 세션 · 경로로 정하고 LLM 출력으로 받지 않는다.

- SSE: ack → status · card · action(여러 번) → token(여러 번) → done(실패면 error). 모든 data에 seq.
- 카드는 kind로 나눈다(CardKind). data 모양은 카드마다 아래 *Data 모델이고, 금액 · 날짜는 계산 엔진 값이다.
- '표준 대비 %'는 카드 · 도구 결과 · 답 어디에도 넣지 않는다(리드 결정).
- 화면 쪽 제안 칸(status.task · card.say · done.chips/suggest · action.kind/status/supersedes · feed.now ·
  board · 업체 checklists/today)은 계약서 3장 '화면 제안 칸'에 넣은 것 · 뺀 것을 적었다.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.agent.v3.schemas import TEXT_MAX

Surface = Literal["customer", "vendor"]
Mode = Literal["llm", "free"]
CardKind = Literal[
    "home_info", "standard_quote", "vendor_picks", "visit_slots", "quote_compare", "schedule",
    "knowledge", "answer", "floorplan_links", "today", "vendor_brief", "quote_checklist",
    "extra", "notice",  # 07 자동화: 추가 금액 · 이웃 안내문 초안
]  # fmt: skip
ActionKind = Literal[
    "home_info", "visit_request", "visit_slot", "vendor_confirm", "dates_accept", "delay_accept",
    "date_change", "window_answer", "decline", "dates",
    "extra_answer", "work_check", "visit_again",  # 07 자동화
]  # fmt: skip
ActionStatus = Literal["proposed", "approved", "executed", "rejected", "expired", "failed"]
TurnStatus = Literal["running", "done", "stopped", "failed"]
Source = Literal["calc", "ai", "guide"]  # 출처 이름표: 믿집 계산 · AI 답변 · 믿집 안내
Half = Literal["am", "pm"]
ClientKey = Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")]
Choice = Annotated[str, Field(min_length=1, max_length=40)]


# ---- 들어오는 몸통 ----


class TurnContextIn(BaseModel):
    """카드에서 고른 것. LLM에는 이 대화에서 도구가 준 ref(v1 · s2 …)만 가고 모르는 값은 버린다."""

    card_id: str | None = Field(
        default=None,
        max_length=64,
        description="보던 카드 id(slots- · brief- · dates- + id는 42자)",
    )
    choice: Choice | Annotated[list[Choice], Field(max_length=5)] | None = Field(
        default=None, description="고른 ref 하나 또는 여러 개(5개까지)"
    )


class TurnIn(BaseModel):
    project_id: uuid.UUID
    client_key: ClientKey
    text: str = Field(min_length=1, max_length=TEXT_MAX)
    context: TurnContextIn | None = None


class VendorTurnIn(BaseModel):
    visit_id: uuid.UUID | None = Field(default=None, description="보던 요청(비우면 작업함 대화)")
    client_key: ClientKey
    text: str = Field(min_length=1, max_length=TEXT_MAX)
    context: TurnContextIn | None = None


class ApproveIn(BaseModel):
    client_key: ClientKey | None = Field(
        default=None, description="누름마다 하나(기록용). 같은 행동의 두 번째 승인은 같은 결과(200)"
    )
    seen: str | None = Field(
        default=None, max_length=40, description="화면이 본 target_ver. 다르면 409 stale"
    )


# ---- 카드 data (kind마다) ----


class NameWon(BaseModel):
    name: str
    won: int


class HomeArea(BaseModel):
    m2: Decimal
    basis: Literal["supply", "exclusive"]
    pyeong: Decimal | None = Field(default=None, description="표시용 평(계산 엔진)")


class FieldChange(BaseModel):
    label: str
    before: str | None
    after: str


Demolition = Literal["full", "partial", "none"]


class HomeInfoData(BaseModel):
    phase: Literal["confirm"] = "confirm"
    facts: list[str] = Field(description="집 요약 줄(코드 값)")
    area: HomeArea | None = None
    demolition: Demolition | None = Field(
        default=None,
        description="철거 범위(모은 조건 demolition): full 전체 철거 · partial 부분 · none 안 함. "
        "전체 철거면 표준견적서가 리모델링 기준이에요",
    )
    changes: list[FieldChange] = Field(default=[], description="제안한 바뀜(승인 전)")
    action_id: uuid.UUID | None = None
    saved: bool = False
    locked: bool = Field(default=False, description="실측을 요청해 더 고칠 수 없음")


class StandardQuoteData(BaseModel):
    total_won: int = Field(description="부가세 포함")
    label: str
    lines: list[NameWon]
    days: Decimal | None = Field(default=None, description="예상 공사 일수(계산 엔진)")
    partial: bool = False
    href: str


class VendorPick(BaseModel):
    ref: str
    vendor_id: uuid.UUID
    name: str
    rating: float | None
    reviews: int
    done_jobs: int
    estimate_won: int = Field(description="가견적(부가세 포함, 업체가 확인한 단가 × 믿집 수량)")
    reasons: list[str] = Field(description="점수 항목 틀 글(AI가 쓰지 않음, 표준 대비 % 없음)")
    badge: str | None = None
    picked: bool
    href: str


class VendorPicksData(BaseModel):
    area_name: str
    picks: list[VendorPick]
    basis: list[str]
    more_href: str


class DateRange(BaseModel):
    start: date
    end: date


class WishOut(BaseModel):
    ref: str
    start: date
    end: date
    open_count: int


class SlotCandidate(BaseModel):
    ref: str
    vendor_name: str
    day: date
    half: Half
    why: list[str] = Field(
        description="이 후보의 까닭(코드 사실을 화면 말로: 가장 빠른 날이에요 · 평일이에요 · 말한 시간대예요 …)"
    )


# 업체가 쓴 자유 글(벽지 사양 · 다른 날 제안 메모 · 날짜 바꾼 까닭)은 카드의 '업체가 적은 말' 칸에만 짧게 둔다.
# 비서 문장 · 요약 · 버튼 문구 · 모델 값에는 넣지 않는다(주입 방어, policy.vendor_note)
VENDOR_NOTE_DESC = (
    "업체가 적은 말(업체가 쓴 글 그대로, 연락처 가림 · 한 줄 · 40자까지). 화면은 이 칸에만 보여요"
)


class VisitSlotsData(BaseModel):
    vendor_name: str
    window: DateRange | None = Field(description="업체가 답한 기간(요청 전이면 비움)")
    candidates: list[SlotCandidate] = Field(default=[], description="요청 뒤 반나절 후보")
    wishes: list[WishOut] = Field(default=[], description="요청 전 희망 기간 후보")
    chosen: str | None = None
    instant: bool = False
    calendar_href: str
    vendor_note: str | None = Field(default=None, description=VENDOR_NOTE_DESC)


class CompareFileOut(BaseModel):
    kind: Literal["pdf", "image", "sheet"]
    label: str
    href: str


class VersionDiff(BaseModel):
    from_version: int
    diff_won: int


class CompareCol(BaseModel):
    ref: str
    visit_id: uuid.UUID
    vendor_name: str
    state: Literal["quoted", "waiting"]
    version: int | None = None
    received_on: date | None = None
    total_won: int | None = None
    changed: VersionDiff | None = Field(default=None, description="앞 판과 차액(계산 엔진)")
    diff_vs_estimate_won: int | None = None
    days: int | None = None
    valid_until: date | None = None
    valid_soon: bool = False
    expired: bool = False
    demolish: bool | None = None
    waste: bool | None = None
    vendor_note: str | None = Field(
        default=None, description=VENDOR_NOTE_DESC + " (견적서의 벽지 사양 칸)"
    )
    warranty_months: int | None = None
    file: CompareFileOut | None = None
    wait_note: str | None = None
    chosen: bool = Field(default=False, description="고객이 이 업체로 확정함")
    chat_href: str | None = Field(
        default=None, description="이 업체와 열린 믿집 채팅(/chat/{id}, 실측이 확정되면 열려요)"
    )


class QuoteCompareData(BaseModel):
    cols: list[CompareCol]
    gap_won: int | None = Field(description="받은 견적서 합계 차이(2곳 이상, 계산 엔진)")
    ask_chips: list[str] = []
    href: str
    decided: bool = Field(
        default=False, description="이 공정을 이미 확정함(확정 단추를 두지 않아요)"
    )


class LinkOut(BaseModel):
    label: str
    href: str


class ScheduleDay(BaseModel):
    day: date
    am: str | None
    pm: str | None
    off: bool = False


class ScheduleData(BaseModel):
    phase: Literal["dates", "final"]
    vendor_name: str
    start: date
    end: date
    work_days: int
    days: list[ScheduleDay]
    conflicts: list[str] = []
    plan_version: int
    href: str
    ics_href: str | None = None
    vendor_note: str | None = Field(
        default=None, description=VENDOR_NOTE_DESC + " (날짜를 바꾼 까닭)"
    )
    proposal_ref: str | None = Field(
        default=None,
        description="수락 기다리는 공사 날짜 제안 이름표(p…, phase dates일 때). "
        "[이 날짜로 수락]은 choice '<proposal_kind>:<proposal_ref>'",
    )
    proposal_kind: Literal["dates_accept", "delay_accept"] | None = Field(
        default=None,
        description="처음 올린 날짜면 dates_accept, 수락한 뒤 바뀐 날짜면 delay_accept",
    )
    action_id: uuid.UUID | None = Field(
        default=None,
        description="이 날짜의 수락 승인 카드가 열려 있으면 그 행동 id. 그때는 카드 단추(proposal_ref · "
        "proposal_kind)를 비워 수락 단추가 승인 카드 하나만 남아요",
    )
    chats: list[LinkOut] = Field(
        default=[], description="공사 업체와 열린 믿집 채팅(업체에 물어볼 때 누를 곳)"
    )


class CheckItem(BaseModel):
    key: str
    label: str
    done: bool = False


class KnowledgeData(BaseModel):
    title: str
    lines: list[str]
    source: str
    checklist: list[CheckItem] = []
    href: str | None = None


class AnswerData(BaseModel):
    text: str
    src: Source
    links: list[LinkOut] = []


class FloorLink(BaseModel):
    label: str
    href: str
    source: str


class FloorplanLinksData(BaseModel):
    complex: str
    links: list[FloorLink]
    note: str


TodayIcon = Literal["doc", "calendar", "file", "chat", "bulb", "inbox"]


class RowAction(BaseModel):
    label: str
    href: str | None = None
    say: str | None = Field(default=None, description="누르면 비서에게 보낼 말")
    primary: bool = False
    choice: Choice | None = Field(
        default=None,
        description="누르면 say와 함께 보낼 카드 고르기(context.choice, 업체 공사 날짜 'dates:d#,n#'). "
        "이름표는 이 대화의 표에 있다",
    )


class TodayRow(BaseModel):
    id: str
    icon: TodayIcon
    title: str
    sub: str | None = None
    due: bool = False
    action: RowAction | None = None


class TodayData(BaseModel):
    date: date
    nudge_id: uuid.UUID | None = None
    dismissed: bool = False
    todo: list[TodayRow]
    waiting: list[TodayRow]
    news: list[TodayRow]
    know: list[TodayRow] = []


class FitRow(BaseModel):
    key: Literal["trade", "area", "schedule", "paper"]
    label: str
    ok: bool = Field(description="맞음(state ok)일 때만 참")
    text: str
    state: Literal["ok", "check", "no"] = Field(
        description="맞음 · 확인 필요(고객이 아직 정하지 않음, 벽지 미정) · 맞지 않음"
    )


class BriefEstimate(BaseModel):
    total_won: int
    basis: str


class BriefDay(BaseModel):
    day: date
    off: bool = False


class BriefHalves(BaseModel):
    days: list[BriefDay]
    taken: dict[str, str] = Field(description="잡힌 칸 'YYYY-MM-DD:am' → 동네(고객 정보 없음)")
    open_count: int


class BriefSuggest(BaseModel):
    action_id: uuid.UUID
    start: date
    end: date
    excluded: list[date]
    instant: bool
    open_count: int


class BriefWindow(BaseModel):
    """답할 기간 후보 하나(계산 엔진 calc.slots.best_windows). 단추는 choice 'window_answer:<ref>'."""

    ref: str
    start: date
    end: date
    excluded: list[date]
    open_count: int


class VendorBriefData(BaseModel):
    visit_id: uuid.UUID
    title: str
    facts: list[str]
    fit: list[FitRow]
    estimate: BriefEstimate | None
    halves: BriefHalves
    suggest: BriefSuggest | None
    windows: list[BriefWindow] = Field(
        default=[], description="답할 기간 후보 w…(요청함일 때, 첫 것이 suggest와 같은 기간)"
    )
    due_at: datetime | None
    memo: str | None = Field(description="고객이 남긴 말(자료, 가림)")
    sentence: str | None = Field(default=None, description="AI 문장 하나(없으면 비움)")
    diy: list[str] = Field(
        default=[],
        description="고객이 직접 할 일(반셀프 칩 화면 말, 요청 때 고객이 승인해 고정한 사본 · 자료)",
    )


class ChecklistRow(BaseModel):
    key: str
    label: str
    state: Literal["ok", "check", "missing"]
    hint: str | None = None


class FieldValue(BaseModel):
    label: str
    value: str | None


class PrevQuote(BaseModel):
    version: int
    total_won: int


class QuoteChecklistData(BaseModel):
    visit_id: uuid.UUID
    items: list[ChecklistRow]
    fields: list[FieldValue]
    easy_miss: list[str]
    prev: PrevQuote | None


class VendorTodayData(BaseModel):
    date: date
    rows: list[TodayRow]


class ExtraData(BaseModel):
    """추가 금액 카드(07 4.3). 금액은 schedule service가 계산 엔진으로 만든 값 그대로예요.
    단추는 choice 'extra_answer:<ref>'(승인) · '<ref>,reject'(거절) · '<ref>,ask'(채팅으로 묻기)로 승인 카드를 만들어요."""

    ref: str = Field(description="추가 금액 이름표(x…)")
    extra_id: uuid.UUID
    deal_id: uuid.UUID
    vendor_name: str
    trade: str = Field(description="공정 화면 말(도배 · 목공)")
    title: str = Field(description="한 일(업체가 적은 칸, 가림 · 한 줄 · 40자)")
    vendor_note: str | None = Field(
        default=None, description=VENDOR_NOTE_DESC + " (추가 금액 이유)"
    )
    version: int = Field(description="판 번호(업체가 고치면 새 판)")
    answer: Literal["pending", "asked", "approved", "rejected"]
    supply_won: int
    vat_won: int
    total_won: int = Field(description="부가세 포함")
    vat_label: str = Field(description="업체가 적은 방식: 부가세 포함 · 별도 · 면세")
    deal_total_won: int | None = Field(default=None, description="확정 금액(부가세 포함)")
    grand_total_won: int | None = Field(
        default=None, description="지금 공사 금액(확정 금액 + 승인한 추가 금액)"
    )
    after_total_won: int | None = Field(default=None, description="승인하면 공사 금액")
    photo_count: int = 0
    href: str
    chat_href: str | None = Field(
        default=None, description="이 업체와 열린 믿집 채팅(사진 · 까닭을 물어볼 때 누를 곳)"
    )


class NoticeData(BaseModel):
    """이웃 안내문 초안(07 4.4): 코드 틀이고 LLM을 쓰지 않아요. 공사 날짜는 공정표 값, 동 · 호수 · 이름 ·
    연락처는 빈칸(○○)이에요. 믿집은 보내지 않아요."""

    title: str
    text: str = Field(description="안내문 글('-합니다'체)")
    start: date | None = None
    end: date | None = None
    blanks: list[str] = Field(default=[], description="고객이 채울 칸")
    note: str
    style_exempt: bool = Field(
        default=True,
        description="이웃에게 붙이는 글이라 '-합니다'체예요. 화면 문체('-해요') 검사에서 이 카드 본문은 빼요",
    )


class CardOut(BaseModel):
    """카드 하나. 같은 card_id면 화면이 바꿔 끼운다. data는 kind의 *Data 모양(JSON)."""

    card_id: str
    kind: CardKind
    data: dict[str, Any]
    say: str | None = Field(default=None, description="카드 위 한 줄(정해 둔 글)")


# ---- 작업 카드 · 제안 행동 ----

TaskState = Literal["running", "waiting", "done", "failed", "cancelled"]
RowState = Literal["running", "waiting", "done", "failed", "cancelled", "need"]


class TaskRow(BaseModel):
    label: str
    state: RowState
    text: str
    note: str | None = None


class TaskOut(BaseModel):
    task_id: str
    title: str
    state: TaskState
    at: datetime
    due: datetime | None = None
    rows: list[TaskRow] = []
    sources: list[str] = []
    link: LinkOut | None = None
    error: str | None = None


class AmountRow(BaseModel):
    label: str
    won: int


class DiffOut(BaseModel):
    label: str
    from_won: int
    to_won: int
    diff_won: int


class SummaryRow(BaseModel):
    label: str
    value: str
    sub: str | None = None


class ActionSummary(BaseModel):
    """무엇 · 얼마 · 어느 버전. 금액 · 차액은 계산 엔진 값(부가세 포함)."""

    title: str
    amount_won: int | None = None
    amounts: list[AmountRow] = []
    diff: DiffOut | None = None
    version: str | None = None
    rows: list[SummaryRow] = []
    file: LinkOut | None = None
    note: str | None = None
    approve_label: str


class ActionResult(BaseModel):
    text: str
    href: str | None = None
    label: str | None = None


class ActionOut(BaseModel):
    action_id: uuid.UUID
    kind: ActionKind
    status: ActionStatus
    summary: ActionSummary
    target_ver: str | None
    expires_at: datetime
    decided_at: datetime | None = None
    executed_at: datetime | None = None
    error_code: str | None = Field(
        default=None, description="실패 코드. 만료면 까닭(due · replaced)"
    )
    result: ActionResult | None = None
    supersedes: uuid.UUID | None = Field(
        default=None, description="판이 바뀌어 새로 만든 행동이면 옛 행동 id(409 quote_changed 뒤)"
    )
    replaced_by: uuid.UUID | None = Field(
        default=None,
        description="같은 대상의 새 제안으로 바뀌어 닫힌 행동(expired · replaced)이면 그 새 행동 id",
    )


# ---- SSE 이벤트(문서용 모양. 실제로는 text/event-stream으로 흐른다) ----


class AckEvent(BaseModel):
    seq: int
    turn_id: uuid.UUID
    chat_id: uuid.UUID
    at: datetime


class StatusEvent(BaseModel):
    seq: int
    text: str
    task: TaskOut | None = None


class TokenEvent(BaseModel):
    seq: int
    text: str


class SuggestOut(BaseModel):
    """다음에 물을 말 하나(코드가 고름). 누르면 say를 비서에게 보낸다. 먼저 말 걸기에서 왔으면 nudge_id."""

    id: str
    text: str = Field(description="제안 한 줄(정해 둔 글 또는 먼저 말 걸기 문장)")
    why: str = Field(description="까닭 한 줄(코드 사실)")
    say: str = Field(description="누르면 비서에게 보낼 말")
    nudge_id: uuid.UUID | None = None


class DoneEvent(BaseModel):
    seq: int
    rev: int
    mode: Mode
    cards: list[str]
    actions: list[uuid.UUID]
    stopped: bool = False
    chips: list[str] = []
    suggest: list[SuggestOut] = Field(default=[], description="다음에 물을 말 0~3개(코드가 고름)")


class ErrorEvent(BaseModel):
    seq: int
    code: str
    message: str


# ---- 대화 기록 · 턴 ----


class TextPart(BaseModel):
    t: Literal["text"] = "text"
    text: str
    src: Source


class CardPart(BaseModel):
    t: Literal["card"] = "card"
    card: CardOut


class TaskPart(BaseModel):
    t: Literal["task"] = "task"
    task: TaskOut


class ActionPart(BaseModel):
    t: Literal["action"] = "action"
    action: ActionOut


class NotePart(BaseModel):
    t: Literal["note"] = "note"
    text: str


class SuggestPart(BaseModel):
    t: Literal["suggest"] = "suggest"
    suggest: SuggestOut


FeedPart = Annotated[
    TextPart | CardPart | TaskPart | ActionPart | SuggestPart | NotePart, Field(discriminator="t")
]


class UserItem(BaseModel):
    id: str
    role: Literal["user"] = "user"
    at: datetime
    text: str


class ErrorOut(BaseModel):
    code: str
    message: str


class AssistantItem(BaseModel):
    id: str
    role: Literal["assistant"] = "assistant"
    at: datetime
    turn_id: uuid.UUID | None
    parts: list[FeedPart]
    done: bool = True
    mode: Mode | None = None
    error: ErrorOut | None = None
    status: str | None = None
    nudge_id: uuid.UUID | None = Field(
        default=None, description="먼저 말 건 줄이면 그 id(열기 · 닫기 API)"
    )
    settled: bool = Field(
        default=False,
        description="할 일이 끝나 닫힌 먼저 말 건 줄('완료'로 남기고 단추 · 다음에 물을 말이 없다)",
    )


FeedItem = Annotated[UserItem | AssistantItem, Field(discriminator="role")]


class FeedPage(BaseModel):
    items: list[FeedItem]
    before: int | None = Field(description="더 앞 쪽을 읽을 커서(없으면 처음)")
    rev: int
    chips: list[str]
    now: datetime


class TurnOut(BaseModel):
    """GET …/turns/{id}: 턴 하나(대화를 다시 열 때 · 끊긴 SSE 다시 읽기)."""

    turn_id: uuid.UUID
    chat_id: uuid.UUID
    surface: Surface
    status: TurnStatus
    mode: Mode
    tool_calls: int
    text: str | None = Field(description="저장한 답 글(검사를 지난 것)")
    cards: list[CardOut]
    actions: list[ActionOut]
    error_code: str | None
    created_at: datetime
    ended_at: datetime | None


class AssistantThreadOut(BaseModel):
    chat_id: uuid.UUID
    rev: int
    updated_at: datetime


MemoryKey = Literal[
    "avail_days", "avail_half", "living", "style", "material", "priority", "pet", "diy"
]


class MemoryOut(BaseModel):
    """비서가 기억하는 것 한 줄(고객이 한 말에서만). 지우면 다음 턴부터 쓰지 않는다."""

    id: uuid.UUID
    key: MemoryKey
    label: str = Field(description="키의 화면 이름(예: 편한 시간)")
    value: str
    evidence_message_id: uuid.UUID
    evidence_quote: str = Field(description="근거로 옮긴 고객 말(가린 글)")
    updated_at: datetime


NudgeTrigger = Literal[
    "visit_offered", "quote_sent", "dates_proposed", "work_eve", "no_pick",
    "visit_requested", "visit_picked", "deal_confirmed",
    "vendor_out", "extra_added", "work_done", "prep_week", "dates_requested", "quote_due",
]  # fmt: skip
NudgeStatus = Literal["pending", "held", "sent", "opened", "dismissed", "expired"]


class NudgeOut(BaseModel):
    """먼저 말 건 줄 하나(열기 · 닫기 응답). 문장은 Haiku(ai) 또는 정해 둔 틀(guide)이다."""

    nudge_id: uuid.UUID
    trigger: NudgeTrigger
    channel: Literal["feed", "notify"]
    status: NudgeStatus
    body: str | None
    src: Literal["ai", "guide"] | None
    action_id: uuid.UUID | None
    sent_at: datetime | None
    acted_at: datetime | None


class BoardMoneyOut(BaseModel):
    label: str
    won: int | None = Field(
        default=None,
        description="확정한 공정은 지금 공사 금액(확정 금액 + 승인한 추가 금액), 아니면 표준견적서(부가세 포함)",
    )
    range: list[int] | None = Field(
        default=None,
        description="[가장 작은 값, 가장 큰 값]. 확정 전 업체 금액(받은 실측 견적서, 없으면 요청 때 고정한 "
        "가견적, 부가세 포함)이 두 곳 이상일 때",
    )
    extra_won: int | None = Field(
        default=None, description="won에 들어간 승인한 추가 금액(부가세 포함, 없으면 비움)"
    )


class BoardVendorRow(BaseModel):
    name: str
    state: RowState
    text: str
    won: int | None = None


class BoardVendors(BaseModel):
    title: str
    rows: list[BoardVendorRow]


class BoardPeriod(BaseModel):
    label: str
    value: str
    sub: str | None = None


class BoardOut(BaseModel):
    project_name: str
    step: int = Field(ge=0, le=6, description="단계 띠 지금 칸(0 집 정보 ~ 6 공사)")
    facts: list[str]
    confirmed: bool
    todo: int
    waiting: int
    money: BoardMoneyOut | None
    vendors: BoardVendors | None
    period: BoardPeriod | None
    docs: list[LinkOut]
    plan_example: bool
    memory: list[MemoryOut] = Field(default=[], description="비서가 기억하는 것(고객 말에서만)")
    today_pin: int


class HealthOut(BaseModel):
    """비서가 지금 LLM으로 답하는지(글 · 키 없음)."""

    mode: Mode
    reason: Literal["ok", "off", "budget", "breaker"]
