// QA r7 화면 고침 C: 비서 밖(화면 · 업체)에서 처리돼 닫힌 반나절 카드는 카드가 낸 날 대신 지금 잡힌 날을 보여요(M11).
// 업체가 요청 화면에서 기간을 보낸 뒤 작업함 '비서 소식'의 같은 요청 카드는 '처리됨'이에요(N4, 이 탭에 둔 화면 쓰기).
// 서버 · 브라우저 없이 순수 함수와 탭 저장소 흉내만 봐요.
import { expect, test } from "@playwright/test";
import { movedSlotIds, rememberVendorWrite, slotTitleNow, vendorDoneIds, type ActionOut, type SlotNow } from "./assistant";

const VISIT = "0193a000-0000-7000-8000-000000000001";
const slot = (over: Partial<ActionOut>): ActionOut => ({
  action_id: "a1", kind: "visit_slot", status: "proposed",
  summary: { title: "QA벽지공방 실측 11월 25일(수) 오전", amounts: [], rows: [], approve_label: "이 시간으로 고르기" },
  target_id: VISIT, target_ver: "offered", expires_at: "2026-11-27T00:00:00+09:00",
  ...over,
} as ActionOut);
const NOW: Record<string, SlotNow> = { [VISIT]: { vendor: "QA벽지공방", day: "2026-11-26", half: "am" } };

test("화면에서 다른 반나절을 골라 닫힌 카드는 지금 잡힌 날을 제목으로 보여요", () => {
  const closed = slot({ status: "expired", error_code: "handled_elsewhere" });
  expect(slotTitleNow(closed, false, NOW)).toBe("QA벽지공방 실측 11월 26일(목) 오전");
  // 서버 정리 전 화면에서 처리됨으로 접힌 카드도 같아요
  expect(slotTitleNow(slot({}), true, NOW)).toBe("QA벽지공방 실측 11월 26일(목) 오전");
  expect(movedSlotIds([closed, slot({ action_id: "a2" })], { a2: true })).toEqual(["a1", "a2"]);
});

test("열린 카드 · 거절 · 기한 지남 · 다른 카드는 카드 제목 그대로예요", () => {
  expect(slotTitleNow(slot({}), false, NOW)).toBeNull();
  expect(slotTitleNow(slot({ status: "rejected" }), false, NOW)).toBeNull();
  expect(slotTitleNow(slot({ status: "expired", error_code: "due" }), false, NOW)).toBeNull();
  expect(slotTitleNow(slot({ kind: "vendor_confirm", status: "expired", error_code: "handled_elsewhere" }), false, NOW)).toBeNull();
  // 잡힌 반나절이 없으면(취소 · 못 읽음) 카드 제목 그대로
  expect(slotTitleNow(slot({ status: "expired", error_code: "handled_elsewhere" }), false, {})).toBeNull();
  expect(movedSlotIds([slot({}), slot({ status: "rejected" })], {})).toEqual([]);
});

/** 브라우저 탭 저장소(sessionStorage) 흉내. 끝나면 지워요(다른 시험이 window를 보지 않게) */
function withTab(fn: () => void) {
  const m = new Map<string, string>();
  const sessionStorage = { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
  Object.defineProperty(globalThis, "window", { value: { sessionStorage }, configurable: true });
  try { fn(); } finally { delete (globalThis as { window?: unknown }).window; }
}

test("업체가 화면에서 기간을 보냈으면 같은 요청의 열린 기간 답하기 카드만 처리됨이에요(5분 안)", () => {
  withTab(() => {
    const OTHER = "0193a000-0000-7000-8000-000000000002";
    const t0 = 1_800_000_000_000;
    rememberVendorWrite("POST", `/vendor/visits/${VISIT}/window`, t0);
    const mine = slot({ kind: "window_answer", target_ver: "requested" });
    const other = slot({ action_id: "a2", kind: "window_answer", target_id: OTHER });
    const dates = slot({ action_id: "a3", kind: "dates" });
    const closed = slot({ action_id: "a4", kind: "window_answer", status: "expired", error_code: "handled_elsewhere" });
    expect(vendorDoneIds([mine, other, dates, closed], t0 + 60_000)).toEqual(["a1"]);
    // 5분이 지나면(서버 정리가 닫았어요) 더 보지 않아요
    expect(vendorDoneIds([mine], t0 + 5 * 60_000)).toEqual([]);
    // 못 받아요는 기간 답하기 카드도 끝내요. 읽기 · 다른 쓰기는 두지 않아요
    rememberVendorWrite("POST", `/vendor/visits/${OTHER}/decline`, t0);
    rememberVendorWrite("GET", `/vendor/visits/${VISIT}/window`, t0);
    rememberVendorWrite("POST", `/vendor/profile`, t0);
    expect(vendorDoneIds([mine, other], t0 + 60_000)).toEqual(["a1", "a2"]);
  });
});

test("탭 저장소를 못 쓰면 처리됨 표시 없이 넘어가요", () => {
  rememberVendorWrite("POST", `/vendor/visits/${VISIT}/window`);
  expect(vendorDoneIds([slot({ kind: "window_answer" })])).toEqual([]);
});
