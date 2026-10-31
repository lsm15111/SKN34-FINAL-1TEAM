// 서버 쪽 읽기: 업체 정보 관리(승인 업체 본인)는 실제 API, 업체 목록 · 상세 · 추천은 아직 예시 데이터.
import { serverGet, type Schemas } from "@/lib/backend/server";
import { RECOMMEND, VENDORS } from "@/lib/mock/data";
import type { Trade, Vendor } from "@/lib/types";

export type VendorProfile = Schemas["VendorProfileOut"];

/** 승인 업체 본인의 업체 정보. 승인 전이거나 권한이 없으면 null, 잠시 못 읽으면 "error" */
export async function getVendorProfile(): Promise<VendorProfile | null | "error"> {
  try {
    return await serverGet<VendorProfile>("/vendor/profile");
  } catch (e) {
    console.error("업체 정보를 읽지 못했어요", e instanceof Error ? e.message : e);
    return "error";
  }
}

export async function getRecommendations(_projectId: string, trade: Trade) { return RECOMMEND[trade]; }

export type VendorQuery = { trade: Trade; region?: string; q?: string; sort?: "reviews" | "rating" | "cases" };
export async function listVendors({ trade, region, q, sort = "reviews" }: VendorQuery) {
  let list = VENDORS.filter((v) => v.trades.includes(trade) && v.status === "active");
  if (region) list = list.filter((v) => v.areas.includes(region));
  if (q?.trim()) list = list.filter((v) => v.name.includes(q.trim()));
  const key: Record<string, (v: Vendor) => number> = { reviews: (v) => v.reviews, rating: (v) => v.rating, cases: (v) => v.portfolio.length };
  return [...list].sort((a, b) => key[sort](b) - key[sort](a));
}
export async function getVendor(id: string) { return VENDORS.find((v) => v.id === id) ?? null; }
export async function listAllVendors() { return VENDORS; }

export async function vendorName(id: string) { return VENDORS.find((v) => v.id === id)?.name ?? id; }
export const ALL_REGIONS = Array.from(new Set(VENDORS.flatMap((v) => v.areas))).sort((a, b) => a.localeCompare(b, "ko"));
