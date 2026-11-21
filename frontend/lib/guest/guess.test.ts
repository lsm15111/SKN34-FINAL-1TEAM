// 첫 대화 첫 말 → 평형 · 공사할 때 집 · 방 개수 · 공사 희망 시기 미리 고르기(lib/guest/guess)
import { expect, test } from "@playwright/test";
import { guessArea, guessOccupied, guessRooms, guessWhen } from "./guess";

// StartChat 평형 칩과 같은 목록
const CHIPS = ["24", "32", "34", "40"];
const SAID = "노원구 상계동 상계주공 32평이에요. 살면서 도배랑 몰딩 바꾸고 싶어요";

test.describe("평형", () => {
  test("같은 ㎡가 되는 평형 칩을 골라요", () => {
    expect(guessArea(SAID, CHIPS)).toEqual({ area: "105.8", basis: "supply", chip: "32" });
    expect(guessArea("상계주공 34평형", CHIPS)).toEqual({ area: "112.4", basis: "supply", chip: "34" });
    expect(guessArea("24 평 아파트", CHIPS)).toEqual({ area: "79.3", basis: "supply", chip: "24" });
    expect(guessArea("32.0평", CHIPS)).toEqual({ area: "105.8", basis: "supply", chip: "32" });
  });

  test("칩이 없으면 ㎡ 칸 값이에요", () => {
    expect(guessArea("중계동 33평", CHIPS)).toEqual({ area: "109.1", basis: "supply", chip: null });
    expect(guessArea("47평 아파트", CHIPS)).toEqual({ area: "155.4", basis: "supply", chip: null });
  });

  test("전용이 붙으면 전용 ㎡ 칸이에요(공급 칩을 고르지 않아요)", () => {
    expect(guessArea("전용 25평", CHIPS)).toEqual({ area: "82.6", basis: "exclusive", chip: null });
    expect(guessArea("전용면적 32평", CHIPS)).toEqual({ area: "105.8", basis: "exclusive", chip: null });
  });

  test("같은 평을 두 번 말해도 하나로 봐요", () => {
    expect(guessArea("32평 아파트예요. 32평형", CHIPS)).toEqual({ area: "105.8", basis: "supply", chip: "32" });
  });

  test("못 찾거나 헷갈리면 비워요", () => {
    for (const said of [
      "노원구 상계동 푸른숲아파트",
      "101동 1203호",
      "평택시 비전동",
      "30평대 아파트",
      "24평에서 32평으로 넓혀 왔어요",
      "32~34평쯤",
      "베란다 1~2평",
      "5평 원룸",
      "150평",
    ]) {
      expect(guessArea(said, CHIPS), said).toBeNull();
    }
  });
});

test.describe("공사할 때 집", () => {
  test("살면서 · 사는 중 · 거주 → 살면서 공사", () => {
    for (const said of [SAID, "지금 사는 중이에요", "거주 중", "거주하면서 해요"]) expect(guessOccupied(said), said).toBe(true);
  });

  test("빈 집 · 이사 전 · 입주 전 → 빈 집", () => {
    for (const said of ["빈 집이에요", "빈집", "이사 전에 하려고요", "입주 전 도배"]) expect(guessOccupied(said), said).toBe(false);
  });

  test("둘 다 있거나 없으면 비워요", () => {
    for (const said of [
      "노원구 상계동 푸른숲아파트",
      "살면서 하다가 이사 전에 끝내고 싶어요",
      "비거주 주택",
      "실거주 목적이에요",
      "거주 안 해요",
      "거주하지 않아요",
      "공사 끝나고 거주 예정",
    ]) {
      expect(guessOccupied(said), said).toBeNull();
    }
  });
});

test.describe("방 개수", () => {
  test("방 n개 · 방이 세 개 · 쓰리룸", () => {
    const cases: [string, number][] = [
      ["노원구 상계주공 32평 방 3개예요", 3],
      ["방3개 화장실2개", 3],
      ["방이 2개고 욕실 1개", 2],
      ["방 4 욕실 2", 4],
      ["방이 세 개예요", 3],
      ["방 두개짜리", 2],
      ["쓰리룸 아파트", 3],
      ["24평 투룸", 2],
      ["방 3개, 방은 3칸이에요", 3],
    ];
    for (const [said, n] of cases) expect(guessRooms(said), said).toBe(n);
  });

  test("못 찾거나 헷갈리면 비워요", () => {
    for (const said of [
      "노원구 상계동 푸른숲아파트 32평",
      "작은방 2개 도배",
      "안방 1개만 해요",
      "방 6개",
      "방 30평",
      "101동 1203호 방",
      "방 2개에서 방 3개로 늘렸어요",
      "화장실 2개",
    ]) {
      expect(guessRooms(said), said).toBeNull();
    }
  });
});

test.describe("공사 희망 시기", () => {
  test("이번 달 · 다음 달 · 2~3달 뒤", () => {
    const cases: [string, string][] = [
      ["이번 달 안에 하고 싶어요", "this_month"],
      ["이번달 말", "this_month"],
      ["다음 달에 이사해요", "next_month"],
      ["담달 초", "next_month"],
      ["한 달 뒤쯤", "next_month"],
      ["2~3달 뒤", "in_2_3_months"],
      ["2-3개월 후에요", "in_2_3_months"],
      ["두세 달 뒤", "in_2_3_months"],
      ["두 달 후", "in_2_3_months"],
      ["석 달 뒤 입주", "in_2_3_months"],
      ["3개월 후", "in_2_3_months"],
      ["다다음 달", "in_2_3_months"],
    ];
    for (const [said, key] of cases) expect(guessWhen(said), said).toBe(key);
  });

  test("못 찾거나 둘 이상이면 비워요", () => {
    for (const said of [
      "노원구 상계동 푸른숲아파트",
      "이번 달 말이나 다음 달 초",
      "1~2달 뒤",
      "12달 뒤",
      "3~4달 뒤",
      "내년 봄",
      "다음 주",
      "몇 달 뒤",
    ]) {
      expect(guessWhen(said), said).toBeNull();
    }
  });
});
