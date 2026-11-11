// v2 고정 자료 (v10 '고정 자료'를 그대로 옮김). 자재 · 스타일 사진 자료는 public/v2/data.json에서 읽는다.

export type Price = { min: number | null; max: number | null; unit: string; note: string; source: string; checked: string };
export type Material = {
  id: string;
  cat: string;
  tier: "economy" | "basic" | "premium";
  brand: string;
  name: string;
  spec: string;
  price: Price | null;
  styles: string[];
  color: string;
  desc: string;
  good: string;
  watch: string;
  url: string;
  img_mfg: string | null;
  img_mfg_src: string | null;
  img_free: string | null;
  img_free_credit: string | null;
  img_free_src: string | null;
  img_ai: string | null;
  ai_prompt: string;
  rank: number | null;
  tags: string[];
  life: string;
  options: unknown;
  trend_src?: string;
  trend_note?: string;
};
export type StyleData = {
  id: string;
  img_free?: string[];
  img_free_credit?: string[];
  img_free_src?: string[];
  img_mfg?: string | null;
  img_mfg_src?: string | null;
  img_mfg_page?: string | null;
  img_empty?: string | null;
  [k: string]: unknown;
};

export type Style = { id: string; ko: string; tag: string; pal: string[]; keys: string[]; fits: string; care: string };
export const STYLES: Style[] = [
  { id: "modern-white", ko: "모던 화이트", tag: "흰 벽과 밝은 바닥으로 넓어 보이는 집",
    pal: ["#F7F7F5", "#E4E5E2", "#BFC3C4", "#8E9396", "#2B2E30"], keys: ["무몰딩", "밝은 그레이 타일"],
    fits: "20~30평대 · 채광이 아쉬운 집", care: "흰 벽은 얼룩이 잘 보여요. 오염에 강한 실크나 도장이 좋아요." },
  { id: "natural-wood", ko: "내추럴 우드", tag: "밝은 오크와 린넨 톤의 따뜻한 집",
    pal: ["#EFE8DD", "#D8C7AE", "#C2A77F", "#B08A5E", "#5C4A3A"], keys: ["오크 마루", "베이지 벽"],
    fits: "아이 있는 집", care: "오크 톤 강마루로도 분위기가 충분히 나요." },
  { id: "hotel-gray", ko: "호텔식 그레이", tag: "차콜 톤과 간접조명으로 차분한 집",
    pal: ["#2F3236", "#4A4E53", "#6E7277", "#8B7B6B", "#C9C5BF"], keys: ["큰 포세린 타일", "월넛 패널"],
    fits: "30평대 이상", care: "어두운 색은 간접조명 자리를 목공 때 미리 잡아야 해요." },
  { id: "midcentury", ko: "미드센추리 웜", tag: "월넛 가구와 올리브 포인트의 집",
    pal: ["#F2EDE4", "#C9A27A", "#7A4E30", "#6B7A4B", "#B5643C"], keys: ["월넛 톤", "올리브 포인트 벽"],
    fits: "가구 · 소품을 좋아하는 집", care: "포인트 색은 한 면만, 페인트로 하면 바꾸기 쉬워요." },
  { id: "french-neutral", ko: "프렌치 뉴트럴", tag: "아이보리 벽과 몰딩으로 우아한 집",
    pal: ["#F6F1E8", "#E7DDCD", "#D6C8B2", "#C8B79E", "#8C7B66"], keys: ["웨인스코팅", "헤링본 마루"],
    fits: "30평대 이상", care: "웨인스코팅은 거실 한 면부터 해도 분위기가 나요." },
];

/* 공정: 2026-11-09 실제 견적서 공종 구분으로 검증(문 → 목공 · 중문 · 창호 · 필름 · 마감, 설비 → 욕실) */
export type Cat = { id: string; ko: string; what: string };
export const CATS: Cat[] = [
  { id: "wallpaper", ko: "도배", what: "벽 · 천장 벽지" },
  { id: "floor", ko: "바닥재", what: "마루 · 장판 · 데코타일" },
  { id: "tile", ko: "타일", what: "욕실 · 주방 · 현관 타일" },
  { id: "bath", ko: "욕실", what: "변기 · 세면대 · 수전 · 욕실장" },
  { id: "furniture", ko: "가구", what: "주방 · 상판 · 붙박이장 · 신발장" },
  { id: "carpentry", ko: "목공", what: "방문 · 몰딩 · 걸레받이 · 벽 패널" },
  { id: "film", ko: "필름", what: "문 · 몰딩 · 가구 · 현관문 겉면" },
  { id: "paint", ko: "도장", what: "벽 · 천장 · 문 페인트" },
  { id: "middoor", ko: "중문", what: "현관 중문" },
  { id: "light", ko: "조명", what: "조명 · 스위치 · 콘센트" },
  { id: "window", ko: "창호", what: "샷시 · 유리 · 현관문" },
  { id: "finish", ko: "마감", what: "도어록" },
];
export const CAT: Record<string, Cat> = Object.fromEntries(CATS.map((c) => [c.id, c]));
export const TIERS: Record<string, string> = { economy: "베이직", basic: "스탠다드", premium: "프리미엄" };
export const TIER_ORDER = ["economy", "basic", "premium"] as const;
export const TIER_NOTE: Record<string, string> = { economy: "합지 벽지 · 장판", basic: "실크 벽지 · 강마루", premium: "고급 실크 · 원목마루" };

/* 공사 순서: 한샘 리하우스 · 토스피드 · 아정당 안내와 맞춤. 전기는 배선(앞)과 조명 설치(뒤) 두 번 */
export const GUIDE = [
  { n: "철거", d: "2~3일", cats: [] as string[], t: "기존 마감 · 가구 · 욕실을 떼어 내요" },
  { n: "설비 · 창호", d: "2~4일", cats: ["window"], t: "배관 · 방수를 하고 샷시 · 현관문을 바꿔요" },
  { n: "전기 배선", d: "1~2일", cats: [], t: "콘센트 · 조명 자리를 옮겨요" },
  { n: "목공", d: "3~5일", cats: ["carpentry"], t: "천장 · 벽을 잡고 몰딩 · 문틀 · 방문을 달아요" },
  { n: "욕실 · 타일", d: "3~5일", cats: ["bath", "tile"], t: "타일을 붙이고 변기 · 세면대 · 수전을 달아요" },
  { n: "필름 · 도장", d: "2~3일", cats: ["film", "paint"], t: "문 · 몰딩에 필름을 붙이고 칠해요" },
  { n: "도배", d: "1~2일", cats: ["wallpaper"], t: "벽 · 천장에 벽지를 붙여요" },
  { n: "바닥재", d: "1~2일", cats: ["floor"], t: "마루 · 장판을 깔아요" },
  { n: "가구", d: "1~2일", cats: ["furniture"], t: "주방 · 붙박이장 · 신발장을 설치해요" },
  { n: "중문", d: "1일", cats: ["middoor"], t: "현관 중문을 달아요" },
  { n: "조명 · 마감", d: "1~2일", cats: ["light", "finish"], t: "조명 · 스위치 · 도어록을 달고 실리콘을 쏴요" },
  { n: "입주 청소", d: "1일", cats: [], t: "공사 먼지를 치워요" },
];
export const SPACES = [
  { id: "room", ko: "거실 · 방", cats: ["wallpaper", "floor", "carpentry", "film", "paint", "light"] },
  { id: "kitchen", ko: "주방", cats: ["furniture", "tile", "film", "light"] },
  { id: "bath", ko: "욕실", cats: ["bath", "tile", "light"] },
  { id: "entry", ko: "현관", cats: ["middoor", "tile", "finish"] },
  { id: "window", ko: "창호", cats: ["window"] },
];
/** 대표 평면(그림). svg는 v10 그대로 */
export const PLANS = [
  { id: "p24", ko: "20평대 · 2베이", sub: "방 2 · 욕실 1",
    svg: '<rect class="wall" x="4" y="4" width="152" height="92"/><line x1="70" y1="4" x2="70" y2="56"/><line x1="4" y1="56" x2="110" y2="56"/><line x1="110" y1="4" x2="110" y2="96"/><rect class="wet" x="110" y="62" width="46" height="34"/><text x="22" y="34">거실</text><text x="80" y="34">방</text><text x="24" y="80">주방</text><text x="120" y="34">방</text><text x="117" y="84">욕실</text>' },
  { id: "p32", ko: "30평대 · 3베이", sub: "방 3 · 욕실 2",
    svg: '<rect class="wall" x="4" y="4" width="152" height="92"/><line x1="44" y1="4" x2="44" y2="54"/><line x1="112" y1="4" x2="112" y2="54"/><line x1="4" y1="54" x2="156" y2="54"/><line x1="78" y1="54" x2="78" y2="96"/><rect class="wet" x="44" y="54" width="34" height="22"/><rect class="wet" x="122" y="64" width="34" height="32"/><text x="12" y="32">방</text><text x="66" y="32">거실</text><text x="124" y="32">안방</text><text x="12" y="80">방</text><text x="49" y="69">욕실</text><text x="88" y="84">주방</text><text x="128" y="84">욕실</text>' },
  { id: "p40", ko: "40평대 · 4베이", sub: "방 4 · 욕실 2",
    svg: '<rect class="wall" x="4" y="4" width="152" height="92"/><line x1="36" y1="4" x2="36" y2="50"/><line x1="70" y1="4" x2="70" y2="50"/><line x1="122" y1="4" x2="122" y2="50"/><line x1="4" y1="50" x2="156" y2="50"/><line x1="96" y1="50" x2="96" y2="96"/><rect class="wet" x="36" y="50" width="30" height="22"/><rect class="wet" x="126" y="66" width="30" height="30"/><text x="10" y="30">방</text><text x="44" y="30">방</text><text x="86" y="30">거실</text><text x="128" y="30">안방</text><text x="10" y="80">드레스</text><text x="40" y="65">욕실</text><text x="70" y="84">주방</text><text x="104" y="84">다용도</text><text x="130" y="88">욕실</text>' },
];
/* 상담 진행 칸. 지난 칸을 누르면 그 단계를 다시 연다 */
export const STEPS: [string, string][] = [["styles", "스타일"], ["info", "집 정보"], ["scope", "범위"], ["budget", "예산"], ["photo", "사진 · 도면"], ["materials", "자재"], ["quote", "견적서"], ["sched", "공정표"]];
export const STEP_INDEX: Record<string, number> = { welcome: 0, styles: 0, guide: 0, info: 1, scope: 2, budget: 3, photo: 4, plan: 4, materials: 5, done: 5, quote: 6, sched: 7 };

export const MODE_LABEL: Record<string, string> = { free: "무료 사진", mfg: "제조사 사진", ai: "AI 이미지" };
export const SORTS: Record<string, string> = { rec: "추천순", pop: "많이 쓰는 순", low: "낮은 가격순", high: "높은 가격순" };

/** 만 원 → "3,500만 원" · "1.2억 원" (표시만) */
export const manwon = (m: number) => (m >= 10000 ? (m / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 }) + "억 원" : m.toLocaleString("ko-KR") + "만 원");
/** 자재 가격대 글 (표시만) */
export function priceText(p: Price | null | undefined, withUnit = true) {
  if (!p || (p.min == null && p.max == null)) return "가격 확인 중";
  const big = Math.max(p.min || 0, p.max || 0) >= 1000000;
  const f = (n: number) => (big ? (n / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 }) + "만" : n.toLocaleString("ko-KR"));
  const a = p.min != null ? f(p.min) : null;
  const b = p.max != null ? f(p.max) : null;
  const r = a && b && a !== b ? `${a}~${b}원` : `${a || b}원`;
  return r + (withUnit && p.unit ? ` / ${p.unit.replace(/\(.*\)/, "").trim()}` : "");
}
export const unitShort = (m: Material) => (m.price?.unit ? m.price.unit.replace(/\(.*\)/, "").trim() : "");
