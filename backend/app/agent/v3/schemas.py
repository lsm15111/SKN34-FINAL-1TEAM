"""v3 에이전트 입출력 모양 (agents.md 4절).

금액 · 수량 · 날짜는 에이전트가 만들지 않는다. 화면에 숫자가 필요하면 CalcBox로 계산 엔진 결과를 옮겨 담고
(`ref`로 어느 값인지 가리킨다), 답 글에는 그 숫자를 쓰지 않는다.
"""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TradeCode = Literal[
    "dobae", "mokgong", "floor", "tile", "bath", "kitchen", "paint", "film", "electric",
    "window", "demolition", "plumbing", "common",
]  # fmt: skip
Route = Literal[
    "guide", "trade", "quote_explanation", "schedule", "multi", "out_of_scope", "ask_back"
]
PolicyFlag = Literal[
    "price", "period", "vendor_reco", "brand_reco", "defect_judgement", "legal_case", "diy",
    "safety", "my_house",
]  # fmt: skip
GateSource = Literal["button", "waiting", "rule", "model"]
View = Literal[
    "home", "start", "standard", "standard_guest", "vendors", "vendor", "visits", "visit_request",
    "pick", "quotes", "plan", "schedule", "thread",
]  # fmt: skip
Stage = Literal["info", "standard", "vendors", "visit", "after_visit", "construction", "done"]
LineState = Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]
SectionSource = Literal["card", "extract", "llm", "template", "calc", "general"]
Mode = Literal["free", "llm"]

TEXT_MAX = 1000  # 질문 길이 (agents.md 8절)


class TurnContext(BaseModel):
    """서버가 로그인 세션으로 정한 값. LLM 출력 · 도구 인자로 바꾸지 않는다."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    chat_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None  # 가이드는 프로젝트 없이도 돈다
    view: View | None = None
    mode: Mode = "free"
    today: date


# ---- 코드가 먼저 읽어 넘기는 프로젝트 사실 (숫자는 모두 계산 엔진 결과 그대로) ----
class StandardLineFact(BaseModel):
    key: str
    name: str
    state: LineState
    qty: float | None = None
    unit: str = ""
    unit_price: int | None = None
    amount: int | None = None
    trade: TradeCode = "dobae"


class StandardFacts(BaseModel):
    total: int
    supply: int
    vat: int
    trades: dict[
        str, int
    ] = {}  # 공정별 합계(부가세 포함, 계산 엔진 값). 공정이 둘 이상일 때 공정 질문에 씀
    lines: list[StandardLineFact] = []
    days: int | None = None  # 계산 엔진 공정 일수(있을 때만)


class PlanBlockFact(BaseModel):
    trade: TradeCode
    ko: str
    start: date
    end: date


class PlanFacts(BaseModel):
    kind: Literal["expected", "final"] = "expected"
    start: date
    end: date
    work_days: int
    blocks: list[PlanBlockFact] = []


class VisitRecommendFact(BaseModel):
    vendor: str
    day: date
    half: Literal["am", "pm"] | None = None
    basis: str  # 계산 엔진이 쓴 산식 글 (예: "1.4(월) − 20일 = 12.15(화)")


class VendorRangeFact(BaseModel):
    vendor: str
    start: date
    end: date


class VisitDraftFacts(BaseModel):
    """실측 일정 초안 재료. 기간 · 추천일은 계산 엔진이 만든다(dev-04)."""

    wish_start: date | None = None
    wish_end: date | None = None
    basis_start: date | None = None  # 공사 시작 희망일
    formula: str = ""  # 예: "공사 시작 희망일 − 28일 ~ − 14일"
    vendors: list[str] = []  # 담은 업체(화면 이름)
    ranges: list[VendorRangeFact] = []  # 업체가 답한 기간
    recommend: VisitRecommendFact | None = None
    blocked: list[str] = []  # holiday · past_date · vendor_range · slot_taken


class EstimateLineGap(BaseModel):
    key: str
    name: str
    diff: int  # 업체 단가 줄 금액 − 비교 대상 (계산 엔진)


class EstimateFacts(BaseModel):
    vendor: str
    total: int
    vs_standard: int | None = None
    lines: list[EstimateLineGap] = []
    separate: list[str] = []  # 따로 받는 줄 이름


class VendorPickFact(BaseModel):
    """업체 추천(코드): 조건 필터 + 계산 엔진 점수로 고른 업체 한 곳. 사유는 정해 둔 틀로 쓴다(LLM 아님)."""

    vendor_id: str
    name: str
    local: bool = True  # 이 구 업체
    estimate_total: int | None = None  # 가견적(계산 엔진)
    vs_standard_pct: int | None = None  # 표준견적서 대비 %(계산 엔진, 음수 = 낮음)
    rating: float | None = None
    review_count: int = 0
    done_count: int = 0
    instant: bool = False  # 바로 확정 가능
    score: float = 0.0  # 계산 엔진 점수(0~1)
    reasons: list[str] = []  # 사유 1~3줄(틀)


class SizeCalcFact(BaseModel):
    """평수 하나로 센 계산 엔진 값(프로젝트가 없거나 질문에 다른 평수가 나올 때). 빈집 · 벽 + 천장 · 전체 기준."""

    label: str  # 화면 이름: '34평' · '전용 84㎡'
    pyeong: float  # 계산 엔진이 센 평(공급 기준)
    area_m2: float
    area_basis: Literal["supply", "exclusive"] = "supply"
    rooms: int
    dobae_total: int  # 기본형(실크) 부가세 포함
    dobae_total_economy: int  # 저가형(합지)
    dobae_days: float  # 반나절 단위 작업 일수
    dobae_days_occupied: float  # 살면서 할 때
    mokgong_total: int | None = None  # 몰딩 + 걸레받이
    mokgong_days: float | None = None
    # 질문에 시작 날짜가 있을 때: 빈집 기준 일을 그날부터 일하는 날(주말 · 공휴일 빼고)에 놓은 첫날 · 끝날
    dobae_dates: tuple[date, date] | None = None
    mokgong_dates: tuple[date, date] | None = None


class GeneralFacts(BaseModel):
    """질문만 보고 코드가 미리 센 계산 엔진 값. 숫자는 모두 calc 결과 그대로."""

    asked: SizeCalcFact | None = None  # 질문에 나온 평수 · ㎡
    examples: list[SizeCalcFact] = []  # 24 · 34 · 44평
    door_set: int | None = None  # 방문 1개 문틀까지(목공 계산, 부가세 포함)
    door_leaf: int | None = None  # 방문 1개 문짝만
    price_ver: str = ""
    start: date | None = None  # 질문에 나온 시작 날짜(서울 기준, 지난 날짜면 다음 해)


class ProjectFacts(BaseModel):
    """에이전트에 넘기는 프로젝트 칸. 동 · 호 · 연락처는 넣지 않는다."""

    stage: Stage = "info"
    area_m2: float | None = None
    area_basis: Literal["supply", "exclusive"] | None = None
    trades: list[TradeCode] = []
    grade: Literal["economy", "basic"] | None = None
    living: Literal["living", "vacant"] | None = None
    start_wish: date | None = None
    standard: StandardFacts | None = None
    plan: PlanFacts | None = None
    visit_draft: VisitDraftFacts | None = None
    estimates: list[EstimateFacts] = []
    vendors: list[VendorPickFact] = []  # 코드가 고른 추천 업체(조건 필터 + 점수), 최대 3곳
    brief: dict[str, str] = {}  # 지금까지 모은 조건(도배 · 목공 브리프 칸)


# ---- 관문 ----
class Choice(BaseModel):
    """되묻기 · 다음 할 일 버튼. 누르면 route · trade가 같이 와서 다시 분류하지 않는다."""

    text: str
    route: Route | None = None
    trade: TradeCode | None = None
    slot: str | None = None
    value: str | None = None
    action: str | None = None  # 화면 이동: standard · plan · vendors · visits_new · start · login


class GateResult(BaseModel):
    route: Route
    trades: list[TradeCode] = []
    policy: list[PolicyFlag] = []
    confidence: float = Field(default=0.0, ge=0, le=1)
    source: GateSource = "rule"
    label: str | None = None  # 분류기 라벨(평가 · 기록용)
    candidates: list[Choice] = []  # ask_back일 때 버튼 2~3개


class Button(BaseModel):
    """화면 버튼으로 온 요청. 관문을 건너뛴다(source=button)."""

    route: Route
    trade: TradeCode | None = None
    slot: str | None = None
    value: str | None = None


# ---- 답 ----
class Sentence(BaseModel):
    text: str
    cites: list[str] = []  # K#### 조각 · card:<id>@<판>


class Section(BaseModel):
    """담당 하나가 낸 묶음. 오케스트레이터는 이것을 다시 쓰지 않고 이어 붙인다."""

    title: str = ""
    sentences: list[Sentence] = []
    caution: Sentence | None = None
    tip: Sentence | None = None
    source: SectionSource = "template"
    route: Route = "guide"
    trade: TradeCode | None = None
    sources: list[dict] = []  # 인용 조각 출처 {ref, title, kind_ko, publisher} (원문 없음)
    table: list[list[str]] = []  # 비교 블록(2칸 줄). 칸 글도 출력 검사를 지난 것만
    steps: bool = False  # 단계 블록(문장이 순서대로인 단계)


class CalcBox(BaseModel):
    """'믿집 계산' 상자. 값은 계산 엔진 결과를 옮긴 것이고 글로 쓰지 않는다."""

    label: str
    ref: str  # 예: standard.lines.demolish · standard.total · plan.range · visit_draft.recommend
    qty: float | None = None
    unit: str = ""
    unit_price: int | None = None
    amount: int | None = None
    in_total: bool = True
    note: str = ""  # 계산 엔진이 준 산식 글(날짜 산식 등)


class DraftCard(BaseModel):
    """실측 일정 요청 초안. 보내기는 고객이 요청서 API로 한다(AI는 보내지 않는다)."""

    wish_start: date | None = None
    wish_end: date | None = None
    vendors: list[str] = []
    formula: str = ""
    recommend: VisitRecommendFact | None = None


class UiCard(BaseModel):
    kind: Literal[
        "calc", "visit_draft", "open_calendar", "grade_preview", "faq", "choices", "next_step",
        "vendor_reco",
    ]  # fmt: skip
    title: str = ""
    text: str = ""
    choices: list[Choice] = []
    calc: list[CalcBox] = []
    draft: DraftCard | None = None
    vendors: list[VendorPickFact] = []  # vendor_reco: 코드가 고른 업체와 사유


class AskSlot(BaseModel):
    trade: TradeCode
    slot: str
    question: str
    options: list[str]


class Trace(BaseModel):
    """화면에 안 보이는 평가 · 기록용 흔적."""

    route: Route = "guide"
    source: GateSource = "rule"
    confidence: float = 0.0
    trades: list[TradeCode] = []
    policy: list[PolicyFlag] = []
    mode: Mode = "free"
    cards: list[str] = []  # id@판
    chunks: list[str] = []
    prompts: list[str] = []
    card_set: str = ""
    parts: list[str] = []  # 오케스트레이터가 나눈 조각 담당
    failed_parts: int = 0
    dropped: list[str] = []  # 출력 검사가 뺀 이유(문장 원문 없음)
    inherited: bool = False  # 이어 묻기라 앞 턴의 공종 · 꼴을 물려받았는지(context.resolve)


class Brief(BaseModel):
    """짧은 답(brief.py): 질문 꼴에 맞춰 먼저 보일 문장 1~3개. 새 글이 아니라 sections · unknown에서 고른 것."""

    form: str = "other"  # 질문 꼴(brief.FORM_KO)
    lines: list[Sentence] = []
    more: int = 0  # '자세히'에만 있는 문장 수(주의 · 팁 포함)


class AgentAnswer(BaseModel):
    sections: list[Section] = []
    calc: list[CalcBox] = []
    cards: list[UiCard] = []
    ask: AskSlot | None = None
    unknown: list[str] = []
    suggest: list[str] = []
    failed: bool = False
    brief: Brief | None = None
    fixed: int = (
        0  # 앞에서부터 먼저 보낸(SSE part) 고정 묶음 수. 화면이 그 묶음 모양을 part와 같게 그려요
    )
    trace: Trace = Trace()

    def plain(self) -> str:
        """대화 표에 남길 글: 묶음 제목 · 문장만 잇는다(카드 · 상자는 뺀다)."""
        out: list[str] = []
        for s in self.sections:
            if s.title:
                out.append(s.title)
            out.extend(x.text for x in s.sentences)
            if s.caution:
                out.append(s.caution.text)
        out.extend(self.unknown)
        return "\n".join(x for x in out if x)
