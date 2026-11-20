// v4 비서 목업 스위치. 비서 API(백엔드 assistant/)가 아직 없어서 기본은 목업이에요.
// - NEXT_PUBLIC_ASSISTANT=live면 lib/api/assistant.ts가 실제 /api/assistant/*를 불러요(백엔드가 붙으면 기본을 live로 바꿔요).
// - 목업은 lib/mock/assistant/server.ts가 같은 모양의 값 · 같은 SSE 이벤트를 대본으로 흘려요. 화면 코드는 이 값을 직접 보지 않아요.
export const ASSISTANT_MOCK = process.env.NEXT_PUBLIC_ASSISTANT !== "live";

/** 목업 대본: 처음 고객(F1) · 오늘 정할 일 */
export type MockScript = "f1" | "today";
export const MOCK_SCRIPTS: { key: MockScript; label: string }[] = [
  { key: "f1", label: "처음 고객" },
  { key: "today", label: "오늘 정할 일" },
];
