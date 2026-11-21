// 서버 쪽 읽기: 업체 본인(가입 심사 · 작업함 · 실측 요청 · 견적서 · 공사 · 업체 정보 · 단가 · 링크 · 리뷰).
// 예시 데이터 모드(lib/mock/v3c/mode.ts)면 API 대신 lib/mock/v3c/vendor.ts를 돌려줘요. 예시 ↔ 실제는 이 파일 안에서만 바꿔요.
// 금액 · 수량 · 날짜 · 기한은 API(계산 엔진) 값을 그대로 넘기고, 화면은 모양만 바꿔요.
import { redirect } from "next/navigation";
import { serverGet, type Schemas as S } from "@/lib/backend/server";
import { dateSeoul } from "@/lib/format";
import { MOCK } from "@/lib/mock/v3c/mode";
import { mockVendorSession } from "@/lib/mock/v3c/session";
import * as M from "@/lib/mock/v3c/vendor";
import { getSession, requireRole } from "@/lib/session";
import type { Session } from "@/lib/types";

// ───── 타입: API 계약(lib/backend/schema.d.ts, B1a 1단계) ─────
export type VendorApplicationMine = S["ApplicationOut"];
export type ProfileV3 = S["ProfileOut"];
export type PriceRowV3 = S["PriceRowV3Out"];
export type PricesV3 = S["PricesV3Out"];
export type VendorReviewLinks = S["ReviewLinkOut"][];
export type InboxRowV3 = S["InboxRowOut"];
export type VendorInboxPage = S["InboxPageOut"];
export type VendorInboxSummary = S["InboxSummaryOut"];
export type VendorVisitV3 = S["VendorVisitDetailOut"];
export type VendorSchedule = S["VendorScheduleOut"];
export type VendorQuoteBoard = S["QuoteBoardOut"];
export type JobV3 = S["JobOut"];
export type VendorJobLog = S["LogItemOut"][];
export type VendorReviews = S["VendorReviewsOut"];
export type InboxTab = "todo" | "waiting" | "sched" | "jobs" | "done" | "all";
export type InboxSort = "due" | "new";
/** GET /regions (시 · 도 → 시 · 군 · 구) */
export type Region = { id: string; name: string; full: string; groups: { label: string; prefix: string; items: string[] }[] };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** API가 받는 id 모양인지(아니면 부르지 않고 없는 것으로 봐요) */
export const isId = (v: string) => UUID.test(v);
const enc = encodeURIComponent;

type AppVariant = keyof typeof M.MOCK_APPLICATION;
const variant = (v?: string | null): AppVariant => (v === "pending" || v === "needs_info" || v === "rejected" ? v : "approved");

/** 예시 모드의 머리 알림 수 */
export const MOCK_UNREAD = 2;

// ───── 누가 보나 ─────
/** 업체만. 예시 모드에서 진짜 업체 세션이 없으면 예시 업체(마루와벽)로 봐요(?mock=pending|needs_info|rejected) */
export async function vendorGate(next: string, mockVariant?: string | null): Promise<Session> {
  if (MOCK) {
    const s = await getSession();
    return s?.role === "vendor" ? s : mockVendorSession(variant(mockVariant));
  }
  return requireRole("vendor", next);
}
/** 승인된 업체만 쓰는 화면. 승인 전이면 업체 홈(심사 상태)으로 보내요 */
export async function approvedVendorGate(next: string): Promise<Session> {
  const s = await vendorGate(next);
  if (s.vendorStatus !== "approved") redirect("/vendor");
  return s;
}
/** 화면이 기한 · '오늘 · 내일' 말을 만들 때 쓰는 지금 시각(서버 값). 예시 모드는 9판 화면의 '때'예요 */
export function vendorNow(screen: keyof typeof M.MOCK_NOW): string {
  return MOCK ? M.MOCK_NOW[screen] : new Date().toISOString();
}

// ───── 가입 심사 · 업체 정보 ─────
/** 내 가입 신청 · 심사 결과(승인 전에도) */
export async function getMyApplication(mockVariant?: string | null) {
  if (MOCK) return M.MOCK_APPLICATION[variant(mockVariant)];
  return serverGet<VendorApplicationMine>("/vendor/application");
}
/** 내 업체 정보(승인된 업체만, 아니면 null) */
export async function getMyProfile() {
  if (MOCK) return M.MOCK_PROFILE;
  return serverGet<ProfileV3>("/vendor/profile");
}
/** 도배 단가표 v3(1201~1209). 옛 v2 묶음만 있으면 needs_setup */
export async function getMyPricesV3(trade: "dobae"): Promise<PricesV3 | null> {
  if (MOCK) return M.MOCK_PRICES;
  const p = await serverGet<S["PricesOut"]>(`/vendor/prices?trade=${trade}`);
  return (p?.v3 as PricesV3 | null | undefined) ?? null;
}
/** 외부 리뷰 링크(3개까지 · 관리자 확인) */
export async function getReviewLinks(): Promise<VendorReviewLinks> {
  if (MOCK) return M.MOCK_REVIEW_LINKS;
  return (await serverGet<VendorReviewLinks>("/vendor/review-links")) ?? [];
}
/** 다니는 지역 고르기 */
export async function listRegions(): Promise<Region[]> {
  if (MOCK) return M.MOCK_REGIONS;
  return (await serverGet<Region[]>("/regions")) ?? [];
}

// ───── 작업함 · 일정 ─────
const EMPTY_PAGE: VendorInboxPage = { items: [], next_before: null };
const TABS5 = ["todo", "waiting", "sched", "jobs", "done"] as const;
function sortRows(items: InboxRowV3[], sort?: InboxSort): InboxRowV3[] {
  if (sort === "new") return [...items].sort((a, b) => b.received_at.localeCompare(a.received_at));
  if (sort === "due") {
    // 9판 V03 · D04처럼: 기한이 남은 줄을 가까운 순으로, 기한이 지난 줄 · 기한 없는 줄은 뒤로(예시 모드에서만 화면이 정렬해요)
    const key = (r: InboxRowV3) => (r.next?.overdue ? Number.MAX_SAFE_INTEGER - 1 : r.next?.due_at ? new Date(r.next.due_at).getTime() : Number.MAX_SAFE_INTEGER);
    return [...items].sort((a, b) => key(a) - key(b));
  }
  return items;
}
/** 작업함 줄. all(웹 '전체')은 다섯 탭을 이어 붙여요 */
export async function listVendorVisits(tab: InboxTab, sort?: InboxSort): Promise<VendorInboxPage> {
  if (MOCK) {
    // '전체'는 실제 모드처럼 탭마다 정렬해 이어 붙여요
    const items = tab === "all" ? TABS5.flatMap((t) => sortRows(M.MOCK_INBOX[t].items, sort)) : sortRows(M.MOCK_INBOX[tab].items, sort);
    return { items, next_before: null };
  }
  if (tab === "all") {
    const pages = await Promise.all(TABS5.map((t) => listVendorVisits(t, sort)));
    return { items: pages.flatMap((p) => p.items), next_before: null };
  }
  const qs = new URLSearchParams({ tab });
  if (sort) qs.set("sort", sort);
  return (await serverGet<VendorInboxPage>(`/vendor/visits?${qs.toString()}`)) ?? EMPTY_PAGE;
}
/** 탭별 수. 예시 모드 ?mock=first는 받은 요청이 없는 승인 첫날이에요 */
export async function getVisitSummary(mockVariant?: string | null) {
  if (MOCK) return mockVariant === "first" ? { ...M.MOCK_SUMMARY, todo: 0, waiting: 0, sched: 0, jobs: 0, done: 0 } : M.MOCK_SUMMARY;
  return serverGet<VendorInboxSummary>("/vendor/visits/summary");
}
/** 처음 할 일(V02)을 마쳤는지: 단가 = v3 확인 묶음 있음 · 업체 정보 = 한 번이라도 저장 · 링크 = 1개 이상 */
export async function getSetupDone(mockVariant?: string | null): Promise<{ prices: boolean; profile: boolean; links: boolean }> {
  if (MOCK && mockVariant === "first") return { prices: false, profile: false, links: false };
  const [p, prof, links] = await Promise.all([getMyPricesV3("dobae").catch(() => null), getMyProfile().catch(() => null), getReviewLinks().catch(() => [])]);
  return { prices: !!p && !p.needs_setup && !!p.confirmed_at, profile: !!prof?.updated_at, links: links.length > 0 };
}
/** 실측 요청 하나(내 요청이 아니면 null → 404) */
export async function getVendorVisit(vid: string) {
  if (!isId(vid)) return null;
  if (MOCK) return M.MOCK_VISITS[vid] ?? null;
  return serverGet<VendorVisitV3>(`/vendor/visits/${enc(vid)}`);
}
/** 일정 탭: 반나절별 확정 · 잡아 둠. API는 from ~ to(62일 안)가 꼭 있어야 해서 오늘(서울)부터 앞으로 한 달을 물어요.
 *  날짜 범위는 묻는 창일 뿐이고, 칸 · 날은 API가 준 그대로 그려요 */
const SCHEDULE_DAYS = 31;
export async function getVendorSchedule(now: string) {
  if (MOCK) return M.MOCK_SCHEDULE;
  const from = dateSeoul(now);
  const [y, m, d] = from.split("-").map(Number);
  const to = new Date(Date.UTC(y, m - 1, d + SCHEDULE_DAYS)).toISOString().slice(0, 10);
  return serverGet<VendorSchedule>(`/vendor/schedule?from=${from}&to=${to}`);
}

// ───── 실측 견적서 · 공사 ─────
export async function getQuoteBoard(vid: string) {
  if (!isId(vid)) return null;
  if (MOCK) return M.MOCK_VISITS[vid] ? { ...M.MOCK_QUOTE, visit_id: vid } : null;
  return serverGet<VendorQuoteBoard>(`/vendor/visits/${enc(vid)}/quote`);
}
export async function getVendorJob(did: string) {
  if (!isId(did)) return null;
  if (MOCK) return M.MOCK_JOBS[did] ?? null;
  return serverGet<JobV3>(`/vendor/jobs/${enc(did)}`);
}
export async function getVendorJobLog(did: string): Promise<VendorJobLog> {
  if (!isId(did)) return [];
  if (MOCK) return M.MOCK_JOB_LOG[did] ?? [];
  return (await serverGet<VendorJobLog>(`/vendor/jobs/${enc(did)}/log`)) ?? [];
}

// ───── 리뷰 ─────
export async function getVendorReviews(filter: "waiting" | "all"): Promise<VendorReviews | null> {
  if (MOCK) return { ...M.MOCK_REVIEWS, items: M.MOCK_REVIEWS.items.filter((r) => filter === "all" || r.waiting_reply) };
  return serverGet<VendorReviews>(`/vendor/reviews?filter=${filter}`);
}
