// AI 답 글 작은 마크다운(lib/richText): 굵게 · 줄바꿈 · '- ' 목록만, 별표가 화면에 남지 않아요
import { expect, test } from "@playwright/test";
import { blocks, spans } from "./richText";

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
