// v4 비서 API 입구(계약서 '03-agent' 3장). 브라우저에서 불러요(lib/api/chat.ts처럼 /api/* · client.ts).
// - SSE: ack → status · card · action(여러 번) → token(여러 번) → done(실패면 error). 모든 data에 seq가 붙고, 이미 받은 seq 이하는 버려요.
//   POST라 EventSource 대신 fetch 스트림으로 읽어요. 스트림을 열기 전 오류(404 · 409 turn_running · 429)는 ApiError로 던져요.
// - REST: threads/latest · feed · board · today · health · actions(approve · reject) · nudges(open · dismiss) · memory · 업체 브리핑.
// - 먼저 말 걸기(nudges) · 기억(memory)은 다른 담당이 같은 때 만들어요. 계약 모양으로 부르고, 404면 '없음'으로 돌려줘 화면이 숨겨요.
// - 목업(lib/mock/assistant)이면 같은 모양 · 같은 이벤트를 대본으로 흘려요. 목업 모듈은 쓸 때만 불러요(운영 묶음에 안 들어가게).
// - 금액 · 날짜 · 차액 · 기한은 서버(계산 엔진) 값이에요. 화면은 모양만 바꾸고 계산하지 않아요. '표준 대비 %'는 없어요.
import { ApiError, call, type Schemas } from "@/lib/backend/client";
import { ASSISTANT_MOCK } from "@/lib/mock/assistant/mode";

// ───── 카드(kind로 구분, components/assistant/cards/registry). data 모양은 backend assistant/schemas.py의 *Data

export type CardKind =
  | "home_info" | "standard_quote" | "vendor_picks" | "visit_slots" | "quote_compare" | "schedule"
  | "knowledge" | "answer" | "floorplan_links" | "today" | "vendor_brief" | "quote_checklist"
  | "extra" | "notice"
  | "grade_compare" | "market_range" | "options";

/** 출처 이름표: 믿집 계산(계산 엔진) · AI 답변(LLM 글) · 믿집 안내(정해 둔 글) */
export type Source = "calc" | "ai" | "guide";

/** 철거 범위(집 정보 카드 질문). 백엔드도 같은 키 · 값으로 받아요 */
export type Demolition = "full" | "partial" | "none";
export const DEMOLITION: { key: Demolition; label: string }[] = [
  { key: "full", label: "전체 철거" },
  { key: "partial", label: "일부" },
  { key: "none", label: "안 함" },
];

export type HomeInfoData = {
  phase: "confirm";
  /** 집 요약 줄(코드 값) */
  facts: string[];
  /** 면적(㎡) · 기준 · 표시용 평(계산 엔진). Decimal은 글로 와요 */
  area: { m2: string; basis: "supply" | "exclusive"; pyeong: string | null } | null;
  /** 비서가 제안한 바뀜(승인 전) */
  changes: { label: string; before: string | null; after: string }[];
  /** [맞아요, 저장] = 이 제안 행동 승인(propose_home_info) */
  action_id: string | null;
  saved: boolean;
  /** 실측을 요청해 더 고칠 수 없음 */
  locked: boolean;
  /** 철거 범위(모은 조건 demolition). null이면 묻기 칩을 보여요 */
  demolition: Demolition | null;
};

export type StandardQuoteData = {
  /** 부가세 포함 */
  total_won: number;
  label: string;
  lines: { name: string; won: number }[];
  /** 예상 공사 일수(계산 엔진, 글) */
  days: string | null;
  partial: boolean;
  href: string;
};

export type VendorPick = {
  ref: string; vendor_id: string; name: string;
  /** 시공 사진(서버가 주면). 지금 API에는 없어요 */
  photo?: string | null; photo_alt?: string;
  rating: number | null; reviews: number; done_jobs: number;
  /** 가견적(부가세 포함). 업체가 단가를 확인하기 전이면 추천에서 빠져요 */
  estimate_won: number;
  /** 점수 항목 틀 글(AI가 쓰지 않아요) */
  reasons: string[];
  badge?: string | null;
  picked: boolean;
  href: string;
};
export type VendorPicksData = { area_name: string; picks: VendorPick[]; basis: string[]; more_href: string };

export type SlotCandidate = { ref: string; vendor_name: string; day: string; half: "am" | "pm"; why: string[] };
export type WishOut = { ref: string; start: string; end: string; open_count: number };
export type VisitSlotsData = {
  vendor_name: string;
  /** 업체가 답한 기간(요청 전이면 null) */
  window: { start: string; end: string } | null;
  /** 요청 뒤 반나절 후보 */
  candidates: SlotCandidate[];
  /** 요청 전 희망 기간 후보 */
  wishes: WishOut[];
  chosen: string | null;
  instant: boolean;
  calendar_href: string;
  /** 업체가 적은 말(다른 날 제안 메모). 업체 글 그대로라 이 칸에만 보여요 */
  vendor_note?: string | null;
};

export type CompareCol = {
  /** 실측 요청 이름표(m1 …). 확정 단추 choice에 써요 */
  ref: string;
  visit_id: string; vendor_name: string;
  state: "quoted" | "waiting";
  version?: number | null; received_on?: string | null;
  total_won?: number | null;
  /** 앞 판과 차액(서버 값) */
  changed?: { from_version: number; diff_won: number } | null;
  diff_vs_estimate_won?: number | null;
  days?: number | null;
  valid_until?: string | null; valid_soon?: boolean; expired?: boolean;
  demolish?: boolean | null; waste?: boolean | null;
  /** 업체가 적은 말(견적서 벽지 사양 칸, 연락처 가림 · 40자). 업체 글 그대로라 이 칸에만 보여요 */
  vendor_note?: string | null;
  warranty_months?: number | null;
  file?: { kind: "pdf" | "image" | "sheet"; label: string; href: string } | null;
  wait_note?: string | null;
  /** 고객이 이 업체로 확정함 */
  chosen?: boolean;
  /** 이 업체와 열린 믿집 채팅(실측이 확정되면 열려요). 업체에 물어볼 때 누를 곳 */
  chat_href?: string | null;
};
/** decided: 이 공정을 이미 확정함(확정 단추를 두지 않아요) */
/** single: 받은 견적서가 한 곳뿐이라 비교가 아니라 그 견적서 카드(열 하나). 받은 견적서가 없으면 서버가 카드를 보내지 않아요 */
export type QuoteCompareData = { cols: CompareCol[]; gap_won: number | null; ask_chips: string[]; href: string; decided?: boolean; single?: boolean };

export type ScheduleData = {
  /** dates: 업체가 올린 공사 날짜(수락 전) · final: 확정 공정표 */
  phase: "dates" | "final";
  vendor_name: string;
  start: string; end: string; work_days: number;
  /** 하루씩: 오전 · 오후 칸에 들어간 공정 이름(없으면 null) */
  days: { day: string; am: string | null; pm: string | null; off?: boolean }[];
  conflicts: string[];
  plan_version: number;
  href: string;
  ics_href?: string | null;
  /** 업체가 적은 말(날짜를 바꾼 까닭). 업체 글 그대로라 이 칸에만 보여요 */
  vendor_note?: string | null;
  /** 공사 업체와 열린 믿집 채팅(업체에 물어볼 때 누를 곳) */
  chats?: { label: string; href: string }[];
};

export type KnowledgeData = {
  title: string; lines: string[]; source: string;
  checklist?: { key: string; label: string; done: boolean }[];
  href?: string | null;
};
export type AnswerData = { text: string; src: Source; links?: { label: string; href: string }[] };
export type FloorplanLinksData = { complex: string; links: { label: string; href: string; source: string }[]; note: string };

export type TodayIcon = "doc" | "calendar" | "file" | "chat" | "bulb" | "inbox";
/** action.choice: 누르면 say와 함께 보낼 카드 고르기(업체 공사 날짜 'dates:d#,n#', 이름표는 서버 대화 표에 있어요) */
export type TodayRow = { id: string; icon: TodayIcon; title: string; sub?: string | null; due?: boolean; action?: { label: string; href?: string | null; say?: string | null; primary?: boolean; choice?: string | null } | null };
export type TodayData = { date: string; nudge_id: string | null; dismissed?: boolean; todo: TodayRow[]; waiting: TodayRow[]; news: TodayRow[]; know?: TodayRow[] };

/** state: 맞음(ok) · 확인 필요(check: 고객이 아직 안 정함) · 맞지 않음(no). 없으면 ok로만 나눠요(목업) */
export type FitRow = { key: "trade" | "area" | "schedule" | "paper"; label: string; ok: boolean; text: string; state?: "ok" | "check" | "no" };
export type VendorBriefData = {
  visit_id: string;
  title: string;
  facts: string[];
  fit: FitRow[];
  estimate: { total_won: number; basis: string } | null;
  /** 반나절 칸: 날짜 · 쉬는 날, 잡힌 칸(key 'YYYY-MM-DD:am') → 동네 */
  halves: { days: { day: string; off?: boolean }[]; taken: Record<string, string>; open_count: number };
  suggest: { action_id: string; start: string; end: string; excluded: string[]; instant: boolean; open_count: number } | null;
  due_at: string | null;
  memo: string | null;
  /** 문장 하나만 AI(없으면 null) */
  sentence: string | null;
  /** 고객이 직접 할 일(반셀프 칩 화면 말). 요청 때 고객이 승인해 고정한 사본이에요. 없으면 빈 목록 */
  diy?: string[];
  /** 고객이 고른 반나절(날짜 수락 차례일 때만). 수락은 요청 화면(href)에서 해요 */
  picked?: { day: string; half: "am" | "pm"; due_at: string | null; href: string } | null;
};
export type QuoteChecklistData = {
  visit_id: string;
  items: { key: string; label: string; state: "ok" | "check" | "missing"; hint?: string | null }[];
  fields: { label: string; value: string | null }[];
  easy_miss: string[];
  prev: { version: number; total_won: number } | null;
};

/** 추가 금액(07 자동화). 금액은 서버(계산 엔진) 값이에요. 한 일 · 업체가 적은 말은 업체 글이라 그 칸에만 보여요 */
export type ExtraData = {
  ref: string; extra_id: string; deal_id: string; vendor_name: string; trade: string;
  title: string; vendor_note: string | null; version: number;
  answer: "pending" | "asked" | "approved" | "rejected";
  supply_won: number; vat_won: number; total_won: number; vat_label: string;
  deal_total_won: number | null; grand_total_won: number | null; after_total_won: number | null;
  photo_count: number; href: string;
  /** 이 업체와 열린 믿집 채팅(사진 · 까닭을 물어볼 때) */
  chat_href?: string | null;
};
/** 이웃 안내문 초안(07 자동화, 코드 틀). 이웃에게 붙이는 글이라 '-합니다'체예요(style_exempt: 화면 문체 검사에서 빼요) */
export type NoticeData = {
  title: string; text: string; start: string | null; end: string | null;
  blanks: string[]; note: string; style_exempt: boolean;
};

/** 벽지 두 종류 견주기: 지금 집 조건으로 도배 표준견적서를 합지 · 실크로 함께 센 값(저장 안 함). 합계 · 차액 · 줄 금액은 서버(계산 엔진) 값 */
export type GradeCompareData = {
  label: string;
  /** 합계(부가세 포함) */
  economy_won: number; basic_won: number;
  /** 실크 합계 − 합지 합계(계산 엔진) */
  diff_won: number;
  current: "economy" | "basic" | null;
  /** 두 벽지로 금액이 달라지는 줄(부가세 별도, 벽지 줄 먼저) */
  rows: { name: string; economy_won: number | null; basic_won: number | null }[];
  /** 벽지를 바꿀 수 있음(실측 요청 전). [○○로 바꾸기] = choice 'grade:<값>' → 집 정보 승인 카드 */
  can_change: boolean;
  href: string;
};
/** 이 집 조건의 시세 범위(계산 엔진, 부가세 포함 · 만 원 단위)와 출처 한 줄. 원자료는 없어요. 표본이 모자라면 카드가 오지 않아요 */
export type MarketRangeData = {
  trade: string; label: string; found: boolean;
  low_won: number | null; high_won: number | null; count: number;
  source: string; assumed: string[]; note: string | null;
};
/** 고르기 칩: 대상이 여럿일 때 하나를 골라요(누르면 say를 보내요) */
export type OptionsData = { title: string; options: { label: string; say: string; sub?: string | null }[] };

export type CardData = {
  home_info: HomeInfoData; standard_quote: StandardQuoteData; vendor_picks: VendorPicksData; visit_slots: VisitSlotsData;
  quote_compare: QuoteCompareData; schedule: ScheduleData; knowledge: KnowledgeData; answer: AnswerData;
  floorplan_links: FloorplanLinksData; today: TodayData; vendor_brief: VendorBriefData; quote_checklist: QuoteChecklistData;
  extra: ExtraData; notice: NoticeData;
  grade_compare: GradeCompareData; market_range: MarketRangeData; options: OptionsData;
};
export type CardOut<K extends CardKind = CardKind> = { card_id: string; kind: K; data: CardData[K]; say?: string | null };

// ───── 작업 · 제안 행동(승인 카드)

export type TaskState = "running" | "waiting" | "done" | "failed" | "cancelled";
export type RowState = TaskState | "need";
export type TaskRow = { label: string; state: RowState; text: string; note?: string | null };
export type TaskOut = {
  task_id: string; title: string; state: TaskState; at: string;
  due?: string | null; rows?: TaskRow[]; sources?: string[];
  link?: { label: string; href: string } | null;
  error?: string | null;
};

/** 제안 도구와 1:1(propose_*). date_change는 수락한 공사 날짜 바꾸기 요청(propose_date_change), visit_cancel은 보낸 실측 요청 취소 */
export type ActionKind =
  | "home_info" | "visit_request" | "visit_slot" | "vendor_confirm" | "dates_accept" | "delay_accept" | "date_change" | "window_answer" | "decline" | "dates"
  | "extra_answer" | "work_check" | "visit_again" | "visit_cancel";
export type ActionStatus = "proposed" | "approved" | "executed" | "rejected" | "expired" | "failed";
/** 무엇 · 얼마 · 어느 버전(assistant_actions.summary). 금액 · 차액은 서버 값 */
export type ActionSummary = {
  title: string;
  amount_won?: number | null;
  amounts?: { label: string; won: number }[];
  /** 바뀐 때만: 앞 값 → 새 값, 차액 */
  diff?: { label: string; from_won: number; to_won: number; diff_won: number } | null;
  version?: string | null;
  rows?: { label: string; value: string; sub?: string | null }[];
  file?: { label: string; href: string } | null;
  /** 그 뒤 일(한 줄) */
  note?: string | null;
  approve_label: string;
};
export type ActionOut = {
  action_id: string; kind: ActionKind; status: ActionStatus;
  summary: ActionSummary;
  /** 카드가 가리키는 대상 id(공사 · 실측 요청 · 확정 · 공사 날짜 제안 · 추가 금액). 같은 대상이 처리됐으면 단추를 숨겨요 */
  target_id?: string | null;
  target_ver?: string | null;
  expires_at: string;
  decided_at?: string | null; executed_at?: string | null;
  /** 실패 코드. 만료면 까닭(due · replaced · handled_elsewhere), 고객 말로 거둔 카드면 withdrawn */
  error_code?: string | null;
  result?: { text: string; href?: string | null; label?: string | null } | null;
  /** 판이 바뀌어 새로 만든 행동이면 옛 행동 id(409 quote_changed 뒤) */
  supersedes?: string | null;
  /** 같은 대상의 새 제안으로 바뀌어 닫힌 행동(expired · replaced)이면 그 새 행동 id */
  replaced_by?: string | null;
};

/** 다음에 물을 말(코드가 고름). feed의 suggest 조각(먼저 말 건 줄) · done.suggest(0~3개)로 와요. 먼저 말 걸기에서 왔으면 nudge_id */
export type SuggestOut = { id: string; text: string; why: string; say: string; nudge_id?: string | null };

// ───── SSE 이벤트

export type SseAck = { seq: number; turn_id: string; chat_id: string; at?: string };
export type SseStatus = { seq: number; text: string; task?: TaskOut | null };
export type SseCard = { seq: number } & CardOut;
export type SseAction = { seq: number } & ActionOut;
export type SseToken = { seq: number; text: string };
export type SseDone = { seq: number; rev: number; mode: "llm" | "free"; cards: string[]; actions: string[]; stopped?: boolean; chips?: string[]; suggest?: SuggestOut[] };
export type SseError = { seq: number; code: string; message: string };
export type TurnEvent =
  | { type: "ack"; data: SseAck }
  | { type: "status"; data: SseStatus }
  | { type: "card"; data: SseCard }
  | { type: "action"; data: SseAction }
  | { type: "token"; data: SseToken }
  | { type: "done"; data: SseDone }
  | { type: "error"; data: SseError };

/** 한 연결 안에서 이미 받은 seq 이하를 버려요(중복 전송). 다시 이을 때는 새로 만들어요(되돌림은 seq 1부터) */
export function seqFilter(on: (e: TurnEvent) => void): (e: TurnEvent) => void {
  let last = -1;
  return (e) => {
    if (typeof e.data.seq !== "number" || e.data.seq <= last) return;
    last = e.data.seq;
    on(e);
  };
}

// ───── 대화 기록(feed)

export type FeedPart =
  | { t: "text"; text: string; src: Source }
  | { t: "card"; card: CardOut }
  | { t: "task"; task: TaskOut }
  | { t: "action"; action: ActionOut }
  | { t: "suggest"; suggest: SuggestOut }
  | { t: "note"; text: string };
export type AssistantItem = {
  id: string; role: "assistant"; at: string; turn_id: string | null; parts: FeedPart[];
  done?: boolean; mode?: "llm" | "free" | null; error?: { code: string; message: string } | null; status?: string | null;
  /** 먼저 말 건 줄이면 그 id(턴이 아니라 turn_id는 null) */
  nudge_id?: string | null;
  /** 할 일이 끝나 닫힌 먼저 말 건 줄: '완료'로 남기고 단추 · 다음에 물을 말을 두지 않아요(카드는 보낸 때 모습) */
  settled?: boolean;
  /** 한도에 닿아 카드만으로 끝냈어요(done.stopped) */
  stopped?: boolean;
  /** 화면이 만든 말(오늘 정할 일 · 기록 밖 열린 승인 카드). 서버 기록에 없어요 */
  local?: boolean;
};
export type FeedItem = { id: string; role: "user"; at: string; text: string } | AssistantItem;
/** before: 더 앞 쪽을 읽을 커서(턴 번호, 없으면 처음) */
export type FeedPage = { items: FeedItem[]; before: number | null; rev: number; chips: string[]; now: string };

export type TurnIn = {
  project_id: string;
  client_key: string;
  text: string;
  /** 카드에서 고른 것(choice 꼴은 아래 CHOICE). 이름표는 이 대화에서 도구 · 카드가 준 것만 서버가 받아요 */
  context?: { card_id?: string; choice?: string | string[] } | null;
};

/**
 * 카드 단추 → 계약 꼴 choice(backend assistant/choices.py, 계약서 4장 11). 이 꼴이면 무료 모드에서도 코드가 승인 카드를 만들어요.
 * 이름표 v 업체 · r 희망 기간 · s 반나절 · m 실측 요청은 카드 data에 온 것 그대로 써요. 한 choice는 40자 · 이름표 4개까지예요.
 * 집 정보 칸은 `demolition:<full · partial · none>`(HomeInfoCard)이에요.
 */
export const CHOICE = {
  /** 고른 업체(1~3곳)에 실측 요청. 희망 기간을 골랐으면 끝에 붙여요 */
  visitRequest: (vendors: string[], wish?: string | null) => `visit_request:${[...vendors.slice(0, 3), ...(wish ? [wish] : [])].join(",")}`,
  visitSlot: (slot: string) => `visit_slot:${slot}`,
  vendorConfirm: (visit: string) => `vendor_confirm:${visit}`,
  /** 추가 금액(x…)에 답하는 승인 카드: 승인(기본) · 거절 · 채팅으로 묻기 */
  extraAnswer: (extra: string, answer: "approve" | "reject" | "ask" = "approve") =>
    answer === "approve" ? `extra_answer:${extra}` : `extra_answer:${extra},${answer}`,
  /** 집 정보 벽지 칸(벽지 두 종류 견주기 카드): 그 벽지로 바꾸는 집 정보 승인 카드 */
  grade: (grade: "economy" | "basic") => `grade:${grade}`,
};

// ───── 대화 · 보드 · 오늘 · 상태 · 기억 · 알림

export type ThreadOut = { chat_id: string; rev: number; updated_at: string };
export type HealthOut = { mode: "llm" | "free"; reason: "ok" | "off" | "budget" | "breaker" };

export type MemoryKey = "avail_days" | "avail_half" | "living" | "style" | "material" | "priority" | "pet" | "diy" | "move_in";
/** label은 키의 화면 이름(서버 값). 옛 목업 기록처럼 비어 오면 MEMORY_LABEL(서버 memory.LABEL과 같은 말)을 써요 */
export type MemoryOut = { id: string; key: MemoryKey | string; label: string; value: string; evidence_message_id: string; evidence_quote: string; updated_at: string };
export const MEMORY_LABEL: Record<MemoryKey, string> = {
  avail_days: "편한 요일", avail_half: "편한 때", living: "사는 방식", style: "좋아하는 느낌",
  material: "자재 바람", priority: "중요한 것", pet: "반려동물", diy: "직접 할 일", move_in: "이사 · 입주",
};

export type BoardOut = {
  project_name: string;
  /** 단계 띠 지금 칸(0 집 정보 ~ 6 공사) */
  step: number;
  facts: string[];
  confirmed: boolean;
  todo: number; waiting: number;
  /** won: 확정한 공정은 지금 공사 금액(확정 + 승인한 추가 금액). extra_won: 그중 승인한 추가 금액 */
  money: { label: string; won?: number | null; range?: number[] | null; extra_won?: number | null } | null;
  /** 업체 줄: 상태 또는 가견적(won) */
  vendors: { title: string; rows: { name: string; state: RowState; text: string; won?: number | null }[] } | null;
  period: { label: string; value: string; sub?: string | null } | null;
  docs: { label: string; href: string }[];
  plan_example: boolean;
  memory: MemoryOut[];
  /** 대화가 길면 단계 띠 아래 '오늘 정할 일 n ›' */
  today_pin: number;
};

export type NotifyPage = Schemas["NotificationPage"];

// ───── 화면 상태 바꾸기(같은 규칙을 목업 서버도 써요)

const lastAssistant = (items: FeedItem[], turnId: string) => items.findIndex((x) => x.role === "assistant" && x.turn_id === turnId);

/** 턴 이벤트 하나를 대화에 반영. 같은 card_id면 카드를 바꿔 끼우고, 같은 task_id면 작업 카드를 바꿔요(대화 어디에 있든) */
export function applyTurnEvent(items: FeedItem[], turnId: string, ev: TurnEvent, at: string): FeedItem[] {
  let next = items;
  let i = lastAssistant(next, turnId);
  if (i < 0) {
    next = [...next, { id: `a-${turnId}`, role: "assistant", at: ev.type === "ack" && ev.data.at ? ev.data.at : at, turn_id: turnId, parts: [] }];
    i = next.length - 1;
  }
  const item = next[i] as AssistantItem;
  const put = (parts: FeedPart[], patch: Partial<AssistantItem> = {}) =>
    next.map((x, k) => (k === i ? { ...item, ...patch, parts } : x));

  switch (ev.type) {
    case "ack":
      return next;
    case "status": {
      // 글은 '입력 중' 옆에 잠깐 보이는 말이에요(기록에는 남기지 않아요)
      // 작업 카드는 하나만: 같은 task_id가 다른 말에 있으면 빼고 지금 말 아래로 옮겨요(진행이 보는 자리에 오게)
      const task = ev.data.task;
      if (!task) return put(item.parts, { status: ev.data.text });
      const isIt = (p: FeedPart) => p.t === "task" && p.task.task_id === task.task_id;
      if (item.parts.some(isIt)) return put(item.parts.map((p) => (isIt(p) ? { t: "task" as const, task } : p)), { status: ev.data.text });
      const moved = next.map((x, k) => (k !== i && x.role === "assistant" && x.parts.some(isIt) ? { ...x, parts: x.parts.filter((p) => !isIt(p)) } : x));
      return moved.map((x, k) => (k === i ? { ...item, parts: [...item.parts, { t: "task" as const, task }], status: ev.data.text } : x));
    }
    case "card": {
      const { seq: _seq, ...card } = ev.data;
      const swapped = swapPart(next, (p) => p.t === "card" && p.card.card_id === card.card_id, { t: "card", card });
      return swapped ?? put([...item.parts, { t: "card", card }]);
    }
    case "action": {
      const { seq: _seq, ...action } = ev.data;
      const swapped = swapPart(next, (p) => p.t === "action" && p.action.action_id === action.action_id, { t: "action", action });
      if (swapped) return swapped;
      return put([...item.parts, { t: "action", action }]);
    }
    case "token": {
      const parts = [...item.parts];
      const last = parts[parts.length - 1];
      if (last?.t === "text" && last.src === "ai") parts[parts.length - 1] = { ...last, text: last.text + ev.data.text };
      else parts.push({ t: "text", text: ev.data.text, src: "ai" });
      return put(parts);
    }
    case "done": {
      // 다음에 물을 말(0~3개)은 마지막 턴 끝에만 둬요(서버도 기록에 남기지 않아요). 먼저 말 건 줄(turn_id 없음)의 제안은 그대로예요
      const ideas = (ev.data.suggest ?? []).map((suggest): FeedPart => ({ t: "suggest", suggest }));
      const plain = (parts: FeedPart[]) => parts.filter((p) => p.t !== "suggest");
      return next.map((x, k) => {
        if (k === i) return { ...item, parts: [...plain(item.parts), ...ideas], done: true, mode: ev.data.mode, status: null, stopped: !!ev.data.stopped, error: null };
        return x.role === "assistant" && x.turn_id !== null && x.parts.some((p) => p.t === "suggest") ? { ...x, parts: plain(x.parts) } : x;
      });
    }
    case "error":
      return put(item.parts, { done: true, status: null, error: { code: ev.data.code, message: ev.data.message } });
  }
}

/** 같은 client_key로 다시 이으면 서버가 저장한 카드 · 행동 · 글을 처음부터 다시 보내요. 그 턴의 조각을 비우고 받아요 */
export function resetTurn(items: FeedItem[], turnId: string): FeedItem[] {
  return items.map((x) => (x.role === "assistant" && x.turn_id === turnId ? { ...x, parts: [], done: false, error: null, status: null } : x));
}

/** 대화 어디에 있든 맞는 조각 하나를 바꿔 끼워요. 없으면 null */
function swapPart(items: FeedItem[], hit: (p: FeedPart) => boolean, part: FeedPart): FeedItem[] | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.role !== "assistant") continue;
    const k = it.parts.findIndex(hit);
    if (k >= 0) return items.map((x, j) => (j === i ? { ...it, parts: it.parts.map((p, n) => (n === k ? part : p)) } : x));
  }
  return null;
}

/**
 * 대화를 다시 열 때도 '같은 card_id면 바꿔 끼우기'(계약서 3장)가 스트림 때와 같게 보이도록:
 * 같은 card_id는 처음 나온 자리에 마지막 값으로 하나만 남겨요(스트림의 applyTurnEvent card와 같은 결과).
 */
export function foldCards(items: FeedItem[]): FeedItem[] {
  const latest = new Map<string, CardOut>();
  for (const it of items) if (it.role === "assistant") for (const p of it.parts) if (p.t === "card") latest.set(p.card.card_id, p.card);
  const seen = new Set<string>();
  return items.map((it) => {
    if (it.role !== "assistant") return it;
    let changed = false;
    const parts = it.parts.flatMap((p): FeedPart[] => {
      if (p.t !== "card") return [p];
      if (seen.has(p.card.card_id)) { changed = true; return []; }
      seen.add(p.card.card_id);
      const card = latest.get(p.card.card_id) ?? p.card;
      if (card !== p.card) changed = true;
      return [{ t: "card", card }];
    });
    return changed ? { ...it, parts } : it;
  });
}

/**
 * 다시 읽은 첫 쪽(지금)에 이미 읽어 둔 앞 쪽('앞 대화 더 보기')을 이어 붙여요: 첫 쪽 첫 말보다 앞인 말만 남겨요.
 * (실시간 소식으로 첫 쪽을 다시 읽어도 위에 읽어 둔 대화가 사라져 보던 자리가 튀지 않게)
 */
export function keepOlder(cur: FeedItem[], page: FeedItem[]): FeedItem[] {
  const first = page[0];
  if (!first) return page;
  const t = Date.parse(first.at);
  const have = new Set(page.map((x) => x.id));
  const older = cur.filter((x) => !have.has(x.id) && Date.parse(x.at) < t);
  return older.length ? [...older, ...page] : page;
}

/** 승인 · 거절 결과로 행동 카드를 바꿔요 */
export function replaceAction(items: FeedItem[], action: ActionOut): FeedItem[] {
  return swapPart(items, (p) => p.t === "action" && p.action.action_id === action.action_id, { t: "action", action }) ?? items;
}

/** 카드 하나의 data를 바꿔요(오늘 정할 일 닫기 등) */
export function replaceCard(items: FeedItem[], card: CardOut): FeedItem[] {
  return swapPart(items, (p) => p.t === "card" && p.card.card_id === card.card_id, { t: "card", card }) ?? items;
}

/** 대화에 그려진 행동 모두(같은 id면 마지막 것) */
export function actionsIn(items: FeedItem[]): ActionOut[] {
  const out = new Map<string, ActionOut>();
  for (const it of items) if (it.role === "assistant") for (const p of it.parts) if (p.t === "action") out.set(p.action.action_id, p.action);
  return [...out.values()];
}

/**
 * 공사에 한 번만 정하는 종류(대상이 공사 · 공정 하나): 집 정보 · 실측 요청 · 업체 확정(한 곳을 확정하면 다른 곳 확정 제안도 끝나요).
 * 나머지(반나절 · 공사 날짜 · 날짜 바꾸기 · 추가 금액 …)는 실측 · 확정 · 추가 금액마다 열린 제안이 따로 있어요.
 */
const ONE_DECISION: ReadonlySet<ActionKind> = new Set<ActionKind>(["home_info", "visit_request", "vendor_confirm"]);

/**
 * 할 일을 마친 먼저 말 건 줄(nudge_id): 서버가 '완료'로 보낸 줄(settled), 그 줄에 달린 승인 카드가 실행됐거나, 화면 v3 단추로
 * 처리됐거나(handled · handled_elsewhere), 같은 대상의 새 카드로 바뀐(replaced) 뒤 그 새 카드(replaced_by를 따라감)가 실행 · 처리됐으면요.
 * replaced_by가 없는 옛 행동은 공사에 한 번 정하는 종류만 '뒤에 같은 종류 실행'으로 봐요(다른 업체 반나절 실행으로 닫지 않게).
 * 화면은 그 줄을 바로 '완료'로 그려요(제안 · 카드 단추 없이). 서버 정리(2분) 전에는 열린 줄로 와서 그릴 때마다 다시 봐요.
 */
export function settledNudges(items: FeedItem[], handled: Record<string, true>): string[] {
  const byId = new Map(actionsIn(items).map((a) => [a.action_id, a]));
  const finished = (a: ActionOut) => a.status === "executed" || !!handled[a.action_id] || (a.status === "expired" && a.error_code === "handled_elsewhere");
  const replaced = (a: ActionOut) => a.status === "expired" && a.error_code === "replaced";
  /** 새 카드 사슬 끝이 실행 · 처리됐는지 */
  const chainDone = (a: ActionOut): boolean => {
    const seen = new Set<string>();
    let cur: ActionOut | undefined = a;
    while (cur && replaced(cur) && cur.replaced_by && !seen.has(cur.action_id)) {
      seen.add(cur.action_id);
      cur = byId.get(cur.replaced_by);
    }
    return !!cur && cur !== a && finished(cur);
  };
  const out: string[] = [];
  items.forEach((it, i) => {
    if (it.role !== "assistant" || !it.nudge_id) return;
    if (it.settled) { out.push(it.nudge_id); return; }
    const later = (kind: ActionKind) =>
      items.slice(i + 1).some((x) => x.role === "assistant" && x.parts.some((p) => p.t === "action" && p.action.kind === kind && p.action.status === "executed"));
    const done = it.parts.some((p) => p.t === "action" && (
      finished(p.action)
      || (replaced(p.action) && (p.action.replaced_by ? chainDone(p.action) : ONE_DECISION.has(p.action.kind) && later(p.action.kind)))
    ));
    if (done) out.push(it.nudge_id);
  });
  return out;
}

/** 대화에서 가장 나중에 그려진 그 kind 카드(test를 주면 맞는 것만). '완료' 줄의 카드(보낸 때 모습)는 빼요. 없으면 null */
export function lastCardIn<K extends CardKind>(items: FeedItem[], kind: K, test?: (c: CardOut<K>) => boolean): CardOut<K> | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.role !== "assistant" || it.settled) continue;
    for (let k = it.parts.length - 1; k >= 0; k--) {
      const p = it.parts[k];
      if (p.t === "card" && p.card.kind === kind && (!test || test(p.card as CardOut<K>))) return p.card as CardOut<K>;
    }
  }
  return null;
}

/** 대화에서 가장 나중에 그려진 그 종류 행동(상태 상관없이, test를 주면 맞는 것만). 없으면 null */
export function lastActionIn(items: FeedItem[], kind: ActionKind, test?: (a: ActionOut) => boolean): ActionOut | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.role !== "assistant") continue;
    for (let k = it.parts.length - 1; k >= 0; k--) {
      const p = it.parts[k];
      if (p.t === "action" && p.action.kind === kind && (!test || test(p.action))) return p.action;
    }
  }
  return null;
}

/**
 * 화면이 만든 말(오늘 정할 일 · 기록 밖 열린 승인 카드)을 끼울 자리: 처음 열 때 마지막 말(anchor) 바로 뒤.
 * 그 뒤에 보낸 말 · 답은 늘 그 아래에 붙어요. 그 말이 기록에서 빠졌으면(실패 턴 등) 그 말 시각까지의 말 뒤, 처음에 대화가 비었으면 맨 앞이에요.
 */
export function anchorIndex(items: FeedItem[], anchor: { id: string; at: string } | null): number {
  if (!anchor) return 0;
  const i = items.findIndex((x) => x.id === anchor.id);
  if (i >= 0) return i + 1;
  const t = Date.parse(anchor.at);
  let at = 0;
  items.forEach((x, k) => { if (Date.parse(x.at) <= t) at = k + 1; });
  return at;
}

/**
 * v3 단추 쓰기(kindsForWrite) 뒤 '처리됨'으로 볼 열린 승인 카드 id(서버 행은 그대로라 화면에서만).
 * 공사에 한 번 정하는 종류는 그 종류 열린 카드 모두. 대상이 여럿일 수 있는 종류(반나절 · 공사 날짜 · 취소)는 쓰기 주소의 대상
 * (targetOfWrite)과 행동의 대상 id(target_id)가 같은 카드만이에요. 대상 id가 없는 옛 행동이면 쓰기 종류의 열린 카드가 하나뿐일
 * 때만 그 카드예요(둘 이상이면 어느 것인지 몰라 서버 정리 handled_elsewhere를 기다려요).
 */
export function handledByWrite(kinds: ActionKind[], actions: ActionOut[], target: string | null = null): string[] {
  const live = actions.filter((a) => a.status === "proposed" && kinds.includes(a.kind));
  const ids = (xs: ActionOut[]) => [...new Set(xs.map((a) => a.action_id))];
  if (kinds.length && kinds.every((k) => ONE_DECISION.has(k))) return ids(live);
  if (target && live.some((a) => a.target_id)) return ids(live.filter((a) => a.target_id === target));
  const open = ids(live);
  return open.length === 1 ? open : [];
}

/** 대상을 끝내는 행동: 실행되면 같은 대상의 다른 열린 카드(반나절 고르기 · 확정 …)는 쓸 데가 없어요 */
const ENDS_TARGET: ReadonlySet<ActionKind> = new Set<ActionKind>(["visit_cancel"]);

/**
 * 같은 대상이 처리된 열린 승인 카드 id: 대상을 끝내는 행동(실측 요청 취소)이 실행됐으면 같은 대상(target_id)의 열린 카드는
 * 단추를 숨겨요(서버는 같은 트랜잭션에서 닫지만 대화는 다시 읽기 전까지 열린 모습이에요).
 */
export function handledByTarget(actions: ActionOut[]): string[] {
  const ended = new Set(actions.filter((a) => a.status === "executed" && ENDS_TARGET.has(a.kind) && a.target_id).map((a) => a.target_id));
  return [...new Set(actions.filter((a) => a.status === "proposed" && !!a.target_id && ended.has(a.target_id)).map((a) => a.action_id))];
}

/** v3 단추 쓰기 주소의 대상 id(실측 요청 · 공사 날짜 제안 · 확정 · 추가 금액). 행동의 target_id와 견줘요. 모르면 null */
export function targetOfWrite(method: string, path: string): string | null {
  if (method !== "POST") return null;
  const hit = [
    /\/visits\/([^/]+)\/(?:pick|proposal\/pick|repick|cancel|window|decline)$/,
    /\/quotes\/([^/]+)\/confirm$/,
    /\/deals\/[^/]+\/dates\/([^/]+)\/accept$/,
    /\/deals\/([^/]+)\/date-requests$/,
    /\/extras\/([^/]+)\/answer$/,
    /^\/vendor\/jobs\/([^/]+)\/dates$/,
  ].map((rx) => rx.exec(path)).find(Boolean);
  return hit ? hit[1] : null;
}

/** 사이트 안 경로만(링크 · 이동): '/'로 시작하고 '//' · '/\'(브라우저가 다른 사이트로 읽음) · 역빗금 · 공백 · 제어 문자가 없어요
 *  (브라우저는 주소의 탭 · 줄바꿈을 지우고 역빗금을 빗금으로 읽어요: '/\t/x' · '/\x'도 '//x'가 돼요) */
export function insideHref(h: string): boolean {
  if (!h.startsWith("/") || h.startsWith("//") || h.includes("\\")) return false;
  for (let i = 0; i < h.length; i++) {
    const c = h.charCodeAt(i);
    if (c <= 0x20 || c === 0x7f) return false;
  }
  return true;
}

/**
 * 전체 화면 카드 안 v3 단추(사람이 누른 요청)가 한 쓰기 → 같은 일을 하는 제안 행동 종류.
 * 이 쓰기가 성공하면 같은 일을 하던 열린 승인 카드는 '처리됨'으로 보여요(handledByWrite, 서버 행은 그대로라 화면에서만).
 */
export function kindsForWrite(method: string, path: string, projectId: string): ActionKind[] {
  const base = `/projects/${projectId}`;
  if (!path.startsWith(base)) return [];
  const tail = path.slice(base.length);
  if (method === "PATCH" && tail === "") return ["home_info"];
  if (method !== "POST") return [];
  if (tail === "/visits") return ["visit_request"];
  if (/^\/visits\/[^/]+\/(pick|proposal\/pick|repick)$/.test(tail)) return ["visit_slot"];
  // 화면에서 실측 요청을 취소하면 그 요청의 취소 · 반나절 · 확정 카드가 끝나요(대상 id로 그 요청만)
  if (/^\/visits\/[^/]+\/cancel$/.test(tail)) return ["visit_cancel", "visit_slot", "vendor_confirm"];
  if (/^\/quotes\/[^/]+\/confirm$/.test(tail)) return ["vendor_confirm"];
  if (/^\/deals\/[^/]+\/dates\/[^/]+\/accept$/.test(tail)) return ["dates_accept", "delay_accept"];
  if (/^\/deals\/[^/]+\/date-requests$/.test(tail)) return ["date_change"];
  if (/^\/deals\/[^/]+\/extras\/[^/]+\/answer$/.test(tail)) return ["extra_answer"];
  return [];
}
/** 업체 쪽 v3 쓰기 → 같은 일을 하는 제안 행동 종류 */
export function vendorKindsForWrite(method: string, path: string): ActionKind[] {
  if (method !== "POST") return [];
  if (/^\/vendor\/visits\/[^/]+\/window$/.test(path)) return ["window_answer"];
  if (/^\/vendor\/visits\/[^/]+\/decline$/.test(path)) return ["decline", "window_answer"];
  if (/^\/vendor\/jobs\/[^/]+\/dates$/.test(path)) return ["dates"];
  return [];
}

// ───── 실제 API(목업이면 대본)

const mock = () => import("@/lib/mock/assistant/server");
const enc = encodeURIComponent;
/** 다른 담당이 아직 안 만든 API(404)면 null */
async function orGone<T>(p: Promise<T>): Promise<T | null> {
  try { return await p; } catch (e) { if (e instanceof ApiError && e.status === 404) return null; throw e; }
}

/** 이 공사의 비서 대화(없으면 null). 다시 열 때 feed를 읽을지 · 바뀌었는지(rev) 봐요 */
export async function getLatestThread(projectId: string): Promise<ThreadOut | null> {
  if (ASSISTANT_MOCK) return (await mock()).latest(projectId);
  return call<ThreadOut | null>("GET", `/assistant/threads/latest?project_id=${enc(projectId)}`);
}

/** 대화 기록 첫 쪽(30개). before를 주면 그 턴보다 앞 쪽 */
export async function getFeed(projectId: string, before?: number | null): Promise<FeedPage> {
  if (ASSISTANT_MOCK) return (await mock()).feed(projectId);
  const q = new URLSearchParams({ project_id: projectId, limit: "30" });
  if (before) q.set("before", String(before));
  return call<FeedPage>("GET", `/assistant/feed?${q}`);
}

/** 내 공사 보드(우리 집 · 지금 · 낼 금액 · 업체 · 기간 · 서류 · 기억) */
export async function getBoard(projectId: string): Promise<BoardOut> {
  if (ASSISTANT_MOCK) return (await mock()).board(projectId);
  return call<BoardOut>("GET", `/assistant/board?project_id=${enc(projectId)}`);
}

/** 오늘 정할 일(줄은 코드가 골라요) */
export async function getToday(projectId: string): Promise<TodayData> {
  if (ASSISTANT_MOCK) return (await mock()).today(projectId);
  return call<TodayData>("GET", `/assistant/today?project_id=${enc(projectId)}`);
}

/** 비서가 지금 LLM으로 답하는지(무료 모드 띠). 못 읽으면 null */
export async function getHealth(): Promise<HealthOut | null> {
  if (ASSISTANT_MOCK) return (await mock()).health();
  try { return await call<HealthOut>("GET", "/assistant/health"); } catch { return null; }
}

/** 끊긴 턴을 같은 client_key로 다시 이을 때 기다리는 시간(턴 상한 45초를 넘기도록). 고객 · 업체 턴이 같이 써요 */
export const TURN_RETRY_MS = [1200, 2500, 4000, 6000, 8000, 10000, 12000];

/** 한 턴(SSE). 스트림을 열기 전 오류(404 · 409 turn_running · 429 · 422)는 ApiError로 던져요. 끝(done · error)을 받았으면 true */
export async function streamTurn(body: TurnIn, on: (e: TurnEvent) => void, signal?: AbortSignal): Promise<boolean> {
  let ended = false;
  const emit = seqFilter((e) => { if (e.type === "done" || e.type === "error") ended = true; on(e); });
  if (ASSISTANT_MOCK) { await (await mock()).turn(body, emit, signal); return true; }
  await postSse("/api/assistant/turns", body, emit, signal);
  return ended;
}

export type VendorTurnIn = { visit_id?: string | null; client_key: string; text: string; context?: TurnIn["context"] };
/** 업체 비서 한 턴(SSE, 작업함 대화). 오늘 할 일 단추의 고르기(choice)로 승인 카드를 받아요. 목업에는 업체 턴이 없어 바로 끝나요 */
export async function streamVendorTurn(body: VendorTurnIn, on: (e: TurnEvent) => void, signal?: AbortSignal): Promise<boolean> {
  let ended = false;
  const emit = seqFilter((e) => { if (e.type === "done" || e.type === "error") ended = true; on(e); });
  if (ASSISTANT_MOCK) return true;
  await postSse("/api/vendor/assistant/turns", body, emit, signal);
  return ended;
}

async function postSse(url: string, body: TurnIn | VendorTurnIn, emit: (e: TurnEvent) => void, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST", credentials: "same-origin", signal,
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError(0, "network", "서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.");
  }
  if (!res.ok || !res.body) {
    const e = (await res.json().catch(() => null))?.error;
    throw new ApiError(res.status, e?.code ?? "unknown", e?.message ?? (res.status === 429 ? "너무 많이 물었어요. 잠시 뒤에 다시 해 주세요." : "답을 만들지 못했어요. 다시 해 주세요."));
  }
  try {
    await readSse(res.body, emit);
  } catch (e) {
    if (signal?.aborted) throw e;
    // 읽다 끊겼어요: 서버는 끝까지 돌려 저장해요(부르는 쪽이 같은 client_key로 다시 이어요)
  }
}

const TYPES = new Set(["ack", "status", "card", "action", "token", "done", "error"]);
/** text/event-stream 읽기: 'event: 이름' · 'data: JSON' 묶음을 빈 줄로 나눠요('id:' 줄은 seq로 대신해요) */
export async function readSse(body: ReadableStream<Uint8Array>, on: (e: TurnEvent) => void): Promise<void> {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    buf += dec.decode(value ?? new Uint8Array(), { stream: !done });
    buf = buf.replace(/\r\n/g, "\n");
    let cut = buf.indexOf("\n\n");
    while (cut >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      const name = /^event: ?(.*)$/m.exec(block)?.[1]?.trim();
      const raw = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
      if (name && TYPES.has(name) && raw) {
        try { on({ type: name, data: JSON.parse(raw) } as TurnEvent); } catch { /* 모양이 다른 글은 버려요 */ }
      }
      cut = buf.indexOf("\n\n");
    }
    if (done) break;
  }
}

/** 제안 행동 목록(status를 주면 그 상태만). 같은 대상의 열린 제안은 하나만 살아 있어요 */
export async function listActions(projectId: string, status?: ActionStatus): Promise<ActionOut[]> {
  if (ASSISTANT_MOCK) return (await mock()).actions(projectId, status);
  const q = new URLSearchParams({ project_id: projectId });
  if (status) q.set("status", status);
  return call<ActionOut[]>("GET", `/assistant/actions?${q}`);
}

/** 승인: 멱등 키 · 본 판(target_ver)을 같이 보내요. 이미 실행한 행동이면 200(같은 결과), 판이 바뀌었거나 닫혔으면 409 */
export async function approveAction(projectId: string, actionId: string, seen: { client_key: string; seen: string | null }): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).approve(projectId, actionId, seen.client_key);
  return call<ActionOut>("POST", `/assistant/actions/${enc(actionId)}/approve`, seen);
}
export async function rejectAction(projectId: string, actionId: string): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).reject(projectId, actionId);
  return call<ActionOut>("POST", `/assistant/actions/${enc(actionId)}/reject`);
}

/** 먼저 말 건 제안 열기 · 닫기(닫으면 같은 일을 3일 쉬어요). API가 없거나(404) 그 제안이 없으면 false → 화면이 숨겨요 */
export async function openNudge(projectId: string, nudgeId: string): Promise<boolean> {
  if (ASSISTANT_MOCK) return (await mock()).openNudge(projectId, nudgeId);
  return (await orGone(call("POST", `/assistant/nudges/${enc(nudgeId)}/open`))) !== null;
}
export async function dismissNudge(projectId: string, nudgeId: string): Promise<boolean> {
  if (ASSISTANT_MOCK) return (await mock()).dismiss(projectId, nudgeId);
  return (await orGone(call("POST", `/assistant/nudges/${enc(nudgeId)}/dismiss`))) !== null;
}

/** 비서가 기억한 것(사용자 말에서만). API가 아직 없으면(404) null → 화면이 칸을 숨겨요 */
export async function getMemory(): Promise<MemoryOut[] | null> {
  if (ASSISTANT_MOCK) return (await mock()).memory();
  const got = await orGone(call<MemoryOut[] | { items: MemoryOut[] }>("GET", "/assistant/memory"));
  if (got === null) return null;
  return Array.isArray(got) ? got : got.items ?? [];
}
export async function forgetMemory(memoryId: string): Promise<void> {
  if (ASSISTANT_MOCK) return (await mock()).forget(memoryId);
  await orGone(call("DELETE", `/assistant/memory/${enc(memoryId)}`));
}

/** 머리 종: 알림 목록 · 모두 읽음 · 하나 읽음(지금 있는 /notifications) */
export async function getNotifications(projectId: string): Promise<NotifyPage> {
  if (ASSISTANT_MOCK) return (await mock()).notifications(projectId);
  return call<NotifyPage>("GET", "/notifications");
}
export async function readAllNotifications(projectId: string): Promise<void> {
  if (ASSISTANT_MOCK) return (await mock()).readAll(projectId);
  await call("POST", "/notifications/read-all");
}
export async function readNotification(projectId: string, id: string): Promise<void> {
  if (ASSISTANT_MOCK) return (await mock()).readOne(projectId, id);
  await call("POST", `/notifications/${enc(id)}/read`);
}
/** 알림 링크에 붙은 먼저 말 걸기 id(?nudge=). 없으면 null */
export function nudgeOfLink(link: string): string | null {
  const q = link.split("?")[1]?.split("#")[0];
  return q ? new URLSearchParams(q).get("nudge") : null;
}

/** 서버가 먼저 보내는 턴(먼저 말 걸기 · 승인 뒤 이어지는 일). 목업만 여기서 흘려요.
 *  실제는 /stream(LiveProvider)의 state · notif로 대화를 다시 읽어요(hooks/useAssistant). 돌려준 함수로 그만 들어요 */
export function subscribeTurns(projectId: string, on: (turnId: string, e: TurnEvent) => void): () => void {
  if (!ASSISTANT_MOCK) return () => {};
  let stop: (() => void) | null = null;
  let alive = true;
  void mock().then((m) => { if (alive) stop = m.subscribe(projectId, on); });
  return () => { alive = false; stop?.(); };
}

/** 목업 대본 바꾸기 · 처음부터(개발 화면 전용) */
export async function resetMock(projectId: string, script: "f1" | "today"): Promise<void> {
  if (ASSISTANT_MOCK) (await mock()).reset(projectId, script);
}
export async function mockScriptOf(projectId: string): Promise<"f1" | "today" | null> {
  return ASSISTANT_MOCK ? (await mock()).scriptOf(projectId) : null;
}

// ───── 업체(V1 요청 브리핑 · V3 견적서 체크리스트 · 오늘 · 비서 소식 · 승인)

/** 업체가 보는 요청 사실(서버 화면이 넘겨요). 목업 브리핑이 이 값으로 요약 줄을 채워요 */
export type BriefSeed = { region?: string | null; area?: string | null; grade?: string | null; occupied?: boolean | null; wish?: { start: string; end: string } | null; work_wish_on?: string | null; estimate_won?: number | null; photos?: number; due_at?: string | null; memo?: string | null };

/** 브리핑 카드: POST가 추천 기간 답하기 제안을 만들어요(열린 제안은 덮지 않아요). GET은 읽기만이라 제안을 만들지 않아요 */
export async function getVendorBrief(visitId: string, seed?: BriefSeed): Promise<VendorBriefData> {
  if (ASSISTANT_MOCK) return (await mock()).vendorBrief(visitId, seed);
  return call<VendorBriefData>("POST", `/vendor/assistant/briefs/${enc(visitId)}`);
}
export async function getQuoteChecklist(visitId: string): Promise<QuoteChecklistData> {
  if (ASSISTANT_MOCK) return (await mock()).quoteChecklist(visitId);
  return call<QuoteChecklistData>("GET", `/vendor/assistant/checklists/${enc(visitId)}`);
}
export async function approveVendorAction(actionId: string, clientKey: string, seen: string | null = null): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).approveVendor(actionId);
  return call<ActionOut>("POST", `/vendor/assistant/actions/${enc(actionId)}/approve`, { client_key: clientKey, seen });
}
export async function rejectVendorAction(actionId: string): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).rejectVendor(actionId);
  return call<ActionOut>("POST", `/vendor/assistant/actions/${enc(actionId)}/reject`);
}
/** 업체 비서 대화 기록(작업함 대화 · 먼저 말 건 브리핑) */
export async function getVendorFeed(before?: number | null): Promise<FeedPage> {
  if (ASSISTANT_MOCK) return (await mock()).vendorFeed();
  const q = new URLSearchParams({ limit: "30" });
  if (before) q.set("before", String(before));
  return call<FeedPage>("GET", `/vendor/assistant/feed?${q}`);
}
/** 업체 제안 행동(기간 답하기 · 못 받아요 · 공사 날짜) */
export async function listVendorActions(status?: ActionStatus): Promise<ActionOut[]> {
  if (ASSISTANT_MOCK) return (await mock()).vendorActions(status);
  return call<ActionOut[]>("GET", `/vendor/assistant/actions${status ? `?status=${status}` : ""}`);
}

export type VendorTodayData = { date: string; rows: TodayRow[] };
/** 업체 작업함에서 비서 턴을 보낸 뒤(오늘 할 일 단추) '비서 소식'이 다시 읽게 알리는 이벤트 */
export const VENDOR_ASSISTANT_EVENT = "mj-vendor-assistant";
/** 업체 작업함 맨 위 '오늘 브리핑'(줄은 코드가 골라요) */
export async function getVendorToday(): Promise<VendorTodayData> {
  if (ASSISTANT_MOCK) return (await mock()).vendorToday();
  return call<VendorTodayData>("GET", "/vendor/assistant/today");
}

/** 멱등 키(승인 · 턴마다 하나). 서버 규칙: 영문 · 숫자 · _ · - 8~64자 */
export function newClientKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** 실측 시간 후보 근거 코드(calc.slots) → 화면 말. 모르는 코드는 숨겨요(영어 값을 보이지 않아요) */
const WHY: Record<string, string> = {
  prefer_half: "말한 시간대예요",
  prefer_day: "말한 요일이에요",
  start_minus_20: "공사 시작 20일 전쯤이에요",
  earliest: "가장 빠른 날이에요",
  vendor_proposal: "업체가 낸 날이에요",
};
export function whyText(why: string[]): string[] {
  return why.map((w) => WHY[w] ?? (/^[a-z0-9_]+$/.test(w) ? "" : w)).filter(Boolean);
}
