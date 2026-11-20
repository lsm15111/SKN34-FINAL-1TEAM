// v4 비서 목업 서버(브라우저 안). 계약서 3장의 SSE 이벤트 · REST 응답을 같은 모양으로 흘려요.
// - 대본 두 개: f1(처음 고객: 첫 대화(/start)에서 집을 저장한 뒤 → 표준견적서 · 먼저 말 건 제안 → 추천 3곳 → 실측 요청 승인 →
//   시간 후보 → 견적 비교 → 확정 승인 → 공정표) · today(오늘 정할 일). 상태는 공사마다 localStorage에 둬서 새로 고쳐도 그대로예요.
// - 승인 카드만 일을 실행해요. 빠른 답 칩 · 글은 실행하지 않아요(승인 없이 실행 0건).
// - 결도배 확정을 처음 누르면 '판 바뀜'(409 quote_changed)을 한 번 돌려줘요(새 판 + 차액 승인 카드 확인용).
// - 승인 뒤 이어지는 일(업체 답 · 견적서 도착)은 서버가 먼저 보내는 턴으로 흘려요(subscribe). 시각은 대본 시계예요.
// - 실제 서버처럼 전체 화면 카드 안 v3 단추가 한 일은 행동 행을 닫지 않아요('처리됨'은 화면이 표시해요).
import { ApiError, type Schemas } from "@/lib/backend/client";
import {
  applyTurnEvent, MEMORY_LABEL, replaceAction, replaceCard,
  type ActionKind, type ActionOut, type ActionStatus, type ActionSummary, type BoardOut, type BriefSeed, type CardOut, type CompareCol,
  type Demolition, type FeedItem, type FeedPage, type HealthOut, type HomeInfoData, type MemoryOut, type NotifyPage, type QuoteChecklistData,
  type QuoteCompareData, type SuggestOut, type TaskOut, type TaskRow, type ThreadOut, type TodayData, type TurnEvent, type TurnIn, type VendorBriefData,
  type VendorTodayData,
} from "@/lib/api/assistant";
import { dateLong, dateShort, euro, halfDayText, rangeText, won } from "@/lib/format";
import type { MockScript } from "./mode";
import * as D from "./data";

type Stage = "standard" | "vendors" | "requested" | "slots" | "booked" | "compare" | "confirmed" | "dates" | "final";
type Note = Schemas["NotificationOut"];
type State = {
  v: number;
  pid: string;
  script: MockScript;
  stage: Stage;
  clock: string;
  items: FeedItem[];
  actions: Record<string, ActionOut>;
  chips: string[];
  rev: number;
  n: number;
  notes: Note[];
  picks: string[];
  quoteVer: 1 | 2;
  quoteFailOnce: boolean;
  todayDismissed: boolean;
  demolition: Demolition | null;
  /** 희망 기간 카드에서 고른 기간(r1 …). 실측 요청 승인 카드의 희망 기간이 돼요 */
  wish: string | null;
  /** 확정 승인 카드를 만든 · 확정한 업체 */
  deal: "gyeol" | "bareun";
  /** 승인 뒤 이어질 일(새로 고쳐도 이어지게 시각과 함께 저장) */
  pending: { beat: Beat; at: number }[];
};
type Beat = "sent" | "answered" | "booked" | "maruBooked" | "quoted" | "closed" | "dates" | "final";
type Draft =
  | { type: "ack"; data: { turn_id: string; chat_id: string; at: string } }
  | { type: "status"; data: { text: string; task?: TaskOut | null } }
  | { type: "card"; data: CardOut }
  | { type: "action"; data: ActionOut }
  | { type: "token"; data: { text: string } }
  | { type: "done"; data: { rev: number; mode: "llm" | "free"; cards: string[]; actions: string[]; chips?: string[]; stopped?: boolean; suggest?: SuggestOut[] } }
  | { type: "error"; data: { code: string; message: string } };
type Step = { wait: number; ev: Draft; clock?: string; apply?: (s: State) => void; dup?: boolean };
type Plan = { steps: Step[]; after?: (s: State) => void };

const VERSION = 6;
const KEY = (pid: string) => `mj_v4_mock:${pid}`;
const MEMORY_KEY = "mj_v4_mock:memory";
const cache = new Map<string, State>();
const subs = new Map<string, Set<(turnId: string, e: TurnEvent) => void>>();
const chains = new Map<string, Promise<unknown>>();

// ───── 저장 · 불러오기

function load(pid: string): State {
  const hit = cache.get(pid);
  if (hit) return hit;
  let s: State | null = null;
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(KEY(pid)) : null;
    const v = raw ? (JSON.parse(raw) as State) : null;
    if (v && v.v === VERSION) s = v;
  } catch { /* 못 읽으면 처음부터 */ }
  s ??= init(pid, "f1");
  // 새로 고침으로 끊긴 턴은 받은 데까지로 끝내요(입력 중 점이 남지 않게)
  s.items = s.items.map((it) => (it.role === "assistant" && !it.done ? { ...it, done: true, status: null } : it));
  cache.set(pid, s);
  // 새로 고친 뒤 남은 일은 화면이 들을 준비를 마친 뒤에 다시 보내요(최소 1.5초)
  for (const p of s.pending) arm(pid, p.beat, Math.max(1500, p.at - Date.now()));
  return s;
}
function save(s: State) {
  cache.set(s.pid, s);
  try { window.localStorage.setItem(KEY(s.pid), JSON.stringify(s)); } catch { /* 못 써도 이번 탭에서는 이어져요 */ }
}
/** 기억은 사람마다(공사와 상관없이) 하나예요 */
function readMemory(): MemoryOut[] {
  try { const raw = window.localStorage.getItem(MEMORY_KEY); const v: unknown = raw ? JSON.parse(raw) : []; return Array.isArray(v) ? (v as MemoryOut[]) : []; } catch { return []; }
}
function writeMemory(m: MemoryOut[]) {
  try { window.localStorage.setItem(MEMORY_KEY, JSON.stringify(m.slice(-12))); } catch { /* 편의 */ }
}
const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((ok) => {
    if (!ms || signal?.aborted) return ok();
    const t = setTimeout(ok, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); ok(); }, { once: true });
  });
function enqueue<T>(pid: string, fn: () => Promise<T>): Promise<T> {
  const prev = chains.get(pid) ?? Promise.resolve();
  const next = prev.then(fn, fn);
  chains.set(pid, next.catch(() => undefined));
  return next;
}

// ───── 조각 만들기

const base = (pid: string, script: MockScript, clock: string): State => ({
  v: VERSION, pid, script, stage: "standard", clock, items: [], actions: {}, chips: [], rev: 1, n: 0,
  notes: [], picks: ["gyeol", "bareun", "maru"], quoteVer: 1, quoteFailOnce: true, todayDismissed: false, demolition: null, wish: null, deal: "gyeol", pending: [],
});
const href = (s: State, tail = "") => `/projects/${encodeURIComponent(s.pid)}${tail}`;
const nextId = (s: State, p: string) => `${p}-${++s.n}`;

function note(s: State, body: string, tail: string, kind = "assistant") {
  s.notes = [{ id: nextId(s, "n"), kind, project_id: s.pid, body, link: href(s, tail), created_at: s.clock, read: false }, ...s.notes];
}

function makeAction(s: State, kind: ActionKind, summary: ActionSummary, expires_at: string, extra: Partial<ActionOut> = {}): ActionOut {
  const a: ActionOut = { action_id: nextId(s, `act-${kind}`), kind, status: "proposed", summary, expires_at, ...extra };
  s.actions[a.action_id] = a;
  return a;
}
function setAction(s: State, a: ActionOut) {
  s.actions[a.action_id] = a;
  s.items = replaceAction(s.items, a);
}
/** 같은 종류의 열린 제안은 하나만: 새로 만들면 옛 것은 '새 카드로 바뀜' */
function closeOpen(s: State, kind: ActionKind): Step[] {
  return Object.values(s.actions)
    .filter((a) => a.kind === kind && a.status === "proposed")
    .map((a) => {
      const closed: ActionOut = { ...a, status: "expired", error_code: "replaced" };
      s.actions[a.action_id] = closed;
      return { wait: 0, ev: { type: "action", data: closed } } as Step;
    });
}

const step = (ev: Draft, wait = 0, more: Partial<Step> = {}): Step => ({ wait, ev, ...more });
const sentences = (text: string, wait = 260): Step[] => text.split(/(?<=[.?!요])\s+/).filter(Boolean).map((t, i) => step({ type: "token", data: { text: (i ? " " : "") + t } }, wait));
const done = (s: State, chips: string[], extra: Partial<Extract<Draft, { type: "done" }>["data"]> = {}): Step =>
  step({ type: "done", data: { rev: s.rev + 1, mode: "llm", cards: [], actions: [], chips, ...extra } }, 120, { apply: (x) => { x.rev += 1; x.chips = chips; } });

const DEMO_LABEL: Record<Demolition, string> = { full: "전체 철거", partial: "일부", none: "안 함" };
function homeCard(s: State, extra: Partial<HomeInfoData> = {}): CardOut<"home_info"> {
  return {
    card_id: "home", kind: "home_info",
    data: { phase: "confirm", facts: D.HOME.facts, area: D.HOME.area, changes: [], action_id: null, saved: true, locked: s.stage !== "standard" && s.stage !== "vendors", demolition: s.demolition, ...extra },
  };
}
function standardCard(s: State): CardOut<"standard_quote"> {
  return { card_id: "standard", kind: "standard_quote", say: "표준견적서가 나왔어요.", data: { ...D.STANDARD, href: href(s, "/standard") } };
}
function picksCard(s: State): CardOut<"vendor_picks"> {
  return {
    card_id: "picks-dobae", kind: "vendor_picks", say: "노원구에서 이 집 조건에 맞는 곳이에요.",
    data: {
      area_name: "노원구",
      picks: D.VENDORS.map((v) => ({
        ref: v.ref, vendor_id: v.id, name: v.name, photo: v.photo, photo_alt: `${v.name} 시공 사례`, rating: v.rating, reviews: v.reviews,
        done_jobs: v.done, estimate_won: v.est, reasons: v.reasons, badge: v.badge ?? null, picked: s.picks.includes(v.key), href: href(s, "/vendors"),
      })),
      basis: ["이 구에서 일하고 이 공정을 해요", "업체가 단가를 확인해 가견적이 있어요", "별점 · 끝낸 공사 · 가견적으로 점수를 매겨요"],
      more_href: href(s, "/vendors"),
    },
  };
}
function visitRequestAction(s: State): ActionOut {
  const vs = D.VENDORS.filter((v) => s.picks.includes(v.key));
  const w = D.WISHES.find((x) => x.ref === s.wish) ?? D.WISH;
  return makeAction(s, "visit_request", {
    title: "실측 요청 보내기",
    amounts: vs.map((v) => ({ label: v.name, won: v.est })),
    rows: [
      { label: "가견적", value: "11월 15일 확인한 단가로 고정돼요" },
      { label: "희망 기간", value: rangeText(w.start, w.end, { weekday: true }), sub: s.wish ? "고른 희망 기간이에요" : `공사 시작 희망 ${dateLong(D.WISH.work_wish_on)} 기준` },
      { label: "사진", value: "4장" },
    ],
    note: "업체마다 48시간 안에 갈 수 있는 기간을 답해요. 연락은 믿집 채팅으로 이어요",
    approve_label: `${vs.length}곳에 요청 보내기`,
  }, D.T("2026-11-22", "10:05"), { target_ver: "prices-2026-11-15" });
}
function visitTask(s: State, phase: "sent" | "answered" | "booked" | "quoted" | "closed"): TaskOut {
  const due = dueTextOf("2026-11-23", "10:06");
  const rows: Record<typeof phase, TaskRow[]> = {
    sent: D.VENDORS.filter((v) => s.picks.includes(v.key)).map((v) => ({ label: v.name, state: "waiting", text: "답 기다림", note: due })),
    answered: [
      { label: "결도배", state: "need", text: "날짜 고를 차례", note: "11.23~11.28 중 반나절" },
      { label: "바른벽", state: "done", text: "실측 확정", note: "11.24(화) 오후 · 바로 확정" },
      { label: "마루와벽", state: "waiting", text: "답 기다림", note: due },
    ],
    booked: [
      { label: "결도배", state: "done", text: "실측 확정", note: "11.24(화) 오전" },
      { label: "바른벽", state: "done", text: "실측 확정", note: "11.24(화) 오후" },
      { label: "마루와벽", state: "waiting", text: "답 기다림", note: due },
    ],
    quoted: [
      { label: "결도배", state: "done", text: "견적서 옴", note: `${s.quoteVer}판 · 11.26(목)` },
      { label: "바른벽", state: "done", text: "견적서 옴", note: "1판 · 11.25(수)" },
      { label: "마루와벽", state: "need", text: "날짜 고를 차례", note: "업체가 다른 날을 냈어요" },
    ],
    closed: D.VENDORS.map((v): TaskRow => (v.key === s.deal
      ? { label: v.name, state: "done", text: "확정", note: `${v.key === "gyeol" ? s.quoteVer : 1}판` }
      : { label: v.name, state: "cancelled", text: "닫힘", note: "다른 업체를 확정했어요" })),
  };
  const title = phase === "quoted" || phase === "closed" ? "실측 · 견적서 3곳" : `실측 요청 ${rows.sent.length || 3}곳`;
  const state = phase === "closed" ? "done" : "waiting";
  return { task_id: "task-visits", title, state, at: s.clock, rows: rows[phase], link: { label: "실측 일정 보기", href: href(s, "/visits") } };
}
const dueTextOf = (day: string, hm: string) => `${dateShort(day)} ${hm}까지`;

function slotsCard(s: State, who: "gyeol" | "maru", chosen: string): CardOut<"visit_slots"> {
  const list = who === "gyeol" ? D.SLOTS : D.MARU_SLOTS;
  const v = D.vendorOf(who);
  const am = readMemory().some((m) => m.key === "avail_half");
  return {
    card_id: `slots-${who}`, kind: "visit_slots",
    say: who === "gyeol" ? "결도배가 갈 수 있는 기간을 답했어요. 이 시간 어때요?" : "마루와벽이 다른 날을 냈어요. 이 중에서 골라 주세요.",
    data: {
      vendor_name: v.name,
      window: who === "gyeol" ? { start: "2026-11-23", end: "2026-11-28" } : { start: "2026-11-25", end: "2026-11-26" },
      candidates: list.map((c) => ({ ref: c.ref, vendor_name: v.name, day: c.day, half: c.half, why: am && c.half === "am" && who === "gyeol" ? ["prefer_half", ...c.why] : c.why })),
      wishes: [],
      chosen, instant: who === "maru", calendar_href: href(s, "/visits"),
      vendor_note: who === "maru" ? D.MARU_NOTE : null,
    },
  };
}
/** 반나절 이름표 → 그 업체(마루와벽이 낸 날이면 maru) */
const slotOwner = (ref: string): "gyeol" | "maru" => (D.MARU_SLOTS.some((x) => x.ref === ref) ? "maru" : "gyeol");
function slotAction(s: State, ref: string): ActionOut {
  const c = [...D.SLOTS, ...D.MARU_SLOTS].find((x) => x.ref === ref) ?? D.SLOTS[0];
  const who = slotOwner(c.ref);
  const v = D.vendorOf(who);
  return makeAction(s, "visit_slot", {
    title: `${v.name} 실측 ${halfDayText(c.day, c.half)}`,
    version: who === "gyeol" ? "업체가 답한 기간 11.23~11.28" : "업체가 낸 날 2개",
    rows: [{ label: "그 뒤 일", value: who === "maru" ? "고르면 바로 확정돼요" : "업체가 수락하면 확정돼요" }],
    note: "시각은 실측 전날 채팅으로 정해요",
    approve_label: "이 시간으로 고르기",
  }, who === "gyeol" ? D.T("2026-11-23", "09:20") : D.T("2026-11-24", "18:00"), { target_ver: `${who}-window-1` });
}

function compareCard(s: State): CardOut<"quote_compare"> {
  const g = s.quoteVer === 2 ? D.QUOTES.gyeol2 : D.QUOTES.gyeol1;
  const b = D.QUOTES.bareun1;
  const col = (ref: string, vid: string, name: string, q: typeof g | typeof b, changed: CompareCol["changed"]): CompareCol => ({
    ref, visit_id: vid, vendor_name: name, state: "quoted", version: q.version, received_on: q.received_on, total_won: q.total_won, changed,
    diff_vs_estimate_won: q.diff_vs_estimate_won, days: q.days, valid_until: q.valid_until, valid_soon: q.valid_until === "2026-11-27",
    demolish: q.demolish, waste: q.waste, vendor_note: q.vendor_note, warranty_months: q.warranty_months,
    file: { kind: q.file === "PDF" ? "pdf" : "image", label: q.file, href: href(s, "/quotes") },
  });
  const data: QuoteCompareData = {
    cols: [
      col("m1", "vq-gyeol", "결도배", g, s.quoteVer === 2 ? { from_version: 1, diff_won: D.QUOTES.change } : null),
      col("m2", "vq-bareun", "바른벽", b, null),
      { ref: "m3", visit_id: "vq-maru", vendor_name: "마루와벽", state: "waiting", wait_note: "견적서 기다림" },
    ],
    gap_won: s.quoteVer === 2 ? D.QUOTES.gap2 : D.QUOTES.gap1,
    ask_chips: ["폐기물 처리도 포함인가요?"],
    href: href(s, "/quotes"),
  };
  return { card_id: "compare-dobae", kind: "quote_compare", say: "실측 견적서가 2곳 왔어요.", data };
}
/** 확정할 업체의 지금 견적서(결도배는 판이 바뀔 수 있어요) */
const quoteOf = (s: State, who: "gyeol" | "bareun") => (who === "bareun" ? D.QUOTES.bareun1 : s.quoteVer === 2 ? D.QUOTES.gyeol2 : D.QUOTES.gyeol1);
/** 비교 카드 열 이름표(m1 결도배 · m2 바른벽) → 업체. 견적서가 없는 열(m3)은 null */
const quoteOwner = (ref: string): "gyeol" | "bareun" | null => (ref === "m1" ? "gyeol" : ref === "m2" ? "bareun" : null);
function confirmAction(s: State, who: "gyeol" | "bareun" = "gyeol", supersedes: string | null = null): ActionOut {
  const g = quoteOf(s, who);
  const name = euro(D.vendorOf(who).name);
  return makeAction(s, "vendor_confirm", {
    title: `${name} 확정`,
    amount_won: g.total_won,
    diff: who === "gyeol" && s.quoteVer === 2 ? { label: "1판보다", from_won: D.QUOTES.gyeol1.total_won, to_won: g.total_won, diff_won: D.QUOTES.change } : null,
    version: `견적서 ${g.version}판`,
    rows: [{ label: "공사 기간", value: `${g.days}일` }, { label: "유효기간", value: `${g.valid_until}까지` }],
    note: "확정하면 같은 공정의 다른 요청은 닫혀요",
    approve_label: `${name} 확정`,
  }, D.T(g.valid_until, "18:00"), { target_ver: `${who}-${g.version}`, supersedes });
}
/** 확정한 업체 이름 + 이/가(결도배가 · 바른벽이) */
const dealWho = (s: State) => `${D.vendorOf(s.deal).name}${s.deal === "gyeol" ? "가" : "이"}`;
function datesCard(s: State, phase: "dates" | "final"): CardOut<"schedule"> {
  return {
    card_id: phase === "dates" ? "dates-1" : "plan-2", kind: "schedule",
    say: phase === "dates" ? `${dealWho(s)} 공사 날짜를 올렸어요.` : "확정 공정표예요.",
    data: {
      phase, vendor_name: D.vendorOf(s.deal).name, start: D.WORK.start, end: D.WORK.end, work_days: D.WORK.work_days, days: D.WORK.days,
      conflicts: [], plan_version: phase === "dates" ? 1 : 2,
      href: href(s, phase === "dates" ? "/schedule" : "/plan"), ics_href: phase === "final" ? `/api/projects/${encodeURIComponent(s.pid)}/plan.ics` : null,
    },
  };
}
function datesAction(s: State): ActionOut {
  return makeAction(s, "dates_accept", {
    title: `도배 ${rangeText(D.WORK.start, D.WORK.end, { weekday: true })} 수락`,
    version: "공정표 1판",
    rows: [{ label: "일하는 날", value: `${D.WORK.work_days}일` }],
    note: "수락하면 확정 공정표가 만들어지고, 공사 전날 준비물을 알려 드려요",
    approve_label: "이 날짜로 수락",
  }, D.T("2026-11-29", "11:00"), { target_ver: "1" });
}
function knowCard(): CardOut<"knowledge"> {
  return { card_id: "know-move", kind: "knowledge", say: "공사 전에 알아 두면 좋아요.", data: { ...D.KNOW.move, href: null } };
}
function answerCard(s: State, text: string, links: { label: string; href: string }[] = []): CardOut<"answer"> {
  return { card_id: nextId(s, "ans"), kind: "answer", data: { text, src: "guide", links } };
}

// ───── 처음 상태

function init(pid: string, script: MockScript): State {
  return script === "today" ? initToday(pid) : initF1(pid);
}
function initF1(pid: string): State {
  const s = base(pid, "f1", D.T("2026-11-21", "10:00"));
  // 먼저 말 건 줄(서버 feed처럼 turn_id 없음 · nudge_id)이라 턴이 이어져도 제안이 남아요
  s.items = [{
    id: "a-hello", role: "assistant", at: s.clock, turn_id: null, nudge_id: "nudge-vendors", done: true,
    parts: [
      { t: "text", src: "guide", text: "안녕하세요. 공사를 끝까지 챙기는 믿집 비서예요.\n첫 대화에서 넣은 집으로 표준견적서를 만들었어요." },
      { t: "card", card: homeCard(s) },
      { t: "card", card: standardCard(s) },
      { t: "suggest", suggest: { id: "sg-vendors", text: "업체 3곳을 골라 둘까요?", why: "노원구에서 가견적을 낸 도배 업체가 5곳 있어요", say: "업체 추천해 줘", nudge_id: "nudge-vendors" } },
    ],
  }];
  s.chips = ["업체 추천해 줘", "표준견적서 금액 풀이해 줘", "가견적은 어떻게 계산해요?"];
  return s;
}
function initToday(pid: string): State {
  const s = base(pid, "today", D.T("2026-11-24", "09:00"));
  s.stage = "compare";
  s.quoteVer = 2;
  s.quoteFailOnce = false;
  if (!readMemory().length) writeMemory(D.MEMORY_SEED.map((m) => ({ ...m })));
  const sent: TaskOut = { task_id: "task-sent", title: "실측 요청 3곳", state: "done", at: D.T("2026-11-21", "10:06"), rows: [], link: { label: "실측 일정 보기", href: href(s, "/visits") } };
  const old = makeAction(s, "visit_slot", {
    title: "마루와벽 실측 11.23(월) 오후", version: "업체가 답한 기간 11.23~11.27",
    rows: [{ label: "그 뒤 일", value: "고르면 바로 확정돼요" }], approve_label: "이 시간으로 고르기",
  }, D.T("2026-11-23", "09:20"));
  const expired: ActionOut = { ...old, status: "expired", error_code: "due" };
  s.actions[old.action_id] = expired;
  const today: CardOut<"today"> = { card_id: "today", kind: "today", data: todayData(s) };
  s.items = [
    { id: "a-old-1", role: "assistant", at: D.T("2026-11-21", "10:06"), turn_id: "old-1", done: true, parts: [{ t: "task", task: sent }, { t: "text", src: "guide", text: "희망 기간 11.23~12.4로 세 곳에 보냈어요." }] },
    { id: "a-old-2", role: "assistant", at: D.T("2026-11-22", "09:20"), turn_id: "old-2", done: true, parts: [{ t: "action", action: expired }] },
    { id: "a-today", role: "assistant", at: s.clock, turn_id: "today", done: true, parts: [{ t: "text", src: "ai", text: "좋은 아침이에요. 오늘은 두 가지만 정하면 돼요." }, { t: "card", card: today }] },
  ];
  s.chips = ["견적서 비교 보기", "마루와벽 날짜 고르기", "오늘은 그만"];
  s.notes = [
    { id: "n-4", kind: "assistant", project_id: pid, body: "오늘 정할 일이 2개 있어요", link: `${href(s)}?nudge=nudge-today`, created_at: D.T("2026-11-24", "09:00"), read: false },
    { id: "n-3", kind: "quote_resent", project_id: pid, body: "결도배가 실측 견적서를 다시 보냈어요", link: href(s, "/quotes"), created_at: D.T("2026-11-23", "20:14"), read: false },
    { id: "n-2", kind: "visit_offered", project_id: pid, body: "마루와벽이 다른 날을 냈어요", link: href(s, "/visits"), created_at: D.T("2026-11-23", "08:50"), read: true },
    { id: "n-1", kind: "quote_sent", project_id: pid, body: "바른벽이 실측 견적서를 보냈어요", link: href(s, "/quotes"), created_at: D.T("2026-11-22", "11:05"), read: true },
  ];
  return s;
}
function todayData(s: State): TodayData {
  if (s.script !== "today") {
    // f1: 열린 제안만 줄로(실제 today_for처럼 코드가 골라요)
    const open = Object.values(s.actions).filter((a) => a.status === "proposed" && a.kind !== "home_info");
    return { date: s.clock.slice(0, 10), nudge_id: null, todo: open.map((a) => ({ id: `a-${a.action_id}`, icon: "doc" as const, title: a.summary.title, sub: "승인 기다림" })), waiting: [], news: [], know: [] };
  }
  return {
    date: "2026-11-24", nudge_id: "nudge-today", dismissed: s.todayDismissed,
    todo: [
      { id: "t1", icon: "doc", title: "견적서 두 곳 보고 확정하기", sub: "바른벽 견적서는 11.27(금)까지 유효해요", due: true, action: { label: "비교 보기", say: "견적서 비교 보기", primary: true } },
      { id: "t2", icon: "calendar", title: "마루와벽 실측 날짜 고르기", sub: "오늘 18:00까지 · 11.25(수) 오전 · 11.26(목) 오후", due: true, action: { label: "날짜 고르기", say: "마루와벽 날짜 고르기" } },
    ],
    waiting: [],
    news: [
      { id: "n1", icon: "file", title: "결도배가 견적서 2판을 보냈어요", sub: `어제 20:14 · 1판보다 +${won(D.QUOTES.change)}` },
      { id: "n2", icon: "chat", title: "마루와벽이 채팅에 사진 2장을 보냈어요", sub: "어제 21:03", action: { label: "채팅", href: "/chat" } },
    ],
    know: [{ id: "k1", icon: "bulb", title: D.KNOW.move.title, sub: "공사 전날 준비물 · 표준 시방서", action: { label: "보기", say: "알아 두기 보여 줘" } }],
  };
}

// ───── 보드

const STEP: Record<Stage, number> = { standard: 1, vendors: 2, requested: 3, slots: 3, booked: 3, compare: 4, confirmed: 4, dates: 5, final: 6 };
function boardOf(s: State): BoardOut {
  const i = STEP[s.stage];
  const facts = [...D.HOME.facts, ...(s.demolition ? [`철거 ${DEMO_LABEL[s.demolition]}`] : [])];
  const g = s.quoteVer === 2 ? D.QUOTES.gyeol2 : D.QUOTES.gyeol1;
  const money: BoardOut["money"] =
    s.stage === "compare" ? { label: "받은 견적서 · 부가세 포함", range: [g.total_won, D.QUOTES.bareun1.total_won] }
      : i >= 4 ? { label: "확정 금액 · 부가세 포함", won: quoteOf(s, s.deal).total_won }
        : { label: "표준견적서 · 부가세 포함", won: D.STANDARD.total_won };
  const picked = D.VENDORS.filter((v) => s.picks.includes(v.key));
  const vendors: BoardOut["vendors"] =
    s.stage === "vendors" ? { title: `고른 업체 ${picked.length}/3`, rows: picked.map((v) => ({ name: v.name, state: "need", text: "가견적", won: v.est })) }
      : s.stage === "requested" ? { title: "업체", rows: picked.map((v) => ({ name: v.name, state: "waiting", text: "답 기다림" })) }
        : s.stage === "slots" || s.stage === "booked" ? { title: "업체", rows: visitTask(s, s.stage === "slots" ? "answered" : "booked").rows!.map((r) => ({ name: r.label, state: r.state, text: r.text })) }
          : s.stage === "compare" ? { title: "업체", rows: [{ name: "결도배", state: "done", text: `견적서 ${s.quoteVer}판` }, { name: "바른벽", state: "done", text: "견적서 1판" }, { name: "마루와벽", state: "need", text: "날짜 고르기" }] }
            : i >= 4 ? { title: "확정 업체", rows: [{ name: D.vendorOf(s.deal).name, state: "done", text: s.stage === "final" ? "공사 날짜 수락" : s.stage === "dates" ? "공사 날짜 옴" : "공사 날짜 기다림" }] }
              : null;
  const period: BoardOut["period"] =
    s.stage === "dates" || s.stage === "final"
      ? { label: "공사", value: rangeText(D.WORK.start, D.WORK.end, { weekday: true }), sub: s.stage === "final" ? "확정 공정표" : "수락 전" }
      : { label: "공사 시작 희망", value: dateLong(D.WISH.work_wish_on) };
  const docs = [{ label: "표준견적서", href: href(s, "/standard") }, { label: s.stage === "final" ? "확정 공정표" : "예상 공정표", href: href(s, "/plan") },
    ...(i >= 4 ? [{ label: "실측 견적서", href: href(s, "/quotes") }] : [])];
  const open = Object.values(s.actions).filter((a) => a.status === "proposed").length;
  const waiting = ({ standard: 0, vendors: 0, requested: picked.length, slots: 1, booked: 3, compare: 0, confirmed: 1, dates: 0, final: 0 } as Record<Stage, number>)[s.stage];
  return {
    project_name: "노원구 아파트 도배", step: i, facts, confirmed: true, todo: open, waiting, money, vendors, period, docs,
    plan_example: s.stage !== "final", memory: [], today_pin: s.script === "today" && !s.todayDismissed ? 2 : 0,
  };
}

// ───── 턴 대답

function learn(text: string) {
  const rules: [RegExp, MemoryOut["key"]][] = [[/오전|오후|주말|평일/, "avail_half"], [/냄새|친환경|풀/, "material"], [/강아지|고양이|반려/, "pet"], [/살면서|비어 있|빈 집/, "living"]];
  let m = readMemory();
  for (const [re, key] of rules) {
    // 카드에서 고른 날짜 말('11.25(수) 오후로 할래요')은 기억하지 않아요
    if (!re.test(text) || text.length > 40 || /\d+\.\d+/.test(text)) continue;
    const value = text.replace(/[.!?]+$/, "").slice(0, 30);
    const label = MEMORY_LABEL[key as keyof typeof MEMORY_LABEL];
    m = [...m.filter((x) => x.key !== key), { id: `mem-${Date.now().toString(36)}-${key}`, key, label, value, evidence_message_id: "u", evidence_quote: text, updated_at: new Date().toISOString() }];
  }
  writeMemory(m);
}

function respond(s: State, body: TurnIn, turnId: string): Plan {
  const text = body.text.trim();
  const choice = body.context?.choice;
  const head: Step[] = [step({ type: "ack", data: { turn_id: turnId, chat_id: "chat-mock", at: s.clock } })];
  const reply = (steps: Step[], after?: Plan["after"]): Plan => ({ steps: [...head, ...steps], after });
  const answer = (t: string, links: { label: string; href: string }[] = [], chips = s.chips) =>
    reply([step({ type: "status", data: { text: "답을 찾고 있어요" } }, 300), step({ type: "card", data: answerCard(s, t, links) }, 500), done(s, chips)]);

  // 카드 단추(계약 꼴 choice, 서버 assistant/choices.py와 같게): 칸 · 행동이면 승인 카드를 만들어요. 다른 꼴은 말로만 봐요
  const picked = typeof choice === "string" ? choice : "";
  const cut = picked.indexOf(":");
  const kind = cut > 0 ? picked.slice(0, cut) : "";
  const rest = cut > 0 ? picked.slice(cut + 1) : "";
  const args = rest.split(",").map((x) => x.trim()).filter(Boolean);
  if (kind === "demolition") return reply(demolitionAsked(s, rest as Demolition));
  if (kind === "visit_request") return reply(repick(s, args));
  if (kind === "visit_slot" && args[0]) return reply(reslot(s, args[0]));
  if (kind === "vendor_confirm" && args[0]) return reply(confirmBeat(s, args[0]));

  if (/다시 만들어/.test(text)) {
    if (/실측 요청/.test(text)) return reply(vendorsBeat(s));
    if (/확정/.test(text)) return reply(compareBeat(s, true));
    if (/마루와벽/.test(text)) return reply(maruBeat(s));
    if (/실측/.test(text)) return reply(reslot(s, "s1"));
    if (/수락/.test(text)) {
      const close = closeOpen(s, "dates_accept");
      return reply([step({ type: "card", data: datesCard(s, "dates") }, 400), ...close, step({ type: "action", data: datesAction(s) }, 300), done(s, s.chips)]);
    }
  }
  if ((s.stage === "standard" || s.stage === "vendors") && /업체/.test(text) && /추천|골라/.test(text)) return reply(vendorsBeat(s));
  if ((s.stage === "standard" || s.stage === "vendors") && /실측\S{0,2}\s*(?:시간|언제|날짜|일정)|희망 기간 후보/.test(text)) return reply(wishBeat(s));
  if (/다른 업체/.test(text)) return answer("업체 목록에서 더 볼 수 있어요. 가견적 낮은 순으로 보여요.", [{ label: "업체 목록 열기", href: href(s, "/vendors") }]);
  if (/가견적/.test(text)) return answer("가견적은 업체가 확인한 단가에 믿집이 센 수량을 곱해 계산 엔진이 만든 금액이에요. 실측 뒤 업체가 보내는 견적서와 달라질 수 있어요.", [{ label: "표준견적서 보기", href: href(s, "/standard") }]);
  if (/견적서 비교|비교 보기/.test(text)) return reply(compareBeat(s, true));
  if (/마루와벽/.test(text) && /날짜|고르/.test(text)) return reply(maruBeat(s));
  if (/오늘은 그만/.test(text)) {
    s.todayDismissed = true;
    return reply([step({ type: "card", data: { card_id: "today", kind: "today", data: todayData(s) } }, 200), step({ type: "token", data: { text: "알겠어요. 오늘은 더 알리지 않고, 정할 일이 바뀌면 다시 알려 드릴게요." } }, 300), done(s, ["견적서 비교 보기", "마루와벽 날짜 고르기"])]);
  }
  if (/준비물|알아 두기/.test(text)) return reply([step({ type: "status", data: { text: "자료를 찾고 있어요" } }, 300), step({ type: "card", data: knowCard() }, 500), done(s, s.chips)]);
  if (/평면도/.test(text)) {
    const card: CardOut<"floorplan_links"> = {
      card_id: nextId(s, "floor"), kind: "floorplan_links",
      data: {
        complex: "상계 푸른숲마을 7단지",
        links: [{ label: "세움터 건축물대장 평면도", href: "https://www.eais.go.kr", source: "국토교통부 세움터" }, { label: "정부24 건축물대장 열람", href: "https://www.gov.kr", source: "정부24" }],
        note: "평면도 그림은 믿집이 찾아 넣지 않아요. 받은 파일을 보드에 올리면 실측 때 같이 봐요.",
      },
    };
    return reply([step({ type: "status", data: { text: "받을 곳을 찾고 있어요" } }, 300), step({ type: "card", data: card }, 600), done(s, s.chips)]);
  }
  if (/풀이/.test(text)) {
    return reply([
      step({ type: "status", data: { text: "표준견적서를 읽고 있어요" } }, 300),
      step({ type: "card", data: standardCard(s) }, 500),
      ...sentences("가장 큰 줄은 벽지 값과 도배 품이에요. 짐 옮기기와 부분 보수는 실측 뒤에 바뀔 수 있어요."),
      done(s, ["업체 추천해 줘", "가견적은 어떻게 계산해요?"]),
    ]);
  }
  if (/표준견적서/.test(text)) return answer("표준견적서는 공공 기준 단가로 믿집이 계산한 참고 금액이에요. 업체 견적이 아니에요.", [{ label: "표준견적서 열기", href: href(s, "/standard") }]);
  if (/공정표/.test(text)) return answer("공정표는 반나절 단위로 일을 놓고 하루 단위 날짜로 보여 줘요.", [{ label: "공정표 열기", href: href(s, "/plan") }]);
  if (/순서/.test(text)) return answer("집 정보 → 표준견적서 → 업체 고르기 → 실측 → 견적서 비교 · 확정 → 공사 날짜 순서예요. 비서가 단계마다 알려 드려요.");
  if (/희망 기간/.test(text)) return answer("희망 기간은 요청서에서 바꿀 수 있어요. 보내기 전이라면 승인 카드에 바로 반영돼요.", [{ label: "요청서 열기", href: href(s, "/visits/new") }]);
  if (/폐기물/.test(text)) return answer("바른벽 견적서에는 폐기물 처리가 적혀 있지 않아요. 채팅에 물어볼 말을 넣어 둘게요. 보내기는 직접 눌러 주세요.", [{ label: "채팅 열기", href: "/chat" }]);
  if (/다른 시간|달력/.test(text)) return answer("달력에서 업체가 답한 기간 안의 반나절을 직접 고를 수 있어요.", [{ label: "실측 일정 열기", href: href(s, "/visits") }]);
  if (/다른 날짜/.test(text)) return answer("다른 날짜는 두 번까지 요청할 수 있어요. 요청하면 업체가 다시 골라 올려요.", [{ label: "공사 날짜 열기", href: href(s, "/schedule") }]);
  if (/달력에 넣기/.test(text)) return answer("확정 공정표를 휴대폰 달력에 넣을 수 있어요.", [{ label: "달력 파일 받기", href: `/api/projects/${encodeURIComponent(s.pid)}/plan.ics` }]);
  if (/언제/.test(text)) return answer("업체는 요청을 받고 48시간 안에 답해요. 견적서는 보통 실측 다음 날까지 와요. 오면 바로 알려 드릴게요.");
  if (/실측은 무엇/.test(text)) return answer("실측 때 업체가 벽 상태 · 몰딩 · 짐을 보고 견적서를 보내요. 한 시간 안쪽이면 끝나요.");
  return answer("예시 화면이라 정해 둔 말에만 답해요. 아래 칩이나 카드의 단추로 이어 가 보세요.");
}

/** 철거 범위를 고르면 비서가 '집 정보 저장' 제안을 만들어요(승인해야 저장) */
function demolitionAsked(s: State, key: Demolition): Step[] {
  if (!DEMO_LABEL[key]) return [done(s, s.chips)];
  const close = closeOpen(s, "home_info");
  const act = makeAction(s, "home_info", {
    title: "집 정보 저장",
    rows: [{ label: "철거 범위", value: DEMO_LABEL[key], sub: `지금 ${s.demolition ? DEMO_LABEL[s.demolition] : "없음"}` }],
    note: "저장하면 표준견적서를 새로 계산해요",
    approve_label: "맞아요, 저장",
  }, D.T("2026-11-28", "10:00"), { target_ver: "3" });
  const card = homeCard(s, { saved: false, action_id: act.action_id, changes: [{ label: "철거 범위", before: s.demolition ? DEMO_LABEL[s.demolition] : null, after: DEMO_LABEL[key] }], demolition: key });
  return [
    ...close, step({ type: "action", data: act }, 200), step({ type: "card", data: { ...card, say: "이 집 정보가 맞는지 확인해 주세요." } }, 300),
    ...sentences(`철거 범위를 '${DEMO_LABEL[key]}'로 바꿔 둘게요. 집 카드에서 [맞아요, 저장]을 누르면 표준견적서를 다시 계산해요.`),
    done(s, s.chips),
  ];
}
function vendorsBeat(s: State): Step[] {
  const close = closeOpen(s, "visit_request");
  const act = visitRequestAction(s);
  return [
    step({ type: "status", data: { text: "업체를 고르고 있어요" } }, 300),
    step({ type: "card", data: picksCard(s) }, 900),
    ...close,
    step({ type: "action", data: act }, 400, { apply: (x) => { x.stage = "vendors"; } }),
    ...sentences("세 곳 모두 단가를 확인한 업체예요. 고른 곳에만 실측 요청이 가요."),
    // 다음에 물을 말은 목록(0~3개)이에요: 첫 것은 제안 카드, 나머지는 칩으로 보여요
    done(s, ["가견적은 어떻게 계산해요?", "실측은 무엇을 봐요?"], { suggest: [
      { id: "step-pick", text: "실측 희망 기간을 볼까요?", why: "담은 업체에 실측을 요청할 차례예요", say: "실측 시간 찾아 줘" },
      { id: "idea-standard", text: "표준견적서 금액을 풀어 볼까요?", why: "가장 큰 줄부터 볼 수 있어요", say: "표준견적서 금액 풀이해 줘" },
    ] }),
  ];
}
/** 희망 기간 카드(요청 전): 첫 고른 업체의 빈 반나절로 고른 기간 후보. 고르면 실측 요청 승인 카드가 그 기간으로 바뀌어요 */
function wishCard(s: State): CardOut<"visit_slots"> {
  const v = D.VENDORS.find((x) => s.picks.includes(x.key)) ?? D.VENDORS[0];
  return {
    card_id: `wish-${v.ref}`, kind: "visit_slots",
    data: { vendor_name: v.name, window: null, candidates: [], wishes: D.WISHES, chosen: null, instant: false, calendar_href: href(s, "/visits/new"), vendor_note: null },
  };
}
function wishBeat(s: State): Step[] {
  return [
    step({ type: "status", data: { text: "업체 빈 시간을 보고 있어요" } }, 300),
    // 처음(추천 전)이면 업체 추천 카드도 같이 보여요(승인 카드 없이: 고른 업체로 [n곳에 실측 요청하기])
    ...(s.stage === "standard" ? [step({ type: "card", data: picksCard(s) }, 500)] : []),
    step({ type: "card", data: wishCard(s) }, 600),
    ...sentences("공사 시작 희망일에 맞춘 실측 희망 기간 후보예요. 고르면 실측 요청 승인 카드가 그 기간으로 바뀌어요."),
    done(s, s.chips),
  ];
}
/** visit_request:v…[,r…] → 고른 업체(목업 key)와 희망 기간으로 실측 요청 승인 카드를 새로 만들어요 */
function repick(s: State, refs: string[]): Step[] {
  const wish = refs.find((r) => D.WISHES.some((w) => w.ref === r));
  if (wish) s.wish = wish;
  const keys = D.VENDORS.filter((v) => refs.includes(v.ref)).map((v) => v.key);
  if (!keys.length) return [step({ type: "token", data: { text: "고른 업체가 없어요. 업체 카드에서 다시 골라 주세요." } }, 200), done(s, s.chips)];
  s.picks = keys;
  const close = closeOpen(s, "visit_request");
  return [step({ type: "card", data: picksCard(s) }, 0), ...close, step({ type: "action", data: visitRequestAction(s) }, 500, { apply: (x) => { if (x.stage === "standard") x.stage = "vendors"; } }), done(s, s.chips)];
}
function reslot(s: State, ref: string): Step[] {
  const close = closeOpen(s, "visit_slot");
  return [step({ type: "card", data: slotsCard(s, slotOwner(ref), ref) }, 0), ...close, step({ type: "action", data: slotAction(s, ref) }, 500), done(s, s.chips)];
}
/** vendor_confirm:m… → 그 업체 확정 승인 카드(같은 종류 열린 카드는 새 카드로 바뀌어요) */
function confirmBeat(s: State, ref: string): Step[] {
  const who = quoteOwner(ref);
  if (!who) return [step({ type: "token", data: { text: "아직 확정할 수 있는 견적서가 없어요." } }, 200), done(s, s.chips)];
  const close = closeOpen(s, "vendor_confirm");
  return [...close, step({ type: "action", data: confirmAction(s, who) }, 400), done(s, s.chips)];
}
function compareBeat(s: State, inline: boolean): Step[] {
  const close = closeOpen(s, "vendor_confirm");
  return [
    ...(inline ? [step({ type: "status", data: { text: "견적서를 놓고 보고 있어요" } }, 300)] : []),
    step({ type: "card", data: compareCard(s) }, 700),
    ...sentences(s.quoteVer === 2 ? "결도배 2판은 1판보다 금액 하나만 바뀌었어요. 바른벽은 폐기물 처리가 적혀 있지 않아 확정 전에 물어보면 좋아요." : "두 곳 모두 철거는 포함이에요. 바른벽은 폐기물 처리가 적혀 있지 않아 확정 전에 물어보면 좋아요."),
    ...close,
    step({ type: "action", data: confirmAction(s) }, 300, { apply: (x) => { x.stage = "compare"; } }),
    done(s, ["폐기물 처리도 포함인가요?", "표준견적서 다시 보기"]),
  ];
}
function maruBeat(s: State): Step[] {
  const close = closeOpen(s, "visit_slot");
  const first = D.MARU_SLOTS[0].ref;
  return [step({ type: "card", data: slotsCard(s, "maru", first) }, 600), ...close, step({ type: "action", data: slotAction(s, first) }, 300), done(s, s.chips)];
}

// ───── 승인 뒤 이어지는 일(서버가 먼저 보내는 턴)

function follow(s: State, a: ActionOut) {
  switch (a.kind) {
    case "visit_request": later(s, "sent", 600); later(s, "answered", 3400); return;
    case "visit_slot":
      if (a.summary.title.startsWith("마루와벽")) { later(s, "maruBooked", 500); return; }
      later(s, "booked", 600); later(s, "quoted", 3400); return;
    case "vendor_confirm": later(s, "closed", 600); later(s, "dates", 3400); return;
    case "dates_accept": later(s, "final", 500); return;
    default: return;
  }
}

/** 이어질 일 하나: 대본 시계를 옮기고(날이 바뀌면 날짜 줄이 생겨요) 보낼 이벤트 */
function beatOf(s: State, beat: Beat): { clock?: string; steps: Step[] } {
  switch (beat) {
    case "sent":
      return { steps: [
        step({ type: "status", data: { text: "업체에 보냈어요", task: visitTask(s, "sent") } }, 300, { apply: (x) => { x.stage = "requested"; } }),
        ...sentences("업체가 48시간 안에 갈 수 있는 기간을 답해요. 답이 오면 바로 알려 드릴게요."),
        done(s, ["답은 언제 와요?", "실측은 무엇을 봐요?"]),
      ] };
    case "answered":
      note(s, "결도배가 실측 기간을 답했어요", "/visits", "visit_offered");
      note(s, "바른벽 실측이 11.24(화) 오후로 확정됐어요", "/visits", "visit_booked");
      return { clock: D.T("2026-11-22", "09:20"), steps: [
        step({ type: "status", data: { text: "업체가 답했어요", task: visitTask(s, "answered") } }, 300, { apply: (x) => { x.stage = "slots"; } }),
        ...closeOpen(s, "visit_slot"),
        step({ type: "card", data: slotsCard(s, "gyeol", "s1") }, 700),
        step({ type: "action", data: slotAction(s, "s1") }, 300),
        done(s, ["다른 시간도 볼래요", "실측은 무엇을 봐요?"]),
      ] };
    case "booked":
      return { steps: [
        step({ type: "status", data: { text: "실측이 잡혔어요", task: visitTask(s, "booked") } }, 300, { apply: (x) => { x.stage = "booked"; } }),
        ...sentences("실측 날 업체가 집을 보고 견적서를 보내요. 오면 같이 놓고 볼게요."),
        done(s, ["견적서는 언제 와요?", "실측은 무엇을 봐요?"]),
      ] };
    case "maruBooked":
      return { steps: [step({ type: "token", data: { text: "마루와벽 실측이 잡혔어요. 견적서가 오면 같이 놓고 볼게요." } }, 300), done(s, s.chips)] };
    case "quoted":
      note(s, "결도배가 실측 견적서를 보냈어요", "/quotes", "quote_sent");
      note(s, "바른벽이 실측 견적서를 보냈어요", "/quotes", "quote_sent");
      return { clock: D.T("2026-11-26", "18:30"), steps: [
        step({ type: "status", data: { text: "견적서가 왔어요", task: visitTask(s, "quoted") } }, 300),
        ...compareBeat(s, false),
      ] };
    case "closed":
      return { steps: [
        step({ type: "status", data: { text: "확정했어요", task: visitTask(s, "closed") } }, 300, { apply: (x) => { x.stage = "confirmed"; } }),
        ...sentences(`${dealWho(s)} 공사 날짜를 올리면 알려 드릴게요. 확정한 견적서는 바뀌지 않아요.`),
        done(s, ["공사 날짜는 언제 와요?"]),
      ] };
    case "dates":
      note(s, `${dealWho(s)} 공사 날짜를 올렸어요`, "/schedule", "dates_proposed");
      return { clock: D.T("2026-11-27", "11:00"), steps: [
        step({ type: "card", data: datesCard(s, "dates") }, 500, { apply: (x) => { x.stage = "dates"; } }),
        step({ type: "action", data: datesAction(s) }, 400),
        done(s, ["다른 날짜 요청하기", "공정표 보기"]),
      ] };
    case "final":
      return { steps: [
        step({ type: "status", data: { text: "공정표를 만들고 있어요" } }, 300),
        step({ type: "card", data: datesCard(s, "final") }, 900, { apply: (x) => { x.stage = "final"; } }),
        step({ type: "card", data: knowCard() }, 500),
        ...sentences("공사 전날 저녁 6시에 준비물을 한 번 더 알려 드릴게요."),
        done(s, ["공사 전날 준비물", "공정표 보기", "달력에 넣기"]),
      ] };
  }
}

function later(s: State, beat: Beat, wait: number) {
  s.pending = [...s.pending, { beat, at: Date.now() + wait }];
  save(s);
  arm(s.pid, beat, wait);
}
function arm(pid: string, beat: Beat, wait: number) {
  if (typeof window === "undefined") return;
  setTimeout(() => {
    void enqueue(pid, async () => {
      const s = load(pid);
      const i = s.pending.findIndex((p) => p.beat === beat);
      if (i < 0) return;
      s.pending = s.pending.filter((_, k) => k !== i);
      const turnId = `p-${++s.n}`;
      const b = beatOf(s, beat);
      if (b.clock) s.clock = b.clock;
      save(s);
      const steps = [step({ type: "ack", data: { turn_id: turnId, chat_id: "chat-mock", at: s.clock } }), ...b.steps];
      await run(pid, turnId, steps, (e) => subs.get(pid)?.forEach((fn) => fn(turnId, e)));
    });
  }, Math.max(0, wait));
}

async function run(pid: string, turnId: string, steps: Step[], emit: (e: TurnEvent) => void, signal?: AbortSignal) {
  let seq = 0;
  for (const st of steps) {
    await sleep(st.wait, signal);
    const s = load(pid);
    if (st.clock) s.clock = st.clock;
    const ev = { type: st.ev.type, data: { ...st.ev.data, seq: ++seq } } as TurnEvent;
    if (ev.type === "ack") ev.data.at = s.clock;
    s.items = applyTurnEvent(s.items, turnId, ev, s.clock);
    st.apply?.(s);
    save(s);
    if (signal?.aborted) continue;
    emit(ev);
    // 다시 잇기 · 중복 전송 흉내: 같은 seq를 한 번 더 보내요(화면이 버려야 해요)
    if (st.dup) emit(ev);
  }
}

// ───── 바깥에 보이는 함수(lib/api/assistant.ts가 불러요)

export async function latest(pid: string): Promise<ThreadOut | null> {
  const s = load(pid);
  return s.items.length ? { chat_id: "chat-mock", rev: s.rev, updated_at: s.clock } : null;
}
export async function feed(pid: string): Promise<FeedPage> {
  const s = load(pid);
  return { items: s.items, before: null, rev: s.rev, chips: s.chips, now: s.clock };
}
export async function board(pid: string): Promise<BoardOut> {
  return boardOf(load(pid));
}
export async function today(pid: string): Promise<TodayData> {
  return todayData(load(pid));
}
export async function health(): Promise<HealthOut> {
  return { mode: "llm", reason: "ok" };
}
export async function turn(body: TurnIn, emit: (e: TurnEvent) => void, signal?: AbortSignal): Promise<void> {
  const pid = body.project_id;
  await enqueue(pid, async () => {
    const s = load(pid);
    const uid = `u-${body.client_key}`;
    if (!s.items.some((x) => x.id === uid)) s.items = [...s.items, { id: uid, role: "user", at: s.clock, text: body.text }];
    learn(body.text);
    const turnId = `t-${++s.n}`;
    save(s);
    const plan = respond(s, body, turnId);
    save(s);
    await run(pid, turnId, plan.steps, emit, signal);
    plan.after?.(load(pid));
  });
}
export async function actions(pid: string, status?: ActionStatus): Promise<ActionOut[]> {
  return Object.values(load(pid).actions).filter((a) => !status || a.status === status);
}
export async function approve(pid: string, actionId: string, _clientKey: string): Promise<ActionOut> {
  return enqueue(pid, async () => {
    const s = load(pid);
    const a = s.actions[actionId];
    if (!a) throw new ApiError(404, "not_found", "제안을 찾을 수 없어요.");
    if (a.status === "executed") return a;
    if (a.status !== "proposed") throw new ApiError(409, a.status === "expired" && a.error_code === "due" ? "expired" : "action_closed", a.error_code === "replaced" ? "새 카드로 바뀐 제안이에요." : "기한이 지난 제안이에요. 비서에게 다시 만들어 달라고 해 주세요.");
    await sleep(700);
    const bareun = a.kind === "vendor_confirm" && a.summary.title.startsWith("바른벽");
    if (a.kind === "vendor_confirm" && !bareun && s.quoteFailOnce && s.quoteVer === 1) {
      // 그사이 결도배가 2판을 보냈어요 → 옛 행동은 실패(quote_changed), 새 판 + 차액으로 새 행동(supersedes)
      s.quoteFailOnce = false;
      s.quoteVer = 2;
      s.clock = D.T("2026-11-26", "18:41");
      const failed: ActionOut = { ...a, status: "failed", error_code: "quote_changed" };
      s.actions[a.action_id] = failed;
      const fresh = confirmAction(s, "gyeol", a.action_id);
      s.items = s.items.map((it) => (it.role === "assistant" ? { ...it, parts: it.parts.map((p) => (p.t === "action" && p.action.action_id === a.action_id ? { t: "action" as const, action: fresh } : p)) } : it));
      s.items = replaceCard(s.items, compareCard(s));
      note(s, "결도배가 실측 견적서를 다시 보냈어요", "/quotes", "quote_resent");
      save(s);
      throw new ApiError(409, "quote_changed", "견적서가 새 판으로 바뀌었어요. 바뀐 값을 보고 다시 눌러 주세요.");
    }
    const at = s.clock;
    const result: ActionOut["result"] =
      a.kind === "home_info" ? { text: "집 정보를 저장했어요" }
        : a.kind === "visit_request" ? { text: `${s.picks.length}곳에 요청을 보냈어요`, href: href(s, "/visits"), label: "실측 일정 보기" }
          : a.kind === "visit_slot" ? { text: a.summary.title.startsWith("마루와벽") ? "실측을 잡았어요" : "고른 시간을 보냈어요. 업체가 수락하면 확정돼요", href: href(s, "/visits"), label: "실측 일정 보기" }
            : a.kind === "vendor_confirm" ? { text: `${a.summary.title}했어요`, href: href(s, "/quotes"), label: "견적서 보기" }
              : a.kind === "dates_accept" ? { text: "공사 날짜를 수락했어요", href: href(s, "/plan"), label: "공정표 보기" }
                : { text: "했어요" };
    const fin: ActionOut = { ...a, status: "executed", decided_at: at, executed_at: at, result };
    setAction(s, fin);
    if (a.kind === "vendor_confirm") s.deal = bareun ? "bareun" : "gyeol";
    if (a.kind === "home_info") {
      const picked = /전체/.test(a.summary.rows?.[0]?.value ?? "") ? "full" : /일부/.test(a.summary.rows?.[0]?.value ?? "") ? "partial" : "none";
      s.demolition = picked;
      s.items = replaceCard(s.items, homeCard(s, { action_id: a.action_id, saved: true }));
    }
    save(s);
    follow(s, fin);
    return fin;
  });
}
export async function reject(pid: string, actionId: string): Promise<ActionOut> {
  return enqueue(pid, async () => {
    const s = load(pid);
    const a = s.actions[actionId];
    if (!a) throw new ApiError(404, "not_found", "제안을 찾을 수 없어요.");
    if (a.status !== "proposed") return a;
    const fin: ActionOut = { ...a, status: "rejected", decided_at: s.clock };
    setAction(s, fin);
    save(s);
    return fin;
  });
}
export async function openNudge(_pid: string, _nudgeId: string): Promise<boolean> {
  return true;
}
export async function dismiss(pid: string, nudgeId: string): Promise<boolean> {
  const s = load(pid);
  if (nudgeId === "nudge-today") {
    s.todayDismissed = true;
    s.items = replaceCard(s.items, { card_id: "today", kind: "today", data: todayData(s) });
  }
  save(s);
  return true;
}
export async function memory(): Promise<MemoryOut[]> {
  return readMemory();
}
export async function forget(id: string): Promise<void> {
  writeMemory(readMemory().filter((m) => m.id !== id));
}
export async function notifications(pid: string): Promise<NotifyPage> {
  const s = load(pid);
  return { items: s.notes, unread: s.notes.filter((n) => !n.read).length };
}
export async function readAll(pid: string): Promise<void> {
  const s = load(pid);
  s.notes = s.notes.map((n) => ({ ...n, read: true }));
  save(s);
}
export async function readOne(pid: string, id: string): Promise<void> {
  const s = load(pid);
  s.notes = s.notes.map((n) => (n.id === id ? { ...n, read: true } : n));
  save(s);
}
export function subscribe(pid: string, on: (turnId: string, e: TurnEvent) => void): () => void {
  const set = subs.get(pid) ?? new Set();
  set.add(on);
  subs.set(pid, set);
  return () => { set.delete(on); };
}
export function reset(pid: string, script: MockScript) {
  const s = init(pid, script);
  save(s);
}
export function scriptOf(pid: string): MockScript {
  return load(pid).script;
}

// ───── 업체(V1 · V3 · 오늘 브리핑 · 비서 소식 · 승인)

const vendorActs = new Map<string, ActionOut>();
/** 'YYYY-MM-DD'에 n일 더하기(목업 서버 안에서만) */
const addDays = (iso: string, n: number) => { const [y, m, d] = iso.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10); };
/** 희망 기간 첫 주 반나절(일요일 쉼, 잡힌 칸 몇 개) */
function halvesFrom(start: string): VendorBriefData["halves"] {
  const TAKEN: [number, "am" | "pm", string][] = [[0, "pm", "중계동"], [3, "am", "창동"], [4, "am", "하계동"], [4, "pm", "하계동"]];
  const days = Array.from({ length: 7 }, (_, i) => { const day = addDays(start, i); return { day, off: new Date(`${day}T00:00:00Z`).getUTCDay() === 0 }; });
  const taken: Record<string, string> = {};
  for (const [i, h, where] of TAKEN) if (!days[i].off) taken[`${days[i].day}:${h}`] = where;
  const open = days.filter((d) => !d.off).length * 2 - Object.keys(taken).length;
  return { days, taken, open_count: open };
}
const windowAction = (id: string, start: string, end: string): ActionOut => vendorActs.get(id) ?? {
  action_id: id, kind: "window_answer", status: "proposed",
  summary: { title: "이 기간으로 답하기", rows: [{ label: "기간", value: rangeText(start, end, { weekday: true }) }], note: "고객이 이 기간 안에서 반나절을 골라요", approve_label: "이 기간으로 답하기" },
  target_ver: "1", expires_at: D.T("2026-11-23", "10:06"),
};

export async function vendorBrief(visitId: string, seed?: BriefSeed): Promise<VendorBriefData> {
  await sleep(200);
  const region = seed?.region ?? "노원구 상계동";
  const area = seed ? seed.area : "공급 112.4㎡";
  const grade = seed?.grade ?? "실크";
  const hapji = /합지/.test(grade);
  const wish = seed?.wish ?? { start: "2026-11-23", end: "2026-12-04" };
  const est = seed?.estimate_won ?? D.VENDOR_SIDE.estimate;
  const halves = halvesFrom(wish.start);
  const work = halves.days.filter((d) => !d.off);
  const id = `vact-${visitId}`;
  const act = vendorActs.get(id);
  return {
    visit_id: visitId,
    title: [region, area, `도배 ${grade}`].filter(Boolean).join(" · "),
    // 씨앗에 없는 사실(사는 중 · 사진 수)은 지어내지 않아요
    facts: [
      "아파트", "도배 전체",
      seed ? (seed.occupied === true ? "사는 중" : seed.occupied === false ? "빈 집" : null) : "사는 중",
      `공사 시작 희망 ${dateShort(seed?.work_wish_on ?? D.WISH.work_wish_on)}`,
      seed ? (seed.photos != null ? `사진 ${seed.photos}장` : null) : "사진 4장",
    ].filter((x): x is string => !!x),
    fit: [
      { key: "trade", label: "공정", ok: true, text: "도배 · 우리 업체가 하는 공정이에요" },
      { key: "area", label: "지역", ok: true, text: "출장 지역 안이에요" },
      { key: "schedule", label: "일정", ok: true, text: `고객 희망 ${rangeText(wish.start, wish.end, { weekday: true })} · 첫 주 빈 반나절 ${halves.open_count}칸` },
      { key: "paper", label: "벽지", ok: !hapji, text: hapji ? "합지 단가를 아직 확인하지 않았어요" : `${grade} · 확인한 단가가 있어요` },
    ],
    estimate: { total_won: est, basis: "내 단가(11.15 확인) × 믿집 수량" },
    halves,
    suggest: act && act.status !== "proposed" ? null : { action_id: id, start: work[0].day, end: work[work.length - 1].day, excluded: halves.days.filter((d) => d.off).map((d) => d.day), instant: false, open_count: halves.open_count },
    due_at: seed?.due_at ?? D.T("2026-11-23", "10:06"),
    memo: seed ? seed.memo ?? null : "아이 방은 냄새 적은 풀이면 좋겠어요.",
    sentence: null,
  };
}
export async function quoteChecklist(visitId: string): Promise<QuoteChecklistData> {
  await sleep(200);
  return {
    visit_id: visitId,
    items: D.VENDOR_SIDE.checklist,
    fields: [{ label: "낼 금액", value: null }, { label: "부가세 방식", value: null }, { label: "공사 기간", value: "2일" }, { label: "유효기간", value: null }],
    easy_miss: D.VENDOR_SIDE.easy_miss,
    prev: null,
  };
}
export async function approveVendor(actionId: string): Promise<ActionOut> {
  await sleep(700);
  const cur = windowAction(actionId, "2026-11-23", "2026-11-28");
  if (cur.status === "executed") return cur;
  if (cur.status !== "proposed") throw new ApiError(409, "action_closed", "거절한 제안이에요.");
  const a: ActionOut = { ...cur, status: "executed", decided_at: D.T("2026-11-21", "11:20"), executed_at: D.T("2026-11-21", "11:20"),
    result: { text: "기간을 보냈어요. 고객이 날짜를 고르면 알려 드릴게요", href: "/vendor?tab=waiting", label: "기다림 보기" } };
  vendorActs.set(actionId, a);
  return a;
}
export async function rejectVendor(actionId: string): Promise<ActionOut> {
  const a: ActionOut = { ...windowAction(actionId, "2026-11-23", "2026-11-28"), status: "rejected", decided_at: D.T("2026-11-21", "11:20") };
  vendorActs.set(actionId, a);
  return a;
}
const VENDOR_SEED_ACT = "vact-feed-1";
export async function vendorActions(status?: ActionStatus): Promise<ActionOut[]> {
  const all = [windowAction(VENDOR_SEED_ACT, "2026-11-24", "2026-11-28"), ...[...vendorActs.values()].filter((a) => a.action_id !== VENDOR_SEED_ACT)];
  return all.filter((a) => !status || a.status === status);
}
export async function vendorFeed(): Promise<FeedPage> {
  const a = windowAction(VENDOR_SEED_ACT, "2026-11-24", "2026-11-28");
  return {
    items: [{
      id: "va-1", role: "assistant", at: D.T("2026-11-21", "09:10"), turn_id: null, done: true,
      parts: [{ t: "text", src: "guide", text: "중계동 새 요청에 답할 기간을 골라 뒀어요." }, { t: "action", action: a }],
    }],
    before: null, rev: 2, chips: [], now: D.T("2026-11-21", "09:30"),
  };
}
export async function vendorToday(): Promise<VendorTodayData> {
  return {
    date: "2026-11-21",
    rows: [
      { id: "vt1", icon: "inbox", title: "새 요청 2", sub: "상계동 · 중계동 · 답 기한 11.23(월)", due: true },
      { id: "vt2", icon: "calendar", title: "오늘 실측 1", sub: "하계동 · 오후" },
      { id: "vt3", icon: "file", title: "보낼 견적서 1", sub: "창동 · 실측 11.20(금)" },
    ],
  };
}
