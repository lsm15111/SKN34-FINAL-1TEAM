// 상담 API가 생기면 바꾸는 예시 데이터. 발표 자료의 '묻기' 장면 4개(시작 안내 · 도배 상담 · 두 공정 · 견적 설명)와
// 입력한 말로 장면을 고르는 낱말 맞추기. 금액 · 수량은 여기 두지 않는다(견적 설명은 저장된 표준견적서에서 읽는다).

export type Scene = "guide" | "dobae" | "both" | "price";
export type Reply = Scene | "out" | "none";

/** 창을 열면 보이는 질문 칩 */
export const ASK_CHIPS: { scene: Scene; q: string }[] = [
  { scene: "guide", q: "도배랑 목공만 하려면 뭐부터 해요?" },
  { scene: "dobae", q: "작은방 도배만 새로 하고 싶어요" },
  { scene: "both", q: "거실 몰딩 바꾸고 도배도 새로 하려는데, 뭘 먼저 정해야 해요?" },
  { scene: "price", q: "천장 몰딩 설치는 왜 이 금액이에요?" },
];

/** 답 머리 이름 */
export const WHO: Record<Reply, string> = {
  guide: "자동 답변 · 시작 안내",
  dobae: "자동 답변 · 도배",
  both: "자동 답변 · 목공 · 도배",
  price: "자동 답변 · 목공",
  out: "자동 답변",
  none: "자동 답변",
};

export const INTRO = "궁금한 공사 질문을 적어 보내거나 아래 질문을 눌러 보세요.";
export const MORE = "다른 질문도 눌러 볼 수 있어요";
const AFTER_VISIT = "실측 후";
export const NO_ROOM = "정하지 않았어요";
export const CARD_TITLE = "이렇게 정리했어요";

/** 1. 시작 안내 */
export const GUIDE = {
  lead: "이 순서로 준비하면 돼요.",
  steps: [
    "관리사무소 공사 신고 · 이웃 동의서",
    "예상 공정표로 순서 확인 (목공 → 도배)",
    "표준견적서로 기준 금액 확인",
    "업체 고르기에서 가견적 비교 · 실측 요청",
  ],
  // 공사 화면이면 그 공사의 화면으로, 아니면 견적 받기 · 내 공사로 보낸다
  acts: [
    { sub: "standard", label: "표준견적서 보기" },
    { sub: "plan", label: "예상 공정표 보기" },
  ],
  actsNoProject: [
    { href: "/start", label: "견적 받기" },
    { href: "/my", label: "내 공사 보기" },
  ],
};

/** 2. 도배 상담 · 기존 벽지 */
export type Wall = "strip" | "overlay" | "unknown";
export const WALL: { v: Wall; label: string; sum: string; say: string }[] = [
  { v: "strip", label: "뜯고 새로", sum: "뜯고 새로", say: "기존 벽지를 뜯고 새로 붙이는 걸로 정리했어요. 뜯는 양은 실측 때 업체가 보고 확인해요." },
  { v: "overlay", label: "덧바름", sum: "덧바름", say: "잘 붙어 있는 벽지면 위에 덧바를 수 있어요. 들뜬 곳이 보이면 실측 때 업체가 알려 줘요." },
  { v: "unknown", label: "모르겠어요", sum: AFTER_VISIT, say: "들뜬 곳이 있으면 뜯는 게 좋아요. 실측 때 업체가 보고 정하도록 ‘실측 후’로 남겨 둘게요." },
];
export const DOBAE = {
  ask: "기존 벽지를 뜯고 새로 붙일까요, 위에 덧바를까요?",
  grade: "기본형",
};

/** 3. 두 공정 한 번에 */
export const BOTH = {
  working: "두 공정을 같이 보고 있어요.",
  workingTag: "만드는 중",
  progress: [
    { label: "목공 · 물어볼 것을 정했어요", done: true },
    { label: "도배 · 확인하고 있어요", done: false },
  ],
  waitMs: 1600,
  leadStrong: "목공을 먼저 하고 도배를 해요.",
  lead: "4가지만 알려 주세요.",
  send: "답 보내기",
  sent: "답을 보냈어요",
  done: "정리했어요. 목공이 끝나면 도배를 해요.",
  doneLater: "모르는 것은 실측 때 업체가 보고 정해요.",
  order: "목공 → 도배",
  missing: "아직 고르지 않았어요",
  badLen: "천장 몰딩 길이를 숫자로 적어 주세요. 예: 12.5",
  lenLabel: "천장 몰딩 길이(m)",
};

export type BothKey = "molding" | "base" | "wall" | "grade";
export type BothQ = { k: BothKey; label: string; short: string; choices: { v: string; label: string; sum: string }[] };
export const BOTH_QS: { trade: string; items: BothQ[] }[] = [
  {
    trade: "목공",
    items: [
      { k: "molding", label: "천장 몰딩 길이", short: "몰딩 길이", choices: [
        { v: "input", label: "직접 입력", sum: "" },
        { v: "unknown", label: "모르겠어요", sum: AFTER_VISIT },
      ] },
      { k: "base", label: "걸레받이도 바꿔요?", short: "걸레받이", choices: [
        { v: "yes", label: "네", sum: "바꿔요" },
        { v: "no", label: "아니요", sum: "그대로 둬요" },
      ] },
    ],
  },
  {
    trade: "도배",
    items: [
      { k: "wall", label: "기존 벽지는요?", short: "기존 벽지", choices: WALL.map(({ v, label, sum }) => ({ v, label, sum })) },
      { k: "grade", label: "도배 유형", short: "도배 유형", choices: [
        { v: "economy", label: "저가형", sum: "저가형" },
        { v: "basic", label: "기본형", sum: "기본형" },
      ] },
    ],
  },
];
/** 정리 카드에 쓰는 이름 */
export const BOTH_SUM: Record<BothKey, string> = { molding: "천장 몰딩 길이", base: "걸레받이", wall: "기존 벽지", grade: "도배 유형" };

/** 4. 견적 설명 (숫자는 저장된 표준견적서 줄에서 읽는다) */
export const PRICE = {
  lineKey: "molding",
  say: "천장 몰딩 길이에 1m당 표준 단가를 곱한 금액이에요. 길이는 실측 때 다시 재요.",
  calcTag: "믿집 계산",
  estimated: "평형으로 어림한 길이",
  basis: "근거",
  basisLink: "/legal#prices",
  loading: "표준견적서를 읽고 있어요.",
  noLine: "이 공사의 표준견적서에는 천장 몰딩 줄이 없어요.",
  noProject: "공사 화면에서 물어보면 그 공사의 표준견적서 금액으로 풀어 드려요.",
};

/** 맞는 장면이 없거나 범위 밖일 때 */
export const NONE_TEXT = "이 질문은 아직 답을 준비하지 못했어요. 아래 질문을 눌러 보거나 자주 묻는 질문을 확인해 주세요.";
export const OUT_TEXT = ["지금은 도배 · 목공만 도와드려요.", "바닥 · 욕실 · 전기 같은 공정은 아직 도와드리지 못해요."];

const ROOMS = ["작은방", "안방", "거실", "침실", "아이방", "드레스룸", "서재", "주방", "현관", "복도"];
const MOK = ["몰딩", "목공", "걸레받이"];
const DOB = ["도배", "벽지"];
const MONEY = ["금액", "가격", "얼마", "단가", "비싸", "비용"];
const START = ["뭐부터", "무엇부터", "순서", "시작", "처음", "준비"];
const OUT = ["바닥", "마루", "장판", "타일", "욕실", "화장실", "전기", "조명", "콘센트", "배선", "싱크", "샷시", "창호", "페인트", "보일러"];

/** 입력한 말로 장면을 고른다. 칩 문장은 그대로 맞춘다 */
export function pickReply(text: string): Reply {
  const t = text.replace(/\s+/g, "");
  const chip = ASK_CHIPS.find((c) => c.q.replace(/\s+/g, "") === t);
  if (chip) return chip.scene;
  const has = (words: string[]) => words.some((w) => t.includes(w));
  if (has(MONEY) && t.includes("몰딩")) return "price";
  if (has(OUT)) return "out";
  if (has(START) && !t.includes("몰딩") && !t.includes("걸레받이")) return "guide";
  if (has(MOK) && has(DOB)) return "both";
  if (has(DOB)) return "dobae";
  if (has(START)) return "guide";
  return "none";
}

/** 말에 나온 공간 이름. 없으면 null */
export function roomOf(text: string): string | null {
  return ROOMS.find((r) => text.includes(r)) ?? null;
}
