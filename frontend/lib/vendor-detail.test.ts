// 업체 자세히 판정(components/vendors/v3text): 리뷰 미리 보기 고르기(topReviews) · 섹션 띠의 지금 보는 묶음(pickSection)
import { expect, test } from "@playwright/test";
import { pickSection, topReviews, type SectionBox } from "@/components/vendors/v3text";

const R = (id: string, rating: number, day: string) => ({ id, rating, created_at: `${day}T15:00:00+09:00` });

test("리뷰는 별점 높은 순, 같은 별점이면 최근 것 먼저 3개예요", () => {
  const items = [R("a", 5, "2026-11-02"), R("b", 4, "2026-11-20"), R("c", 5, "2026-09-20"), R("d", 5, "2026-10-30"), R("e", 3, "2026-11-23")];
  expect(topReviews(items).map((r) => r.id)).toEqual(["a", "d", "c"]);
  expect(items.map((r) => r.id)).toEqual(["a", "b", "c", "d", "e"]); // 받은 목록은 그대로예요
});

test("리뷰가 적으면 있는 만큼, 별점이 모두 다르면 별점 순이에요", () => {
  expect(topReviews([R("a", 2, "2026-11-02"), R("b", 4, "2026-01-01")]).map((r) => r.id)).toEqual(["b", "a"]);
  expect(topReviews([])).toEqual([]);
  expect(topReviews([R("a", 5, "2026-11-02"), R("b", 4, "2026-11-03")], 1).map((r) => r.id)).toEqual(["a"]);
});

test("별점 · 날짜가 같으면 id 순이라 늘 같은 차례예요", () => {
  expect(topReviews([R("b", 5, "2026-11-02"), R("a", 5, "2026-11-02")]).map((r) => r.id)).toEqual(["a", "b"]);
});

// 띠 아래 선(line) 100. 가견적 · 시공 사례 · 리뷰가 화면 순서예요
const at = (est: number, cases: number, reviews: number): SectionBox[] => [
  { id: "est", top: est, bottom: cases - 16 },
  { id: "cases", top: cases, bottom: reviews - 140 },
  { id: "reviews", top: reviews, bottom: reviews + 300 },
];

test("선을 지난 마지막 묶음이 지금 보는 묶음이고, 아직 아무것도 안 지났으면 첫 묶음이에요", () => {
  expect(pickSection(at(160, 900, 1300), 100, false)).toBe("est");
  expect(pickSection(at(-600, 90, 500), 100, false)).toBe("cases");
  expect(pickSection(at(-900, -300, 100), 100, false)).toBe("reviews");
  expect(pickSection([], 100, false)).toBeNull();
});

test("끝까지 내리면 선까지 못 올라온 짧은 마지막 묶음(리뷰)이에요", () => {
  expect(pickSection(at(-900, -100, 400), 100, true)).toBe("reviews");
});

test("끝에서 누른 묶음이 띠 아래에 보이면 그 묶음 그대로예요(더 못 내려가는 짧은 화면)", () => {
  const boxes = at(-700, 220, 600);
  expect(pickSection(boxes, 100, true, "cases")).toBe("cases");
  // 누른 묶음이 이미 띠 위로 지나갔으면 마지막 묶음이에요
  expect(pickSection(at(-900, -500, 300), 100, true, "est")).toBe("reviews");
  // 끝이 아니면 누른 것과 상관없이 선으로 골라요
  expect(pickSection(at(-600, 90, 500), 100, false, "reviews")).toBe("cases");
});
