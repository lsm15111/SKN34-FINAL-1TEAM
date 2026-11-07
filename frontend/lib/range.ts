// 예상 범위 글: 폭의 이유(driver) 이름과 '알려 주시면 줄어요' 안내. 금액은 API 값을 그대로 넣고 새로 계산하지 않는다.
import type { Schemas } from "@/lib/backend/server";
import { won } from "./format";

export type ApiRange = Schemas["RangeOut"];
export type ApiRangePart = Schemas["RangePartOut"];

const NAME: Record<string, string> = {
  "qty:area": "도배 면적을 집 면적으로 어림했어요",
  "qty:edge": "몰딩 · 걸레받이 길이를 집 면적으로 어림했어요",
  "qty:flat": "천장 평탄화 면적을 어림했어요",
  "qty:door": "방문 개수를 어림했어요",
  "share:area": "고른 공간 크기를 흔한 평면으로 잡았어요",
  "share:edge": "고른 공간 크기를 흔한 평면으로 잡았어요",
  price: "업체마다 단가가 달라요",
  visit: "실측 뒤 업체가 수량 · 단가를 조금 고쳐요",
  "cond:removal": "기존 벽지 철거를 할지 아직 몰라요",
  "cond:waste": "폐기물 처리비를 따로 받을지 몰라요",
  "cond:moving": "짐 이동 · 보양이 필요할지 몰라요",
  "cond:remove_ceiling": "기존 등박스 · 우물천장을 뜯을지 몰라요",
  "cond:remove_door": "기존 방문 · 문틀 철거비를 따로 받을지 몰라요",
  "cond:remove_trim": "기존 몰딩 · 걸레받이 철거비를 따로 받을지 몰라요",
};

// 조건 줄: '…를 하게 되면' 앞말
const COND_WHAT: Record<string, string> = {
  "cond:removal": "기존 벽지 철거를",
  "cond:waste": "폐기물 처리를 따로",
  "cond:moving": "짐 이동 · 보양을",
  "cond:remove_ceiling": "등박스 · 우물천장 철거를",
  "cond:remove_door": "기존 방문 · 문틀 철거를",
  "cond:remove_trim": "기존 몰딩 · 걸레받이 철거를",
};

export function partName(driver: string): string {
  return NAME[driver] ?? "그 밖의 차이";
}

/** 몫(0~1 소수 문자열) → "45%" */
export function shareText(share: string | number): string {
  return `${Math.round(Number(share) * 100)}%`;
}

/** 범위 "210만~340만 원" (끝값은 만 원 단위라 '만 원'으로 끝난다) */
export function spanText(low: number, high: number): string {
  return `${won(low).replace(/ 원$/, "")}~${won(high)}`;
}

export type Hint = { key: string; text: string; href?: string; cta?: string };

/** 폭을 줄이는 안내. 갈 곳(areaHref · vendorsHref)이 없으면 글만 둔다. 몫이 큰 순, 많아야 limit개 */
export function rangeHints(r: ApiRange, opts: { areaHref?: string; vendorsHref?: string; limit?: number } = {}): Hint[] {
  const out: Hint[] = [];
  for (const p of r.parts) {
    if (Number(p.share) < 0.05) continue;
    const to = p.low_if != null && p.high_if != null ? spanText(p.low_if, p.high_if) : null;
    if (p.driver.startsWith("qty:") && p.better === "area" && to) {
      out.push({ key: p.driver, text: `전용면적(관리비 고지서 · 등기부등본)을 넣으면 ${to}으로 좁혀져요.`, href: opts.areaHref, cta: "면적 넣기" });
    } else if (p.driver.startsWith("share:") && to) {
      out.push({ key: p.driver, text: `고른 공간의 가로 · 세로를 알면 ${to}까지 좁혀져요. 실측 때 업체가 방마다 재요.` });
    } else if (p.driver.startsWith("qty:") && p.better === "self" && to) {
      out.push({ key: p.driver, text: `방마다 재 보면 ${to}까지 좁혀져요. 실측 때 업체가 재요.` });
    } else if (p.driver === "price" && to) {
      out.push({ key: p.driver, text: `업체 가견적을 보면 ${to}으로 좁혀져요.`, href: opts.vendorsHref, cta: "업체 가견적 보기" });
    } else if (p.driver.startsWith("cond:") && to && p.low_if_no != null && p.high_if_no != null) {
      const what = COND_WHAT[p.driver] ?? "이 일을";
      out.push({ key: p.driver, text: `${what} 하게 되면 ${to}, 안 하면 ${spanText(p.low_if_no, p.high_if_no)}이에요. 실측 때 업체에 물어보세요.` });
    }
    if (out.length >= (opts.limit ?? 2)) break;
  }
  return out;
}

export function precisionText(r: ApiRange): string {
  const size = r.precision === "area" ? "넣은 면적" : "평형대의 흔한 평형";
  return r.whole ? `집 크기는 ${size}으로 잡았어요.` : `집 크기는 ${size}으로, 고른 공간은 흔한 평면 비율로 잡았어요.`;
}
