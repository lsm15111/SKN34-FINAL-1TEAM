// 백과의 가벼운 값(글 · 용어 데이터 없이). 브라우저 조각(찾기 창 · 단추)은 여기만 불러서 데이터가 묶이지 않아요.
import type { TradeKey } from "./types";

export const TRADE_LABEL: Record<TradeKey, string> = { dobae: "도배", mokgong: "목공", common: "공통", oos: "다른 공정" };
export const TRADE_ORDER: TradeKey[] = ["dobae", "mokgong", "common", "oos"];
export const IMG_NOTE = "AI로 그린 이해용 그림이라 실제 자재 · 시공과 다를 수 있어요";
/** 글을 근거와 맞춰 본 때 */
export const CHECKED = "2026년 11월 확인";
/** 찾기 창 · AI 채팅 창을 여는 신호(백과 화면 어디서나) */
export const FIND_EVENT = "mj:guide-find";
export const ASK_EVENT = "mj:guide-ask";
/** 찾기 창 맨 앞 '많이 찾는 용어' · 첫 화면 그림 카드 */
export const POPULAR = ["퍼티", "초배", "천장 몰딩", "걸레받이"];

export const termHrefId = (id: string, from = "/guide/terms") => `${from}?term=${encodeURIComponent(id)}`;
export const articleHref = (slug: string) => `/guide/${slug}`;

/** 찾기 창이 받는 가벼운 목록(/guide/search-index) */
export type SearchIndex = {
  terms: { id: string; term: string; aliases: string[]; easy: string; trade: TradeKey; img?: string }[];
  articles: { slug: string; title: string; lead: string; heads: string[] }[];
  faq: { id: string; q: string; a: string }[];
};
