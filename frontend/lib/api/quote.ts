// 서버 쪽 읽기: 가견적. 후보 업체 · 받는 길 · 보낸 요청 · 업체 받은편지함은 실제 API,
// 표준견적서 · 가견적 · 비교 · 실측 견적은 아직 예시 데이터(예시 프로젝트 p1).
import { serverGet, type Schemas } from "@/lib/backend/server";
import { FX, QUOTE_REQUESTS } from "@/lib/mock/data";
import type { Trade } from "@/lib/types";

export type Sourcing = Schemas["SourcingOut"];
export type SentRequest = Schemas["SentRequestOut"];
export type InboxItem = Schemas["InboxItemOut"];

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** 가견적 후보 업체와 받는 길. 없거나 남의 것이면 null, 잠시 못 읽으면(요청 제한 · 서버 오류) "error" */
export async function getSourcing(projectId: string): Promise<Sourcing | null | "error"> {
  if (!UUID.test(projectId)) return null;
  try {
    return await serverGet<Sourcing>(`/projects/${projectId}/sourcing`);
  } catch (e) {
    console.error("가견적 후보를 읽지 못했어요", e instanceof Error ? e.message : e);
    return "error";
  }
}
/** 이 프로젝트에서 앱 업체에 보낸 가견적 요청과 상태 (새 것부터) */
export async function getSentRequests(projectId: string) {
  return UUID.test(projectId) ? ((await serverGet<SentRequest[]>(`/projects/${projectId}/quote-requests`)) ?? []) : [];
}
/** 승인 업체가 받은 가견적 요청. 승인 전이면 null */
export async function getVendorInbox() { return serverGet<InboxItem[]>("/vendor/quote-requests"); }

export async function getStandardQuote(_projectId: string) { return { ...FX.standard, createdAt: "2026-10-20" }; }
export async function getQuoteRequests(projectId: string) { return QUOTE_REQUESTS[projectId] ?? []; }
export async function getVendorQuotes(_projectId: string, trade: Trade) { return FX.quotes[trade]; }
export async function getCompare(_projectId: string, trade: Trade) { return FX.compare[trade]; }
export async function getFinalQuote(_projectId: string, trade: Trade) { return FX.finals[trade]; }
