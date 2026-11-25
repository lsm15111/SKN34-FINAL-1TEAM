// 브라우저 쓰기 한 곳(B2b 화면). 진짜면 lib/backend/client.ts call()로 /api/*에 보내고,
// 예시 데이터(MOCK_V3B)면 보내지 않고 9판 이야기의 다음 단계로 넘겨요(쿠키 mj_v3b_step → 화면이 다시 읽음).
// 예시에 없는 쓰기는 보내지 않고 '예시 데이터라 보내지 않았어요'를 오류로 돌려줘요(거짓으로 됐다고 하지 않아요).
import { ApiError, call } from "@/lib/backend/client";
import { MOCK_V3B, STEP_COOKIE, type StepKey } from "./mode";

type Method = "POST" | "PUT" | "PATCH" | "DELETE";
export type MockPlan<T> = { step?: StepKey; result?: T };

export function setMockStep(step: StepKey) {
  document.cookie = `${STEP_COOKIE}=${step}; path=/; max-age=86400; samesite=lax`;
}

export async function send<T = unknown>(method: Method, path: string, body?: unknown, mock?: MockPlan<T>, headers?: Record<string, string>): Promise<T> {
  if (!MOCK_V3B) return call<T>(method, path, body, headers);
  await new Promise((r) => setTimeout(r, 250));
  if (!mock) throw new ApiError(0, "mock", "예시 데이터라 보내지 않았어요.");
  if (mock.step) setMockStep(mock.step);
  return mock.result as T;
}

/** 파일 올리기(POST /files, multipart). 예시면 올리지 않고 가짜 id를 돌려줘요 */
export async function upload(file: File, kind: string): Promise<{ id: string; filename: string; size: number }> {
  if (MOCK_V3B) {
    await new Promise((r) => setTimeout(r, 250));
    return { id: crypto.randomUUID(), filename: file.name, size: file.size };
  }
  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("file", file);
  return call("POST", "/files", fd);
}
