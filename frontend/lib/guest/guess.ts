// 첫 대화 첫 말(주소 · 단지 이름과 같이 적은 글)에서 집 정보 칸을 미리 고르는 코드 규칙(v4 StartChat). LLM은 쓰지 않아요.
// - 숫자 + 평 → 같은 ㎡가 되는 평형 칩, 없으면 ㎡ 칸(공급 기준, 앞에 '전용'이 붙으면 전용). 평 → ㎡는 넣기 도움(pyeongToM2)이에요.
//   '30평대'처럼 범위로 말했거나 서로 다른 평이 둘 이상이면 비워요.
// - '살면서 · 사는 중 · 거주' → 살면서 공사, '빈 집 · 이사 전 · 입주 전' → 빈 집. 둘 다 있으면 비워요.
// 못 찾으면 null(칸을 비워 둬요).
import { pyeongToM2, type Basis } from "./info";

export type AreaGuess = { area: string; basis: Basis; chip: string | null };

/** 아파트로 볼 평 범위(밖이면 집 면적이 아닌 말로 봐요) */
const MIN_PY = 10;
const MAX_PY = 120;
// 숫자 앞이 숫자 · 점 · 물결 · 줄표면 다른 말의 끝이라 빼요('1~2평' · '32~34평'), 뒤가 '대'면 범위('30평대')
const PY_RE = /(전용\s*(?:면적)?\s*)?(?<![\d.~-])(\d{1,3}(?:\.\d+)?)\s*평(?!대)/g;

/** 적은 글의 '32평' → 평형 칩(같은 ㎡가 되는 칩) 또는 ㎡ 칸 값 */
export function guessArea(text: string, chips: readonly string[]): AreaGuess | null {
  const found = new Map<string, AreaGuess>();
  for (const m of text.matchAll(PY_RE)) {
    const n = Number(m[2]);
    const area = pyeongToM2(m[2]);
    if (!area || !(n >= MIN_PY && n <= MAX_PY)) continue;
    const basis: Basis = m[1] ? "exclusive" : "supply";
    const chip = basis === "supply" ? chips.find((c) => pyeongToM2(c) === area) ?? null : null;
    found.set(`${basis}:${area}`, { area, basis, chip });
  }
  return found.size === 1 ? [...found.values()][0] : null;
}

// 띄어쓰기를 지운 글에서 찾아요. '비거주 · 실거주 · 거주 안 해요 · 거주하지 않아요 · 거주 예정'은 살면서로 보지 않아요
const LIVE_RE = /살면서|사는중|(?<![비실])거주(?!안|하지않|하지는않|예정)/;
const EMPTY_RE = /빈집|이사전|입주전/;

/** 공사할 때 집: true 살면서 공사 · false 빈 집 · null 모름(둘 다 있거나 없음) */
export function guessOccupied(text: string): boolean | null {
  const q = text.replace(/\s+/g, "");
  const live = LIVE_RE.test(q);
  const empty = EMPTY_RE.test(q);
  return live === empty ? null : live;
}
