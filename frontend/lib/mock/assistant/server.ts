// v4 비서 목업 서버(브라우저 안). 계약서 3장의 SSE 이벤트 · REST 응답을 같은 모양으로 흘려요.
// - 대본 두 개: f1(처음 고객: 주소 → 집 확인 → 표준견적서 → 추천 3곳 → 실측 요청 승인 → 시간 후보 → 견적 비교 → 확정 승인 → 공정표)
//   · today(오늘 정할 일). 상태는 공사마다 localStorage에 둬서 새로 고쳐도 대화가 그대로예요.
// - 승인 카드만 일을 실행해요. 빠른 답 칩 · 글은 실행하지 않아요(승인 없이 실행 0건).
// - 결도배 확정을 처음 누르면 '판 바뀜'(409 quote_changed)을 한 번 돌려줘요(새 판 + 차액 승인 카드 확인용).
// - 승인 뒤 이어지는 일(업체 답 · 견적서 도착)은 서버가 먼저 보내는 턴으로 흘려요(subscribe). 시각은 대본 시계예요.
import { ApiError, type Schemas } from "@/lib/backend/client";
import {
  applyTurnEvent, replaceAction, replaceCard,
  type ActionKind, type ActionOut, type ActionSummary, type AddressHit, type BoardOut, type BriefSeed, type CardOut, type FeedItem,
  type FeedPage, type MemoryOut, type NotifyPage, type QuoteChecklistData, type TaskOut, type TaskRow, type TurnEvent, type TurnIn,
  type VendorBriefData, type VendorTodayData, type CompareCol, type QuoteCompareData,
} from "@/lib/api/assistant";
import { dateLong, dateShort, halfDayText, rangeText, won } from "@/lib/format";
import type { MockScript } from "./mode";
import * as D from "./data";

type Stage = "address" | "home" | "standard" | "vendors" | "requested" | "slots" | "booked" | "compare" | "confirmed" | "dates" | "final";
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
  memory: MemoryOut[];
  picks: string[];
  quoteVer: 1 | 2;
  quoteFailOnce: boolean;
  todayDismissed: boolean;
  /** 승인 뒤 이어질 일(새로 고쳐도 이어지게 시각과 함께 저장) */
  pending: { beat: Beat; at: number }[];
};
type Beat = "standard" | "sent" | "answered" | "booked" | "maruBooked" | "quoted" | "closed" | "dates" | "final";
type Draft =
  | { type: "ack"; data: { turn_id: string; chat_id: string; at: string } }
  | { type: "status"; data: { text: string; task?: TaskOut | null } }
  | { type: "card"; data: CardOut }
  | { type: "action"; data: ActionOut }
  | { type: "token"; data: { text: string } }
  | { type: "done"; data: { rev: number; mode: "llm" | "free"; cards: string[]; actions: string[]; chips?: string[]; suggest?: { id: string; text: string; why: string; say: string } | null } }
  | { type: "error"; data: { code: string; message: string } };
type Step = { wait: number; ev: Draft; clock?: string; apply?: (s: State) => void; dup?: boolean };
type Plan = { steps: Step[]; after?: (s: State) => void };

const VERSION = 4;
const KEY = (pid: string) => `mj_v4_mock:${pid}`;
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
  v: VERSION, pid, script, stage: "address", clock, items: [], actions: {}, chips: [], rev: 1, n: 0,
  notes: [], memory: [], picks: ["gyeol", "bareun", "maru"], quoteVer: 1, quoteFailOnce: true, todayDismissed: false, pending: [],
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

function homeSearch(query = "", hits: AddressHit[] = D.HOME.hits, picked: string | null = null): CardOut<"home_info"> {
  return { card_id: "home-search", kind: "home_info", data: { phase: "search", query, hits, picked } };
}
function homeConfirm(actionId: string | null, saved: boolean): CardOut<"home_info"> {
  return { card_id: "home", kind: "home_info", say: "이 집이 맞는지 확인해 주세요.", data: { phase: "confirm", complex: D.HOME.complex, dongs: D.HOME.dongs, area: D.HOME.area, sources: D.HOME.sources, action_id: actionId, saved } };
}
function standardCard(s: State): CardOut<"standard_quote"> {
  return { card_id: "standard", kind: "standard_quote", say: "표준견적서가 나왔어요.", data: { ...D.STANDARD, href: href(s, "/standard") } };
}
function picksCard(s: State): CardOut<"vendor_picks"> {
  return {
    card_id: "picks", kind: "vendor_picks", say: "노원구에서 이 집 조건에 맞는 세 곳이에요.",
    data: {
      area_name: "노원구",
      picks: D.VENDORS.map((v) => ({
        ref: v.key, vendor_id: v.id, name: v.name, photo: v.photo, photo_alt: `${v.name} 시공 사례`, rating: v.rating, reviews: v.reviews,
        done_jobs: v.done, estimate_won: v.est, reasons: v.reasons, badge: v.badge ?? null, picked: s.picks.includes(v.key), href: href(s, "/vendors"),
      })),
      basis: ["이 구에서 일하고 도배를 해요", "단가를 확인해 가견적이 있어요", "가견적 · 별점 · 답 속도 · 끝낸 공사로 점수를 매겨요"],
      more_href: href(s, "/vendors"),
    },
  };
}
function visitRequestAction(s: State): ActionOut {
  const vs = D.VENDORS.filter((v) => s.picks.includes(v.key));
  return makeAction(s, "visit_request", {
    title: "실측 요청 보내기",
    amounts: vs.map((v) => ({ label: v.name, won: v.est })),
    rows: [
      { label: "가견적", value: "11월 15일 확인한 단가로 고정돼요" },
      { label: "희망 기간", value: rangeText(D.WISH.start, D.WISH.end, { weekday: true }), sub: `공사 시작 희망 ${dateLong(D.WISH.work_wish_on)} 기준` },
    ],
    photos: D.PHOTOS,
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
    closed: [
      { label: "결도배", state: "done", text: "확정", note: `${s.quoteVer}판` },
      { label: "바른벽", state: "cancelled", text: "닫힘", note: "다른 업체를 확정했어요" },
      { label: "마루와벽", state: "cancelled", text: "닫힘", note: "다른 업체를 확정했어요" },
    ],
  };
  const title = phase === "quoted" || phase === "closed" ? "실측 · 견적서 3곳" : `실측 요청 ${rows.sent.length || 3}곳`;
  const state = phase === "closed" ? "done" : "waiting";
  return { task_id: "task-visits", title, state, at: s.clock, rows: rows[phase], link: { label: "실측 일정 보기", href: href(s, "/visits") } };
}
const dueTextOf = (day: string, hm: string) => `${dateShort(day)} ${hm}까지`;

function slotsCard(s: State, who: "gyeol" | "maru", chosen: string): CardOut<"visit_slots"> {
  const list = who === "gyeol" ? D.SLOTS : D.MARU_SLOTS;
  const v = D.vendorOf(who);
  return {
    card_id: `slots-${who}`, kind: "visit_slots",
    say: who === "gyeol" ? "결도배가 갈 수 있는 기간을 답했어요. 이 시간 어때요?" : "마루와벽이 다른 날을 냈어요. 이 중에서 골라 주세요.",
    data: {
      vendor_name: v.name,
      window: who === "gyeol" ? { start: "2026-11-23", end: "2026-11-28" } : { start: "2026-11-25", end: "2026-11-26" },
      candidates: list.map((c) => ({ ref: c.ref, vendor_name: v.name, day: c.day, half: c.half, why: s.memory.some((m) => m.key === "avail_half") && c.half === "am" ? [...c.why, "평일 오전이 편하다고 했어요"] : c.why })),
      chosen, instant: who === "maru", calendar_href: href(s, "/visits"),
    },
  };
}
function slotAction(s: State, who: "gyeol" | "maru", ref: string): ActionOut {
  const c = [...D.SLOTS, ...D.MARU_SLOTS].find((x) => x.ref === ref) ?? D.SLOTS[0];
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
  const col = (vid: string, name: string, q: typeof g | typeof b, changed: CompareCol["changed"]): CompareCol => ({
    visit_id: vid, vendor_name: name, state: "quoted", version: q.version, received_on: q.received_on, total_won: q.total_won, changed,
    diff_vs_estimate_won: q.diff_vs_estimate_won, days: q.days, valid_until: q.valid_until, valid_soon: q.valid_until === "2026-11-27",
    demolish: q.demolish, waste: q.waste, paper: q.paper, warranty_months: q.warranty_months,
    file: { kind: q.file === "PDF" ? "pdf" : "image", label: q.file, href: href(s, "/quotes") },
  });
  const data: QuoteCompareData = {
    cols: [
      col("vq-gyeol", "결도배", g, s.quoteVer === 2 ? { from_version: 1, diff_won: D.QUOTES.change } : null),
      col("vq-bareun", "바른벽", b, null),
      { visit_id: "vq-maru", vendor_name: "마루와벽", state: "waiting", wait_note: "실측 전" },
    ],
    gap_won: s.quoteVer === 2 ? D.QUOTES.gap2 : D.QUOTES.gap1,
    ask_chips: ["폐기물 처리도 포함인가요?"],
    href: href(s, "/quotes"),
  };
  return { card_id: "compare", kind: "quote_compare", say: "실측 견적서가 두 곳 왔어요.", data };
}
function confirmAction(s: State, supersedes: string | null = null): ActionOut {
  const g = s.quoteVer === 2 ? D.QUOTES.gyeol2 : D.QUOTES.gyeol1;
  return makeAction(s, "vendor_confirm", {
    title: "결도배로 확정",
    amount_won: g.total_won,
    diff: s.quoteVer === 2 ? { label: "1판보다", from_won: D.QUOTES.gyeol1.total_won, to_won: g.total_won, diff_won: D.QUOTES.change } : null,
    version: `견적서 ${g.version}판 · ${dateLong(g.received_on)} 받음`,
    rows: [{ label: "공사 기간", value: `${g.days}일` }, { label: "유효기간", value: `${dateLong(g.valid_until)}까지` }],
    file: { label: "PDF", href: href(s, "/quotes") },
    note: "확정하면 바른벽 · 마루와벽 요청은 닫혀요",
    approve_label: "결도배로 확정",
  }, D.T("2026-12-31", "18:00"), { target_ver: `quote-gyeol-${g.version}`, supersedes });
}
function datesCard(s: State, phase: "dates" | "final"): CardOut<"schedule"> {
  return {
    card_id: phase === "dates" ? "plan-dates" : "plan-final", kind: "schedule",
    say: phase === "dates" ? "결도배가 공사 날짜를 올렸어요." : "확정 공정표가 나왔어요.",
    data: {
      phase, vendor_name: "결도배", start: D.WORK.start, end: D.WORK.end, work_days: D.WORK.work_days, days: D.WORK.days,
      conflicts: [], plan_version: phase === "dates" ? 1 : 2, move_in: D.WISH.move_in,
      href: href(s, "/plan"), ics_href: phase === "final" ? `/api/projects/${encodeURIComponent(s.pid)}/plan.ics` : null,
    },
  };
}
function datesAction(s: State): ActionOut {
  return makeAction(s, "dates_accept", {
    title: `도배 ${rangeText(D.WORK.start, D.WORK.end, { weekday: true })} 수락`,
    version: "공정표 1판",
    rows: [{ label: "일하는 날", value: `${D.WORK.work_days}일` }, { label: "입주 희망", value: dateLong(D.WISH.move_in), sub: "여유가 있어요" }],
    note: "수락하면 확정 공정표가 만들어지고, 공사 전날 준비물을 알려 드려요",
    approve_label: "이 날짜로 수락",
  }, D.T("2026-11-29", "11:00"), { target_ver: "plan-1" });
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
  s.items = [{
    id: "a-hello", role: "assistant", at: s.clock, turn_id: "hello", done: true,
    parts: [{ t: "text", src: "guide", text: "안녕하세요. 공사를 끝까지 챙기는 믿집 비서예요.\n집 주소부터 알려 주세요." }, { t: "card", card: homeSearch() }],
  }];
  s.chips = ["상계 푸른숲마을 7단지", "평형만 알아요"];
  return s;
}
function initToday(pid: string): State {
  const s = base(pid, "today", D.T("2026-11-24", "09:00"));
  s.stage = "compare";
  s.quoteVer = 2;
  s.quoteFailOnce = false;
  s.memory = D.MEMORY_SEED.map((m) => ({ ...m }));
  const sent: TaskOut = { task_id: "task-sent", title: "실측 요청 3곳", state: "done", at: D.T("2026-11-21", "10:06"), rows: [], link: { label: "실측 일정 보기", href: href(s, "/visits") } };
  const old = makeAction(s, "visit_slot", {
    title: "마루와벽 실측 11.23(월) 오후", version: "업체가 답한 기간 11.23~11.27",
    rows: [{ label: "그 뒤 일", value: "고르면 바로 확정돼요" }], approve_label: "이 시간으로 고르기",
  }, D.T("2026-11-23", "09:20"));
  const expired: ActionOut = { ...old, status: "expired", error_code: "due" };
  s.actions[old.action_id] = expired;
  const today: CardOut<"today"> = {
    card_id: "today", kind: "today",
    data: {
      date: "2026-11-24", nudge_id: "nudge-today",
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
    },
  };
  s.items = [
    { id: "a-old-1", role: "assistant", at: D.T("2026-11-21", "10:06"), turn_id: "old-1", done: true, parts: [{ t: "task", task: sent }, { t: "text", src: "guide", text: "희망 기간 11.23~12.4로 세 곳에 보냈어요." }] },
    { id: "a-old-2", role: "assistant", at: D.T("2026-11-22", "09:20"), turn_id: "old-2", done: true, parts: [{ t: "action", action: expired }] },
    { id: "a-today", role: "assistant", at: s.clock, turn_id: "today", done: true, parts: [{ t: "text", src: "ai", text: "좋은 아침이에요. 오늘은 두 가지만 정하면 돼요." }, { t: "card", card: today }] },
  ];
  s.chips = ["견적서 비교 보기", "마루와벽 날짜 고르기", "오늘은 그만"];
  s.notes = [
    { id: "n-4", kind: "assistant", project_id: pid, body: "오늘 정할 일이 2개 있어요", link: href(s), created_at: D.T("2026-11-24", "09:00"), read: false },
    { id: "n-3", kind: "quote_resent", project_id: pid, body: "결도배가 실측 견적서를 다시 보냈어요", link: href(s, "/quotes"), created_at: D.T("2026-11-23", "20:14"), read: false },
    { id: "n-2", kind: "visit_offered", project_id: pid, body: "마루와벽이 다른 날을 냈어요", link: href(s, "/visits"), created_at: D.T("2026-11-23", "08:50"), read: true },
    { id: "n-1", kind: "quote_sent", project_id: pid, body: "바른벽이 실측 견적서를 보냈어요", link: href(s, "/quotes"), created_at: D.T("2026-11-22", "11:05"), read: true },
  ];
  return s;
}

// ───── 보드

const STEP: Record<Stage, number> = { address: 0, home: 0, standard: 1, vendors: 2, requested: 3, slots: 3, booked: 3, compare: 4, confirmed: 4, dates: 5, final: 6 };
function boardOf(s: State): BoardOut {
  const i = STEP[s.stage];
  const known = s.stage !== "address";
  const facts = known ? ["서울 노원구 상계동", "상계 푸른숲마을 7단지", "전용 84.97㎡", "34평형", ...(i >= 1 ? ["살면서 공사", "도배 · 실크"] : [])] : [];
  const g = s.quoteVer === 2 ? D.QUOTES.gyeol2 : D.QUOTES.gyeol1;
  const money: BoardOut["money"] =
    i === 0 ? null
      : s.stage === "compare" ? { label: "받은 견적서 · 부가세 포함", range: [g.total_won, D.QUOTES.bareun1.total_won] }
        : i >= 4 ? { label: "확정 금액 · 부가세 포함", won: g.total_won }
          : { label: "표준견적서 · 부가세 포함", won: D.STANDARD.total_won };
  const picked = D.VENDORS.filter((v) => s.picks.includes(v.key));
  const vendors: BoardOut["vendors"] =
    s.stage === "vendors" ? { title: `고른 업체 ${picked.length}/3`, rows: picked.map((v) => ({ name: v.name, state: "need", text: "가견적", won: v.est })) }
      : s.stage === "requested" ? { title: "업체", rows: picked.map((v) => ({ name: v.name, state: "waiting", text: "답 기다림" })) }
        : s.stage === "slots" || s.stage === "booked" ? { title: "업체", rows: visitTask(s, s.stage === "slots" ? "answered" : "booked").rows!.map((r) => ({ name: r.label, state: r.state, text: r.text })) }
          : s.stage === "compare" ? { title: "업체", rows: [{ name: "결도배", state: "done", text: `견적서 ${s.quoteVer}판` }, { name: "바른벽", state: "done", text: "견적서 1판" }, { name: "마루와벽", state: "need", text: "날짜 고르기" }] }
            : i >= 4 ? { title: "확정 업체", rows: [{ name: "결도배", state: "done", text: s.stage === "final" ? "공사 날짜 수락" : s.stage === "dates" ? "공사 날짜 옴" : "공사 날짜 기다림" }] }
              : null;
  const period: BoardOut["period"] =
    s.stage === "dates" || s.stage === "final"
      ? { label: "공사", value: rangeText(D.WORK.start, D.WORK.end, { weekday: true }), sub: s.stage === "final" ? "확정 공정표" : "수락 전" }
      : i >= 1 ? { label: "공사 시작 희망", value: dateLong(D.WISH.work_wish_on), sub: `입주 희망 ${dateLong(D.WISH.move_in)}` } : null;
  const docs = i >= 1
    ? [{ label: "표준견적서", href: href(s, "/standard") }, { label: s.stage === "final" ? "확정 공정표" : "예상 공정표", href: href(s, "/plan") },
      ...(i >= 4 ? [{ label: "실측 견적서", href: href(s, "/quotes") }] : []), ...(i >= 4 ? [{ label: "서류 모두", href: href(s, "/docs") }] : [])]
    : [];
  const todo = ({ address: 1, home: 1, standard: 0, vendors: 1, requested: 0, slots: 1, booked: 0, compare: s.script === "today" ? 2 : 1, confirmed: 0, dates: 1, final: 0 } as Record<Stage, number>)[s.stage];
  const waiting = ({ address: 0, home: 0, standard: 0, vendors: 0, requested: picked.length, slots: 1, booked: 3, compare: 0, confirmed: 1, dates: 0, final: 0 } as Record<Stage, number>)[s.stage];
  return {
    project_name: "상계동 아파트 도배", step: i, facts, confirmed: i >= 1, todo, waiting, money, vendors, period, docs,
    plan_example: i === 0, memory: s.memory, today_pin: s.script === "today" && !s.todayDismissed ? 2 : 0,
  };
}

// ───── 턴 대답

function learn(s: State, text: string) {
  const rules: [RegExp, MemoryOut["key"]][] = [[/오전|오후|주말|평일/, "avail_half"], [/냄새|친환경|풀/, "material"], [/강아지|고양이|반려/, "pet"], [/살면서|비어 있|빈 집/, "living"]];
  for (const [re, key] of rules) {
    if (!re.test(text) || text.length > 40) continue;
    const value = text.replace(/[.!?]+$/, "").slice(0, 30);
    s.memory = [...s.memory.filter((m) => m.key !== key), { id: nextId(s, "mem"), key, value, evidence_message_id: "u", evidence_quote: text }].slice(-12);
  }
}

function respond(s: State, body: TurnIn, turnId: string): Plan {
  const text = body.text.trim();
  const choice = body.context?.choice;
  const cardId = body.context?.card_id ?? "";
  const head: Step[] = [step({ type: "ack", data: { turn_id: turnId, chat_id: "chat-mock", at: s.clock } })];
  const reply = (steps: Step[], after?: Plan["after"]): Plan => ({ steps: [...head, ...steps], after });
  const answer = (t: string, links: { label: string; href: string }[] = [], chips = s.chips) =>
    reply([step({ type: "status", data: { text: "답을 찾고 있어요" } }, 300), step({ type: "card", data: answerCard(s, t, links) }, 500), done(s, chips)]);

  if (cardId === "home-search" && typeof choice === "string") return reply(addressPicked(s, choice));
  if (cardId === "home-manual" && typeof choice === "string") return reply(manualPicked(s, choice));
  if (cardId === "picks" && Array.isArray(choice)) return reply(repick(s, choice));
  if (cardId.startsWith("slots-") && typeof choice === "string") return reply(reslot(s, cardId === "slots-maru" ? "maru" : "gyeol", choice));

  if (s.stage === "address") {
    const hit = D.HOME.hits.find((h) => text.includes(h.name) || (text.length >= 2 && h.name.includes(text)));
    if (hit) return reply(addressPicked(s, hit.id));
    if (/평/.test(text) || /주소 없이/.test(text)) return reply(manualStart(s));
    return reply([
      step({ type: "status", data: { text: "주소를 찾고 있어요" } }, 300),
      step({ type: "card", data: homeSearch(text, D.HOME.hits) }, 500),
      step({ type: "token", data: { text: "비슷한 곳을 찾았어요. 맞는 주소를 골라 주세요." } }, 260),
      done(s, s.chips),
    ]);
  }
  if (/직접 고칠/.test(text)) return reply(manualStart(s));
  if (/다시 만들어/.test(text)) {
    if (/실측 요청/.test(text)) return reply(vendorsBeat(s));
    if (/확정/.test(text)) return reply(compareBeat(s, true));
    if (/마루와벽/.test(text)) return reply(maruBeat(s));
    if (/실측/.test(text)) return reply(reslot(s, "gyeol", "s1"));
    if (/수락/.test(text)) {
      const close = closeOpen(s, "dates_accept");
      return reply([step({ type: "card", data: datesCard(s, "dates") }, 400), ...close, step({ type: "action", data: datesAction(s) }, 300), done(s, s.chips)]);
    }
  }
  if (s.stage === "standard" && /업체/.test(text) && !/다른/.test(text)) return reply(vendorsBeat(s));
  if (/다른 업체/.test(text)) return answer("업체 목록에서 더 볼 수 있어요. 가견적 낮은 순으로 보여요.", [{ label: "업체 목록 열기", href: href(s, "/vendors") }]);
  if (/가견적/.test(text)) return answer("가견적은 업체가 확인한 단가에 믿집이 센 수량을 곱해 계산 엔진이 만든 금액이에요. 실측 뒤 업체가 보내는 견적서와 달라질 수 있어요.", [{ label: "표준견적서 보기", href: href(s, "/standard") }]);
  if (/견적서 비교|비교 보기/.test(text)) return reply(compareBeat(s, true));
  if (/마루와벽/.test(text) && /날짜|고르/.test(text)) return reply(maruBeat(s));
  if (/오늘은 그만/.test(text)) {
    s.todayDismissed = true;
    return reply([step({ type: "card", data: todayClosed(s) }, 200), step({ type: "token", data: { text: "알겠어요. 오늘은 더 알리지 않고, 정할 일이 바뀌면 다시 알려 드릴게요." } }, 300), done(s, ["견적서 비교 보기", "마루와벽 날짜 고르기"])]);
  }
  if (/준비물|알아 두기/.test(text)) return reply([step({ type: "status", data: { text: "자료를 찾고 있어요" } }, 300), step({ type: "card", data: knowCard() }, 500), done(s, s.chips)]);
  if (/평면도/.test(text)) {
    const card: CardOut<"floorplan_links"> = {
      card_id: nextId(s, "floor"), kind: "floorplan_links",
      data: {
        complex: D.HOME.complex.name,
        links: [{ label: "세움터 건축물대장 평면도", href: "https://www.eais.go.kr", source: "국토교통부 세움터" }, { label: "정부24 건축물대장 열람", href: "https://www.gov.kr", source: "정부24" }],
        note: "평면도 그림은 믿집이 찾아 넣지 않아요. 받은 파일을 보드에 올리면 실측 때 같이 봐요.",
      },
    };
    return reply([step({ type: "status", data: { text: "받을 곳을 찾고 있어요" } }, 300), step({ type: "card", data: card }, 600), done(s, s.chips)]);
  }
  if (/표준견적서/.test(text)) return answer("표준견적서는 공공 기준 단가로 믿집이 계산한 참고 금액이에요. 업체 견적이 아니에요.", [{ label: "표준견적서 열기", href: href(s, "/standard") }]);
  if (/공정표/.test(text)) return answer("공정표는 반나절 단위로 일을 놓고 하루 단위 날짜로 보여 줘요.", [{ label: "공정표 열기", href: href(s, "/plan") }]);
  if (/희망 기간/.test(text)) return answer("희망 기간은 요청서에서 바꿀 수 있어요. 보내기 전이라면 승인 카드에 바로 반영돼요.", [{ label: "요청서 열기", href: href(s, "/visits/new") }]);
  if (/폐기물/.test(text)) return answer("바른벽 견적서에는 폐기물 처리가 적혀 있지 않아요. 채팅에 물어볼 말을 넣어 둘게요. 보내기는 직접 눌러 주세요.", [{ label: "채팅 열기", href: "/chat" }]);
  if (/다른 시간|달력/.test(text)) return answer("달력에서 업체가 답한 기간 안의 반나절을 직접 고를 수 있어요.", [{ label: "실측 일정 열기", href: href(s, "/visits") }]);
  if (/다른 날짜/.test(text)) return answer("다른 날짜는 두 번까지 요청할 수 있어요. 요청하면 업체가 다시 골라 올려요.", [{ label: "공사 날짜 열기", href: href(s, "/schedule") }]);
  if (/달력에 넣기/.test(text)) return answer("확정 공정표를 휴대폰 달력에 넣을 수 있어요.", [{ label: "달력 파일 받기", href: `/api/projects/${encodeURIComponent(s.pid)}/plan.ics` }]);
  if (/언제/.test(text)) return answer("업체는 요청을 받고 48시간 안에 답해요. 견적서는 보통 실측 다음 날까지 와요. 오면 바로 알려 드릴게요.");
  if (/실측은 무엇/.test(text)) return answer("실측 때 업체가 벽 상태 · 몰딩 · 짐을 보고 견적서를 보내요. 한 시간 안쪽이면 끝나요.");
  return answer("예시 화면이라 정해 둔 말에만 답해요. 아래 칩이나 카드의 단추로 이어 가 보세요.");
}

function addressPicked(s: State, hitId: string): Step[] {
  const hit = D.HOME.hits.find((h) => h.id === hitId) ?? D.HOME.hits[0];
  const task: TaskOut = { task_id: "task-home", title: "단지 · 면적 찾기", state: "running", at: s.clock, sources: [] };
  const homeAct = makeAction(s, "home_info", { title: "집 정보 저장", approve_label: "맞아요" }, D.T("2026-11-28", "10:00"), { target_ver: "home-1" });
  return [
    step({ type: "card", data: homeSearch(hit.name, D.HOME.hits, hit.id) }, 0),
    step({ type: "status", data: { text: "단지 · 면적을 찾고 있어요", task } }, 250),
    step({ type: "status", data: { text: "찾았어요", task: { ...task, state: "done", at: D.T("2026-11-21", "10:02"), sources: D.HOME.sources } } }, 1100, { clock: D.T("2026-11-21", "10:02"), dup: true }),
    step({ type: "action", data: homeAct }, 0),
    step({ type: "card", data: homeConfirm(homeAct.action_id, false) }, 350, { apply: (x) => { x.stage = "home"; } }),
    done(s, ["직접 고칠게요", "평면도는 어디서 받아요?"]),
  ];
}
function manualStart(s: State): Step[] {
  const card: CardOut<"home_info"> = { card_id: "home-manual", kind: "home_info", say: "평형만 알아도 시작할 수 있어요.", data: { phase: "manual", pyeong_options: D.HOME.pyeongs, picked: null } };
  return [step({ type: "card", data: card }, 400), done(s, s.chips)];
}
function manualPicked(s: State, pyeong: string): Step[] {
  const homeAct = makeAction(s, "home_info", { title: "집 정보 저장", approve_label: "맞아요" }, D.T("2026-11-28", "10:00"), { target_ver: "home-1" });
  const card: CardOut<"home_info"> = { card_id: "home-manual", kind: "home_info", data: { phase: "manual", pyeong_options: D.HOME.pyeongs, picked: pyeong } };
  return [
    step({ type: "card", data: card }, 0),
    step({ type: "action", data: homeAct }, 0),
    step({ type: "card", data: homeConfirm(homeAct.action_id, false) }, 600, { apply: (x) => { x.stage = "home"; } }),
    done(s, ["직접 고칠게요"]),
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
    done(s, ["다른 업체도 보기", "희망 기간 바꾸기", "가견적은 어떻게 계산해요?"]),
  ];
}
function repick(s: State, keys: string[]): Step[] {
  const valid = keys.filter((k) => D.VENDORS.some((v) => v.key === k));
  s.picks = valid;
  if (!valid.length) return [step({ type: "card", data: picksCard(s) }, 0), ...closeOpen(s, "visit_request"), step({ type: "token", data: { text: "업체를 한 곳 이상 골라 주세요." } }, 200), done(s, s.chips)];
  const close = closeOpen(s, "visit_request");
  return [step({ type: "card", data: picksCard(s) }, 0), ...close, step({ type: "action", data: visitRequestAction(s) }, 500), done(s, s.chips)];
}
function reslot(s: State, who: "gyeol" | "maru", ref: string): Step[] {
  const close = closeOpen(s, "visit_slot");
  return [step({ type: "card", data: slotsCard(s, who, ref) }, 0), ...close, step({ type: "action", data: slotAction(s, who, ref) }, 500), done(s, s.chips)];
}
function compareBeat(s: State, inline: boolean): Step[] {
  const close = closeOpen(s, "vendor_confirm");
  return [
    ...(inline ? [step({ type: "status", data: { text: "견적서를 놓고 보고 있어요" } }, 300)] : []),
    step({ type: "card", data: compareCard(s) }, 700),
    ...sentences(s.quoteVer === 2 ? "결도배 2판은 1판보다 금액 하나만 바뀌었어요. 바른벽은 폐기물 처리가 적혀 있지 않아 확정 전에 물어보면 좋아요." : "두 곳 모두 철거는 포함이에요. 바른벽은 폐기물 처리가 적혀 있지 않아 확정 전에 물어보면 좋아요."),
    ...close,
    step({ type: "action", data: confirmAction(s) }, 300, { apply: (x) => { x.stage = "compare"; } }),
    done(s, ["바른벽에 폐기물 묻기", "마루와벽도 기다릴래요", "표준견적서 다시 보기"]),
  ];
}
function maruBeat(s: State): Step[] {
  const close = closeOpen(s, "visit_slot");
  return [step({ type: "card", data: slotsCard(s, "maru", "m1") }, 600), ...close, step({ type: "action", data: slotAction(s, "maru", "m1") }, 300), done(s, s.chips)];
}
function todayClosed(s: State): CardOut<"today"> {
  const hit = s.items.flatMap((x) => (x.role === "assistant" ? x.parts : [])).find((p) => p.t === "card" && p.card.card_id === "today");
  const card = hit && hit.t === "card" ? (hit.card as CardOut<"today">) : null;
  return { card_id: "today", kind: "today", data: { ...(card?.data ?? { date: "2026-11-24", nudge_id: null, todo: [], waiting: [], news: [], know: [] }), dismissed: true } };
}

// ───── 승인 뒤 이어지는 일(서버가 먼저 보내는 턴)

function follow(s: State, a: ActionOut) {
  switch (a.kind) {
    case "home_info": later(s, "standard", 500); return;
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
    case "standard":
      return { steps: [
        step({ type: "status", data: { text: "표준견적서를 계산하고 있어요" } }, 300),
        step({ type: "card", data: standardCard(s) }, 900, { apply: (x) => { x.stage = "standard"; } }),
        ...sentences("가장 큰 줄은 벽지 값과 도배 품이에요. 짐 옮기기와 부분 보수는 실측 뒤에 바뀔 수 있어요."),
        done(s, ["업체 추천해 줘", "가견적은 어떻게 계산해요?", "예상 공정표 보기"], { suggest: { id: "sg-vendors", text: "업체 3곳을 골라 둘까요?", why: "노원구에서 가견적을 낸 도배 업체가 5곳 있어요", say: "업체 추천해 줘" } }),
      ] };
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
        step({ type: "action", data: slotAction(s, "gyeol", "s1") }, 300),
        done(s, ["다른 시간 볼래요", "실측은 무엇을 봐요?"]),
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
        ...sentences("결도배가 공사 날짜를 올리면 알려 드릴게요. 확정한 견적서는 바뀌지 않아요."),
        done(s, ["공사 날짜는 언제 와요?"]),
      ] };
    case "dates":
      note(s, "결도배가 공사 날짜를 올렸어요", "/schedule", "dates_proposed");
      return { clock: D.T("2026-11-27", "11:00"), steps: [
        step({ type: "card", data: datesCard(s, "dates") }, 500, { apply: (x) => { x.stage = "dates"; } }),
        step({ type: "action", data: datesAction(s) }, 400),
        done(s, ["다른 날짜 요청하기", "공정표 열기"]),
      ] };
    case "final":
      return { steps: [
        step({ type: "status", data: { text: "공정표를 만들고 있어요" } }, 300),
        step({ type: "card", data: datesCard(s, "final") }, 900, { apply: (x) => { x.stage = "final"; } }),
        step({ type: "card", data: knowCard() }, 500),
        ...sentences("공사 전날 저녁 6시에 준비물을 한 번 더 알려 드릴게요."),
        done(s, ["공사 전날 준비물", "공정표 열기", "달력에 넣기"]),
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

export async function feed(pid: string): Promise<FeedPage> {
  const s = load(pid);
  return { items: s.items, before: null, rev: s.rev, chips: s.chips, now: s.clock };
}
export async function board(pid: string): Promise<BoardOut> {
  return boardOf(load(pid));
}
export async function turn(body: TurnIn, emit: (e: TurnEvent) => void, signal?: AbortSignal): Promise<void> {
  const pid = body.project_id;
  await enqueue(pid, async () => {
    const s = load(pid);
    const uid = `u-${body.client_key}`;
    if (!s.items.some((x) => x.id === uid)) s.items = [...s.items, { id: uid, role: "user", at: s.clock, text: body.text }];
    learn(s, body.text);
    const turnId = `t-${++s.n}`;
    save(s);
    const plan = respond(s, body, turnId);
    save(s);
    await run(pid, turnId, plan.steps, emit, signal);
    plan.after?.(load(pid));
  });
}
export async function actions(pid: string): Promise<ActionOut[]> {
  return Object.values(load(pid).actions).filter((a) => a.status === "proposed");
}
export async function approve(pid: string, actionId: string, _clientKey: string): Promise<ActionOut> {
  return enqueue(pid, async () => {
    const s = load(pid);
    const a = s.actions[actionId];
    if (!a) throw new ApiError(404, "not_found", "제안을 찾지 못했어요.");
    if (a.status === "executed") return a;
    if (a.status !== "proposed") throw new ApiError(409, "action_closed", a.error_code === "replaced" ? "새 카드로 바뀐 제안이에요." : "이미 끝난 제안이에요.");
    await sleep(700);
    if (a.kind === "vendor_confirm" && s.quoteFailOnce && s.quoteVer === 1) {
      // 그사이 결도배가 2판을 보냈어요 → 옛 행동은 실패(quote_changed), 새 판 + 차액으로 새 행동
      s.quoteFailOnce = false;
      s.quoteVer = 2;
      s.clock = D.T("2026-11-26", "18:41");
      setAction(s, { ...a, status: "failed", error_code: "quote_changed" });
      const fresh = confirmAction(s, a.action_id);
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
            : a.kind === "vendor_confirm" ? { text: "결도배로 확정했어요", href: href(s, "/quotes"), label: "견적서 보기" }
              : a.kind === "dates_accept" ? { text: "공사 날짜를 수락했어요", href: href(s, "/plan"), label: "공정표 보기" }
                : { text: "했어요" };
    const fin: ActionOut = { ...a, status: "executed", decided_at: at, executed_at: at, result };
    setAction(s, fin);
    if (a.kind === "home_info") s.items = replaceCard(s.items, homeConfirm(a.action_id, true));
    save(s);
    follow(s, fin);
    return fin;
  });
}
export async function reject(pid: string, actionId: string): Promise<ActionOut> {
  return enqueue(pid, async () => {
    const s = load(pid);
    const a = s.actions[actionId];
    if (!a) throw new ApiError(404, "not_found", "제안을 찾지 못했어요.");
    if (a.status !== "proposed") return a;
    const fin: ActionOut = { ...a, status: "rejected", decided_at: s.clock };
    setAction(s, fin);
    save(s);
    return fin;
  });
}
export async function dismiss(pid: string, _nudgeId: string): Promise<CardOut | null> {
  const s = load(pid);
  s.todayDismissed = true;
  const card = todayClosed(s);
  s.items = replaceCard(s.items, card);
  save(s);
  return card;
}
export async function memory(pid: string): Promise<MemoryOut[]> {
  return load(pid).memory;
}
export async function forget(pid: string, id: string): Promise<void> {
  const s = load(pid);
  s.memory = s.memory.filter((m) => m.id !== id);
  save(s);
}
export async function searchAddress(q: string): Promise<AddressHit[]> {
  await sleep(250);
  const t = q.trim();
  if (!t) return [];
  const hits = D.HOME.hits.filter((h) => h.name.includes(t) || h.road.includes(t) || t.includes(h.name));
  return hits.length ? hits : /상계|푸른|노원/.test(t) ? D.HOME.hits : [];
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

// ───── 업체(V1 · V3 · 오늘 브리핑)

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

export async function vendorBrief(visitId: string, seed?: BriefSeed): Promise<VendorBriefData> {
  await sleep(200);
  const region = seed?.region ?? "노원구 상계동";
  const area = seed ? seed.area : "전용 84.97㎡";
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
    sentence: "희망 기간 첫 주에 빈 반나절이 많아요. 이 기간으로 답하면 고객이 바로 고를 수 있어요.",
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
  const a: ActionOut = {
    action_id: actionId, kind: "window_answer", status: "executed",
    summary: { title: "이 기간으로 답하기", approve_label: "이 기간으로 답하기" },
    expires_at: D.T("2026-11-23", "10:06"), executed_at: D.T("2026-11-21", "11:20"),
    result: { text: "기간을 보냈어요. 고객이 날짜를 고르면 알려 드릴게요", href: "/vendor?tab=waiting", label: "기다림 보기" },
  };
  vendorActs.set(actionId, a);
  return a;
}
export async function rejectVendor(actionId: string): Promise<ActionOut> {
  const a: ActionOut = { action_id: actionId, kind: "window_answer", status: "rejected", summary: { title: "이 기간으로 답하기", approve_label: "이 기간으로 답하기" }, expires_at: D.T("2026-11-23", "10:06") };
  vendorActs.set(actionId, a);
  return a;
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
