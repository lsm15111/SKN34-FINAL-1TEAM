// 표준견적서 줄 → 화면 줄(lib/guest/standard toQuoteLines): 벽지 직접 구매(API own_paper)면 도배지 줄은 '고객 구매'
import { expect, test } from "@playwright/test";
import { toQuoteLines, type StdLineIn } from "./standard";

const PAPER: StdLineIn = {
  key: "paper", name: "실크벽지 시장 평균 가격", qty: "21.0", unit: "벽지 평", unit_price: 10749, amount: 225729,
  state: "excluded", source: "고객 구매 · 벽지 시장 평균 가격 · 실크벽지 근거 279줄 (paper-market-2026.11)", basis: "market",
};

test("벽지 직접 구매면 도배지 줄은 '고객 구매' · 롤 수만 보이고 금액은 '—'(합계 밖)이에요", () => {
  const [l] = toQuoteLines([PAPER], "full", { rolls: "실크(106cm × 15.6m) 약 5롤 · 여분 1~2롤은 따로" });
  // 단위는 하나만(QA r3 v1 L11): 사는 양은 롤 수로 보이고 벽지 평 수량은 빼요
  expect(l).toEqual({
    key: "paper", name: "실크벽지", note: "고객 구매 · 실크(106cm × 15.6m) 약 5롤 · 여분 1~2롤은 따로", amount: null,
  });
});

test("벽지 직접 구매인데 롤 수가 없으면 벽지 평 수량 하나만 보여요", () => {
  const [l] = toQuoteLines([PAPER], "full", { rolls: null });
  expect(l).toEqual({ key: "paper", name: "실크벽지", note: "고객 구매", qty: "21.0", unit: " 벽지 평", amount: null });
});

test("벽지를 사지 않으면 도배지 줄은 시장 평균 가격 그대로예요", () => {
  const [l] = toQuoteLines([{ ...PAPER, state: "included", source: "벽지 시장 평균 가격" }], "full");
  expect([l.note, l.amount, l.state]).toEqual(["시장 평균 가격", 225729, "included"]);
});

// 전체 철거(QA r7 N2): 계산 엔진이 '기존 벽지 철거' 줄을 '안 함'으로 두고 줄 근거 글 앞머리에 까닭을 적어요(calc/dobae.py DEMOLISHED_REMOVAL)
const REMOVAL: StdLineIn = {
  key: "removal", name: "기존 벽지 철거", qty: "184.1", unit: "㎡", unit_price: 1727, amount: 317941,
  state: "excluded", source: "전체 철거 공사에서 떼요(도배 견적 밖) · 표준품셈 벽지 떼내기 × 2026.9.1 보통인부 노임", basis: "public",
};

test("전체 철거면 기존 벽지 철거 줄은 '안 함' 대신 까닭을 보이고 수량 × 단가 · 금액은 빼요", () => {
  for (const scope of ["full", "partial"] as const) {
    const [l] = toQuoteLines([REMOVAL], scope);
    expect(l).toEqual({ key: "removal", name: "기존 벽지 철거", amount: null, state: "excluded", stateText: "전체 철거 공사에서 떼요(도배 견적 밖)" });
  }
});

test("철거하지 않으면 기존 벽지 철거 줄은 실측 후 · 괄호 금액 그대로예요", () => {
  const [l] = toQuoteLines([{ ...REMOVAL, state: "after_visit", source: "표준품셈 벽지 떼내기 × 2026.9.1 보통인부 노임" }], "full");
  expect([l.qty, l.unitPrice, l.amount, l.state, l.stateText]).toEqual(["184.1", 1727, 317941, "after_visit", undefined]);
});
