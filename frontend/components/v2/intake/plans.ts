// 예시 평면도(백엔드 /mvp/plans)와 도면 수량(/mvp/plans/{id}/qty) 읽기 · 기억 (v10 PLANS9 · CALC9.fromPlan 자리).
// 수량은 백엔드 계산 엔진이 만든다. 여기서는 받아 두고 보여 줄 글만 만든다.
import type { components } from "@/lib/backend/schema";
import { SPACES } from "../data";
import { mvpGet } from "../api";
import { S, touch } from "../store";

export type PlanBrief = components["schemas"]["MvpPlanBriefOut"];
export type PlanQty = components["schemas"]["MvpPlanQtyOut"];
export type PlanSpace = components["schemas"]["MvpPlanSpaceOut"];

/* 평형대(공급 평): 고객이 아는 말로 */
export const PP9_BANDS: [string, string][] = [["all", "전체"], ["20", "20평 안팎"], ["25", "24~26평"], ["30", "30평대 초반"], ["34", "34평 안팎"], ["40", "38평 이상"]];
export const pp9PyBand = (py: number) => (py < 23 ? "20" : py < 28 ? "25" : py < 32 ? "30" : py < 37 ? "34" : "40");
export const pp9Band = (p: PlanBrief) => pp9PyBand(p.supply_py);
export const pp9Title = (p: PlanBrief) => `${p.name} ${p.type}`;
export const pp9Area = (p: PlanBrief) => `전용 ${p.excl_m2 ?? "-"}㎡ · 공급 ${p.supply_py}평`;
export const pp9Sub = (p: PlanBrief) => [`방 ${p.rooms} · 욕실 ${p.baths}`, p.layout, p.year ? `${p.year}년 입주` : p.stage].filter(Boolean).join(" · ");
/* 상담 범위가 '일부만'이면 그 공간 종류만(거실 · 방 = 거실 · 방 · 복도 · 드레스룸) */
export const PP9_KINDS: Record<string, string[]> = { room: ["living", "room", "hall", "dress"], kitchen: ["kitchen"], entry: ["entry"], bath: ["bath"], window: [] };
export function pp9Kinds(): string[] | null {
  if (S.scope?.kind !== "part" || !S.scope.spaces?.length) return null;
  return [...new Set(S.scope.spaces.flatMap((sp) => PP9_KINDS[sp] || []))];
}
export const pp9ScopeKo = () => (pp9Kinds() ? SPACES.filter((x) => S.scope.spaces.includes(x.id)).map((x) => x.ko).join(" · ") + "만" : "집 전체");
/** 표시 형식만 (소수 한 자리까지) */
export const pp9Fmt = (n: number | string) => Number(n).toLocaleString("ko-KR", { maximumFractionDigits: 1 });
/* 입력한 평형에 맞는 띠를 먼저 */
export function pp9Guess() {
  const py = S.info?.pyeong;
  if (!py) return "all";
  return pp9PyBand(py);
}
/** 평형으로 고르는 대표 평면 (v10 planGuess) */
export function planGuess() {
  const py = S.info.pyeong;
  return py ? (py < 28 ? "p24" : py < 38 ? "p32" : "p40") : null;
}

/* ---------- 평면도 목록 ---------- */
export const plansState = { list: null as PlanBrief[] | null };
let plansP: Promise<PlanBrief[]> | null = null;
export function loadPlans(): Promise<PlanBrief[]> {
  if (plansState.list) return Promise.resolve(plansState.list);
  if (!plansP)
    plansP = mvpGet<PlanBrief[]>("plans").then(
      (ls) => {
        plansState.list = ls;
        return ls;
      },
      (e) => {
        plansP = null;
        throw e;
      },
    );
  return plansP;
}
export const planById = (id: string | undefined) => (id ? plansState.list?.find((p) => p.id === id) ?? null : null);

/* ---------- 도면 수량 (받은 값을 기억해 둔다) ---------- */
const qtyKey = (id: string, expanded: boolean, kinds: string[] | null, ceiling = true) =>
  `${id}|${expanded ? 1 : 0}|${kinds ? [...kinds].sort().join(",") : "*"}${ceiling ? "" : "|c0"}`;
const qtyCache = new Map<string, PlanQty>();
const failed = new Set<string>();
let loading: string | null = null;

export async function fetchQty(id: string, expanded: boolean, kinds: string[] | null, ceiling = true): Promise<PlanQty> {
  const key = qtyKey(id, expanded, kinds, ceiling);
  const hit = qtyCache.get(key);
  if (hit) return hit;
  const qs = new URLSearchParams({ expanded: String(expanded) });
  if (!ceiling) qs.set("ceiling", "false");
  for (const k of kinds || []) qs.append("kinds", k);
  const q = await mvpGet<PlanQty>(`plans/${encodeURIComponent(id)}/qty?${qs}`);
  qtyCache.set(key, q);
  failed.delete(key);
  return q;
}

/** 지금 고른 도면(S.plan)의 수량. 아직 안 받았으면 받아 오고(끝나면 touch) null을 돌려준다 */
function currentQty(): { p: PlanBrief; q: PlanQty } | null {
  if (S.plan?.kind !== "apt" || !S.plan.id) return null;
  const id = S.plan.id, expanded = S.plan.expanded !== false, kinds = pp9Kinds();
  const key = qtyKey(id, expanded, kinds);
  const p = planById(id), q = qtyCache.get(key);
  if (p && q) return { p, q };
  if (loading !== key && !failed.has(key)) {
    loading = key;
    Promise.all([loadPlans(), fetchQty(id, expanded, kinds)])
      .then(() => touch())
      .catch(() => failed.add(key))
      .finally(() => {
        if (loading === key) loading = null;
      });
  }
  return null;
}

const rollsOf = (q: PlanQty, kind: string) => q.rolls.find((r) => r.kind === kind)?.rolls ?? 0;

/** 고른 예시 도면의 수량 (v10 pp9Measured). 다른 작업자(자재 · 견적서)가 F.pp9Measured()로 읽는다 */
export function pp9Measured() {
  const c = currentQty();
  if (!c) return null;
  const { p, q } = c;
  return {
    py: p.supply_py,
    supply_m2: Number(p.supply_m2),
    m: {
      name: pp9Title(p) + (pp9Kinds() ? ` (${pp9ScopeKo()})` : ""),
      wall_m2: Number(q.wall_m2),
      ceiling_m2: Number(q.ceiling_m2),
      molding_m: Number(q.molding_m),
      base_m: Number(q.base_m),
      doors: q.doors,
    },
  };
}
/** 받은 수량 응답 그대로 (창 길이 windows_m 등이 필요할 때) */
export const pp9Qty = () => currentQty()?.q ?? null;

/** AI에 넘길 도면 수량 글 (v10 pp9Context) */
export function pp9Context() {
  const c = currentQty();
  if (!c) return null;
  const t = c.q;
  return `도면 수량(계산 엔진, 실측 전 어림): 벽 도배 ${+t.wall_m2}㎡ · 천장 ${+t.ceiling_m2}㎡ · 실크 ${rollsOf(t, "silk")}롤 · 합지 ${rollsOf(t, "hapji")}롤 · 몰딩 ${+t.molding_m}m · 걸레받이 ${+t.base_m}m · 방문 ${t.doors}개`;
}
export { rollsOf };

/** 처음부터: 받아 둔 수량 · 실패 기록을 비운다 (평면도 목록은 그대로) */
export function resetPlans() {
  qtyCache.clear();
  failed.clear();
  loading = null;
}
