// 브라우저에서 FastAPI를 부른다. 같은 주소의 /api/*로 보내고(개발 Next, 운영 Caddy가 넘김), 로그인 쿠키는 브라우저가 붙인다.
// 오류는 API가 주는 {"error": {code, message, fields?}}를 ApiError로 바꿔 던진다. message는 화면에 그대로 보여도 되는 문장이다.
import type { components } from "./schema";

export type Schemas = components["schemas"];
export type FieldError = { loc: string[]; msg: string };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public fields?: FieldError[]) {
    super(message);
  }
}

/** 화면에 보일 오류 문장 */
export function errorText(e: unknown) {
  return e instanceof ApiError ? e.message : "잠시 문제가 생겼어요. 다시 해 주세요.";
}

// 주소 속 값(화면 경로의 id 등)에 '..' · 인코딩한 빗금 · 역빗금이 섞이면 다른 API를 내 쿠키로 부르게 된다(CSPT).
// 경로 조각은 encodeURIComponent로 넣고, 여기서는 그런 경로를 보내지 않는다. 물음표 뒤(검색어)는 보지 않는다.
const BAD_PATH = /(^|\/)(\.|%2e){1,2}(\/|$)|%2f|%5c|\\/i;

export function isSafeApiPath(path: string): boolean {
  const p = path.split(/[?#]/)[0];
  return p.startsWith("/") && !p.startsWith("//") && !BAD_PATH.test(p);
}

/** headers: 멱등 키(Idempotency-Key)처럼 요청마다 붙일 머리 */
export async function call<T = unknown>(method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE", path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  if (!isSafeApiPath(path)) throw new ApiError(0, "bad_path", "요청을 처리하지 못했어요.");
  const init: RequestInit = { method, credentials: "same-origin", headers: { ...headers } };
  if (body instanceof FormData) init.body = body; // 경계값이 붙은 Content-Type은 브라우저가 정한다
  else if (body !== undefined) { init.body = JSON.stringify(body); init.headers = { ...headers, "content-type": "application/json" }; }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "network", "서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (res.ok) return data as T;
  const e = data?.error;
  if (e?.message) throw new ApiError(res.status, e.code ?? "unknown", e.message, e.fields);
  if (res.status === 413) throw new ApiError(413, "too_large", "파일이 너무 커요.");
  throw new ApiError(res.status, "unknown", res.status >= 500 ? "잠시 문제가 생겼어요. 다시 해 주세요." : "요청을 처리하지 못했어요.");
}
