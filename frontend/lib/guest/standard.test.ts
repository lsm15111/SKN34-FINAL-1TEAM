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
