// QA r7 화면 고침 C: 비서 밖(화면 · 업체)에서 처리돼 닫힌 반나절 카드는 카드가 낸 날 대신 지금 잡힌 날을 보여요(M11).
// 서버 · 브라우저 없이 순수 함수만 봐요.
import { expect, test } from "@playwright/test";
import { movedSlotIds, slotTitleNow, type ActionOut, type SlotNow } from "./assistant";

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
