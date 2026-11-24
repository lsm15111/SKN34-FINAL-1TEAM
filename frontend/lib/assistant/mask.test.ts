// 받은 견적서 사진 가리기 모양 함수(lib/assistant/mask)와 점검 카드 화면 말(lib/assistant/outside). 계산 없는 함수만 봐요.
import { expect, test } from "@playwright/test";
import { canUpload, dragBox, fitSize, MIN_BOX, PHOTO_SAY, sendText, toImage } from "@/lib/assistant/mask";
import { budgetText, diffText, ROW_CHIP, rowParts, sortRows } from "@/lib/assistant/outside";
import type { OutsideRow } from "@/lib/api/assistant";
import { won } from "@/lib/format";

test("긴 변만 2000px 아래로 줄이고 작은 그림은 그대로예요", () => {
  expect(fitSize(4000, 3000)).toEqual({ w: 2000, h: 1500 });
  expect(fitSize(1200, 3000)).toEqual({ w: 800, h: 2000 });
  expect(fitSize(800, 600)).toEqual({ w: 800, h: 600 });
  expect(fitSize(0, 10)).toEqual({ w: 0, h: 0 });
});

test("누른 곳은 그려진 칸 비율로 그림 좌표가 되고 그림 밖은 가장자리로 붙어요", () => {
  const rect = { left: 10, top: 20, width: 200, height: 100 };
  expect(toImage(110, 70, rect, 2000, 1000)).toEqual({ x: 1000, y: 500 });
  expect(toImage(-50, 500, rect, 2000, 1000)).toEqual({ x: 0, y: 1000 });
});

test("어느 쪽으로 끌어도 같은 상자이고 스친 것은 버려요", () => {
  const box = { x: 10, y: 20, w: 90, h: 30 };
  expect(dragBox({ x: 10, y: 20 }, { x: 100, y: 50 }, 500, 500)).toEqual(box);
  expect(dragBox({ x: 100, y: 50 }, { x: 10, y: 20 }, 500, 500)).toEqual(box);
  expect(dragBox({ x: 490, y: 490 }, { x: 600, y: 600 }, 500, 500)).toEqual({ x: 490, y: 490, w: 10, h: 10 });
  expect(dragBox({ x: 10, y: 10 }, { x: 10 + MIN_BOX - 1, y: 40 }, 500, 500)).toBeNull();
});

test("'개인정보를 가렸어요'를 확인해야 올릴 수 있어요", () => {
  expect(canUpload(false, true, false)).toBe(false);
  expect(canUpload(true, false, false)).toBe(false);
  expect(canUpload(true, true, true)).toBe(false);
  expect(canUpload(true, true, false)).toBe(true);
});

test("사진만 보내면 정해 둔 말을 남겨요", () => {
  expect(sendText("  이거 봐 주세요 ", 1)).toBe("이거 봐 주세요");
  expect(sendText("   ", 2)).toBe(PHOTO_SAY);
  expect(sendText("", 0)).toBe("");
});

const row = (state: OutsideRow["state"], o: number | null, s: number | null): OutsideRow => ({
  key: state, name: state, state, outside_won: o, standard_won: s, diff_won: o != null && s != null ? o - s : null, lines: [],
});

test("판정 칩은 글자와 같이 가고 금액 말은 서버 값 그대로예요", () => {
  expect(ROW_CHIP.missing).toEqual({ label: "빠짐", tone: "bad" });
  expect(ROW_CHIP.more.label).toBe("많음");
  expect(ROW_CHIP.same.label).toBe("비슷");
  expect(rowParts(row("missing", null, 165000), won)).toEqual(["견적서에 없어요", "표준 16만 5,000원"]);
  expect(rowParts(row("extra", 220000, null), won)).toEqual(["견적서 22만 원"]);
  expect(rowParts(row("more", 1540000, 1210000), won)).toEqual(["견적서 154만 원", "표준 121만 원"]);
});

test("차이 · 희망 예산 말은 서버 값에 표시만 붙여요", () => {
  expect(diffText(550000, won)).toBe("+55만 원");
  expect(diffText(-110000, won)).toBe("−11만 원");
  expect(diffText(0, won)).toBe("차이 없음");
  const label = "희망 예산 150만~250만 원";
  expect(budgetText({ state: "over", label, gap_won: 470000 }, won)).toBe(`${label} · 47만 원 넘어요`);
  expect(budgetText({ state: "under", label, gap_won: 30000 }, won)).toBe(`${label} · 3만 원 남아요`);
  expect(budgetText({ state: "within", label, gap_won: null }, won)).toBe(`${label} · 예산 안이에요`);
});

test("빠짐 · 많음 줄을 앞으로 모으고 나머지 차례는 그대로예요", () => {
  const rows = [row("same", 1, 1), row("missing", null, 1), row("extra", 2, null), row("more", 3, 1)];
  expect(sortRows(rows).map((r) => r.state)).toEqual(["missing", "more", "same", "extra"]);
});
