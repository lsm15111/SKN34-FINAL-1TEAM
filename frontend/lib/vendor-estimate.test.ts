// 업체 자세히 가견적 줄 → 화면 줄(components/vendors/v3text estimateLines). 금액은 API(계산 엔진) 값 그대로 옮겨요.
// '선택' 줄(API optional: 퍼티 · 운송비, 판 2026.11b)은 표준견적서 선택 줄과 같은 꼴(state optional → 괄호 금액 · 선택 · 합계 밖)
import { expect, test } from "@playwright/test";
import { estimateLines } from "@/components/vendors/v3text";

type In = Parameters<typeof estimateLines>[0][number];
const L = (code: string, key: string, name: string, qty: string, unit: string, unit_price: number | null, amount: number, extra: Partial<In> = {}): In =>
  ({ code, key, name, qty, unit, unit_price, amount, mode: "price", included_in: null, in_standard: true, optional: false, ...extra });

// 도배만 하는 공사 기준(판 2026.11b) 집: 퍼티 · 운송비는 표준견적서 '선택' 일, 식대는 표준견적서에 줄이 없어요
const LINES: In[] = [
  L("1201", "putty", "퍼티작업", "21.0", "공급 평", 20000, 420000, { in_standard: false, optional: true, note: "사전퍼티 또는 밀작업" }),
  L("1203", "paper_hapji", "합지", "53.9", "벽지 평", null, 0, { mode: "excluded", label: "합지벽지" }),
  L("1204", "paper_silk", "실크", "53.9", "벽지 평", 9500, 512050, { label: "실크벽지" }),
  L("1205", "material", "부자재", "21.0", "공급 평", 13000, 273000),
  L("1206", "labor", "인건비", "4.5", "품", 300000, 1350000),
  L("1207", "meal", "식대", "4.5", "품", 11000, 49500, { in_standard: false }),
  L("1208", "truck", "운송비", "1", "대", 50000, 50000, { in_standard: false, optional: true }),
];

test("선택 줄은 표준견적서 선택 줄처럼 state optional이고 금액은 그대로예요", () => {
  const { inside, outside } = estimateLines(LINES, "basic");
  expect(inside.map((l) => [l.name, l.amount, l.state])).toEqual([
    ["실크벽지", 512050, undefined],
    ["부자재", 273000, undefined],
    ["인건비", 1350000, undefined],
  ]);
  expect(outside.map((l) => [l.name, l.amount, l.state])).toEqual([
    ["퍼티작업", 420000, "optional"],
    ["식대", 49500, undefined], // 선택이 아니면 가견적 합계에 든 줄 그대로
    ["운송비", 50000, "optional"],
  ]);
  const putty = outside[0];
  expect([putty.note, putty.qty, putty.unit, putty.unitPrice]).toEqual(["사전퍼티 또는 밀작업", "21.0", " 공급 평", 20000]);
});

test("다른 줄에 포함 · 빼기로 둔 선택 줄은 그 꼴 그대로예요(선택 표시 없음)", () => {
  const { outside } = estimateLines([
    L("1201", "putty", "퍼티작업", "21.0", "공급 평", null, 0, { in_standard: false, optional: true, mode: "included", included_in: "labor" }),
    L("1206", "labor", "인건비", "4.5", "품", 300000, 1350000),
    L("1208", "truck", "운송비", "1", "대", null, 0, { in_standard: false, optional: true, mode: "excluded" }),
  ], "basic");
  expect(outside.map((l) => [l.name, l.amount, l.state])).toEqual([
    ["퍼티작업", null, undefined],
    ["운송비", null, "excluded"],
  ]);
});
