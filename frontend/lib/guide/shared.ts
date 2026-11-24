// 백과의 가벼운 값(글 · 용어 데이터 없이). 브라우저 조각(찾기 창 · 단추)은 여기만 불러서 데이터가 묶이지 않아요.
import type { TradeKey } from "./types";

export const TRADE_LABEL: Record<TradeKey, string> = { dobae: "도배", mokgong: "목공", common: "공통", oos: "다른 공정" };
export const TRADE_ORDER: TradeKey[] = ["dobae", "mokgong", "common", "oos"];
/** 글을 근거와 맞춰 본 때 */
export const CHECKED = "2026년 11월 확인";
/** 찾기 창 · AI 채팅 창을 여는 신호(백과 화면 어디서나) */
export const FIND_EVENT = "mj:guide-find";
export const ASK_EVENT = "mj:guide-ask";
/** 찾기 창 맨 앞 '많이 찾는 용어' · 첫 화면 그림 카드 */
export const POPULAR = ["퍼티", "초배", "천장 몰딩", "걸레받이"];

/** 용어 사전 화면에서 바로 여는 주소(백과 밖에서 링크할 때). 백과 안에서는 withTerm으로 보던 화면 위에 열어요 */
export const termHrefId = (id: string, from = "/guide/terms") => `${from}?term=${encodeURIComponent(id)}`;
export const articleHref = (slug: string) => `/guide/${slug}`;
/** 보던 화면 주소(path · 검색어)에 ?term=만 바꿔 붙여요. id가 없으면 ?term=만 빼요(용어 사전 갈래 같은 다른 검색어는 그대로) */
export function withTerm(path: string, search: string, id?: string): string {
  const p = new URLSearchParams(search);
  if (id) p.set("term", id);
  else p.delete("term");
  const q = p.toString();
  return q ? `${path}?${q}` : path;
}

/** 찾기 창이 받는 가벼운 목록(/guide/search-index) */
export type SearchIndex = {
  terms: { id: string; term: string; aliases: string[]; easy: string; trade: TradeKey; img?: string }[];
  articles: { slug: string; title: string; lead: string; heads: string[] }[];
  faq: { id: string; q: string; a: string }[];
};
