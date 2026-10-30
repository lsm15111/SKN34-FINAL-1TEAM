// 서버 쪽 읽기: 표준견적서 · 가견적 요청 · 가견적 · 비교 · 실측 견적. 지금은 예시 데이터.
import { FX, QUOTE_REQUESTS } from "@/lib/mock/data";
import type { Trade } from "@/lib/types";

export async function getStandardQuote(_projectId: string) { return { ...FX.standard, createdAt: "2026-10-20" }; }
export async function getQuoteRequests(projectId: string) { return QUOTE_REQUESTS[projectId] ?? []; }
export async function getVendorQuotes(_projectId: string, trade: Trade) { return FX.quotes[trade]; }
export async function getCompare(_projectId: string, trade: Trade) { return FX.compare[trade]; }
export async function getFinalQuote(_projectId: string, trade: Trade) { return FX.finals[trade]; }
