// 믿집 백과: 글 · 용어 찾기, 첫 화면 갈래, 단계 안내 묶음. 서버 · 브라우저 어디서나 읽기만 해요.
import { FAQ_V3 } from "@/components/home/faq";
import { ARTICLES } from "./articles.data";
import { TERMS } from "./terms.data";
import { POPULAR, articleHref, termHrefId, type SearchIndex } from "./shared";
import type { Article, Term, TradeKey } from "./types";

export * from "./shared";

export { ARTICLES, TERMS };
export type { Article, Term, TradeKey };

/** 이 용어가 나오는 글 */
export const articlesWithTerm = (t: Term): Article[] => ARTICLES.filter((a) => a.terms.some((n) => termByName(n)?.id === t.id));

const byId = new Map(TERMS.map((t) => [t.id, t]));
const byName = new Map<string, Term>();
for (const t of TERMS) {
  byName.set(t.term, t);
  for (const a of t.aliases) if (!byName.has(a)) byName.set(a, t);
}
/** 용어 이름(현장에서 부르는 말도)으로 찾아요 */
export const termByName = (name: string): Term | undefined => byName.get(name.trim());
export const termById = (id: string): Term | undefined => byId.get(id);
export const termHref = (t: Term, from = "/guide/terms") => termHrefId(t.id, from);

const bySlug = new Map(ARTICLES.map((a) => [a.slug, a]));
export const articleBySlug = (slug: string): Article | undefined => bySlug.get(slug);

/** 글 속 [[용어]]를 글 · 용어 조각으로 나눠요. 용어집에 없는 이름은 그냥 글로 둬요 */
export type Piece = string | { term: Term; label: string };
export function pieces(text: string): Piece[] {
  const out: Piece[] = [];
  const re = /\[\[([^\]]+)\]\]/g;
  let at = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > at) out.push(text.slice(at, m.index));
    const t = termByName(m[1]);
    out.push(t ? { term: t, label: m[1] } : m[1]);
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}
/** 찾기 · 요약에 쓰는 맨 글(용어 표시를 뺌) */
export const plain = (text: string) => text.replace(/\[\[([^\]]+)\]\]/g, "$1");

/** 읽는 데 걸리는 시간(분). 한글 1분에 500자 안팎으로 셈해요 */
export function readMinutes(a: Article): number {
  let n = a.lead.length + a.learn.join("").length + (a.pitfall ?? "").length + (a.mijip?.text ?? "").length + a.checks.join("").length;
  for (const s of a.sections) {
    n += s.title.length;
    for (const b of s.blocks) {
      if (b.t === "p") n += b.text.length;
      else if (b.t === "list") n += b.items.join("").length;
      else if (b.t === "steps") n += b.items.reduce((k, i) => k + i.title.length + i.text.length, 0);
      else n += b.caption.length;
    }
  }
  return Math.max(2, Math.round(n / 500));
}

/** 첫 화면 '처음이에요'(순서대로 읽는 길) */
export const PATH: { title: string; href: string }[] = [
  { title: "인테리어는 이렇게 진행돼요", href: articleHref("how-it-goes") },
  { title: "믿집으로 하는 순서", href: "/guide/steps" },
  { title: "우리 집 정보 준비하기", href: articleHref("home-info") },
  { title: "표준견적서 읽기", href: articleHref("read-standard") },
  { title: "업체 고르고 실측 일정 잡기", href: articleHref("pick-vendor") },
  { title: "공사 중 · 끝난 뒤", href: articleHref("during-after") },
];

/** 첫 화면 '찾아볼래요' 주제. 글은 앞에서부터 읽어요 */
export type Topic = { key: string; label: string; desc: string; icon: "doc" | "box" | "calendar" | "info" | "lock" | "store" | "warn" | "chat"; slugs: string[]; href?: string };
export const TOPICS: Topic[] = [
  { key: "dobae", label: "도배", desc: "합지 · 실크 · 순서", icon: "doc", slugs: ["dobae-how", "dobae-hapji-silk", "dobae-care"] },
  { key: "mokgong", label: "목공", desc: "몰딩 · 문 · 천장", icon: "box", slugs: ["mokgong-molding", "mokgong-door", "mokgong-ceiling"] },
  { key: "order", label: "공사 순서", desc: "무엇부터 할까", icon: "calendar", slugs: ["work-order", "other-trades"] },
  { key: "quote", label: "견적서 읽기", desc: "줄 · 포함 상태", icon: "info", slugs: ["read-standard", "quote-kinds", "quote-missing"] },
  { key: "contract", label: "계약 · 잔금", desc: "계약 전 확인", icon: "lock", slugs: ["before-contract"] },
  { key: "office", label: "관리사무소", desc: "동의 · 공사 규칙", icon: "store", slugs: ["management-office", "living-during"] },
  { key: "after", label: "하자 · A/S", desc: "점검 · 접수", icon: "warn", slugs: ["defects", "disputes"] },
  { key: "faq", label: "자주 묻는 질문", desc: "견적 · 업체 · 실측", icon: "chat", slugs: [], href: "/faq" },
];
export const topicHref = (t: Topic) => t.href ?? articleHref(t.slugs.find((s) => bySlug.has(s)) ?? t.slugs[0]);
/** 글이 하나라도 있는 주제만(법령 확인 전 글은 빠져 있어요) */
export const visibleTopics = (): Topic[] => TOPICS.filter((t) => t.href || t.slugs.some((s) => bySlug.has(s)));

/** 글 왼쪽 목록 묶음(있는 글만 보여요) */
export const NAV_GROUPS: { title: string; slugs: string[] }[] = [
  { title: "처음이에요", slugs: ["how-it-goes", "home-info", "read-standard", "pick-vendor", "during-after"] },
  { title: "도배", slugs: ["dobae-how", "dobae-hapji-silk", "dobae-care"] },
  { title: "목공", slugs: ["mokgong-molding", "mokgong-door", "mokgong-ceiling"] },
  { title: "공사 순서", slugs: ["work-order", "other-trades"] },
  { title: "견적 · 계약", slugs: ["quote-kinds", "quote-missing", "before-contract"] },
  { title: "공사 중 · 끝난 뒤", slugs: ["management-office", "living-during", "defects", "disputes"] },
];

/** 단계 안내: 공사 화면의 6단계(lib/guest/info STEP_NAMES)와 같은 이름 · 순서예요 */
export type GuideStep = { name: string; desc: string; slugs: string[]; flow?: { label: string; or?: string }[] };
export const STEPS: GuideStep[] = [
  { name: "기본 정보", desc: "집 크기 · 방 · 공사 범위를 넣어요", slugs: ["home-info", "how-it-goes"] },
  { name: "표준견적서", desc: "공공 기준으로 계산한 참고 금액을 봐요", slugs: ["read-standard", "quote-missing"] },
  { name: "업체 담기", desc: "가견적을 견줘 실측 받을 업체를 담아요", slugs: ["pick-vendor", "quote-kinds"] },
  { name: "실측 일정", desc: "믿집이 업체와 실측 날짜를 맞춰요", slugs: ["pick-vendor", "living-during"] },
  { name: "실측", desc: "업체가 집을 보고 실측 견적서를 내요", slugs: ["quote-kinds", "quote-missing"] },
  {
    name: "실측 뒤", desc: "견적서를 견줘 업체를 확정하고 공사로 이어 가요",
    slugs: ["before-contract", "management-office", "work-order", "defects"],
    flow: [{ label: "견적서 비교" }, { label: "업체 확정", or: "다시 고르기" }, { label: "공사 날짜" }, { label: "공사" }, { label: "끝 확인" }],
  },
];

/** 많이 찾는 용어(있는 것만) */
export const popularTerms = (): Term[] => POPULAR.map((n) => termByName(n)).filter((x) => x !== undefined);

export function searchIndex(): SearchIndex {
  return {
    terms: TERMS.map((t) => ({ id: t.id, term: t.term, aliases: t.aliases, easy: t.easy, trade: t.trade, img: t.images[0]?.src })),
    articles: ARTICLES.map((a) => ({ slug: a.slug, title: a.title, lead: plain(a.lead), heads: a.sections.map((s) => s.title) })),
    faq: FAQ_V3.map((f) => ({ id: f.id, q: f.q, a: f.a })),
  };
}
