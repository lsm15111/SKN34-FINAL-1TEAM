// v4 비서 API 입구(계약서 '03-비서 백엔드 설계' 3장 · 5장). 브라우저에서 불러요(lib/api/chat.ts처럼 /api/* · client.ts).
// - SSE: ack → status · card · action(여러 번) → token(여러 번) → done(실패면 error). 모든 data에 seq가 붙고, 이미 받은 seq 이하는 버려요.
// - REST: feed · actions(approve · reject) · nudges(open · dismiss) · memory · 업체 브리핑.
// - 목업(lib/mock/assistant)이면 같은 모양 · 같은 이벤트를 대본으로 흘려요. 목업 모듈은 쓸 때만 불러요(운영 묶음에 안 들어가게).
// - 금액 · 날짜 · 차액 · 기한은 서버(계산 엔진) 값이에요. 화면은 모양만 바꾸고 계산하지 않아요.
// 계약서에 없어서 화면 쪽에서 제안한 칸: status.task · card.say · done.chips · done.suggest · action.kind · status · supersedes · feed.now · board
import { ApiError, call, type Schemas } from "@/lib/backend/client";
import { ASSISTANT_MOCK } from "@/lib/mock/assistant/mode";

// ───── 카드(kind로 구분, components/assistant/cards/registry)

export type CardKind =
  | "home_info" | "standard_quote" | "vendor_picks" | "visit_slots" | "quote_compare" | "schedule"
  | "knowledge" | "answer" | "floorplan_links" | "today" | "vendor_brief" | "quote_checklist";

/** 출처 이름표: 믿집 계산(계산 엔진) · AI 답변(LLM 글) · 믿집 안내(정해 둔 글) */
export type Source = "calc" | "ai" | "guide";

export type AddressHit = { id: string; name: string; road: string };
export type HomeInfoData = {
  /** search: 주소 찾기 · confirm: 단지 · 면적 확인 · manual: 평형만 */
  phase: "search" | "confirm" | "manual";
  query?: string;
  hits?: AddressHit[];
  picked?: string | null;
  complex?: { name: string; road: string; households: number; approved_year: number; corridor: string } | null;
  dongs?: string[];
  area?: { exclusive_m2: string; supply_m2: string; pyeong_type: string } | null;
  pyeong_options?: string[];
  sources?: string[];
  /** 맞아요 = 이 제안 행동 승인(propose_home_info). 승인 뒤에는 카드가 끝난 모양으로 남아요 */
  action_id?: string | null;
  saved?: boolean;
};

export type StandardQuoteData = {
  total_won: number;
  /** '도배 · 실크 · 전용 84.97㎡ · 살면서 공사' */
  label: string;
  lines: { name: string; won: number }[];
  decided?: string[];
  partial?: boolean;
  href: string;
};

export type VendorPick = {
  ref: string; vendor_id: string; name: string;
  photo: string | null; photo_alt: string;
  rating: number | null; reviews: number; done_jobs: number;
  /** 가견적(부가세 포함). 업체가 단가를 확인하기 전이면 추천에서 빠져요 */
  estimate_won: number;
  /** 점수 항목 템플릿 글(AI가 쓰지 않아요) */
  reasons: string[];
  badge?: string | null;
  picked: boolean;
  href: string;
};
export type VendorPicksData = { area_name: string; picks: VendorPick[]; basis: string[]; more_href: string };

export type SlotCandidate = { ref: string; vendor_name: string; day: string; half: "am" | "pm"; why: string[] };
export type VisitSlotsData = { vendor_name: string; window: { start: string; end: string }; candidates: SlotCandidate[]; chosen: string | null; instant: boolean; calendar_href: string };

export type CompareCol = {
  visit_id: string; vendor_name: string;
  state: "quoted" | "waiting";
  version?: number; received_on?: string;
  total_won?: number | null;
  /** 앞 판과 차액(서버 값) */
  changed?: { from_version: number; diff_won: number } | null;
  diff_vs_estimate_won?: number | null;
  days?: number | null;
  valid_until?: string | null; valid_soon?: boolean; expired?: boolean;
  demolish?: boolean | null; waste?: boolean | null;
  paper?: string | null; warranty_months?: number | null;
  file?: { kind: "pdf" | "image"; label: string; href: string } | null;
  wait_note?: string | null;
};
export type QuoteCompareData = { cols: CompareCol[]; gap_won: number | null; ask_chips: string[]; href: string };

export type ScheduleData = {
  /** dates: 업체가 올린 공사 날짜(수락 전) · final: 확정 공정표 */
  phase: "dates" | "final";
  vendor_name: string;
  start: string; end: string; work_days: number;
  /** 하루씩: 오전 · 오후 칸에 들어간 공정 이름(없으면 null) */
  days: { day: string; am: string | null; pm: string | null; off?: boolean }[];
  conflicts: string[];
  plan_version: number;
  move_in?: string | null;
  href: string;
  ics_href?: string | null;
};

export type KnowledgeData = {
  title: string; lines: string[]; source: string;
  checklist?: { key: string; label: string; done: boolean }[];
  href?: string | null;
};
export type AnswerData = { text: string; src: Source; links?: { label: string; href: string }[] };
export type FloorplanLinksData = { complex: string; links: { label: string; href: string; source: string }[]; note: string };

export type TodayIcon = "doc" | "calendar" | "file" | "chat" | "bulb" | "inbox";
export type TodayRow = { id: string; icon: TodayIcon; title: string; sub?: string; due?: boolean; action?: { label: string; href?: string; say?: string; primary?: boolean } };
export type TodayData = { date: string; nudge_id: string | null; dismissed?: boolean; todo: TodayRow[]; waiting: TodayRow[]; news: TodayRow[]; know: TodayRow[] };

export type FitRow = { key: "trade" | "area" | "schedule" | "paper"; label: string; ok: boolean; text: string };
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
  /** 문장 하나만 AI(실패하면 null) */
  sentence: string | null;
};
export type QuoteChecklistData = {
  visit_id: string;
  items: { key: string; label: string; state: "ok" | "check" | "missing"; hint?: string }[];
  fields: { label: string; value: string | null }[];
  easy_miss: string[];
  prev: { version: number; total_won: number } | null;
};

export type CardData = {
  home_info: HomeInfoData; standard_quote: StandardQuoteData; vendor_picks: VendorPicksData; visit_slots: VisitSlotsData;
  quote_compare: QuoteCompareData; schedule: ScheduleData; knowledge: KnowledgeData; answer: AnswerData;
  floorplan_links: FloorplanLinksData; today: TodayData; vendor_brief: VendorBriefData; quote_checklist: QuoteChecklistData;
};
export type CardOut<K extends CardKind = CardKind> = { card_id: string; kind: K; data: CardData[K]; say?: string | null };

// ───── 작업 · 제안 행동(승인 카드)

export type TaskState = "running" | "waiting" | "done" | "failed" | "cancelled";
export type RowState = TaskState | "need";
export type TaskRow = { label: string; state: RowState; text: string; note?: string };
export type TaskOut = {
  task_id: string; title: string; state: TaskState; at: string;
  due?: string | null; rows?: TaskRow[]; sources?: string[];
  link?: { label: string; href: string } | null;
  error?: string | null;
};

/** 제안 도구와 1:1(propose_*) */
export type ActionKind = "home_info" | "visit_request" | "visit_slot" | "vendor_confirm" | "dates_accept" | "delay_accept" | "window_answer" | "decline" | "dates";
export type ActionStatus = "proposed" | "approved" | "executed" | "rejected" | "expired" | "failed";
/** 무엇 · 얼마 · 어느 버전(assistant_actions.summary). 금액 · 차액은 서버 값 */
export type ActionSummary = {
  title: string;
  amount_won?: number | null;
  amounts?: { label: string; won: number }[];
  /** 바뀐 때만: 앞 값 → 새 값, 차액 */
  diff?: { label: string; from_won: number; to_won: number; diff_won: number } | null;
  version?: string | null;
  rows?: { label: string; value: string; sub?: string }[];
  photos?: string[];
  file?: { label: string; href: string } | null;
  /** 그 뒤 일(한 줄) */
  note?: string | null;
  approve_label: string;
};
export type ActionOut = {
  action_id: string; kind: ActionKind; status: ActionStatus;
  summary: ActionSummary;
  target_ver?: string | null;
  expires_at: string;
  decided_at?: string | null; executed_at?: string | null;
  error_code?: string | null;
  result?: { text: string; href?: string | null; label?: string | null } | null;
  /** 판이 바뀌어 새로 만든 행동이면 옛 행동 id(409 quote_changed 뒤) */
  supersedes?: string | null;
};

export type SuggestOut = { id: string; text: string; why: string; say: string; nudge_id?: string | null };

// ───── SSE 이벤트

export type SseAck = { seq: number; turn_id: string; chat_id: string; at?: string };
export type SseStatus = { seq: number; text: string; task?: TaskOut | null };
export type SseCard = { seq: number } & CardOut;
export type SseAction = { seq: number } & ActionOut;
export type SseToken = { seq: number; text: string };
export type SseDone = { seq: number; rev: number; mode: "llm" | "free"; cards: string[]; actions: string[]; stopped?: boolean; chips?: string[]; suggest?: SuggestOut | null };
export type SseError = { seq: number; code: string; message: string };
export type TurnEvent =
  | { type: "ack"; data: SseAck }
  | { type: "status"; data: SseStatus }
  | { type: "card"; data: SseCard }
  | { type: "action"; data: SseAction }
  | { type: "token"; data: SseToken }
  | { type: "done"; data: SseDone }
  | { type: "error"; data: SseError };

/** 같은 턴에서 이미 받은 seq 이하를 버려요(다시 잇기 · 중복 전송) */
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
export type FeedItem =
  | { id: string; role: "user"; at: string; text: string }
  | { id: string; role: "assistant"; at: string; turn_id: string | null; parts: FeedPart[]; done?: boolean; mode?: "llm" | "free"; error?: { code: string; message: string } | null; status?: string | null };
export type FeedPage = { items: FeedItem[]; before: string | null; rev: number; chips: string[]; now: string };

export type TurnIn = {
  project_id: string;
  client_key: string;
  text: string;
  /** 카드에서 고른 것(주소 · 업체 · 반나절 등). LLM에는 ref만 가요 */
  context?: { card_id?: string; choice?: string | string[] } | null;
};

// ───── 보드 · 기억 · 알림

export type MemoryKey = "avail_days" | "avail_half" | "living" | "style" | "material" | "priority" | "pet" | "diy";
export type MemoryOut = { id: string; key: MemoryKey; value: string; evidence_message_id: string; evidence_quote: string };

export type BoardOut = {
  project_name: string;
  /** 단계 띠 지금 칸(0 집 정보 ~ 6 공사) */
  step: number;
  facts: string[];
  confirmed: boolean;
  todo: number; waiting: number;
  money: { label: string; won?: number | null; range?: [number, number] | null } | null;
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
  const item = next[i] as Extract<FeedItem, { role: "assistant" }>;
  const put = (parts: FeedPart[], patch: Partial<Extract<FeedItem, { role: "assistant" }>> = {}) =>
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
      const parts = ev.data.suggest ? [...item.parts, { t: "suggest" as const, suggest: ev.data.suggest }] : item.parts;
      return put(parts, { done: true, mode: ev.data.mode, status: null });
    }
    case "error":
      return put(item.parts, { done: true, status: null, error: { code: ev.data.code, message: ev.data.message } });
  }
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

/** 승인 · 거절 결과로 행동 카드를 바꿔요 */
export function replaceAction(items: FeedItem[], action: ActionOut): FeedItem[] {
  return swapPart(items, (p) => p.t === "action" && p.action.action_id === action.action_id, { t: "action", action }) ?? items;
}

/** 카드 하나의 data를 바꿔요(오늘 정할 일 닫기 등) */
export function replaceCard(items: FeedItem[], card: CardOut): FeedItem[] {
  return swapPart(items, (p) => p.t === "card" && p.card.card_id === card.card_id, { t: "card", card }) ?? items;
}

// ───── 실제 API(목업이면 대본)

const mock = () => import("@/lib/mock/assistant/server");
const enc = encodeURIComponent;

/** 대화 기록 첫 쪽(30개). before를 주면 그 앞 쪽 */
export async function getFeed(projectId: string, before?: string): Promise<FeedPage> {
  if (ASSISTANT_MOCK) return (await mock()).feed(projectId);
  const q = new URLSearchParams({ project_id: projectId, limit: "30" });
  if (before) q.set("before", before);
  return call<FeedPage>("GET", `/assistant/feed?${q}`);
}

/** 내 공사 보드(우리 집 · 지금 · 낼 금액 · 업체 · 기간 · 서류 · 기억) */
export async function getBoard(projectId: string): Promise<BoardOut> {
  if (ASSISTANT_MOCK) return (await mock()).board(projectId);
  return call<BoardOut>("GET", `/assistant/board?project_id=${enc(projectId)}`);
}

/** 한 턴(SSE). 스트림을 열기 전 오류(404 · 409 turn_running · 429)는 ApiError로 던져요 */
export async function streamTurn(body: TurnIn, on: (e: TurnEvent) => void, signal?: AbortSignal): Promise<void> {
  const emit = seqFilter(on);
  if (ASSISTANT_MOCK) return (await mock()).turn(body, emit, signal);
  let res: Response;
  try {
    res = await fetch("/api/assistant/turns", {
      method: "POST", credentials: "same-origin", signal,
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.");
  }
  if (!res.ok || !res.body) {
    const e = (await res.json().catch(() => null))?.error;
    throw new ApiError(res.status, e?.code ?? "unknown", e?.message ?? "답을 만들지 못했어요. 다시 해 주세요.");
  }
  await readSse(res.body, emit);
}

const TYPES = new Set(["ack", "status", "card", "action", "token", "done", "error"]);
/** text/event-stream 읽기: 'event: 이름' · 'data: JSON' 묶음을 빈 줄로 나눠요 */
export async function readSse(body: ReadableStream<Uint8Array>, on: (e: TurnEvent) => void): Promise<void> {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    buf += dec.decode(value ?? new Uint8Array(), { stream: !done });
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

/** 열린 제안 행동(같은 종류는 하나만 살아 있어요) */
export async function listActions(projectId: string): Promise<ActionOut[]> {
  if (ASSISTANT_MOCK) return (await mock()).actions(projectId);
  return call<ActionOut[]>("GET", `/assistant/actions?project_id=${enc(projectId)}&status=proposed`);
}

/** 승인: 멱등 키 · 본 버전을 같이 보내요. 이미 실행한 행동이면 200(같은 결과), 판이 바뀌었으면 409 */
export async function approveAction(projectId: string, actionId: string, seen: { client_key: string; seen: string | null }): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).approve(projectId, actionId, seen.client_key);
  return call<ActionOut>("POST", `/assistant/actions/${enc(actionId)}/approve`, seen);
}
export async function rejectAction(projectId: string, actionId: string): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).reject(projectId, actionId);
  return call<ActionOut>("POST", `/assistant/actions/${enc(actionId)}/reject`);
}

/** 먼저 말 건 카드 열기 · 닫기(닫으면 같은 일을 3일 쉬어요) */
export async function openNudge(projectId: string, nudgeId: string): Promise<void> {
  if (ASSISTANT_MOCK) return;
  await call("POST", `/assistant/nudges/${enc(nudgeId)}/open`);
}
export async function dismissNudge(projectId: string, nudgeId: string): Promise<CardOut | null> {
  if (ASSISTANT_MOCK) return (await mock()).dismiss(projectId, nudgeId);
  await call("POST", `/assistant/nudges/${enc(nudgeId)}/dismiss`);
  return null;
}

export async function getMemory(projectId: string): Promise<MemoryOut[]> {
  if (ASSISTANT_MOCK) return (await mock()).memory(projectId);
  return call<MemoryOut[]>("GET", "/assistant/memory");
}
export async function forgetMemory(projectId: string, memoryId: string): Promise<void> {
  if (ASSISTANT_MOCK) return (await mock()).forget(projectId, memoryId);
  await call("DELETE", `/assistant/memory/${enc(memoryId)}`);
}

/** (새) 주소 찾기: 도로명주소 API 대행(로그인 없이, 요청 제한) */
export async function searchAddress(q: string): Promise<AddressHit[]> {
  if (ASSISTANT_MOCK) return (await mock()).searchAddress(q);
  return call<AddressHit[]>("GET", `/address/search?q=${enc(q)}`);
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

/** 서버가 먼저 보내는 턴(먼저 말 걸기 · 승인 뒤 이어지는 일). 목업만 여기서 흘려요.
 *  실제는 /stream(LiveProvider)의 state · notif로 feed를 다시 읽어요(hooks/useAssistant). 돌려준 함수로 그만 들어요 */
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

// ───── 업체(V1 요청 브리핑 · V3 견적서 체크리스트)

/** 업체가 보는 요청 사실(서버 화면이 넘겨요). 목업 브리핑이 이 값으로 요약 줄을 채워요 */
export type BriefSeed = { region?: string | null; area?: string | null; grade?: string | null; occupied?: boolean | null; wish?: { start: string; end: string } | null; work_wish_on?: string | null; estimate_won?: number | null; photos?: number; due_at?: string | null; memo?: string | null };

export async function getVendorBrief(visitId: string, seed?: BriefSeed): Promise<VendorBriefData> {
  if (ASSISTANT_MOCK) return (await mock()).vendorBrief(visitId, seed);
  return call<VendorBriefData>("GET", `/vendor/assistant/briefs/${enc(visitId)}`);
}
export async function getQuoteChecklist(visitId: string): Promise<QuoteChecklistData> {
  if (ASSISTANT_MOCK) return (await mock()).quoteChecklist(visitId);
  return call<QuoteChecklistData>("GET", `/vendor/assistant/checklists/${enc(visitId)}`);
}
export async function approveVendorAction(actionId: string, clientKey: string): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).approveVendor(actionId);
  return call<ActionOut>("POST", `/vendor/assistant/actions/${enc(actionId)}/approve`, { client_key: clientKey, seen: null });
}
export async function rejectVendorAction(actionId: string): Promise<ActionOut> {
  if (ASSISTANT_MOCK) return (await mock()).rejectVendor(actionId);
  return call<ActionOut>("POST", `/vendor/assistant/actions/${enc(actionId)}/reject`);
}

export type VendorTodayData = { date: string; rows: TodayRow[] };
/** 업체 작업함 맨 위 '오늘 브리핑'(줄은 코드가 골라요) */
export async function getVendorToday(): Promise<VendorTodayData> {
  if (ASSISTANT_MOCK) return (await mock()).vendorToday();
  return call<VendorTodayData>("GET", "/vendor/assistant/today");
}

/** 멱등 키(승인 · 턴마다 하나) */
export function newClientKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
