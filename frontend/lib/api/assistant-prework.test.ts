// 도배 전 점검 카드(갈래 P2): 고른 앞 공사 답 → 한 턴의 choice('prework.<공정>:<값>', 줄 순서)와 고객 말. 저장된 답과 같은 것은
// 빼요(서버가 바뀐 답만 승인 카드에 실어요). 서버 · 브라우저 없이 순수 함수만 봐요(pnpm test:unit).
import { expect, test } from "@playwright/test";
import { CHOICE, preworkSend, type PreworkRow } from "./assistant";

const row = (key: PreworkRow["key"], label: string, state: PreworkRow["state"] = null): PreworkRow => ({ key, label, state, why: "왜" });
const ROWS = [row("mokgong", "목공", "done"), row("electric", "전기"), row("film", "필름"), row("floor", "바닥", "todo")];

test("바꾼 답만 줄 순서로 보내요", () => {
  const got = preworkSend(ROWS, { floor: "done", electric: "todo", mokgong: "done" });
  expect(got).toEqual({
    choice: ["prework.electric:todo", "prework.floor:done"],
    text: "앞 공사 답: 전기 아직이에요 · 바닥 끝났어요",
  });
  expect(got?.choice.every((c) => c.length <= 40)).toBe(true); // 서버 choice 한 칸 40자
});

test("고른 게 없거나 저장된 답과 같으면 보내지 않아요", () => {
  expect(preworkSend(ROWS, {})).toBeNull();
  expect(preworkSend(ROWS, { mokgong: "done", floor: "todo" })).toBeNull();
});

test("choice 꼴은 서버 choices.prework_field와 같아요", () => {
  expect(CHOICE.prework("film", "none")).toBe("prework.film:none");
  expect(preworkSend(ROWS, { mokgong: "none", electric: "done", film: "todo", floor: "none" })?.choice.length).toBe(4); // 한 턴 5개까지
});
