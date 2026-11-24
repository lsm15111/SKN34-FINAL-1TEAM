// QA r10 u1 화면 고침(갈래 H4). 서버 · 브라우저 없이 순수 함수만 봐요(pnpm test:unit).
// - U2: 끝내 잇지 못한 턴(서버 일꾼이 죽어 멈춤 · 같은 client_key 409 turn_running 되풀이) 뒤 기록을 다시 읽었을 때, 보낸 말이 서버
//   기록에 없으면 대화 끝에 안내 한 줄을 두고 입력 칸에 글을 되살려요(afterLost · saidKept).
// - U5: 도배 전 점검 카드는 보낸 때 값이라, 앞 공사 답을 저장한 뒤 다시 열면 단추가 비어 보였어요 → 실행된 승인 카드 값으로 골라진 모양(preworkSaved).
// - U4: 받은 견적서 점검 · 벽지 두 종류 비교 카드 금액은 한 덩어리('309만 1,076원'이 숫자 가운데서 줄이 바뀌지 않게, oneLine).
import { expect, test } from "@playwright/test";
import { diffText, rowParts } from "@/lib/assistant/outside";
import { oneLine, won, wonDelta } from "@/lib/format";
import {
  afterLost, lastActionIn, preworkSaved, preworkSend, saidKept, UNSENT_TEXT,
  type ActionOut, type AssistantItem, type FeedItem, type OutsideRow, type PreworkRow,
} from "./assistant";

const SAID = "동네 지업사 견적이에요. 실크벽지 1,150,000 / 도배 인건비 1,400,000 / 합계 2,700,000 (부가세 별도). 괜찮은 건가요?";
const T0 = "2026-11-25T02:40:00+09:00"; // 보낸 때 화면이 아는 서버 시각
const T1 = "2026-11-25T02:41:12.123456+09:00"; // 턴 시작(ack at)
const user = (id: string, at: string, text: string): FeedItem => ({ id, role: "user", at, text });
const ai = (id: string, at: string, turnId: string | null, extra: Partial<AssistantItem> = {}): AssistantItem =>
  ({ id, role: "assistant", at, turn_id: turnId, parts: [{ t: "text", text: "답이에요.", src: "ai" }], ...extra });
const BEFORE: FeedItem[] = [user("u-1", "2026-11-25T02:30:00+09:00", "예산은 250만 원 안쪽이에요"), ai("a-1", "2026-11-25T02:30:00+09:00", "t-1")];

test("U2 재현: 턴이 멈춰 다시 읽은 기록에 보낸 말이 없으면 입력 칸에 되살리고 안내 한 줄을 둬요", () => {
  // 서버 턴은 아직 running(죽은 일꾼) → 기록에 그 턴 말도 고객 말도 없어요
  const said = { text: SAID, turnId: "t-9", since: T1 };
  expect(saidKept(BEFORE, said)).toBe(false);
  expect(afterLost(BEFORE, said)).toEqual({ restore: true, notice: UNSENT_TEXT });
  // ack 전에 끊겨 턴 번호를 몰라도 같아요
  expect(afterLost(BEFORE, { text: SAID, turnId: null, since: T0 })).toEqual({ restore: true, notice: UNSENT_TEXT });
});

test("U2: 답까지 저장됐으면 기록대로 두고 되살리지 않아요", () => {
  const page = [...BEFORE, user("u-2", T1, SAID), ai("a-2", T1, "t-9")];
  expect(afterLost(page, { text: SAID, turnId: "t-9", since: T1 })).toEqual({ restore: false, notice: null });
  // 턴 번호를 몰라도 보낸 때 뒤 같은 글 고객 말이 있으면 남았어요
  expect(afterLost(page, { text: SAID, turnId: null, since: T0 })).toEqual({ restore: false, notice: null });
});

test("U2: 실패한 턴은 서버가 남긴 고객 말(실패 말과 같은 때)이 있을 때만 남은 거예요", () => {
  const failed = ai("f-t-9", T1, "t-9", { parts: [], error: { code: "llm", message: "답을 끝까지 만들지 못했어요. 다시 해 주세요." } });
  // 서버가 고객 말을 남김(가린 글이라 보낸 글과 달라도)
  expect(saidKept([...BEFORE, user("u-2", T1, "가린 글"), failed], { text: SAID, turnId: "t-9", since: T1 })).toBe(true);
  // 멈춤으로 닫혀 고객 말이 없음
  expect(afterLost([...BEFORE, failed], { text: SAID, turnId: "t-9", since: T1 })).toEqual({ restore: true, notice: UNSENT_TEXT });
});

test("U2: 보낸 때 앞의 같은 글은 이번 말이 아니에요", () => {
  const old = [user("u-0", "2026-11-25T01:00:00+09:00", SAID), ...BEFORE];
  expect(saidKept(old, { text: SAID, turnId: null, since: T0 })).toBe(false);
});

test("U2: 기록을 다시 읽지 못하면 남았는지 몰라 글만 되살려요(끊김 안내는 그대로)", () => {
  expect(afterLost(null, { text: SAID, turnId: "t-9", since: T1 })).toEqual({ restore: true, notice: null });
});

test("U2: 안내는 '-해요'체 한 줄이에요", () => {
  expect(UNSENT_TEXT).toBe("보내지 못했어요. 다시 보내 주세요.");
  expect(UNSENT_TEXT).not.toMatch(/[A-Za-z\n]/);
});

const ROW = (key: PreworkRow["key"], label: string, state: PreworkRow["state"] = null): PreworkRow => ({ key, label, state, why: "왜" });
const CARD_ROWS = [ROW("mokgong", "목공"), ROW("electric", "전기"), ROW("film", "필름"), ROW("floor", "바닥")];
const prework = (id: string, status: ActionOut["status"], rows: { label: string; value: string }[]): ActionOut => ({
  action_id: id, kind: "prework", status, target_id: "p1", target_ver: "p", expires_at: "2026-12-02T02:43:00+09:00",
  summary: { title: "앞 공사 답 저장", rows: rows.map((r) => ({ ...r, sub: "지금 고르지 않음" })), approve_label: "맞아요, 저장" },
});
const feedWith = (...acts: ActionOut[]): FeedItem[] => acts.map((a, i) => ai(`a-${i}`, T1, `t-${i}`, { parts: [{ t: "action", action: a }] }));
const savedBy = (items: FeedItem[]) => (label: string) =>
  lastActionIn(items, "prework", (a) => a.status === "executed" && !!a.summary.rows?.some((x) => x.label === label));

test("U5 재현: 저장한 앞 공사 답은 다시 열어도 그 단추가 골라진 모양이에요", () => {
  const items = feedWith(prework("x1", "executed", [{ label: "목공", value: "끝났어요" }, { label: "전기", value: "안 해요" }, { label: "바닥", value: "아직이에요" }]));
  const rows = preworkSaved(CARD_ROWS, savedBy(items));
  expect(rows.map((r) => r.state)).toEqual(["done", "none", null, "todo"]);
  // 저장된 답과 같은 고르기는 다시 보내지 않아요
  expect(preworkSend(rows, { mokgong: "done", floor: "todo" })).toBeNull();
});

test("U5: 가장 나중에 실행한 답이 이기고, 실행 전 · 거절한 카드는 보지 않아요", () => {
  const items = feedWith(
    prework("x1", "executed", [{ label: "바닥", value: "아직이에요" }]),
    prework("x2", "executed", [{ label: "바닥", value: "끝났어요" }]),
    prework("x3", "rejected", [{ label: "목공", value: "안 해요" }]),
    prework("x4", "proposed", [{ label: "전기", value: "끝났어요" }]),
  );
  expect(preworkSaved(CARD_ROWS, savedBy(items)).map((r) => r.state)).toEqual([null, null, null, "done"]);
  // 승인 카드가 없으면 카드 때 값 그대로(같은 배열)
  const saved = [ROW("mokgong", "목공", "done"), ...CARD_ROWS.slice(1)];
  expect(preworkSaved(saved, savedBy([]))).toEqual(saved);
});

const LINE: OutsideRow = { key: "labor", name: "인건비", state: "less", outside_won: 1540000, standard_won: 1781871, diff_won: -241871, lines: [] };

test("U4: 금액은 한 덩어리(만 · 원 사이를 줄이 안 바뀌는 빈칸으로), 이름과 금액 사이는 그대로 줄이 바뀌어요", () => {
  const one = oneLine(won);
  expect(one(3091076)).toBe("309만 1,076원");
  expect(one(1540000)).toBe("154만 원");
  expect(one(-121076)).toBe("−12만 1,076원");
  expect(one(9800)).toBe("9,800원");
  expect(diffText(-241871, one)).toBe("−24만 1,871원");
  expect(rowParts(LINE, one)).toEqual(["견적서 154만 원", "표준 178만 1,871원"]);
  expect(oneLine(wonDelta)(500560)).toBe("+50만 560원");
  // 보통 금액 말(won)은 그대로예요
  expect(won(3091076)).toBe("309만 1,076원");
});
