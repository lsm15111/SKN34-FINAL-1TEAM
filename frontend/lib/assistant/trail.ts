// 카드 창이 다닌 길(화면 쪽 순수 함수): 이 공사 화면(Shell)이 뜬 뒤 브라우저 기록과 같은 차례로 주소(pathname)를 적어요.
// 창 머리 '앞 화면으로'(한 칸 뒤)를 보일지, 닫기(바탕 · X · Esc)가 대화 자리까지 몇 칸 돌아갈지 이 길로 정해요.
// 주소가 바뀐 까닭: pop(뒤로 · 앞으로, popstate) · push(링크 · router.push) · replace(Shell이 부른 router.replace).
// 같은 주소 안 얕은 칸(?grade= 바꾸기 · ?photo= 크게 보기)은 세지 않아요. 한 칸을 더 세면 닫기가 대화 앞 화면까지 넘어가고,
// 덜 세면 닫기가 카드에 내려앉을 뿐이라(그때 Shell이 그 칸을 대화 주소로 바꿔요) 덜 세는 쪽이 안전해요.

export type Move = "pop" | "push" | "replace";
export type Trail = { list: string[]; at: number; move: Move };

export const EMPTY_TRAIL: Trail = { list: [], at: -1, move: "push" };

/** 주소가 바뀐 뒤의 길. pop은 to(닫기가 정한 자리) → 한 칸 뒤 · 한 칸 앞 → 가까운 같은 주소 순으로 찾고, 없으면
 *  이 화면이 뜨기 전 칸이라 맨 앞에 붙여요. 지금 칸과 같은 주소면 그대로예요(개발 모드가 효과를 두 번 돌려도 한 칸).
 *  닫기가 정한 자리(to)는 지금 칸과 주소가 같아도 옮겨요(목록 → 업체 → 목록에서 닫으면 처음 목록 칸으로) */
export function walk(t: Trail, path: string, move: Move, to: number | null = null): Trail {
  if (t.at < 0) return { list: [path], at: 0, move };
  if (move === "pop" && to != null && to !== t.at && t.list[to] === path) return { list: t.list, at: to, move };
  if (t.list[t.at] === path) return t;
  if (move === "replace") return { list: t.list.map((x, i) => (i === t.at ? path : x)), at: t.at, move };
  if (move === "push") return { list: [...t.list.slice(0, t.at + 1), path], at: t.at + 1, move };
  const near = [to, t.at - 1, t.at + 1].find((i) => i != null && i >= 0 && t.list[i] === path);
  if (near != null) return { list: t.list, at: near, move };
  const back = t.at > 0 ? t.list.lastIndexOf(path, t.at - 1) : -1;
  const ahead = t.list.indexOf(path, t.at + 1);
  const at = back >= 0 ? back : ahead;
  return at >= 0 ? { list: t.list, at, move } : { list: [path, ...t.list], at: 0, move };
}

/** 창 머리 '앞 화면으로': 한 칸 뒤가 이 공사의 카드 주소일 때만(대화 자리거나 이 화면이 뜨기 전이면 없음) */
export function canBack(t: Trail, base: string): boolean {
  const prev = t.list[t.at - 1];
  return !!prev && prev.startsWith(`${base}/`);
}

/** 닫기: 대화 자리로 가는 길. back은 몇 칸 뒤로인지(가장 가까운 대화 자리까지). 길에 대화 자리가 없으면(링크로 바로 연 창)
 *  처음 카드까지 돌아가 그 칸을 대화 주소로 바꿔요(replace). 창 안에서 다닌 카드가 기록에 남지 않게 해요 */
export function closePlan(t: Trail, base: string): { back: number; replace: boolean } {
  for (let i = t.at - 1; i >= 0; i--) {
    if (t.list[i] === base) return { back: t.at - i, replace: false };
    if (!t.list[i].startsWith(`${base}/`)) return { back: t.at - i - 1, replace: true };
  }
  return { back: Math.max(t.at, 0), replace: true };
}
