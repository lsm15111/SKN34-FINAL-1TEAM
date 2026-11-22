// QA 3차 v1 화면(갈래 W): 오늘 정할 일 자리(takeToday, L2) · 지금 잠김(lockedNow, M6) · 다시 만들기(canRemake, L7) ·
// 업체 턴 넘침 한 번 더(busyOnce, 503). 서버 · 브라우저 없이 순수 함수만 봐요.
import { expect, test } from "@playwright/test";
import { ApiError } from "@/lib/backend/client";
import {
  busyOnce, canRemake, lockedNow, takeToday, TurnBusy,
  type ActionOut, type ActionStatus, type AssistantItem, type FeedItem, type FeedPart, type TodayData,
} from "./assistant";

const AT = "2026-11-22T10:20:00+09:00";
const DAY = "2026-11-22";
const today = (date = DAY, title = "업체를 골라 실측을 요청하세요 · 도배"): TodayData => ({
  date, nudge_id: null, todo: [{ id: "t1", icon: "doc", title }], waiting: [], news: [],
});
const turn = (id: string, parts: FeedPart[]): AssistantItem => ({ id: `a-${id}`, role: "assistant", at: AT, turn_id: id, done: true, parts });
const user = (id: string): FeedItem => ({ id: `u-${id}`, role: "user", at: AT, text: "안녕, 너 뭐 해 줄 수 있어?" });
const card = (d: TodayData): FeedPart => ({ t: "card", card: { card_id: "today", kind: "today", data: d } });
const text: FeedPart = { t: "text", src: "ai", text: "오늘은 업체를 골라 실측을 요청하면 돼요." };
const act = (kind: ActionOut["kind"], status: ActionStatus, error_code: string | null = null): ActionOut => ({
  action_id: `${kind}-${status}`, kind, status, error_code, expires_at: "2026-11-25T10:00:00+09:00",
  summary: { title: "결도배에 보낸 실측 요청 취소", approve_label: "실측 요청 취소하기" },
});

test("L2 같은 날 오늘 정할 일이 턴으로 오면 그 카드는 빼고 마지막 값을 돌려줘요(처음 보인 자리에 그대로)", () => {
  const fresh = today(DAY, "업체 3곳을 골라 실측을 요청하세요");
  const items: FeedItem[] = [user("1"), turn("t1", [card(fresh), text])];
  const got = takeToday(items, DAY);
  expect(got.last).toEqual(fresh);
  expect(got.items[1]).toEqual(turn("t1", [text]));
  expect(got.items[0]).toBe(items[0]);
});

test("L2 다른 날 카드 · 화면이 만든 말은 그대로 두고, 없으면 같은 목록이에요", () => {
  const old = turn("t0", [card(today("2026-11-21")), text]);
  const local: AssistantItem = { ...turn("x", [card(today())]), id: "today-x", turn_id: null, local: true };
  const items: FeedItem[] = [old, local, user("1"), turn("t1", [text])];
  const got = takeToday(items, DAY);
  expect(got.last).toBeNull();
  expect(got.items).toBe(items);
});

test("L2 같은 날 카드가 여러 번 오면 마지막 값이에요(모두 빼요)", () => {
  const a = today(DAY, "앞 값");
  const b = today(DAY, "뒤 값");
  const got = takeToday([turn("t1", [card(a)]), user("2"), turn("t2", [text, card(b)])], DAY);
  expect(got.last).toEqual(b);
  expect(got.items.flatMap((x) => (x.role === "assistant" ? x.parts : []))).toEqual([text]);
});

test("M6 지금 잠김: 처음 연 때 잠김 · 보드 단계가 실측 칸 이상 · 이 대화에서 실측 요청을 실행했으면", () => {
  expect(lockedNow(false, null, [])).toBe(false);
  expect(lockedNow(false, { step: 2 }, [turn("t1", [{ t: "action", action: act("visit_request", "proposed") }])])).toBe(false);
  expect(lockedNow(true, { step: 1 }, [])).toBe(true);
  expect(lockedNow(false, { step: 3 }, [])).toBe(true);
  expect(lockedNow(false, { step: 2 }, [turn("t1", [{ t: "action", action: act("visit_request", "executed") }])])).toBe(true);
});

test("L7 말로 거둔 카드(withdrawn)는 다시 만들기가 없어요. 거절 · 기한 지남은 있어요", () => {
  expect(canRemake(act("visit_cancel", "rejected", "withdrawn"))).toBe(false);
  for (const code of ["replaced", "quote_changed", "handled_elsewhere"]) expect(canRemake(act("visit_slot", "expired", code))).toBe(false);
  expect(canRemake(act("visit_cancel", "rejected"))).toBe(true);
  expect(canRemake(act("visit_slot", "expired", "due"))).toBe(true);
  expect(canRemake(act("visit_slot", "failed", "conflict"))).toBe(true);
});

test("업체 턴 503: Retry-After만큼 기다렸다 같은 몸통으로 한 번 더, 또 넘치면 TurnBusy를 던져요", async () => {
  const waits: number[] = [];
  const pause = async (ms: number) => { waits.push(ms); };
  let n = 0;
  expect(await busyOnce(async () => { n += 1; if (n === 1) throw new TurnBusy("busy", "많아요", 3000); return "ended"; }, pause)).toBe("ended");
  expect([n, waits]).toEqual([2, [3000]]);

  n = 0;
  const twice = await busyOnce(async () => { n += 1; throw new TurnBusy("busy", "많아요", 2000); }, pause).catch((e: unknown) => e);
  expect(twice).toBeInstanceOf(TurnBusy);
  expect(n).toBe(2);

  n = 0;
  const other = await busyOnce(async () => { n += 1; throw new ApiError(409, "turn_running", "도는 중"); }, pause).catch((e: unknown) => e);
  expect(other).toBeInstanceOf(ApiError);
  expect(other).not.toBeInstanceOf(TurnBusy);
  expect(n).toBe(1);
});
