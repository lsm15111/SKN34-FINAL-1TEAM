// 자재 단계 상태: 고르는 화면의 모듈 변수(v10 matCard · matCat · matFilter …) · 비교 바구니 · 추천 자리 고정 · 목공 자재.
// 금액은 만들지 않는다. 목공 자재 · 정해진 단가 항목은 백엔드(/mvp/materials), 목공 금액 · 길이는 견적 API(/mvp/v2/quote)가 준다.
import { mvpGet, v2Post } from "@/components/v2/api";
import { DATA, type MokSt, S, touch, V3 } from "@/components/v2/store";
import { F, live } from "@/components/v2/engine";
import { flashBoard } from "@/components/v2/Board";
import type { Material } from "@/components/v2/data";

export const LIST_STEP = 6;

/** 자재 화면 상태 (v10 matCard · matCat · matFilter · matSort · matShow · matQuery · matTag · matAdd) */
export const M = {
  cardId: 0, // 0이면 아직 카드가 없다 (v10 matCard = null)
  cat: null as string | null,
  filter: "all",
  sort: "rec",
  show: LIST_STEP,
  query: "",
  tag: null as string | null,
  add: false,
  full: false, // 자재 크게 보기 (v10 mat-full)
};
/** 공정마다 비교에 담은 자재 id (최대 3개) */
export const CMP: Record<string, string[]> = {};
const REC_SLOTS: Record<string, string[]> = {};

export function listReset() {
  M.filter = "all";
  M.show = LIST_STEP;
  M.query = "";
  M.tag = null;
  M.add = false;
}

/** 추천 3개 자리를 지킨다: 앞서 보인 자재가 여전히 추천이면 같은 자리에 둔다 */
export function keepSlots(cat: string, list: Material[]) {
  const prev = REC_SLOTS[cat] || [], ids = new Set(list.map((m) => m.id));
  const out: (Material | null)[] = prev.map((id) => (ids.has(id) ? list.find((m) => m.id === id) || null : null));
  const rest = list.filter((m) => !out.includes(m));
  for (let i = 0; i < out.length; i++) if (!out[i]) out[i] = rest.shift() || null;
  const res = [...(out.filter(Boolean) as Material[]), ...rest];
  REC_SLOTS[cat] = res.map((m) => m.id);
  return res;
}

/** v10 renderBoard(true) · refreshMat 자리 */
export function redraw(flash = false) {
  if (flash) flashBoard();
  touch();
}

/* ---------- 목공 자재 (백엔드 /mvp/materials = v10 MOK10 prod · extras · init) ---------- */
export type MokProduct = { id: string; kind: string; name: string; price: number; why: string; len_m: string | number | null; type: string | null };
export type MokExtra = { key: string; group: string; ko: string; what: string; unit: string; price: number; basis: string; src: string; auto: string | null };
export type MokGrade = { molding_type: string; molding: string; base: string; leaf: string; door_set: string };
export type MokData = { version: string; products: MokProduct[]; extras: MokExtra[]; grades: Record<string, MokGrade> };

export const MOLDING_TYPES: [MokSt["molding"]["type"], string][] = [["flat", "평몰딩"], ["step", "계단몰딩"], ["minus", "무몰딩(마이너스)"], ["none", "안 함"]];
export const DOOR_MODES: [MokSt["door"]["mode"], string][] = [["none", "안 함"], ["replace", "문틀까지 교체"], ["overlay", "문틀 덧방"], ["leaf", "문짝만 교체"]];

export const MOK = { data: null as MokData | null, prod: {} as Record<string, MokProduct>, err: false };
let mokLoading: Promise<void> | null = null;
/** 목공 자재를 한 번만 받아 둔다. 실패하면 다음에 다시 받는다 */
export function loadMok() {
  if (MOK.data) return Promise.resolve();
  mokLoading ??= mvpGet<MokData>("materials")
    .then((d) => {
      MOK.data = d;
      MOK.prod = Object.fromEntries(d.products.map((p) => [p.id, p]));
      MOK.err = false;
    })
    .catch(() => {
      MOK.err = true;
    })
    .finally(() => {
      mokLoading = null;
      touch();
    });
  return mokLoading;
}

const firstOf = (kind: string, fallback: string) => MOK.data?.products.find((p) => p.kind === kind)?.id ?? fallback;

/** 목공 고른 값. 처음엔 등급별 처음 자재(문은 '안 함'). 자료를 아직 못 받았으면 저장하지 않는 빈 값 */
export function mok10St(): MokSt {
  if (!S.mok10) {
    const g = MOK.data && (MOK.data.grades[S.tier] || MOK.data.grades.basic);
    const blank: MokSt = {
      door: { mode: "none", pick: null, count: null },
      slide: { n: 0, pick: firstOf("slide", "door-yerim-hidden-sliding-set") },
      hidden: { n: 0, pick: firstOf("hidden", "door-yerim-hidden-set") },
      molding: { type: "none", pick: null },
      base: { pick: null },
      extras: {},
    };
    if (!g) return blank;
    blank.molding = { type: g.molding_type as MokSt["molding"]["type"], pick: g.molding };
    blank.base = { pick: g.base };
    S.mok10 = blank;
  }
  return S.mok10;
}
/** 보드 '고른 자재'와 다른 화면이 읽는 S.picks.carpentry를 목공 고른 값에 맞춘다 */
export function mok10Sync() {
  const s = mok10St();
  const id = (s.molding.type !== "none" && s.molding.pick) || s.base.pick || (s.door.mode !== "none" && s.door.pick) || S.picks.carpentry;
  if (id) S.picks.carpentry = id;
}
export function mok10Set(fn: (s: MokSt) => void) {
  fn(mok10St());
  mok10Sync();
  redraw(true);
}
export function mok10DefaultPick(mode: string) {
  const g = MOK.data && (MOK.data.grades[S.tier] || MOK.data.grades.basic);
  return g ? (mode === "replace" ? g.door_set : g.leaf) : null;
}

/* 도면 수량 (작업자 A의 F.pp9Measured: v10 pp9Measured와 같은 모양) */
type Measured = { py: number; supply_m2: number; m: { name: string; doors: number; molding_m: number; base_m: number; ceiling_m2: number } };
export const measured = () => (F.pp9Measured?.() as Measured | null | undefined) ?? null;

/** 방문 처음 개수: 도면을 골랐으면 도면에서 센 문, 아니면 항목표 규칙(방 수 + 욕실 수). 개수 표일 뿐 금액은 아니다 */
const roomsFor = (py: number) => (py < 28 ? 2 : py < 38 ? 3 : 4);
const bathsFor = (py: number) => (py < 28 ? 1 : 2);
export function mok10AutoDoors() {
  const pl = measured();
  if (pl && pl.m.doors) return { n: pl.m.doors, how: `도면 ${pl.m.name}에서 센 방문` };
  const p = pl?.py || S.info.pyeong || 32;
  return { n: roomsFor(p) + bathsFor(p), how: `${p}평 기준 방 ${roomsFor(p)} + 욕실 ${bathsFor(p)}` };
}
export const mok10Doors = () => mok10St().door.count ?? mok10AutoDoors().n;

/** 자재 이름(자료에서 읽기만). 없으면 백엔드 이름, 그것도 없으면 id */
export function dataName(id: string | null | undefined) {
  if (!id) return "";
  const m = DATA.materials.find((x) => x.id === id);
  return m ? `${m.brand} ${m.name.replace(m.brand, "").trim()}`.trim() : MOK.prod[id]?.name || id;
}

/* ---------- 목공 금액 · 길이 (견적 API의 정밀 목공 결과) ---------- */
export type QLine = { key: string; name: string; qty: number | string | null; unit: string; calc: string };
export type QTrade = { trade: string; lines: QLine[]; supply: number; total: number; man_days: number | string; days: number | string };
export type QuoteOut = { inp: { py: number; measured: { name: string; molding_m: number | string; base_m: number | string } | null; doors: number }; precise: QTrade[] };

export const mokQuote = live<{ key: string; data: QuoteOut | null; err: boolean }>({ key: "", data: null, err: false });
let qTimer: ReturnType<typeof setTimeout> | undefined;
let qSeq = 0;

/** 목공 패널이 보일 때 견적 API에 목공만 보낸다 (같은 입력이면 다시 부르지 않음) */
export function mokQuoteBody() {
  const plan = S.plan?.kind === "apt" && S.plan.id ? { id: S.plan.id, expanded: S.plan.expanded !== false, kinds: (F.pp9Kinds?.() as string[] | null | undefined) ?? null } : null;
  return { pyeong: S.info.pyeong, living: S.info.living, cats: ["carpentry"], picks: S.picks, plan, balcony: V3.balcony, mok: mok10St() };
}
export function requestMokQuote() {
  const body = mokQuoteBody();
  const key = JSON.stringify(body);
  if (mokQuote.get().key === key) return;
  mokQuote.set({ key, data: null, err: false });
  clearTimeout(qTimer);
  const my = ++qSeq;
  qTimer = setTimeout(() => {
    v2Post<QuoteOut>("quote", body)
      .then((d) => {
        if (my === qSeq) mokQuote.set({ key, data: d, err: false });
      })
      .catch(() => {
        if (my === qSeq) mokQuote.set({ key, data: null, err: true });
      });
  }, 250);
}
