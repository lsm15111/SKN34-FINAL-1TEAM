// v5 기능 확인(서버, 한 요청에 한 번): dev 백엔드에 없는 v4 기능을 켤지 정해요(사용자 결정: 백엔드가 생길 때까지 숨기기).
// - GET /guest/start-options가 200이면 v4 백엔드가 붙은 것으로 봐요. 404 · 연결 실패면 꺼요.
// - 켜지는 것: 방 개수 · 철거 범위 · 직접 할 일 칸(그리기 · 요청 몸통에 넣기), 공사 희망 시기 칩, 방 개수 표(GET /guest/room-rule),
//   모은 조건(GET /projects/{id}/conditions) · 직접 할 일 고치기(PUT /projects/{id}/diy).
// - 브라우저 조각은 Caps 타입만 가져가요(값은 페이지가 props로 넘겨요).
import { cache } from "react";
import { serverGet } from "@/lib/backend/server";
import type { Schemas } from "./types";

export type Caps = { v4: boolean };

/** 기능 확인 + 공사 희망 시기 칩(같은 요청 값이라 한 번만 물어요) */
export const getCaps = cache(async (): Promise<Caps & { wishes: Schemas["StartWishOut"][] }> => {
  try {
    const wishes = await serverGet<Schemas["StartWishOut"][]>("/guest/start-options");
    return Array.isArray(wishes) ? { v4: true, wishes } : { v4: false, wishes: [] };
  } catch {
    return { v4: false, wishes: [] };
  }
});
