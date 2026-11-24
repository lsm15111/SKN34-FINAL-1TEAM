// 실측 일정 취소 단추(components/visit/text cancelAct). 서버가 취소를 받는 상태(visit.service CANCELLABLE)마다
// 날짜가 정해지기 전은 요청 취소, 정해진 뒤는 실측 취소(창에 정한 날)예요. 값 모양은 서버 BoardRowOut · VisitPickOut 그대로예요.
import { expect, test } from "@playwright/test";
import { cancelAct } from "@/components/visit/text";

const DAY = { day: "2026-12-15", half: "am" as const, kind: "booked" as const, hold_until: null };
const HOLD = { day: "2026-12-16", half: "am" as const, kind: "hold" as const, hold_until: "2026-11-22T15:10:00+09:00" };
const ON = { cancel: true };
const REQUEST = { label: "요청 취소", request: true, slot: null };

test("답 기다림 · 날짜 고를 차례는 요청 취소예요", () => {
  expect(cancelAct({ status: "requested", booked: null, can: ON })).toEqual(REQUEST);
  expect(cancelAct({ status: "offered", booked: null, can: ON })).toEqual(REQUEST);
});

test("수락 기다림 · 다른 날 제안 옴도 요청 취소이고, 잡아 둔 날은 정한 날로 넘기지 않아요", () => {
  expect(cancelAct({ status: "picked", booked: HOLD, can: ON })).toEqual(REQUEST);
  expect(cancelAct({ status: "proposed", booked: HOLD, can: ON })).toEqual(REQUEST);
});

test("확정 · 실측 받음은 실측 취소이고 창에 정한 날을 넘겨요", () => {
  const visit = { label: "실측 취소", request: false, slot: { day: "2026-12-15", half: "am" } };
  expect(cancelAct({ status: "booked", booked: DAY, can: ON })).toEqual(visit);
  expect(cancelAct({ status: "visited", booked: DAY, can: ON })).toEqual(visit);
});

test("견적서가 온 뒤 · 끝난 요청은 취소 단추가 없어요", () => {
  for (const status of ["quoted", "chosen", "declined", "expired", "cancelled", "no_show", "closed", "unknown"]) {
    expect(cancelAct({ status, booked: DAY, can: ON }), status).toBeNull();
    expect(cancelAct({ status, booked: DAY }), status).toBeNull();
  }
});

test("상태판이 취소를 막으면(can.cancel 거짓) 단추가 없어요", () => {
  for (const status of ["requested", "offered", "picked", "proposed", "booked", "visited"]) {
    expect(cancelAct({ status, booked: DAY, can: { cancel: false } }), status).toBeNull();
  }
});

test("날짜 고르기 화면(can 없음)은 상태로만 골라요", () => {
  expect(cancelAct({ status: "offered", booked: null })).toEqual(REQUEST);
  expect(cancelAct({ status: "booked", booked: DAY })?.label).toBe("실측 취소");
  expect(cancelAct({ status: "booked", booked: null })).toEqual({ label: "실측 취소", request: false, slot: null });
});
