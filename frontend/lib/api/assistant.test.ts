// 먼저 말 건 줄 닫기(settledNudges): 서버 '완료' 줄 · 그 줄의 승인 카드(같은 대상)를 실행 · 처리하면 닫아요.
// 첫 쪽 다시 읽기(keepOlder) · 마지막 카드 · 행동 찾기(lastCardIn · lastActionIn) · v3 단추 쓰기 → 행동 종류 · 처리됨(kindsForWrite · handledByWrite)
// 화면이 만든 말 자리(anchorIndex) · 사이트 안 링크(insideHref)
import { expect, test } from "@playwright/test";
import {
  anchorIndex, handledByWrite, insideHref, keepOlder, kindsForWrite, lastActionIn, lastCardIn, settledNudges, vendorKindsForWrite,
  type ActionKind, type ActionOut, type ActionStatus, type AssistantItem, type CardOut, type FeedItem, type FeedPart,
} from "./assistant";

const AT = "2026-11-21T10:00:00+09:00";
const act = (id: string, kind: ActionKind, status: ActionStatus, error_code: string | null = null, more: Partial<ActionOut> = {}): ActionOut => ({
  action_id: id, kind, status, error_code, expires_at: "2026-11-23T10:00:00+09:00", summary: { title: "반나절 고르기", approve_label: "이 시간으로 고르기" }, ...more,
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

test("새 카드로 바뀐 뒤 그 새 카드(replaced_by)가 실행 · 처리되면 닫아요", () => {
  const items = [nudge("x", act("a1", "visit_slot", "expired", "replaced", { replaced_by: "a2" })), user("1"), turn("t1", [{ t: "action", action: act("a2", "visit_slot", "executed") }])];
  expect(settledNudges(items, {})).toEqual(["x"]);
  // 같은 대상의 다른 종류로 바뀌어도 · 여러 번 바뀌어도 사슬 끝을 봐요
  const chain = [
    nudge("x", act("a1", "visit_slot", "expired", "replaced", { replaced_by: "a2" })),
    turn("t1", [{ t: "action", action: act("a2", "visit_slot", "expired", "replaced", { replaced_by: "a3" }) }]),
    turn("t2", [{ t: "action", action: act("a3", "visit_again", "proposed") }]),
  ];
  expect(settledNudges(chain, {})).toEqual([]);
  expect(settledNudges(chain, { a3: true })).toEqual(["x"]);
});

test("새 카드가 다른 대상이면(다른 업체 반나절 실행) 닫지 않아요", () => {
  // 사슬이 다른 행동을 가리키면 그 행동만 봐요
  const other = [
    nudge("x", act("a1", "visit_slot", "expired", "replaced", { replaced_by: "a2" })),
    turn("t1", [{ t: "action", action: act("a2", "visit_slot", "proposed") }, { t: "action", action: act("b1", "visit_slot", "executed") }]),
  ];
  expect(settledNudges(other, {})).toEqual([]);
  // replaced_by가 없는 옛 행동: 대상이 여럿일 수 있는 종류는 뒤 실행으로 닫지 않고, 공사에 한 번 정하는 종류만 닫아요
  expect(settledNudges([nudge("x", act("a1", "visit_slot", "expired", "replaced")), turn("t1", [{ t: "action", action: act("b1", "visit_slot", "executed") }])], {})).toEqual([]);
  expect(settledNudges([nudge("x", act("a1", "vendor_confirm", "expired", "replaced")), turn("t1", [{ t: "action", action: act("a2", "vendor_confirm", "executed") }])], {})).toEqual(["x"]);
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

test("v3 단추 쓰기 뒤 처리됨: 공사에 한 번 정하는 종류는 모두, 업체마다 따로인 종류는 하나뿐일 때만", () => {
  const slot = kindsForWrite("POST", "/projects/p1/visits/v1/pick", "p1");
  // 반나절 승인 카드가 업체마다 열려 있으면 어느 것인지 몰라 표시하지 않아요(서버 정리를 기다려요)
  expect(handledByWrite(slot, [act("a", "visit_slot", "proposed"), act("b", "visit_slot", "proposed")])).toEqual([]);
  // 하나뿐이면 그 카드(닫힌 카드 · 다른 종류는 세지 않아요, 같은 id가 두 번 와도 하나)
  const one = [act("a", "visit_slot", "proposed"), act("a", "visit_slot", "proposed"), act("b", "visit_slot", "executed"), act("c", "dates_accept", "proposed")];
  expect(handledByWrite(slot, one)).toEqual(["a"]);
  // 공사 날짜 수락은 두 종류(처음 · 바뀐 날짜)를 같이 세요: 공사마다 열린 제안이 하나라 둘이면 다른 공사예요
  const accept = kindsForWrite("POST", "/projects/p1/deals/d1/dates/x1/accept", "p1");
  expect(handledByWrite(accept, [act("a", "dates_accept", "proposed"), act("b", "delay_accept", "proposed")])).toEqual([]);
  expect(handledByWrite(accept, [act("b", "delay_accept", "proposed")])).toEqual(["b"]);
  // 업체 확정 · 집 정보 · 실측 요청은 열린 것 모두(한 곳을 확정하면 다른 곳 확정 제안도 끝나요)
  const confirm = kindsForWrite("POST", "/projects/p1/quotes/v1/confirm", "p1");
  expect(handledByWrite(confirm, [act("a", "vendor_confirm", "proposed"), act("b", "vendor_confirm", "proposed")])).toEqual(["a", "b"]);
  expect(handledByWrite(kindsForWrite("PATCH", "/projects/p1", "p1"), [act("h", "home_info", "proposed")])).toEqual(["h"]);
  expect(handledByWrite([], [act("a", "visit_slot", "proposed")])).toEqual([]);
  // 업체 쪽(요청마다 기간 답하기 · 못 받아요)도 같은 규칙
  const answer = vendorKindsForWrite("POST", "/vendor/visits/v1/window");
  expect(handledByWrite(answer, [act("a", "window_answer", "proposed"), act("b", "window_answer", "proposed")])).toEqual([]);
  expect(handledByWrite(answer, [act("a", "window_answer", "proposed")])).toEqual(["a"]);
});

test("마지막 행동 찾기는 test에 맞는 것만 봐요", () => {
  const items = [turn("t1", [{ t: "action", action: act("a1", "extra_answer", "executed", null, { target_ver: "pending:1" }) }]), turn("t2", [{ t: "action", action: act("a2", "extra_answer", "proposed", null, { target_ver: "asked:2" }) }])];
  expect(lastActionIn(items, "extra_answer")?.action_id).toBe("a2");
  expect(lastActionIn(items, "extra_answer", (a) => a.target_ver === "pending:1")?.action_id).toBe("a1");
  expect(lastActionIn(items, "extra_answer", (a) => a.target_ver === "pending:9")).toBeNull();
});

test("화면이 만든 말 자리: 처음 열 때 마지막 말 뒤, 그 말이 빠지면 그 시각까지의 말 뒤, 처음에 비었으면 맨 앞", () => {
  const page = [said("1", 1), said("2", 2)];
  const anchor = { id: "u-2", at: at(2) };
  // 새 말(보낸 말 · 답)은 자리 아래로
  expect(anchorIndex([...page, said("3", 3), said("4", 4)], anchor)).toBe(2);
  // 앞 쪽을 더 읽어도 그 말 뒤
  expect(anchorIndex([said("0", 0), ...page, said("3", 3)], anchor)).toBe(3);
  // 그 말이 빠졌으면(실패 턴이 뒤 턴에 밀려 빠짐) 그 시각까지의 말 뒤
  expect(anchorIndex([said("1", 1), said("3", 3)], anchor)).toBe(1);
  expect(anchorIndex([said("3", 3)], anchor)).toBe(0);
  // 처음에 대화가 비었으면 맨 앞(보낸 말이 화면이 만든 말 아래에 쌓여요)
  expect(anchorIndex([said("1", 1)], null)).toBe(0);
});

test("사이트 안 링크만: 다른 사이트로 읽히는 '//' · 역빗금 · 탭 · 공백은 막아요", () => {
  for (const h of ["/projects/p1/quotes", "/api/projects/p1/plan.ics", "/notifications?x=1#a"]) expect(insideHref(h)).toBe(true);
  for (const h of ["//evil.example", "/\\evil.example", "/\t/evil.example", "/x\\y", "https://evil.example", "javascript:alert(1)", "", "/ evil", "/\n/evil"]) {
    expect(insideHref(h)).toBe(false);
  }
});
