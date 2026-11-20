// 브라우저 → API: 손님 계산 · 가입 뒤 답 옮기기 · 동 목록. 쓰기는 모두 같은 주소 /api/*(lib/backend/client.ts)예요.
// mock(개발 예시)이면 API 대신 lib/mock/v3a 값을 써요. 예시 모듈은 그때만 불러와요(운영 화면 묶음에 넣지 않게).
import { ApiError, call, type Schemas } from "@/lib/backend/client";
import { readGuest, clearGuest, draftOf } from "./store";
import { checkDraft, projectName, stepName, toHomeInfo, type HomeBody } from "./info";

export type GuestStandard = Schemas["GuestStandardOut"];

/**
 * 집 정보 몸통 보내기(POST /guest/standard · POST /projects · PATCH /projects/{id}).
 * 철거 범위(demolition)는 백엔드 담당이 같은 키로 더하는 중이라, 아직 그 칸을 모르는 서버(422, fields에 demolition)면 그 칸만 빼고 한 번 더 보내요.
 */
export async function sendHome<T>(method: "POST" | "PATCH", path: string, body: HomeBody, headers?: Record<string, string>): Promise<T> {
  try {
    return await call<T>(method, path, body, headers);
  } catch (e) {
    const unknownKey = e instanceof ApiError && e.status === 422 && (e.fields ?? []).some((f) => f.loc.includes("demolition"));
    if (body.demolition === undefined || !unknownKey) throw e;
    const { demolition: _skip, ...rest } = body;
    return call<T>(method, path, rest, headers);
  }
}

/** 로그인 없이 표준견적서 계산(POST /guest/standard). 서버가 저장하지 않아요 */
export async function calcGuest(info: HomeBody, mock: boolean): Promise<GuestStandard> {
  if (mock) return (await import("@/lib/mock/v3a/standard")).mockGuestStandard(info);
  return sendHome<GuestStandard>("POST", "/guest/standard", info);
}

/** 기기에 둔 답이 다 찼으면 그 API 몸통 */
export function guestBody(): { key: string; body: HomeBody } | null {
  const g = readGuest();
  if (!g) return null;
  const d = draftOf(g);
  return Object.keys(checkDraft(d)).length ? null : { key: g.key, body: toHomeInfo(d) };
}

/**
 * 가입 · 로그인 뒤 기기 답을 내 공사로 옮겨요(dev-03): POST /projects + Idempotency-Key(기기 답의 key).
 * 같은 키를 두 번 보내도 공사는 하나예요(서버가 처음 것을 돌려줘요). 성공하면 기기 답을 지워요. 옮길 답이 없으면 null.
 */
export async function moveGuest(mock: boolean): Promise<{ id: string } | null> {
  const g = guestBody();
  if (!g) return null;
  if (mock) {
    const { MOCK_PROJECT } = await import("@/lib/mock/v3a/mode");
    clearGuest();
    return { id: g.body.scope === "partial" ? MOCK_PROJECT.part : MOCK_PROJECT.full };
  }
  const p = await sendHome<Schemas["ProjectOut"]>("POST", "/projects", g.body, { "Idempotency-Key": g.key });
  clearGuest();
  return { id: p.id };
}

/** 로그인한 고객의 진행 중 공사(이어 하기 창 C41). 못 읽으면 빈 목록 */
/** 진행 중 공사(이어 하기 창 C41) */
export type Ongoing = { id: string; name: string; step: string; href?: string };

export async function myOngoing(): Promise<Ongoing[]> {
  try {
    const list = await call<Schemas["MyProjectOut"][]>("GET", "/projects");
    return list.filter((p) => p.phase !== "done").map((p) => ({ id: p.id, name: projectName(p.emd, p.region, p.trades), step: stepName(p.current) }));
  } catch {
    return [];
  }
}

/** 읍면동 목록(GET /regions/{sido}/{sgg}). 자료가 아직 없으면(501 · 404) null → 화면은 동 이름을 직접 받아요 */
export async function loadEmds(sido: string, sgg: string, mock: boolean): Promise<string[] | null> {
  if (mock) {
    const m: Record<string, string[]> = {
      노원구: ["공릉동", "상계동", "월계동", "중계동", "하계동"],
      강북구: ["미아동", "번동", "수유동", "우이동"],
      도봉구: ["도봉동", "방학동", "쌍문동", "창동"],
    };
    return m[sgg] ?? null;
  }
  try {
    const list = await call<Schemas["EmdOut"][]>("GET", `/regions/${encodeURIComponent(sido)}/${encodeURIComponent(sgg)}`);
    return list.length ? list.map((e) => e.name) : null;
  } catch {
    return null;
  }
}

/** 화면에 보일 오류 글: 0단계 뼈대(501)는 '아직 준비 중이에요' 그대로 */
export function moveErrorText(e: unknown): string {
  return e instanceof ApiError ? e.message : "잠시 문제가 생겼어요. 다시 해 주세요.";
}
