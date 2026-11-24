// 한도에 닿아 멈춘 턴 안내(stoppedNote): 카드가 없는 턴에는 '카드만 보여 드려요'라고 하지 않아요(QA r9 c2 T2)
import { expect, test } from "@playwright/test";
import { stoppedNote } from "./assistant";

test("멈춘 턴: 카드가 있으면 카드만 보인다고, 없으면 다시 물어 달라고 해요", () => {
  expect(stoppedNote(true)).toBe("설명을 끝까지 만들지 못해 카드만 보여 드려요");
  expect(stoppedNote(false)).toBe("답을 끝까지 만들지 못했어요. 다시 물어봐 주세요");
  expect(stoppedNote(false)).not.toContain("카드");
});
