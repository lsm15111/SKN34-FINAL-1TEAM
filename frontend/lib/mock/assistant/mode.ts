// v4 비서 목업 스위치. 기본은 실제 비서 API(/api/assistant/* · /api/vendor/assistant/*)예요.
// - 목업은 NEXT_PUBLIC_ASSISTANT=mock이거나, 개발 서버를 NEXT_PUBLIC_MJ_MOCK=1로 띄웠을 때만 써요(v3 예시 데이터와 같은 이름).
// - 목업은 lib/mock/assistant/server.ts가 같은 모양의 값 · 같은 SSE 이벤트를 대본으로 흘려요. 화면 코드는 이 값을 직접 보지 않아요.
const DEV_MOCK = process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_MJ_MOCK === "1";
export const ASSISTANT_MOCK = DEV_MOCK || process.env.NEXT_PUBLIC_ASSISTANT === "mock";

/** 목업 대본: 처음 고객(F1) · 오늘 정할 일 */
export type MockScript = "f1" | "today";
export const MOCK_SCRIPTS: { key: MockScript; label: string }[] = [
  { key: "f1", label: "처음 고객" },
  { key: "today", label: "오늘 정할 일" },
];
