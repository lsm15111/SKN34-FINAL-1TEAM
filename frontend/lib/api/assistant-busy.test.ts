// 턴 POST 넘침(503 busy · unavailable): Retry-After를 읽어 TurnBusy로 던지고(부르는 쪽이 같은 client_key로 한 번 다시 보내요),
// 그 밖 오류는 그대로 ApiError예요. 서버 · 브라우저 없이 fetch만 바꿔 봐요.
import { expect, test } from "@playwright/test";
import { ApiError } from "@/lib/backend/client";
import { BUSY_TEXT, busyWaitMs, streamTurn, TurnBusy } from "./assistant";

const BODY = { project_id: "p1", client_key: "k-12345678", text: "오늘 뭐 하면 돼요?" };

async function refused(status: number, code: string, retryAfter: string | null): Promise<unknown> {
  const real = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ error: { code, message: "지금 묻는 분이 많아요. 잠시 뒤 다시 해 주세요." } }), {
      status,
      headers: { "content-type": "application/json", ...(retryAfter === null ? {} : { "retry-after": retryAfter }) },
    });
  try {
    await streamTurn(BODY, () => undefined);
    return null;
  } catch (e) {
    return e;
  } finally {
    globalThis.fetch = real;
  }
}

test("Retry-After 초를 기다릴 ms로(없거나 이상하면 2초, 길어도 10초)", () => {
  expect(busyWaitMs("5")).toBe(5000);
  expect(busyWaitMs("1")).toBe(1000);
  expect(busyWaitMs("600")).toBe(10000);
  for (const bad of [null, "", "0", "-3", "soon"]) expect(busyWaitMs(bad)).toBe(2000);
});

test("503 busy · unavailable은 TurnBusy(기다릴 때 포함)예요", async () => {
  for (const code of ["busy", "unavailable"]) {
    const e = await refused(503, code, "5");
    expect(e).toBeInstanceOf(TurnBusy);
    expect(e).toBeInstanceOf(ApiError);
    expect((e as TurnBusy).waitMs).toBe(5000);
    expect((e as TurnBusy).code).toBe(code);
  }
});

test("그 밖 오류는 그대로 ApiError예요", async () => {
  for (const [status, code] of [[409, "turn_running"], [429, "too_many"], [503, "server_error"], [500, "server_error"]] as const) {
    const e = await refused(status, code, "5");
    expect(e).toBeInstanceOf(ApiError);
    expect(e).not.toBeInstanceOf(TurnBusy);
  }
});

test("다시 보내도 넘칠 때 안내는 '-해요'체 한 줄이에요", () => {
  expect(BUSY_TEXT).toMatch(/요\.$/);
  expect(BUSY_TEXT).not.toMatch(/[A-Za-z]/);
});
