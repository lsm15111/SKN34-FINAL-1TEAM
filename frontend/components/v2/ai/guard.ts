// 출력 검사 (v10 GUARD = 팀 backend/app/agent/guards.py를 옮긴 것).
// LLM 글을 문장마다 보고, 계산 엔진 값 · 인용한 자료에 없는 숫자가 든 문장은 버린다. 한글 금액 · 금지 표현도 버린다.

const NUM = /(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(만\s*원|천\s*원|억\s*원|억|만|원|%|퍼센트|㎡|m²|평|일|개월|개|롤|cm|mm|m|배|시간|주|층|장|짝|명|인|품)?/g;
const COUNT_WORDS = /^\s*(가지|번|단계|번째|곳|군데|가지씩)/;
const HANGUL_MONEY = /(?:[일이삼사오육칠팔구]?[십백천])+\s*(?:만|억)?\s*원/;
const HANGUL_AREA = /(?:[일이삼사오육칠팔구]?[십백천])+\s*평/;
const PHONE = /01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}/g;
const UNIT_NO = /\d{1,4}\s*동\s*\d{1,4}\s*호/g;
const MULT: Record<string, number> = { 만원: 1e4, 만: 1e4, 천원: 1e3, 억원: 1e8, 억: 1e8 };
const BANNED = /사기꾼|바가지|양아치|업체가\s*속이|법적으로\s*(?:아무\s*)?문제(?:가)?\s*없|무조건\s*(?:승소|이겨)|하자가\s*확실히\s*아니|(?:이|그)\s*금액으로\s*확정|금액을\s*보장|100\s*%\s*(?:보장|안전)/;

const val = (raw: string, unit?: string) => {
  const v = Number(raw.replace(/,/g, ""));
  const u = (unit || "").replace(/\s/g, "");
  return Number.isFinite(v) ? (MULT[u] ? v * MULT[u] : v) : null;
};
/** 같은 값을 여러 표시로 허용: 원 금액은 만 원 단위 반올림 표시도 허용(예 3,364,291원 → 336만 원) */
function numbers(text: string) {
  const out = new Set<number>();
  for (const m of String(text).matchAll(NUM)) {
    const v = val(m[1], m[2]);
    if (v == null) continue;
    out.add(+v.toFixed(4));
    if (v >= 10000) {
      out.add(Math.round(v / 1e4) * 1e4);
      out.add(Math.floor(v / 1e4) * 1e4);
    }
  }
  return out;
}
const mask = (t: string) => String(t).replace(PHONE, "(번호 가림)").replace(UNIT_NO, "(동호수 가림)");
function smallCount(v: number, unit: string | undefined, rest: string) {
  if (unit || v > 10 || !Number.isInteger(v)) return false;
  return COUNT_WORDS.test(rest) || !rest.trim() || ".)".includes(rest[0]);
}
function badNumber(sentence: string, allowed: Set<number>) {
  for (const m of sentence.matchAll(NUM)) {
    const v = val(m[1], m[2]);
    if (v == null || allowed.has(+v.toFixed(4)) || smallCount(v, m[2], sentence.slice((m.index ?? 0) + m[0].length))) continue;
    return m[0].trim();
  }
  return null;
}
/** text: LLM 글, allowedText: 계산 엔진 값 · 인용 자료를 이은 글 */
function check(text: string, allowedText: string) {
  const allowed = numbers(allowedText), kept: string[] = [], dropped: { s: string; why: string }[] = [];
  const parts: string[] = [];
  for (const x of mask(text).split(/(?<=[.!?。요])\s+|\n+/).map((y) => y.trim()).filter(Boolean)) {
    if (/^\[K\d+\]/.test(x) && parts.length) parts[parts.length - 1] += " " + x;
    else parts.push(x); // 근거 표시는 앞 문장에 붙인다
  }
  for (const s of parts) {
    let why: string | null = null, bad: string | null;
    if (HANGUL_MONEY.test(s) || HANGUL_AREA.test(s)) why = "한글로 쓴 금액 · 면적";
    else if ((bad = badNumber(s, allowed))) why = `계산 결과 · 자료에 없는 숫자(${bad})`;
    else if (BANNED.test(s)) why = "쓰면 안 되는 표현";
    if (why) dropped.push({ s, why });
    else kept.push(s);
  }
  return { text: kept.join("\n"), dropped, ok: !dropped.length };
}

export const GUARD = { check, numbers, mask };
