// 먼저 말 건 줄 닫기(settledNudges): 서버 '완료' 줄 · 그 줄의 승인 카드(같은 대상)를 실행 · 처리하면 닫아요.
// 첫 쪽 다시 읽기(keepOlder) · 마지막 카드 찾기(lastCardIn) · v3 단추 쓰기 → 행동 종류(kindsForWrite)
import { expect, test } from "@playwright/test";
import {
  keepOlder, kindsForWrite, lastCardIn, settledNudges,
  type ActionKind, type ActionOut, type ActionStatus, type AssistantItem, type CardOut, type FeedItem, type FeedPart,
} from "./assistant";

const AT = "2026-11-21T10:00:00+09:00";
const act = (id: string, kind: ActionKind, status: ActionStatus, error_code: string | null = null): ActionOut => ({
  action_id: id, kind, status, error_code, expires_at: "2026-11-23T10:00:00+09:00", summary: { title: "반나절 고르기", approve_label: "이 시간으로 고르기" },
});
const nudge = (id: string, a: ActionOut | null): AssistantItem => ({
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

test("서버가 '완료'로 보낸 줄은 승인 카드가 없어도 닫혀 있어요", () => {
  const done: AssistantItem = { ...nudge("x", null), settled: true };
  expect(settledNudges([done, nudge("y", act("b1", "dates_accept", "proposed"))], {})).toEqual(["x"]);
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

const at = (min: number) => `2026-11-21T10:${String(min).padStart(2, "0")}:00+09:00`;
const said = (id: string, min: number): FeedItem => ({ id: `u-${id}`, role: "user", at: at(min), text: "물어봐요" });

test("첫 쪽을 다시 읽어도 읽어 둔 앞 쪽은 그대로 이어 붙여요", () => {
  const older = [said("1", 1), said("2", 2)];
  const first = [said("3", 3), said("4", 4)];
  const fresh = [said("3", 3), said("4", 4), { ...nudge("n", null), at: at(5) }, said("5", 6)];
  expect(keepOlder([...older, ...first], fresh).map((x) => x.id)).toEqual(["u-1", "u-2", "u-3", "u-4", "n-n", "u-5"]);
  // 새 말이 늘어 첫 쪽이 뒤로 밀려도, 첫 쪽 첫 말보다 앞인 것만 남겨요(같은 id는 새 쪽 것)
  const moved = [said("4", 4), said("5", 6)];
  expect(keepOlder([...older, ...first], moved).map((x) => x.id)).toEqual(["u-1", "u-2", "u-3", "u-4", "u-5"]);
  // 시각 꼴이 달라도(Z · +09:00) 시각으로 견줘요
  expect(keepOlder([{ ...said("0", 0), at: "2026-11-21T00:59:00Z" }], first).map((x) => x.id)).toEqual(["u-0", "u-3", "u-4"]);
  expect(keepOlder(older, [])).toEqual([]);
});

test("마지막 카드는 '완료' 줄의 카드(보낸 때 모습)를 빼고 찾아요", () => {
  const card = (id: string): CardOut<"quote_compare"> => ({ card_id: id, kind: "quote_compare", data: { cols: [], gap_won: null, ask_chips: [], href: "/" } });
  const live = turn("t1", [{ t: "card", card: card("compare-dobae") }]);
  const done: AssistantItem = { ...nudge("x", null), settled: true, parts: [{ t: "card", card: card("compare-dobae@x") }] };
  expect(lastCardIn([live, done], "quote_compare")?.card_id).toBe("compare-dobae");
  expect(lastCardIn([done], "quote_compare")).toBeNull();
});

test("v3 단추로 공사 날짜 바꾸기를 요청하면 같은 일을 하는 승인 카드(date_change)는 처리됨이에요", () => {
  expect(kindsForWrite("POST", "/projects/p1/deals/d1/date-requests", "p1")).toEqual(["date_change"]);
  expect(kindsForWrite("POST", "/projects/p1/deals/d1/dates/x1/accept", "p1")).toEqual(["dates_accept", "delay_accept"]);
  expect(kindsForWrite("GET", "/projects/p1/deals/d1/date-requests", "p1")).toEqual([]);
  expect(kindsForWrite("POST", "/projects/p2/deals/d1/date-requests", "p1")).toEqual([]);
});
