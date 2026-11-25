// 서버 쪽 읽기: 프로젝트(내 공사 목록 · 보기 · 지역 목록) + v3 공사 한 건 머리(공사 띠 · 기본 정보 · 공정표 · 공사 전 할 일).
// 예시(lib/mock/v3a)는 개발에서 NEXT_PUBLIC_MJ_MOCK=1이고 예시 공사 id일 때만 써요. 그 밖에는 모두 실제 API예요.
import { cache } from "react";
import { serverGet } from "@/lib/backend/server";
import type { Schemas } from "@/lib/v5/types";
import { getCaps } from "@/lib/v5/caps";
import { v5Href } from "@/lib/v5/paths";
import type { BandTask } from "@/components/site/ProjectBand";
import { dueText } from "@/lib/v5/format";
import { ROOM_RULE_EMPTY, diyOfKeys, projectName, stepIndex, type DiyKey } from "@/lib/v5/guest/info";
import { mockKeyOf } from "@/lib/mock/v3a/mode";
import { MOCK_CHECKS, mockPlan, mockProject } from "@/lib/mock/v3a/project";
import { SIDO } from "@/lib/mock/regions";

export type ApiProject = Schemas["ProjectOut"];
export type ApiProjectItem = Schemas["MyProjectOut"];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** API가 받는 프로젝트 id 모양인지 (아니면 부르지 않고 없는 것으로 본다) */
export const isUuid = (id: string) => UUID.test(id);
const seg = (id: string) => encodeURIComponent(id);

export async function listMyProjects() { return (await serverGet<ApiProjectItem[]>("/projects")) ?? []; }
/** 내 프로젝트(또는 관리자). 없거나 남의 것이면 null. 한 요청 안에서는 한 번만 부른다(레이아웃과 화면이 같이 써도). */
export const getMyProject = cache(async (id: string) => (UUID.test(id) ? serverGet<ApiProject>(`/projects/${seg(id)}`) : null));

/** 고른 직접 할 일(반셀프 칩): 모은 조건(GET /projects/{id}/conditions)의 diy.* 줄. 아직 안 물었거나 못 읽으면 null, '없어요'면 [].
 *  기본 정보(HomeInfoOut)에는 이 칸이 없어서 따로 읽어요 */
export async function getDiy(id: string): Promise<DiyKey[] | null> {
  // dev 백엔드에는 모은 조건이 없어요(기능 확인이 꺼지면 묻지 않아요)
  if (!isUuid(id) || !(await getCaps()).v4) return null;
  const rows = await serverGet<Schemas["ConditionOut"][]>(`/projects/${seg(id)}/conditions`).catch(() => null);
  return rows ? diyOfKeys(rows.map((r) => r.key)) : null;
}

/** 견적 받기 지역 고르기: 시 · 도 → 시 · 군 · 구 (GET /regions) */
export type Region = { id: string; name: string; full: string; groups: { label: string; prefix: string; items: string[] }[] };
export async function listRegions() { return (await serverGet<Region[]>("/regions")) ?? []; }

/** 기본 정보(C02) 지역 목록. API가 비었거나 못 읽으면 같은 행정구역 표(backend shared/regions.py와 같은 자료)를 써요 */
export async function getRegions(): Promise<Region[]> {
  const fallback = SIDO.map((s) => ({ ...s, groups: s.groups.map((g) => ({ label: g.label ?? "", prefix: g.prefix, items: g.items })) }));
  try {
    const r = await listRegions();
    return r.length ? r : fallback;
  } catch {
    return fallback;
  }
}

/** 방 개수 칸 범위 · 평형 기본값 표(GET /guest/room-rule). 못 읽으면 칸 범위만(기본값 3개) */
export async function getRoomRule(): Promise<Schemas["RoomRuleOut"]> {
  if (!(await getCaps()).v4) return ROOM_RULE_EMPTY;
  try {
    return (await serverGet<Schemas["RoomRuleOut"]>("/guest/room-rule")) ?? ROOM_RULE_EMPTY;
  } catch {
    return ROOM_RULE_EMPTY;
  }
}

/** 공사 희망 시기 칩(이번 달 · 다음 달 · 2~3달 뒤 → 계산 엔진 날짜, GET /guest/start-options). 못 읽으면 빈 목록(아직 몰라요 · 날짜 고르기만) */
export async function getStartWishes(): Promise<Schemas["StartWishOut"][]> {
  // 기능 확인과 같은 요청(GET /guest/start-options)이에요. 꺼져 있으면 빈 목록
  return (await getCaps()).wishes;
}

// ───── v3 공사 한 건 머리

export type HomeSaved = Schemas["HomeInfoOut"];
/** 표준견적서 '이 조건으로 계산했어요' 줄에 쓰는 값(v2로 만든 공사는 옛 칸에서 모아요) */
export type Condition = { scope: "full" | "partial"; spaces: string[]; faces: string[]; area_m2: string; area_basis: string; grade: string | null; occupied: boolean; rooms?: number | null };

export type ProjectShell = {
  id: string;
  /** '상계동 아파트 도배' */
  name: string;
  region: string;
  locked: boolean;
  home: HomeSaved | null;
  cond: Condition | null;
  budgetWon: number | null;
  /** 단계 띠 지금 단계(0부터) · 실측 뒤 작은 단계(없으면 null) */
  current: number;
  sub: number | null;
  todo: BandTask[];
  waiting: BandTask[];
  /** 예시 공사(개발 미리 보기) */
  mock: boolean;
};

/** 6단계마다 가는 곳(단계 띠 · 한 공사 화면) */
export const stepLinks = (id: string) => [`/v5/start?edit=${id}`, `/v5/projects/${id}/standard`, `/v5/projects/${id}/vendors`, `/v5/projects/${id}/visits`, `/v5/projects/${id}/visits`, `/v5/projects/${id}`];

/** 사이트 안 경로만 링크로 둬요(서버가 준 dev 고객 흐름 주소는 v5 주소로) */
const safeHref = (v: string | null | undefined) => (v && v.startsWith("/") && !v.startsWith("//") && !v.includes("\\") ? v5Href(v) : undefined);

/** 업체마다 다음 할 일(고객 차례면 할 일, 업체 차례면 기다림) */
const CUSTOMER_NEXT: Record<string, string> = { pick: "날짜 고르기", proposal: "제안한 날 고르기", change: "일정 바꾸기 답하기", visit: "실측 받았는지 알려 주기", confirm: "견적서 보고 확정" };
const VENDOR_NEXT: Record<string, string> = { reply: "답 기다림", accept: "수락 기다림", change: "일정 바꾸기 답 기다림", quote: "견적서 기다림", visit: "실측 기다림" };

function bandOf(id: string, item: ApiProjectItem | undefined): Pick<ProjectShell, "current" | "todo" | "waiting"> {
  const todo: BandTask[] = [];
  const waiting: BandTask[] = [];
  for (const v of item?.vendors ?? []) {
    const due = v.next.due_at ? dueText(v.next.due_at) : undefined;
    if (v.next.who === "customer" && CUSTOMER_NEXT[v.next.kind]) {
      const href = v.next.kind === "pick" || v.next.kind === "proposal" ? `/v5/projects/${id}/visits/${seg(v.visit_id)}` : v.next.kind === "confirm" ? `/v5/projects/${id}/quotes` : `/v5/projects/${id}/visits`;
      todo.push({ label: `${v.vendor_name} ${CUSTOMER_NEXT[v.next.kind]}`, href, due });
    } else if (v.next.who === "vendor" && VENDOR_NEXT[v.next.kind]) {
      waiting.push({ label: `${v.vendor_name} ${VENDOR_NEXT[v.next.kind]}`, due });
    }
  }
  if (!todo.length && item?.todo) {
    const t = item.todo;
    todo.push({ label: t.action || t.text, href: safeHref(t.link) });
  }
  return { current: stepIndex(item?.current), todo, waiting };
}

/** 홈 '진행 중' 띠: 고객이 지금 할 일(없으면 업체를 기다리는 일)과 지금 단계(0부터) */
export function nextOf(item: ApiProjectItem): { task: BandTask | null; waiting: boolean; current: number } {
  const b = bandOf(item.id, item);
  if (b.todo[0]) return { task: b.todo[0], waiting: false, current: b.current };
  return { task: b.waiting[0] ?? null, waiting: !!b.waiting[0], current: b.current };
}

type Overview = Schemas["OverviewOut"];
const getOverviewOf = cache(async (id: string) => (isUuid(id) ? serverGet<Overview>(`/projects/${seg(id)}/overview`).catch(() => null) : null));

/** 공사 한 건 머리(레이아웃 · 화면이 같이 써요, 한 요청에 한 번). 없거나 남의 공사면 null */
export const getProjectShell = cache(async (id: string): Promise<ProjectShell | null> => {
  const k = mockKeyOf(id);
  if (k) {
    const m = mockProject(k);
    const h = m.home;
    const cond: Condition = { scope: h.scope, spaces: h.spaces, faces: h.faces, area_m2: String(h.area_m2), area_basis: h.area_basis, grade: h.grade, occupied: h.occupied };
    return { id, name: m.name, region: m.region, locked: m.locked, home: h, cond, budgetWon: h.budget_won, current: m.current, sub: m.after ?? null, todo: m.todo.map((t) => ({ ...t, href: safeHref(t.href) })), waiting: [], mock: true };
  }
  if (!isUuid(id)) return null;
  const [p, list] = await Promise.all([getMyProject(id), listMyProjects().catch(() => [] as ApiProjectItem[])]);
  if (!p) return null;
  const item = list.find((x) => x.id === p.id);
  const trades = (["dobae", "mokgong"] as const).filter((t) => p.trades[t]);
  const h = p.home ?? null;
  const cond: Condition | null = h
    ? { scope: h.scope, spaces: h.spaces, faces: h.faces, area_m2: String(h.area_m2), area_basis: h.area_basis, grade: h.grade, occupied: h.occupied, rooms: h.rooms }
    : p.size.m2
      ? { scope: "full", spaces: [], faces: ["wall", "ceiling"], area_m2: String(p.size.m2), area_basis: p.size.basis ?? "supply", grade: p.trades.dobae?.grade ?? null, occupied: p.occupied }
      : null;
  const band = bandOf(p.id, item);
  let sub: number | null = null;
  if (band.current === 5) {
    const at = (await getOverviewOf(p.id))?.after_steps.findIndex((st) => st.state === "now") ?? -1;
    sub = at >= 0 ? at : null;
  }
  return {
    id: p.id, name: projectName(h?.emd ?? p.emd ?? item?.emd, p.region, trades), region: p.region, locked: p.locked,
    home: h, cond, budgetWon: h?.budget_won ?? p.budget_won ?? null, ...band, sub, mock: false,
  };
});

export type ApiPlan = Schemas["PlanOut"];
/** 공정표(GET /projects/{id}/plan): 수락한 공사 날짜가 있으면 확정, 없으면 예상. 남의 것이면 null */
export async function getPlanView(id: string): Promise<ApiPlan | null> {
  const k = mockKeyOf(id);
  if (k) return mockPlan(k);
  return isUuid(id) ? serverGet<ApiPlan>(`/projects/${seg(id)}/plan`) : null;
}

export type ApiCheck = Schemas["ProjectCheckOut"];
/** 공사 전 할 일(한 공사 화면 API 값) */
export async function getChecks(id: string): Promise<ApiCheck[]> {
  if (mockKeyOf(id)) return MOCK_CHECKS;
  return (await getOverviewOf(id))?.checks ?? [];
}
