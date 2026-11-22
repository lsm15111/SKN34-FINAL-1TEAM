// 고침 4차 P(QA r4 x1 관찰 1): 비서 입력 칸. 보이지 않는 글자만 있는 글은 보내기 단추를 끄고(canSend · sayable),
// 서버 422가 오면 칸 글('보낼 말을 적어 주세요.')을 그대로 보여요(turnErrorText). 서버 · 브라우저 없이 순수 함수와 fetch만 봐요.
import { expect, test } from "@playwright/test";
import { ApiError } from "@/lib/backend/client";
import { canSend, sayable, streamTurn, turnErrorText } from "./assistant";

const ch = (...cps: number[]) => String.fromCodePoint(...cps);
const ZW = ch(0x200b), FILLER = ch(0x3164), BOM = ch(0xfeff), WJ = ch(0x2060), NUL = ch(0), IDEO = ch(0x3000);
// x1이 서버에 보낸 네 꼴(모두 422) + 다른 보이지 않는 글자
const ONLY_HIDDEN = [
  ZW + ZW, FILLER, BOM, `${ZW} ${FILLER}${BOM}${NUL}${IDEO}`, BOM + WJ, ` ${ZW} ${FILLER} `,
  ch(0x115f), ch(0x1160), ch(0xffa0), ch(0x00ad), ch(0x2800), ch(0x200e), ch(0x2068, 0x2069), ch(0xfe0f), ch(0xe0001),
];
const BLANK = "보낼 말을 적어 주세요.";

test("보이지 않는 글자 · 빈칸만 있는 글은 보내기 단추가 꺼져요", () => {
  for (const t of [...ONLY_HIDDEN, "", "   ", "\n\t"]) {
    expect(sayable(t), JSON.stringify(t)).toBe("");
    expect(canSend(t, false), JSON.stringify(t)).toBe(false);
  }
});

test("보이는 글자가 있으면 켜지고, 답을 만드는 중이면 꺼져요", () => {
  const heart = ch(0x2764, 0xfe0f);
  const family = ch(0x1f468, 0x200d, 0x1f469, 0x200d, 0x1f467);
  for (const t of ["도배 언제요?", `${ZW}연락처 010${ZW}1234${ZW}5678로 주세요${FILLER}`, heart, family, "1"]) {
    expect(canSend(t, false), JSON.stringify(t)).toBe(true);
    expect(canSend(t, true)).toBe(false);
  }
  expect(sayable(`${ZW} 도배${FILLER} 언제요 ${BOM}`)).toBe("도배 언제요");
});

test("422는 서버 칸 글을 그대로, 영어 칸 글 · 다른 오류는 오류 문장이에요", () => {
  const invalid = (msgs: string[]) => new ApiError(422, "invalid", "입력한 내용을 확인해 주세요.", msgs.map((msg) => ({ loc: ["text"], msg })));
  expect(turnErrorText(invalid([BLANK]))).toBe(BLANK);
  expect(turnErrorText(invalid([BLANK, BLANK]))).toBe(BLANK); // 같은 글은 한 번
  expect(turnErrorText(invalid(["String should have at most 1000 characters"]))).toBe("입력한 내용을 확인해 주세요.");
  expect(turnErrorText(new ApiError(422, "invalid", "입력한 내용을 확인해 주세요."))).toBe("입력한 내용을 확인해 주세요.");
  expect(turnErrorText(new ApiError(404, "not_found", "공사를 찾지 못했어요."))).toBe("공사를 찾지 못했어요.");
  expect(turnErrorText(new Error("x"))).toBe("잠시 문제가 생겼어요. 다시 해 주세요.");
});

test("턴 POST 422의 칸 글(fields)이 ApiError에 실려 화면 글이 돼요", async () => {
  const real = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ error: { code: "invalid", message: "입력한 내용을 확인해 주세요.", fields: [{ loc: ["text"], msg: BLANK }] } }), {
      status: 422, headers: { "content-type": "application/json" },
    });
  let got: unknown = null;
  try {
    await streamTurn({ project_id: "p1", client_key: "k-12345678", text: ZW + ZW }, () => undefined);
  } catch (e) {
    got = e;
  } finally {
    globalThis.fetch = real;
  }
  expect(got).toBeInstanceOf(ApiError);
  expect((got as ApiError).status).toBe(422);
  expect((got as ApiError).fields).toEqual([{ loc: ["text"], msg: BLANK }]);
  expect(turnErrorText(got)).toBe(BLANK);
});
