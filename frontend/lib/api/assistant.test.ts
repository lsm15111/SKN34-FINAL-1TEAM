// 먼저 말 건 줄 닫기(settledNudges): 그 줄의 승인 카드(같은 대상)를 실행 · 처리하면 닫아요
import { expect, test } from "@playwright/test";
import { settledNudges, type ActionKind, type ActionOut, type ActionStatus, type FeedItem, type FeedPart } from "./assistant";

const AT = "2026-11-21T10:00:00+09:00";
const act = (id: string, kind: ActionKind, status: ActionStatus, error_code: string | null = null): ActionOut => ({
  action_id: id, kind, status, error_code, expires_at: "2026-11-23T10:00:00+09:00", summary: { title: "반나절 고르기", approve_label: "이 시간으로 고르기" },
});
const nudge = (id: string, a: ActionOut | null): FeedItem => ({
  id: `n-${id}`, role: "assistant", at: AT, turn_id: null, nudge_id: id, done: true,
  parts: [
    { t: "text", src: "guide", text: "업체가 실측 기간을 보냈어요." },
    ...(a ? [{ t: "action" as const, action: a }] : []),
    { t: "suggest", suggest: { id: `n-${id}`, text: "실측 날짜를 골라요", why: "업체가 기간을 보냈어요", say: "실측 날짜 고를래요", nudge_id: id } },
  ],
});
const turn = (id: string, parts: FeedPart[]): FeedItem => ({ id: `a-${id}`, role: "assistant", at: AT, turn_id: id, done: true, parts });
const user = (id: string): FeedItem => ({ id: `u-${id}`, role: "user", at: AT, text: "실측 날짜 고를래요" });

test("줄에 달린 승인 카드를 실행하면 닫아요", () => {
  expect(settledNudges([nudge("x", act("a1", "visit_slot", "executed"))], {})).toEqual(["x"]);
});

test("화면 v3 단추로 처리했으면 닫아요", () => {
  expect(settledNudges([nudge("x", act("a1", "dates_accept", "proposed"))], { a1: true })).toEqual(["x"]);
  expect(settledNudges([nudge("x", act("a1", "dates_accept", "expired", "handled_elsewhere"))], {})).toEqual(["x"]);
});

test("새 카드로 바뀐 뒤 같은 종류 행동이 실행되면 닫아요", () => {
  const items = [nudge("x", act("a1", "visit_slot", "expired", "replaced")), user("1"), turn("t1", [{ t: "action", action: act("a2", "visit_slot", "executed") }])];
  expect(settledNudges(items, {})).toEqual(["x"]);
});

test("아직 할 일이 남았으면 그대로 둬요", () => {
  const cases: FeedItem[][] = [
    [nudge("x", act("a1", "visit_slot", "proposed"))],
    [nudge("x", act("a1", "visit_slot", "rejected"))],
    [nudge("x", act("a1", "visit_slot", "expired", "due"))],
    [nudge("x", null)],
    // 바뀐 새 카드가 아직 실행 전이거나, 다른 종류 · 앞서 실행한 행동이면 그대로
    [nudge("x", act("a1", "visit_slot", "expired", "replaced")), turn("t1", [{ t: "action", action: act("a2", "visit_slot", "proposed") }])],
    [nudge("x", act("a1", "visit_slot", "expired", "replaced")), turn("t1", [{ t: "action", action: act("a2", "vendor_confirm", "executed") }])],
    [turn("t0", [{ t: "action", action: act("a0", "visit_slot", "executed") }]), nudge("x", act("a1", "visit_slot", "expired", "replaced"))],
  ];
  for (const items of cases) expect(settledNudges(items, {})).toEqual([]);
});

test("턴 끝 제안에 붙은 줄은 그 턴의 행동으로 닫지 않아요", () => {
  const items = [
    nudge("y", act("b1", "dates_accept", "proposed")),
    turn("t1", [
      { t: "action", action: act("a2", "visit_slot", "executed") },
      { t: "suggest", suggest: { id: "n-y", text: "공사 날짜를 확인해요", why: "업체가 공사 날짜를 올렸어요", say: "공사 날짜 보여 줘", nudge_id: "y" } },
    ]),
  ];
  expect(settledNudges(items, {})).toEqual([]);
});
