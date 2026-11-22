// AI 답 글 작은 마크다운(lib/richText): 굵게 · 줄바꿈 · '- ' 목록만, 별표가 화면에 남지 않아요
import { expect, test } from "@playwright/test";
import { blocks, bubbles, spans } from "./richText";

const b = (text: string) => ({ text, bold: true });
const n = (text: string) => ({ text, bold: false });

test("굵게는 별표 없이 굵은 조각이에요", () => {
  expect(spans("**도배 전:** 덮개를 떼어 두세요")).toEqual([b("도배 전:"), n(" 덮개를 떼어 두세요")]);
  expect(spans("가격은 **부가세 포함**이에요")).toEqual([n("가격은 "), b("부가세 포함"), n("이에요")]);
  expect(spans("별표 없는 글")).toEqual([n("별표 없는 글")]);
});

test("닫는 별표가 아직 안 왔으면 줄 끝까지 굵게 보여요", () => {
  expect(spans("**도배 전")).toEqual([b("도배 전")]);
  expect(spans("a **b** c **d")).toEqual([n("a "), b("b"), n(" c "), b("d")]);
});

test("LLM 모드 답(L-F3-04): 첫 줄 · 목록 두 줄 · 끝 줄", () => {
  const text = [
    "두 단계로 나눠서 하시면 돼요.",
    "- **도배 전:** 기존 콘센트·스위치 덮개를 떼어 두세요.",
    "- **도배 후:** 도배가 끝나면 새 커버를 다시 붙이세요.",
    "덮개를 누가 떼고 붙일지는 실측 때 도배 업체에 확인해 보세요.",
  ].join("\n");
  expect(blocks(text)).toEqual([
    { t: "p", lines: [[n("두 단계로 나눠서 하시면 돼요.")]] },
    {
      t: "list",
      items: [
        [b("도배 전:"), n(" 기존 콘센트·스위치 덮개를 떼어 두세요.")],
        [b("도배 후:"), n(" 도배가 끝나면 새 커버를 다시 붙이세요.")],
      ],
    },
    { t: "p", lines: [[n("덮개를 누가 떼고 붙일지는 실측 때 도배 업체에 확인해 보세요.")]] },
  ]);
});

test("줄바꿈은 한 문단 안의 줄, 빈 줄은 문단 나누기예요", () => {
  expect(blocks("첫 줄\n둘째 줄\n\n새 문단\r\n끝")).toEqual([
    { t: "p", lines: [[n("첫 줄")], [n("둘째 줄")]] },
    { t: "p", lines: [[n("새 문단")], [n("끝")]] },
  ]);
});

test("* · • 목록과 # 제목 줄도 기호 없이 보여요", () => {
  expect(blocks("### 준비물\n* 보양 비닐\n• 사다리")).toEqual([
    { t: "p", lines: [[b("준비물")]] },
    { t: "list", items: [[n("보양 비닐")], [n("사다리")]] },
  ]);
});

test("글 안의 하이픈 · 숫자 목록은 그대로 둬요", () => {
  expect(blocks("12-14일 사이\n1. 짐 정리\n-하이픈")).toEqual([
    { t: "p", lines: [[n("12-14일 사이")], [n("1. 짐 정리")], [n("-하이픈")]] },
  ]);
  expect(blocks("")).toEqual([]);
  expect(blocks("\n\n")).toEqual([]);
});

test("말풍선: 빈 줄마다 나눠요(말풍선 안 줄바꿈은 그대로)", () => {
  expect(bubbles("세 곳을 골라 왔어요!\n\n가견적은 실측 전 값이에요.\n값을 먼저 보시려면 결도배예요.\n\n어느 곳에 요청할까요?")).toEqual([
    "세 곳을 골라 왔어요!",
    "가견적은 실측 전 값이에요.\n값을 먼저 보시려면 결도배예요.",
    "어느 곳에 요청할까요?",
  ]);
  expect(bubbles("하나예요.\n \n\n둘이에요.")).toEqual(["하나예요.", "둘이에요."]);
});

test("말풍선: 빈 줄이 없는 옛 답은 줄마다, 줄도 없으면 하나예요", () => {
  expect(bubbles("첫 줄이에요.\n둘째 줄이에요.")).toEqual(["첫 줄이에요.", "둘째 줄이에요."]);
  expect(bubbles("한 덩어리 답이에요. 두 문장이에요.")).toEqual(["한 덩어리 답이에요. 두 문장이에요."]);
  expect(bubbles("  \n ")).toEqual([]);
});

test("말풍선: 목록이 든 글은 줄로 나누지 않아요", () => {
  expect(bubbles("챙길 것은 셋이에요.\n- 고무장갑\n- 마스킹 테이프")).toEqual(["챙길 것은 셋이에요.\n- 고무장갑\n- 마스킹 테이프"]);
  expect(bubbles("순서예요.\n1. 짐 빼기\n2. 도배")).toEqual(["순서예요.\n1. 짐 빼기\n2. 도배"]);
});
