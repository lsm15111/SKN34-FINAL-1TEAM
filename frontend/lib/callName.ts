// 비서 글의 '고객님'을 로그인한 사람 이름으로 바꿔 그려요('지은 님'이 아니라 등록한 이름 그대로 '김지은 님').
// 이름은 LLM에 보내지 않아요(docs/v4/08-rules.md 고정 선 3). 모델은 '고객님'으로 쓰고, 저장 · LLM 기록도 '고객님' 그대로예요.
// 이름이 없거나 이상하면(숫자 · 기호 · 너무 김 · '님'으로 끝남) '고객님' 그대로 둬요.
// '다른 고객님 · 여러 고객님 · 고객님들'처럼 이 사람이 아닌 말은 바꾸지 않아요. 둘 다 '님'으로 끝나 뒤 조사는 그대로 맞아요.

const NAME = /^[가-힣A-Za-z]+(?: [가-힣A-Za-z]+)?$/;
const NAME_MAX = 12;
const ME = /(?<!(?:다른|여러|모든|많은|어느|어떤|몇몇)\s?)고객님(?!들)/g;

/** 부를 수 있는 이름(앞뒤 · 겹친 빈칸 정리). 이상하면 null */
export function callableName(name: string | null | undefined): string | null {
  const n = (name ?? "").trim().replace(/\s+/g, " ");
  if (!n || n.length > NAME_MAX || !NAME.test(n) || n.endsWith("님")) return null;
  return n;
}

/** 비서 글 → 그릴 글: '고객님'을 '○○ 님'으로(부를 수 없는 이름이면 그대로) */
export function callName(text: string, name: string | null | undefined): string {
  const n = callableName(name);
  return n ? text.replace(ME, `${n} 님`) : text;
}
