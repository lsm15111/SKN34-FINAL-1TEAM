// 겉모양 스위치(서버): v4 비서 화면 ↔ v3 화면. 같은 경로에서 겉모양만 바꿔 나란히 견줘 볼 수 있어요.
// - 쿠키 mj_ui(v3 · v4)가 있으면 그 값, 없으면 NEXT_PUBLIC_UI, 그것도 없으면 v4(기본값은 리드가 정해요).
// - 쿠키는 머리 메뉴 '이전 화면(v3)으로' · v3 화면 위 개발용 띠 '비서 화면(v4)으로'가 바꿔요(UiSwitch).
import { cookies } from "next/headers";

export type UiMode = "v3" | "v4";
export const UI_COOKIE = "mj_ui";
export const UI_DEFAULT: UiMode = process.env.NEXT_PUBLIC_UI === "v3" ? "v3" : "v4";
/** v3 화면에 '비서 화면(v4)으로' 띠를 보일지(개발 서버 · 또는 NEXT_PUBLIC_UI_SWITCH=1) */
export const UI_SWITCH_BAR = process.env.NODE_ENV !== "production" || process.env.NEXT_PUBLIC_UI_SWITCH === "1";

export async function uiMode(): Promise<UiMode> {
  const v = (await cookies()).get(UI_COOKIE)?.value;
  return v === "v3" || v === "v4" ? v : UI_DEFAULT;
}

/** 머리 메뉴 '이전 화면으로 보기'로 v3를 골랐는지(쿠키 mj_ui=v3). 골랐으면 운영 빌드에서도 v3 화면 위에
 *  '비서 화면(v4)으로' 띠를 보여 되돌아갈 수 있게 해요(2026-11-23 사용자: 잘못 눌러 v3로 바뀐 뒤 돌아갈 길이 없었어요) */
export async function uiChoseV3(): Promise<boolean> {
  return (await cookies()).get(UI_COOKIE)?.value === "v3";
}
