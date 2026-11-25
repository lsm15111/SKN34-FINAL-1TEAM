// 예시: 표준견적서(POST /guest/standard · GET /projects/{id}/standard 응답 모양, api.md 1장).
// 숫자는 9판 견본(상계동 공급 69.4㎡ · 실크 · 빈 집 · 예산 300만 원)과 부분 공사 예시(C60)를 그대로 옮겼어요. 화면에서 셈하지 않아요.
import type { Schemas } from "@/lib/v5/types";

export type GuestStandard = Schemas["GuestStandardOut"];
export type HomeInfoBody = Schemas["HomeInfoIn"];

/** 홈 견본 · 예시 공사(full)의 기본 정보 */
export const SAMPLE_INFO: HomeInfoBody = {
  trade: "dobae", scope: "full", spaces: [], faces: ["wall", "ceiling"], housing: "apt",
  sido: "seoul", sgg: "노원구", emd: "상계동", area_m2: "69.4", area_basis: "supply",
  occupied: false, grade: "basic", budget_won: 3_000_000, start_date: "2027-01-04",
};

export const SAMPLE_STANDARD: GuestStandard = {
  formula_ver: "dobae_v3",
  price_ver: "2026H2",
  share_ver: null,
  scope: "full",
  area_m2: "69.4",
  area_basis: "supply",
  pyeong: "21.0",
  lines: [
    { key: "wall", name: "벽 도배 시공", qty: "130.1", unit: "㎡", unit_price: 5993, amount: 779689, state: "included", basis: "public", source: "표준시장단가 2026 하반기 · 도배지바름(풀 포함)" },
    { key: "ceiling", name: "천장 도배 시공", qty: "43.4", unit: "㎡", unit_price: 8531, amount: 370245, state: "included", basis: "public", source: "표준시장단가 2026 하반기 · 천장 도배지바름(풀 포함)" },
    { key: "paper", name: "실크벽지", qty: "63.0", unit: "벽지 평", unit_price: 9500, amount: 598500, state: "included", basis: "assumed", source: "실크벽지 시장 평균 가격 2026" },
    { key: "primer", name: "초배지", qty: "190.8", unit: "㎡", unit_price: 242, amount: 46174, state: "included", basis: "public", source: "조달청 가격 2026 · 초배지" },
    { key: "removal", name: "기존 벽지 철거", qty: "173.5", unit: "㎡", unit_price: 1727, amount: 299635, state: "after_visit", basis: "public", source: "표준시장단가 2026 하반기 · 벽지 떼어내기" },
  ],
  supply: 1794608,
  vat: 179461,
  total: 1974069,
  days: "2",
  man_day: "4.0",
  budget_fit: "within",
  assumptions: ["도배 면적은 공급면적으로 어림했어요. 실측 때 방마다 다시 재요."],
  own_paper: false,
};

/** 부분 공사 예시(C60): 하계동 공급 69.4㎡ · 거실 · 주방 · 벽만 · 실크 */
export const PART_INFO: HomeInfoBody = {
  ...SAMPLE_INFO, emd: "하계동", scope: "partial", spaces: ["living", "kitchen"], faces: ["wall"], budget_won: 1_000_000, start_date: null,
};

export const PART_STANDARD: GuestStandard = {
  formula_ver: "dobae_v3",
  price_ver: "2026H2",
  share_ver: "share_2026_1",
  scope: "partial",
  area_m2: "69.4",
  area_basis: "supply",
  pyeong: "21.0",
  lines: [
    { key: "wall", name: "벽 도배 시공", qty: "59.8", unit: "㎡", unit_price: 5993, amount: 358381, state: "included", basis: "public", source: "표준시장단가 2026 하반기 · 도배지바름(풀 포함)" },
    { key: "paper", name: "실크벽지", qty: "21.7", unit: "벽지 평", unit_price: 9500, amount: 206150, state: "included", basis: "assumed", source: "실크벽지 시장 평균 가격 2026" },
    { key: "primer", name: "초배지", qty: "65.8", unit: "㎡", unit_price: 242, amount: 15924, state: "included", basis: "public", source: "조달청 가격 2026 · 초배지" },
    { key: "ceiling", name: "천장 도배 시공", qty: null, unit: "㎡", unit_price: null, amount: null, state: "excluded", basis: "public", source: "표준시장단가 2026 하반기" },
    { key: "removal", name: "기존 벽지 철거", qty: "59.8", unit: "㎡", unit_price: 1727, amount: 103275, state: "after_visit", basis: "public", source: "표준시장단가 2026 하반기 · 벽지 떼어내기" },
  ],
  supply: 580455,
  vat: 58046,
  total: 638501,
  days: "1",
  man_day: "1.5",
  budget_fit: "within",
  assumptions: ["부분 공사는 고른 공간의 넓이를 어림했어요."],
  own_paper: false,
};

/** 예시 켜짐: 넣은 답의 범위에 맞는 예시를 돌려줘요(계산하지 않아요 · 개발 미리 보기만) */
export function mockGuestStandard(info: HomeInfoBody): GuestStandard {
  return info.scope === "partial" ? PART_STANDARD : SAMPLE_STANDARD;
}
