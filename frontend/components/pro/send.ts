// 업체 · 관리자 화면의 쓰기(브라우저 → /api/*). 예시 데이터 모드에서는 API를 부르지 않고 잠깐 기다린 뒤 성공으로 돌려줘요.
// 예시 모드는 개발 서버에서만 켜져요(lib/mock/v3c/mode.ts). 운영에서는 늘 lib/backend/client.ts의 call()이에요.
// B7 규칙: 경로 속 id는 늘 enc()(encodeURIComponent)로 넣어요(CSPT). 두 번 눌러도 한 번만 돼야 하는 쓰기는
// { idem: 키 }로 Idempotency-Key 머리를 붙여요(화면이 키를 하나 만들어 두고, 다시 누르면 같은 키 → 처음 결과).
import { call, type Schemas } from "@/lib/backend/client";
import { MOCK } from "@/lib/mock/v3c/mode";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** 경로 조각(id)을 넣을 때 */
export const enc = encodeURIComponent;

export async function send<T = unknown>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  opts?: { idem?: string },
): Promise<T> {
  if (MOCK) {
    await wait(350);
    return {} as T;
  }
  return call<T>(method, path, body, opts?.idem ? { "Idempotency-Key": opts.idem } : undefined);
}

/** 파일 올리기(POST /files). 사진의 위치 정보는 서버가 지워요 */
export async function upload(kind: string, file: File): Promise<Schemas["FileOut"]> {
  if (MOCK) {
    await wait(400);
    return { id: newKey(), kind, filename: file.name, content_type: file.type || "application/octet-stream", size: file.size };
  }
  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("file", file, file.name);
  return call<Schemas["FileOut"]>("POST", "/files", fd);
}

/** 같은 요청을 두 번 보내도 한 번만 저장되게 붙이는 키(client_key · Idempotency-Key) */
export function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
