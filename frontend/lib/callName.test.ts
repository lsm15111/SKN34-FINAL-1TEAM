// 비서 글의 '고객님' → 로그인한 사람 이름('○○ 님'). 이상한 이름 · 다른 고객을 가리키는 말은 그대로예요.
import { expect, test } from "@playwright/test";
import { callableName, callName } from "./callName";

test("고객님을 이름으로 바꾸고 조사는 그대로예요", () => {
  expect(callName("고객님, 반가워요! 고객님은 누르기만 하시면 돼요.", "김지은")).toBe("김지은 님, 반가워요! 김지은 님은 누르기만 하시면 돼요.");
  expect(callName("고객님께서 고르신 업체예요.", " Kim  Minsu ")).toBe("Kim Minsu 님께서 고르신 업체예요.");
});

test("이름이 없거나 이상하면 고객님 그대로예요", () => {
  for (const bad of [null, undefined, "", "   ", "test01", "a@b.com", "010-1234-5678", "지은님", "가나다라마바사아자차카타파", "<b>김</b>"]) {
    expect(callableName(bad)).toBeNull();
    expect(callName("고객님, 반가워요!", bad)).toBe("고객님, 반가워요!");
  }
});

test("다른 고객을 가리키는 말은 바꾸지 않아요", () => {
  expect(callName("다른 고객님의 공사는 볼 수 없어요. 고객님 공사만 보여요.", "김지은")).toBe("다른 고객님의 공사는 볼 수 없어요. 김지은 님 공사만 보여요.");
  expect(callName("여러 고객님이 많이 시작해요.", "김지은")).toBe("여러 고객님이 많이 시작해요.");
  expect(callName("고객님들이 많이 골라요.", "김지은")).toBe("고객님들이 많이 골라요.");
});
