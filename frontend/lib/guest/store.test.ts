// 기기에 둔 답(lib/guest/store writeGuest)의 멱등 키: 같은 조건이면 같은 키, 조건이 바뀌면 새 키, 저장소를 못 써도 이 탭에서 같은 키
import { expect, test } from "@playwright/test";
import { EMPTY_DRAFT, type InfoDraft } from "./info";
import { clearGuest, readGuest, writeGuest } from "./store";

const DRAFT: InfoDraft = {
  ...EMPTY_DRAFT, sido: "seoul", sgg: "노원구", area: "105.8", occupied: false, grade: "basic", demolition: "none",
  rooms: 3, when: "next_month", start: "2026-12-15", diy: ["paint"],
};

/** 브라우저 localStorage 흉내(blocked면 읽기 · 쓰기가 막힌 브라우저) */
function storage(blocked = false) {
  const m = new Map<string, string>();
  const no = () => { throw new Error("blocked"); };
  const s = {
    getItem: (k: string) => (blocked ? no() : m.get(k) ?? null),
    setItem: (k: string, v: string) => (blocked ? no() : void m.set(k, v)),
    removeItem: (k: string) => (blocked ? no() : void m.delete(k)),
  };
  Object.defineProperty(globalThis, "localStorage", { value: s, configurable: true });
}

test("같은 조건이면 같은 키라 응답을 잃고 다시 보내도 공사 하나예요", () => {
  storage();
  clearGuest();
  const a = writeGuest(DRAFT);
  expect(writeGuest({ ...DRAFT }).key).toBe(a.key);
  expect(readGuest()?.key).toBe(a.key);
});

test("조건을 고치면 새 키예요(같은 키로 보내 고친 조건이 버려지지 않게)", () => {
  storage();
  clearGuest();
  const a = writeGuest(DRAFT);
  const b = writeGuest({ ...DRAFT, grade: "economy" });
  expect(b.key).not.toBe(a.key);
  // 고친 조건 그대로 다시 보내면 그 키 그대로
  expect(writeGuest({ ...DRAFT, grade: "economy" }).key).toBe(b.key);
  // 보낼 몸통에 없는 고른 시기 칩만 바뀌면 키는 그대로예요
  expect(writeGuest({ ...DRAFT, grade: "economy", when: "date" }).key).toBe(b.key);
  // 지운 뒤에는 같은 조건이어도 새 키(새 공사)
  clearGuest();
  expect(writeGuest({ ...DRAFT, grade: "economy" }).key).not.toBe(b.key);
});

test("저장소를 못 쓰는 브라우저도 이 탭에서는 같은 조건이면 같은 키예요", () => {
  storage(true);
  clearGuest();
  const a = writeGuest(DRAFT);
  expect(writeGuest(DRAFT).key).toBe(a.key);
  expect(writeGuest({ ...DRAFT, rooms: 4 }).key).not.toBe(a.key);
});
