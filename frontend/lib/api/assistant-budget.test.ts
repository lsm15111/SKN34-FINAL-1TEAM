// 희망 예산(갈래 P3): 승인 카드 종류 budget. 집 정보 고치기(PATCH)는 같은 화면의 '예산' 칸도 저장해서, 열린 희망 예산
// 카드도 열린 집 정보 카드처럼 '처리됨'으로 그려요(서버는 값이 바뀌면 stale · 정리가 닫아요).
import { expect, test } from "@playwright/test";
import { handledByWrite, kindsForWrite, type ActionKind, type ActionOut } from "./assistant";

const act = (id: string, kind: ActionKind): ActionOut => ({
  action_id: id, kind, status: "proposed", expires_at: "2026-11-30T10:00:00+09:00", summary: { title: "희망 예산 저장", approve_label: "맞아요, 저장" },
});

test("집 정보 고치기는 열린 집 정보 · 희망 예산 카드를 모두 처리됨으로 봐요", () => {
  const kinds = kindsForWrite("PATCH", "/projects/p1", "p1");
  expect(kinds).toEqual(["home_info", "budget"]);
  const open = [act("h", "home_info"), act("b", "budget"), act("v", "visit_request")];
  expect(handledByWrite(kinds, open)).toEqual(["h", "b"]);
  expect(handledByWrite(kinds, [act("b", "budget")])).toEqual(["b"]);
});

test("다른 쓰기는 희망 예산 카드를 건드리지 않아요", () => {
  expect(kindsForWrite("PUT", "/projects/p1/diy", "p1")).toEqual([]);
  expect(kindsForWrite("POST", "/projects/p1/visits", "p1")).toEqual(["visit_request"]);
  expect(handledByWrite(["visit_request"], [act("b", "budget"), act("v", "visit_request")])).toEqual(["v"]);
});
