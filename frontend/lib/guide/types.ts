// 믿집 백과 데이터 모양. 글 · 용어는 정적 데이터(lib/guide/*.data.ts)이고 화면은 읽기만 해요.

export type TradeKey = "dobae" | "mokgong" | "common" | "oos";

export type TermImage = { src: string; kind: "입체 그림" | "단면 그림" | "예시 그림" | "그림" };
export type GuideSource = { title: string; publisher: string; url?: string };

export type Term = {
  /** 주소에 쓰는 이름(빈칸 → -) */
  id: string;
  term: string;
  /** 현장에서 부르는 말 */
  aliases: string[];
  trade: TradeKey;
  /** 쉬운 말 한 줄 */
  easy: string;
  tip: string;
  detail: string;
  use: string;
  /** 업체에 물어볼 말 */
  ask?: string;
  /** 믿집 1차 범위(도배 · 목공) 밖 공정 */
  oos?: true;
  images: TermImage[];
  sources: GuideSource[];
};

/** 본문 블록. 글 속 [[용어]]는 용어 칸으로 바뀌어요 */
export type Block =
  | { t: "p"; text: string }
  | { t: "steps"; items: { title: string; text: string }[] }
  | { t: "list"; items: string[] }
  | { t: "fig"; term: string; kinds: TermImage["kind"][]; caption: string };

export type Section = { id: string; title: string; blocks: Block[] };

export type Article = {
  slug: string;
  title: string;
  /** 결론 한 줄 */
  lead: string;
  /** 이 글에서 알 수 있어요 */
  learn: string[];
  sections: Section[];
  /** 놓치기 쉬운 것 */
  pitfall?: string;
  /** 믿집에서는 */
  mijip?: { text: string; link?: { label: string; href: string } };
  /** 확인할 것(업체에 물을 말) */
  checks: string[];
  /** 관련 용어(용어 사전 이름) */
  terms: string[];
  sources: GuideSource[];
  /** 근거 번호(지식 카드 · 요약). 화면에는 안 보여요 */
  refs: string[];
};

export type TopicKey = "start" | "dobae" | "mokgong" | "order" | "quote" | "contract" | "office" | "after";
