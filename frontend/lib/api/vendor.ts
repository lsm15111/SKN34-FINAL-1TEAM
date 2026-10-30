// 서버 쪽 읽기: 업체 목록 · 상세 · 추천. 지금은 예시 데이터.
import { RECOMMEND, VENDORS } from "@/lib/mock/data";
import type { Trade, Vendor } from "@/lib/types";

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
