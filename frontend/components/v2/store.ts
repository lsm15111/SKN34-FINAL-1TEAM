// v2 상태: v10의 S(상담 상태) · V3(견적서 · 공정표 상태)를 그대로 옮겼다.
// 흐름 코드는 S를 직접 고치고 touch()를 부르면 화면이 다시 그려진다(useV2). 저장은 이 브라우저에만 한다.
import { useSyncExternalStore } from "react";
import type { Material, StyleData } from "./data";

export type Living = "vacant" | "living";
export type Info = { pyeong: number | null; region: string; living: Living | null; move: string };
export type Scope = { kind: "all" | "part" | null; spaces: string[]; cats: string[] };
export type PhotoItem = { url: string; name: string; file: File };
/** 도면: type = 대표 평면(p24 · p32 · p40), apt = 예시 평면도(백엔드 /mvp/plans), file = 올린 파일 */
export type PlanSel = { kind: "type" | "apt" | "file"; id?: string; name: string; url?: string; expanded?: boolean };
export type Tier = "economy" | "basic" | "premium";

export type MokSt = {
  door: { mode: "none" | "replace" | "overlay" | "leaf"; pick: string | null; count: number | null };
  slide: { n: number; pick: string | null };
  hidden: { n: number; pick: string | null };
  molding: { type: "flat" | "step" | "minus" | "none"; pick: string | null };
  base: { pick: string | null };
  extras: Record<string, boolean | number>;
};

export type State = {
  typed: boolean;
  style: string | null;
  look: string | null;
  guideSeen: boolean;
  info: Info;
  scope: Scope;
  budget: number | null; // 만 원
  budgetUnknown: boolean;
  tier: Tier;
  tierBy: "me" | null;
  photos: PhotoItem[];
  refs: PhotoItem[];
  plan: PlanSel | null;
  picks: Record<string, string>;
  step: string;
  far: number;
  imgMode: "free" | "mfg" | "ai";
  mok10?: MokSt;
};

export const freshState = (): State => ({
  typed: false, style: null, look: null, guideSeen: false,
  info: { pyeong: null, region: "", living: null, move: "" },
  scope: { kind: null, spaces: [], cats: [] },
  budget: null, budgetUnknown: false, tier: "basic", tierBy: null,
  photos: [], refs: [], plan: null,
  picks: {}, step: "welcome", far: 0, imgMode: "ai",
});

/** 상담 상태. 흐름 코드가 직접 고친 뒤 touch()로 알린다 */
export const S: State = freshState();

/** 견적서 · 공정표 상태 (v10 V3). quote · plan은 백엔드 계산 결과를 담는다 */
export const V3 = {
  role: "customer" as "customer" | "vendor",
  balcony: false,
  vp: {} as Record<string, unknown>, // 업체가 낸 날짜 제안
  vpState: {} as Record<string, unknown>,
  vq: {} as Record<string, unknown>, // 업체 실측 견적(받은 견적)
  props: {} as Record<string, unknown>,
  cons: { weekendWork: false, endBy: "", startAfter: "", avoid: [] as string[] },
  accepted: {} as Record<string, unknown>,
  changes: {} as Record<string, unknown>,
  log: [] as string[],
  quote: null as unknown,
  plan: null as unknown,
};

/** 자재 · 스타일 자료 (public/v2/data.json) */
export const DATA: { materials: Material[]; styles: Record<string, StyleData>; ready: boolean } = { materials: [], styles: {}, ready: false };

/** 사진 주소 앞부분 (서버 설정 V2_IMG_BASE). 비어 있으면 저장소 안 /v2/img, 있으면 S3 · CDN 주소 (예 https://cdn.example.com/v2/img) */
export const assetCfg = { imgBase: "" };
/** public/v2 아래 파일 경로. 자료 안 경로는 "img/..." 처럼 상대 경로다. 사진(img/)만 imgBase를 따른다 */
export const asset = (p: string | null | undefined) => {
  if (!p) return null;
  if (/^(https?:|data:|blob:|\/)/.test(p)) return p;
  if (p.startsWith("img/") && assetCfg.imgBase) return `${assetCfg.imgBase.replace(/\/$/, "")}/${p.slice(4)}`;
  return `/v2/${p}`;
};

let version = 0;
const listeners = new Set<() => void>();
const subscribe = (f: () => void) => {
  listeners.add(f);
  return () => listeners.delete(f);
};

/** 상태가 바뀌었다고 알린다 (v10 renderBoard · refreshMat 자리). 저장도 같이 한다 */
export function touch() {
  version++;
  saveState();
  listeners.forEach((f) => f());
}

/** 상태를 읽는 컴포넌트는 이걸 부른다. touch()마다 다시 그려진다 */
export function useV2() {
  useSyncExternalStore(subscribe, () => version, () => 0);
  return S;
}

export const store = {
  get(k: string) {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set(k: string, v: string) {
    try {
      localStorage.setItem(k, v);
    } catch {}
  },
  del(k: string) {
    try {
      localStorage.removeItem(k);
    } catch {}
  },
};

/* 진행 저장(이 브라우저에만). 사진 · 올린 도면은 저장하지 않는다 */
const SAVE_KEY = "mj-v2-state";
export const chat = { built: false };
export function saveState() {
  if (!chat.built || S.step === "welcome") return;
  const { photos: _p, refs: _r, plan, ...rest } = S;
  store.set(SAVE_KEY, JSON.stringify({ ...rest, plan: plan && (plan.kind === "type" || plan.kind === "apt") ? plan : null, savedAt: Date.now() }));
}
export function loadSaved(): (Partial<State> & { savedAt?: number }) | null {
  try {
    const v = JSON.parse(store.get(SAVE_KEY) || "null");
    return v && (v.far > 0 || Object.keys(v.picks || {}).length) ? v : null;
  } catch {
    return null;
  }
}
export const clearSaved = () => store.del(SAVE_KEY);

/** 상태를 처음으로 (사진 종류는 그대로) */
export function resetState() {
  [...S.photos, ...S.refs].forEach((p) => URL.revokeObjectURL(p.url));
  if (S.plan?.url) URL.revokeObjectURL(S.plan.url);
  Object.assign(S, freshState(), { imgMode: S.imgMode });
  Object.assign(V3, { role: "customer", balcony: false, vp: {}, vpState: {}, vq: {}, props: {}, cons: { weekendWork: false, endBy: "", startAfter: "", avoid: [] }, accepted: {}, changes: {}, log: [], quote: null, plan: null });
  clearSaved();
}

/** 움직임 줄이기 설정이면 기다리지 않는다 */
export const wait = (ms: number) =>
  new Promise<void>((r) => setTimeout(r, typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : ms));
