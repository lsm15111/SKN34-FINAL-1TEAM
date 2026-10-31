// 서버 쪽 읽기: 프로젝트. 실제 API(내 프로젝트 목록 · 보기)와 예시 프로젝트(p1) 데이터.
// 견적 · 실측 API가 생기면 예시 부분을 하나씩 실제 호출로 바꾼다.
import { serverGet, type Schemas } from "@/lib/backend/server";
import { FX, HISTORY, PROJECTS, QUOTE_REQUESTS, VENDORS, VISITS } from "@/lib/mock/data";
import { TRADE_KEYS } from "@/lib/labels";
import type { Trade } from "@/lib/types";
import type { TradeLine } from "@/lib/trade-status";
import { md } from "@/lib/format";

export type ApiProject = Schemas["ProjectOut"];
export type ApiProjectItem = Schemas["ProjectListItem"];

/** 예시 프로젝트 id. 이 id만 예시 데이터로 보여 준다. */
export const isDemoProject = (id: string) => PROJECTS.some((p) => p.id === id);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function listMyProjects() { return (await serverGet<ApiProjectItem[]>("/projects")) ?? []; }
/** 내 프로젝트(또는 관리자). 없거나 남의 것이면 null */
export async function getMyProject(id: string) { return UUID.test(id) ? serverGet<ApiProject>(`/projects/${id}`) : null; }

export async function listDemoProjects() { return PROJECTS; }
export async function getProject(id: string) { return PROJECTS.find((p) => p.id === id) ?? null; }

export async function getHistory(projectId: string) { return HISTORY[projectId] ?? []; }

// ── 내 프로젝트 카드의 공정별 상태 (lib/trade-status.ts)

/** 실제 프로젝트: 견적 · 실측 API가 아직 없어서 모든 공정이 '업체 고르기' 단계다. 공정 순서는 화면 순서(TRADE_KEYS) */
export function realTradeLines(trades: string[]): TradeLine[] {
  return TRADE_KEYS.filter((t) => trades.includes(t)).map((trade) => ({ trade, stage: "choosing", text: "업체를 골라 가견적을 요청해요" }));
}

/** 예시 프로젝트: 예시 데이터의 요청 · 실측 · 확정 기록으로 단계를 정한다. */
export async function demoTradeLines(id: string): Promise<TradeLine[]> {
  const p = await getProject(id);
  if (!p) return [];
  const reqs = QUOTE_REQUESTS[id] ?? [];
  const visits = VISITS[id] ?? [];
  return (["dobae", "mokgong"] as Trade[]).filter((t) => p.trades[t]).map((t): TradeLine => {
    const conf = FX.confirmed[t];
    if (conf) return { trade: t, stage: "scheduled", text: `${md(conf.start)} ~ ${md(conf.end)} 공사` };
    if (FX.finals[t]) return { trade: t, stage: "final_arrived", text: `${VENDORS.find((v) => v.id === FX.finals[t].vendorId)?.name ?? ""} 실측 견적이 왔어요` };
    if (visits.some((v) => v.trade === t)) return { trade: t, stage: "visit_wait", text: "실측 견적을 기다려요" };
    const r = reqs.filter((x) => x.trade === t);
    const got = r.filter((x) => x.status !== "requested").length;
    if (got) return { trade: t, stage: "comparing", text: `${r.length}곳 중 ${got}곳 도착` };
    if (r.length) return { trade: t, stage: "estimate_wait", text: `${r.length}곳에 요청했어요` };
    return { trade: t, stage: "choosing", text: "업체를 골라 가견적을 요청해요" };
  });
}

/** 예시 프로젝트의 공사가 끝나는 날 (확정 공정표 마지막 날). 없으면 null */
export async function demoProjectEnd(_id: string): Promise<string | null> {
  const ends = (["dobae", "mokgong"] as Trade[]).map((t) => FX.confirmed[t]?.end).filter((e): e is string => !!e);
  return ends.length ? ends.sort().at(-1)! : null;
}
