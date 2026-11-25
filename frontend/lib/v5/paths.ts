// v5 화면 주소. 고객 흐름(홈 · 인테리어 받기 · 내 공사 · 한 공사 화면)은 /v5 아래에서 이어요.
// 업체 화면 · 채팅 · 백과 · 알림 · 내 정보 · 로그인 · 가입 · 자주 묻는 질문은 dev 주소 그대로예요.
// 서버가 dev 주소로 준 링크(할 일 todo.link · 서류 link 등)를 v5 주소로 바꿀 때 써요. API 경로에는 쓰지 않아요.

/** dev 고객 흐름 주소 → v5 주소('/' → '/v5', '/projects/…' → '/v5/projects/…'). 그 밖의 주소는 그대로 */
export function v5Href(href: string): string {
  if (href === "/") return "/v5";
  if (/^\/[?#]/.test(href)) return `/v5${href.slice(1)}`;
  if (/^\/(?:start|my|projects)(?=[/?#]|$)/.test(href)) return `/v5${href}`;
  return href;
}
