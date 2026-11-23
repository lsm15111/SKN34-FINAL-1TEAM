// 대화 카드는 하나만, 지금 답 아래로(2026-11-23 사용자: 위에 집 정보 카드가 있으면 '집 정보 바꿀게'에 아래로 안 나왔어요).
// 같은 턴 안에서 다시 오면 그 자리, 앞 말에 있던 같은 card_id는 지금 답 아래로 옮기고, 오늘 정할 일은 처음 자리에 마지막 값.
// 대화를 다시 열 때(foldCards)도 스트림과 같은 모양이에요. 서버 · 브라우저 없이 순수 함수만 봐요(pnpm test:unit).
import { expect, test } from "@playwright/test";
import { applyTurnEvent, foldCards, type AssistantItem, type CardOut, type FeedItem, type HomeInfoData, type TodayData } from "./assistant";

const AT = "2026-11-23T01:00:00Z";
const home = (facts: string[]): CardOut<"home_info"> => ({
  card_id: "home", kind: "home_info",
  data: { phase: "confirm", facts, area: null, changes: [], action_id: null, saved: false, locked: false, demolition: null } satisfies HomeInfoData,
});
const today = (date: string, todo = 0): CardOut<"today"> => ({
  card_id: "today", kind: "today", data: { date, nudge_id: null, todo: Array.from({ length: todo }, () => ({}) as never), waiting: [], news: [] } as TodayData,
});
const said = (id: string, text: string): FeedItem => ({ id, role: "user", at: AT, text });
const reply = (turn: string, ...cards: CardOut[]): AssistantItem => ({
  id: `a-${turn}`, role: "assistant", at: AT, turn_id: turn, done: true,
  parts: [{ t: "text", text: `${turn} 답`, src: "ai" }, ...cards.map((card) => ({ t: "card" as const, card }))],
});
const card = (seq: number, c: CardOut) => ({ type: "card" as const, data: { seq, ...c } });
const cardsOf = (it: FeedItem | undefined) => (it && it.role === "assistant" ? it.parts.flatMap((p) => (p.t === "card" ? [p.card] : [])) : []);

test("앞 말에 있던 같은 카드는 지금 답 아래로 옮겨요(하나만, 새 값)", () => {
  const items: FeedItem[] = [said("u1", "집 정보 보여 줘"), reply("t1", home(["서울 노원구", "공급 69.4㎡"])), said("u2", "우리 집 정보 바꿀게")];
  const next = applyTurnEvent(items, "t2", card(1, home(["서울 노원구", "공급 84.9㎡"])), AT);
  expect(cardsOf(next[1])).toEqual([]); // 앞 말에서는 빠지고(글은 그대로)
  expect(next[1].role === "assistant" && next[1].parts.map((p) => p.t)).toEqual(["text"]);
  const last = next[next.length - 1];
  expect(last.role === "assistant" && last.turn_id).toBe("t2");
  expect(cardsOf(last).map((c) => (c.data as HomeInfoData).facts[1])).toEqual(["공급 84.9㎡"]);
});

test("같은 턴 안에서 다시 오면 그 자리에서 바꿔 끼워요", () => {
  const items: FeedItem[] = [said("u1", "집 정보"), reply("t1", home(["a"]), today("2026-11-23"))];
  const next = applyTurnEvent(items, "t1", card(5, home(["b"])), AT);
  expect(cardsOf(next[1]).map((c) => c.kind)).toEqual(["home_info", "today"]);
  expect((cardsOf(next[1])[0].data as HomeInfoData).facts).toEqual(["b"]);
});

test("오늘 정할 일은 처음 자리에 마지막 값이에요(화면이 만든 자리, QA r3 v1 L2)", () => {
  const items: FeedItem[] = [reply("t1", today("2026-11-23", 1)), said("u2", "오늘 뭐 해요?")];
  const next = applyTurnEvent(items, "t2", card(1, today("2026-11-23", 2)), AT);
  expect(cardsOf(next[0]).map((c) => (c.data as TodayData).todo.length)).toEqual([2]);
  expect(next.length).toBe(items.length + 1); // 지금 턴 말은 생기지만 카드는 없어요
  expect(cardsOf(next[next.length - 1])).toEqual([]);
});

test("대화를 다시 열 때도 같은 카드는 마지막 자리에 마지막 값 하나만(오늘 정할 일은 처음 자리)", () => {
  const items: FeedItem[] = [
    reply("t1", home(["옛 값"]), today("2026-11-23", 1)),
    said("u2", "집 정보 바꿀게"),
    reply("t2", home(["새 값"])),
    said("u3", "오늘 뭐 해요?"),
    reply("t3", today("2026-11-23", 3)),
  ];
  const got = foldCards(items);
  expect(cardsOf(got[0]).map((c) => c.kind)).toEqual(["today"]);
  expect((cardsOf(got[0])[0].data as TodayData).todo.length).toBe(3);
  expect(cardsOf(got[2]).map((c) => (c.data as HomeInfoData).facts[0])).toEqual(["새 값"]);
  expect(cardsOf(got[4])).toEqual([]);
  // 바뀔 것이 없으면 같은 말 객체를 그대로 둬요(다시 그리지 않게)
  const plain: FeedItem[] = [reply("t1", home(["a"])), said("u2", "고마워요")];
  expect(foldCards(plain)[0]).toBe(plain[0]);
});
