// 견적서 · 공정표가 부르는 백엔드 API를 이 파일 한 곳에 모은다. 금액 · 수량 · 날짜는 모두 응답 그대로 쓴다.
// quote · plan · check · market-extras는 작업자 E의 API.md 모양. estimate · entered는 API.md에 없어 v10 함수 입력 · 출력으로 가정했다.
import { mvpGet, v2Get, v2Post } from "../api";
import { F } from "../engine";
import { scopeCats } from "../flow";
import { S, V3 } from "../store";

/* ---------- 표준견적서 (POST /mvp/v2/quote = v10 buildQuote) ---------- */
export type LineState = "included" | "bundled" | "separate" | "optional" | "after_visit" | "excluded";
export type QLine = { key: string; name: string; qty: number | null; unit: string; unit_price: number | null; amount: number | null; state: LineState; source: string; basis: string; calc?: string | null };
export type MkLine = { key: string; name: string; qty: number | null; unit: string; unit_price: number | null; amount: number; note?: string | null };
export type Band = {
  lo: number;
  hi: number;
  n: number;
  p: [number, number];
  mk: { trade: string; grade?: string; lines: MkLine[]; supply: number; lo: number; hi: number; band: { lo: number; hi: number; lo80?: number; hi80?: number; n?: number }; version: string };
};
export type GapStep = { key: string; name: string; why: string; d: number };
export type Gap = { from: number; steps: GapStep[]; to: number };
export type Step = { key: string; name: string; half_days: number };
export type Precise = {
  trade: string;
  ko: string;
  lines: QLine[];
  supply: number;
  vat: number;
  total: number;
  man_days: number;
  md_raw?: number;
  crew: number;
  steps: Step[];
  days: number;
  notes: string[];
  grade?: string;
  extra_amount?: number;
  ver?: string;
  band: Band | null;
  gap: Gap | null;
};
export type RefLine = {
  key: string;
  name: string;
  qty: number;
  unit: string;
  lo: number | null;
  hi: number | null;
  state: LineState;
  basis: string;
  source: string;
  calc: string;
  pub: { unit_price: number; amount: number; source: string } | null;
  note: string | null;
};
export type RefTrade = { cat: string; ko: string; level: string; lines: RefLine[]; lo: number; hi: number; vlo: number; vhi: number; days: number; crew: number; steps: Step[]; notes: string[] };
export type Measured = { name: string; wall_m2: number; ceiling_m2: number; molding_m: number; base_m: number; doors: number; [k: string]: unknown };
export type Quote = {
  inp: { py: number; area_m2: number; measured: Measured | null; occupied: boolean; balcony: boolean; grade: string; mok: string[]; doors: number; doors_auto?: { n: number; how: string }; assumed: string[] };
  precise: Precise[];
  ref: RefTrade[];
  missing: string[];
  supply: number;
  vat: number;
  total: number;
  rlo: number;
  rhi: number;
  all_lo: number;
  all_hi: number;
  code: string;
  at: string;
  band: { lo: number; hi: number } | null;
  /** 산식 · 단가 버전 (없으면 v10 값으로 보인다) */
  formula_version?: string;
  price_ver?: string;
};

/** 공통 입력 MvpV2QuoteIn (API.md) */
export function quoteBody() {
  const cats = scopeCats().map((c) => c.id);
  const pl = S.plan;
  const kinds = pl?.kind === "apt" ? ((F.pp9Kinds?.() as string[] | null | undefined) ?? null) : null;
  return {
    pyeong: S.info.pyeong,
    living: S.info.living,
    cats,
    picks: S.picks,
    plan: pl?.kind === "apt" && pl.id ? { id: pl.id, expanded: pl.expanded !== false, kinds, spaces: kinds ? S.scope.spaces : null } : null,
    balcony: V3.balcony,
    mok: S.mok10 ?? null,
    tier: S.tier,
  };
}
export type QuoteIn = ReturnType<typeof quoteBody>;
export const fetchQuote = () => v2Post<Quote>("quote", quoteBody());

/* ---------- 공정표 (POST /mvp/v2/plan = v10 buildPlan: planTrades · defaultStart · fixPlan) ---------- */
export type PlanTrade = { trade: string; ko: string; steps: Step[]; crew: number; fixed: { start: string } | null; state: "confirmed" | "pending" | "expected"; need: number };
export type Block = { trade: string; ko: string; kind: "work" | "dry" | "clean"; start: string; end: string; days: number; crew?: number | null; state: string };
export type PlanDay = { date: string; off: boolean; holiday: string | null; items: { trade: string; ko: string; todo: string[] }[] };
export type Trial = {
  trade: string;
  start: string;
  end: string;
  /** 이 날짜로 하면 밀리는 공정 */
  moved: { trade: string; ko: string; start: string }[];
  /** 다른 공정의 수락한 날짜와 겹침 */
  clash: boolean;
  /** 업체 날짜 검사 문구 (내일부터 · 끝 ≥ 시작 · 120일 · 일하는 날) */
  error: string | null;
  work_days: number;
  need: number;
  /** 필요한 기간보다 짧음 */
  short: boolean;
};
export type Plan = {
  start: string;
  end: string;
  blocks: Block[];
  days: PlanDay[];
  work_days: number;
  warn: string[];
  trades: PlanTrade[];
  today?: string;
  tomorrow?: string;
  /** 업체 답 기한: 오늘 + 1일 18:00 (v10 CALC.dueAt) */
  due_next?: string;
  trial?: Trial | null;
};

export type Prop = { start: string; end: string; crew: number; reason: string | null; change: boolean };
export type Accepted = { start: string; end: string };
export const props = () => V3.props as Record<string, Prop>;
export const accepted = () => V3.accepted as Record<string, Accepted>;

/** MvpV2PlanIn: 견적 입력 + 입주 희망 + 조건(V3.cons 그대로) + 업체가 낸 날짜 · 수락한 날짜 (+ 미리 보기 trial) */
export function planBody(trial: { trade: string; start: string; end: string } | null = null) {
  return {
    quote: quoteBody(),
    move: S.info.move || "",
    cons: V3.cons,
    props: Object.fromEntries(Object.entries(props()).map(([k, v]) => [k, { start: v.start, end: v.end, crew: v.crew }])),
    accepted: accepted(),
    trial,
  };
}
export const fetchPlan = (trial: { trade: string; start: string; end: string } | null = null) => v2Post<Plan>("plan", planBody(trial));

/* ---------- 업체 가견적 (v10 estimateFor: 업체 단가 × 이 집 표준 수량) ---------- */
export type Estimate = { ok: true; supply: number; vat: number; total: number; pct: number | null } | { ok: false; why: string };
export const fetchEstimate = (t: Precise, prices: Record<string, number | undefined>) =>
  v2Post<Estimate>("estimate", { trade: t.trade, grade: t.grade ?? null, lines: t.lines.map((l) => ({ key: l.key, name: l.name, qty: l.qty, state: l.state })), prices, std_total: t.total });

/* ---------- 업체 실측 견적서 요약 칸 (v10 CALC.fromEntered + percentVs) ---------- */
export type VatMode = "excluded" | "included" | "exempt";
export type Entered = { supply: number; vat: number; total: number; pct: number | null };
export const fetchEntered = (amount: number, mode: VatMode, std_total: number | null) => v2Post<Entered>("entered", { amount, mode, std_total });

/* ---------- 받은 견적 맞춰 보기 (POST /mvp/v2/check = v10 quoteCheck go() 숫자 부분 + 범위 막대) ---------- */
export type CheckReq = {
  quote: QuoteIn;
  trade: string;
  amount: number;
  mode: "unknown" | "excluded" | "included";
  /** 도배: ceiling · removal · moving / 목공: casing9 · removal · etc · extras({key: 곳 수}) */
  scope: { ceiling?: boolean; removal?: boolean; moving?: boolean; casing9?: boolean; etc?: boolean; extras?: Record<string, number> };
};
export type CheckRes = {
  warn: string | null;
  trade: string;
  supply: number | null;
  lo: number | null;
  hi: number | null;
  where: "low" | "in" | "high" | null;
  pct: number | null;
  head: string | null;
  notes: string[] | null;
  why: string[] | null;
  vat_unknown: boolean | null;
  bar: { band_left: number; band_width: number; me: number } | null;
};
export const fetchCheck = (b: CheckReq) => v2Post<CheckRes>("check", b);

/** 받은 견적 맞춰 보기 목공 추가 항목 칸 (GET /mvp/v2/market-extras = v10 MARKET.P.mokgong.extras) */
export type MarketExtra = { key: string; name: string; per: "곳" | "식"; lo: number; hi: number; n: number };
let extras: Promise<MarketExtra[]> | null = null;
export function marketExtras() {
  if (!extras)
    extras = v2Get<MarketExtra[]>("market-extras").catch((e) => {
      extras = null;
      throw e;
    });
  return extras;
}

/* ---------- 목공 자재 처음 값 (이미 있는 GET /mvp/materials) ---------- */
type Mats = { products: { id: string; kind: string }[]; grades: Record<string, { molding_type: string; molding: string; base: string; leaf: string; door_set: string }> };
let mats: Promise<Mats> | null = null;
export function materials() {
  if (!mats) mats = mvpGet<Mats>("materials").catch((e) => {
    mats = null;
    throw e;
  });
  return mats;
}
