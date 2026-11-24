// 기한 글(lib/format dueText): 0시 기한은 앞날 24:00으로 적어요(QA r7 N11: '11.27(금) 00:00까지'가 27일까지로 읽혔어요)
// 기간 글(rangeText): 하루짜리는 날짜 하나로 써요(QA r9 U3)
import { expect, test } from "@playwright/test";
import { dueText, rangeText } from "./format";

test("0시 기한은 앞날 24:00까지예요", () => {
  expect(dueText("2026-11-27T00:00:00+09:00")).toBe("11.26(목) 24:00까지");
  expect(dueText("2026-12-01T00:00:00+09:00")).toBe("11.30(월) 24:00까지"); // 달이 바뀌어도
  expect(dueText("2026-11-26T15:00:00Z")).toBe("11.26(목) 24:00까지"); // 서울 0시(UTC 15시)
  // 오늘 · 내일 · 모레도 앞날 기준: 내일 0시면 '오늘 24:00까지'
  expect(dueText("2026-11-25T00:00:00+09:00", { now: "2026-11-24T10:00:00+09:00", relative: true })).toBe("오늘 24:00까지");
});

test("0시가 아니면 그대로예요", () => {
  expect(dueText("2026-11-25T13:00:00+09:00")).toBe("11.25(수) 13:00까지");
  expect(dueText("2026-11-26T08:59:00+09:00", { now: "2026-11-24T10:00:00+09:00", relative: true })).toBe("모레 08:59까지");
  expect(dueText("2027-01-04T00:30:00+09:00", { today: "2026-11-24" })).toBe("2027.1.4(월) 00:30까지");
});

test("하루짜리 기간은 날짜 하나예요('11월 25일~25일'이 아니에요)", () => {
  expect(rangeText("2026-11-25", "2026-11-25")).toBe("11.25");
  expect(rangeText("2026-11-25", "2026-11-25", { long: true })).toBe("11월 25일");
  expect(rangeText("2026-11-25", "2026-11-25", { weekday: true })).toBe("11.25(수)");
});

test("여러 날 기간은 그대로 이어 써요", () => {
  expect(rangeText("2026-11-26", "2026-11-27")).toBe("11.26~11.27");
  expect(rangeText("2026-11-26", "2026-11-27", { long: true })).toBe("11월 26일~27일");
  expect(rangeText("2026-12-28", "2027-01-04", { long: true })).toBe("12월 28일~1월 4일");
  expect(rangeText("2026-11-26", "2026-11-27", { weekday: true })).toBe("11.26(목)~11.27(금)");
});
