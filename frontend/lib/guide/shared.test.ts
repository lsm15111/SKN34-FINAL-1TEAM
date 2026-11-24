// 백과 용어 칸 주소(withTerm): 보던 화면 주소에 ?term=만 붙이고 빼요. 다른 검색어는 그대로예요
import { expect, test } from "@playwright/test";
import { withTerm } from "./shared";

test("보던 화면 주소에 ?term=만 붙여요", () => {
  expect(withTerm("/guide", "", "퍼티")).toBe("/guide?term=%ED%8D%BC%ED%8B%B0");
  expect(withTerm("/guide/how-it-goes", "", "천장-몰딩")).toBe(`/guide/how-it-goes?term=${encodeURIComponent("천장-몰딩")}`);
  // 용어 사전 갈래 · 그림 거르기는 그대로, 열린 용어는 바꿔 써요
  expect(withTerm("/guide/terms", "trade=dobae&img=1", "초배")).toBe(`/guide/terms?trade=dobae&img=1&term=${encodeURIComponent("초배")}`);
  expect(withTerm("/guide/terms", "trade=dobae&term=a", "b")).toBe("/guide/terms?trade=dobae&term=b");
});

test("닫을 때는 ?term=만 빼요", () => {
  expect(withTerm("/guide/how-it-goes", "term=a")).toBe("/guide/how-it-goes");
  expect(withTerm("/guide/terms", "trade=dobae&term=a&img=1")).toBe("/guide/terms?trade=dobae&img=1");
  expect(withTerm("/guide/steps", "")).toBe("/guide/steps");
});
