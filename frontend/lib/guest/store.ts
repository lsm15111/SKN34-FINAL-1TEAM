// 로그인 전에 넣은 답을 이 기기에만 둬요(dev-03 A · security-02). 브라우저에서만 불러요.
// - 키 mj_guest_v3 = { v: 3, key: UUID(가입 뒤 POST /projects의 Idempotency-Key), saved_at, info }
// - 두는 것: 공종 · 범위 · 주거 · 지역 코드 · 면적 · 집 상태 · 벽지 · 예산 · 희망일. 이름 · 연락처 · 동 · 호 · 사진 · 금액은 두지 않아요.
// - 읽을 때 믿지 않고 모양을 검사해요. 틀리거나 30일이 지나면 지워요. 옛 키(mj_start_draft_v4)는 읽어 옮기고 지워요.
import { EMPTY_DRAFT, SPACES, type InfoDraft } from "./info";

const KEY = "mj_guest_v3";
const LEGACY = "mj_start_draft_v4";
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
/** 저장이 바뀌면 같은 탭 안에 알려요(내 공사의 '쓰던 요청서' 카드가 같은 이름을 들어요) */
export const GUEST_EVENT = "mj-draft-change";

/** dev-03 정한 세부의 info 모양(덜 찬 값은 비워 둠) */
type StoredInfo = {
  trade: "dobae";
  scope: "full" | "partial";
  spaces: string[];
  faces: string[];
  /** 방 개수 1~5. 없거나 null이면 면적 기본값(옛 저장본에는 없음) */
  rooms?: number | null;
  housing: "apt";
  sido: string;
  sgg: string;
  emd: string;
  area_m2: string;
  area_basis: "supply" | "exclusive";
  occupied: boolean | null;
  grade: "economy" | "basic" | null;
  budget_won: number | null;
  start_date: string | null;
  /** 철거 범위(v4 첫 대화). 옛 저장본에는 없음 */
  demolition?: "full" | "partial" | "none" | null;
};
export type GuestSaved = { v: 3; key: string; saved_at: string; info: StoredInfo };

const SPACE_KEYS = new Set<string>(SPACES.map((s) => s.key));
const str = (v: unknown, max: number) => typeof v === "string" && v.length <= max;
const day = (v: unknown) => v === null || (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v));

function valid(x: unknown): x is GuestSaved {
  if (!x || typeof x !== "object") return false;
  const g = x as Record<string, unknown>;
  const i = g.info as Record<string, unknown> | undefined;
  if (g.v !== 3 || !str(g.key, 64) || !/^[0-9a-f-]{36}$/i.test(String(g.key)) || !str(g.saved_at, 40) || !i || typeof i !== "object") return false;
  return (
    i.trade === "dobae" && i.housing === "apt" &&
    (i.scope === "full" || i.scope === "partial") &&
    Array.isArray(i.spaces) && i.spaces.length <= 10 && i.spaces.every((s) => typeof s === "string" && SPACE_KEYS.has(s)) &&
    Array.isArray(i.faces) && i.faces.length <= 2 && i.faces.every((f) => f === "wall" || f === "ceiling") &&
    (i.rooms === undefined || i.rooms === null || (Number.isInteger(i.rooms) && (i.rooms as number) >= 1 && (i.rooms as number) <= 5)) &&
    str(i.sido, 20) && str(i.sgg, 20) && str(i.emd, 20) && str(i.area_m2, 10) &&
    (i.area_basis === "supply" || i.area_basis === "exclusive") &&
    (i.occupied === null || typeof i.occupied === "boolean") &&
    (i.grade === null || i.grade === "economy" || i.grade === "basic") &&
    (i.budget_won === null || (Number.isInteger(i.budget_won) && (i.budget_won as number) >= 0 && (i.budget_won as number) <= 10_000_000_000)) &&
    day(i.start_date) &&
    (i.demolition === undefined || i.demolition === null || i.demolition === "full" || i.demolition === "partial" || i.demolition === "none")
  );
}

function uuid(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  // http(사설 IP) 같은 곳에서는 randomUUID가 없어서 같은 꼴로 만들어요
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function toStored(d: InfoDraft): StoredInfo {
  const b = d.budget.replace(/[,\s]/g, "");
  return {
    trade: "dobae", scope: d.scope, spaces: d.spaces, faces: d.faces, rooms: d.rooms, housing: "apt",
    sido: d.sido, sgg: d.sgg, emd: d.emd.slice(0, 20), area_m2: d.area.trim().slice(0, 10), area_basis: d.basis,
    occupied: d.occupied, grade: d.grade,
    budget_won: /^\d{1,6}$/.test(b) ? Number(b) * 10000 : null,
    start_date: d.start,
    demolition: d.demolition ?? null,
  };
}

/** 저장된 답 → 넣는 중인 답 */
export function draftOf(s: GuestSaved): InfoDraft {
  const i = s.info;
  return {
    ...EMPTY_DRAFT,
    scope: i.scope,
    spaces: i.spaces as InfoDraft["spaces"],
    faces: (i.faces.length ? i.faces : ["wall", "ceiling"]) as InfoDraft["faces"],
    rooms: i.rooms ?? null,
    sido: i.sido, sgg: i.sgg, emd: i.emd, area: i.area_m2, basis: i.area_basis,
    occupied: i.occupied, grade: i.grade,
    budget: i.budget_won ? String(Math.round(i.budget_won / 10000)) : "",
    start: i.start_date,
    demolition: i.demolition ?? null,
  };
}

/** 옛 v4 초안(지역 · ㎡ · 집 상태 · 벽지 · 날짜)만 옮겨요. 평형대 · 예산 구간은 v3 칸과 달라 옮기지 않아요 */
function fromLegacy(raw: string): InfoDraft | null {
  try {
    const a = JSON.parse(raw)?.a;
    if (!a || typeof a !== "object") return null;
    const d: InfoDraft = { ...EMPTY_DRAFT };
    if (str(a.sido, 20)) d.sido = a.sido;
    if (str(a.sgg, 20)) d.sgg = a.sgg;
    if (str(a.manualM2, 10) && /^\d{1,3}(\.\d)?$/.test(a.manualM2)) d.area = a.manualM2;
    if (a.manualBasis === "jeon") d.basis = "exclusive";
    if (a.occupied === "yes" || a.occupied === "no") d.occupied = a.occupied === "yes";
    if (a.grade === "economy" || a.grade === "basic") d.grade = a.grade;
    if (a.when === "date" && day(a.whenDate) && a.whenDate) d.start = a.whenDate;
    return d.sido || d.area ? d : null;
  } catch {
    return null;
  }
}

function emit() {
  try { window.dispatchEvent(new Event(GUEST_EVENT)); } catch { /* 이벤트를 못 보내도 저장은 그대로 */ }
}

/** 저장된 답. 없거나 틀리거나 30일이 지났으면 null(틀린 것 · 지난 것은 지워요) */
export function readGuest(): GuestSaved | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const g = JSON.parse(raw);
      const at = valid(g) ? Date.parse(g.saved_at) : NaN;
      if (valid(g) && Number.isFinite(at) && Date.now() - at <= MAX_AGE_MS) return g;
      localStorage.removeItem(KEY);
      return null;
    }
    const old = localStorage.getItem(LEGACY);
    if (old) {
      localStorage.removeItem(LEGACY);
      const d = fromLegacy(old);
      return d ? writeGuest(d) : null;
    }
  } catch {
    /* 저장소를 못 쓰는 브라우저(사생활 보호 등)는 저장 없이 넘어가요 */
  }
  return null;
}

/** 답 저장. 키(멱등 키)는 처음 저장할 때 한 번 만들고 그대로 둬요 */
export function writeGuest(d: InfoDraft): GuestSaved {
  let key: string;
  try {
    const now = JSON.parse(localStorage.getItem(KEY) ?? "null");
    key = valid(now) ? now.key : uuid();
  } catch {
    key = uuid();
  }
  const g: GuestSaved = { v: 3, key, saved_at: new Date().toISOString(), info: toStored(d) };
  try { localStorage.setItem(KEY, JSON.stringify(g)); } catch { /* 저장소가 가득 차거나 막혔으면 이 화면에서만 써요 */ }
  emit();
  return g;
}

/** 답 지우기(가입 뒤 옮긴 다음 · '지우기' · 탈퇴 · 로그아웃) */
export function clearGuest() {
  try {
    localStorage.removeItem(KEY);
    localStorage.removeItem(LEGACY);
  } catch { /* 지울 수 없으면 그대로 */ }
  emit();
}
