// 가입 · 로그인 뒤 가는 곳. 서버(page)와 브라우저(폼) 양쪽에서 쓰므로 서버 전용 코드를 넣지 않는다.
import { euro } from "@/lib/format";
import type { Role } from "@/lib/types";

// 권한별 첫 화면. v3 고객은 홈(C06: 가려던 화면 → 진행 중 공사 → 홈), 업체는 작업함, 관리자는 업체 심사(머리 로고와 같게)
export const HOME: Record<Role, string> = { customer: "/", admin: "/admin/vendors", vendor: "/vendor" };

/** 돌아갈 곳은 이 사이트 안 경로만 받는다(//, 역슬래시, 공백 · 제어 문자가 섞이면 버린다). 아니면 null */
export function safeNext(next?: string | null): string | null {
  if (!next || !/^\/(?![/\\])/.test(next) || /[\s\\]/.test(next)) return null;
  return Array.from(next).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127) ? null : next;
}

/** 가입 · 로그인 화면끼리 오갈 때 돌아갈 곳을 그대로 넘긴다. */
export function withNext(path: string, next?: string | null): string {
  const n = safeNext(next);
  if (!n) return path;
  return `${path}${path.includes("?") ? "&" : "?"}next=${encodeURIComponent(n)}`;
}

// 로그인 화면 '로그인하면 보던 화면 ○○로 이어 가요'(C06). 주소 꼴만 보고 화면 이름을 붙여요(업체 이름 · 공사 내용은 로그인 전이라 보이지 않아요).
const NEXT_NAMES: [RegExp, string][] = [
  [/^\/projects\/[^/?#]+\/visits\/[^/?#]+/, "날짜 고르기"],
  [/^\/projects\/[^/?#]+\/visits/, "실측 일정"],
  [/^\/projects\/[^/?#]+\/vendors/, "업체 보기"],
  [/^\/projects\/[^/?#]+\/quotes/, "실측 견적서 비교"],
  [/^\/projects\/[^/?#]+\/schedule/, "공사 날짜"],
  [/^\/projects\/[^/?#]+\/review/, "리뷰 쓰기"],
  [/^\/projects\/[^/?#]+\/standard/, "표준견적서"],
  [/^\/projects\/[^/?#]+\/plan/, "공정표"],
  [/^\/projects\/[^/?#]+/, "공사 요약"],
  [/^\/chat/, "채팅"],
  [/^\/notifications/, "알림"],
  [/^\/my/, "내 공사"],
  [/^\/account/, "내 정보"],
];
/** '날짜 고르기로' 같은 화면 이름(+ 로/으로). 모르는 주소면 null */
export function nextScreen(next?: string | null): string | null {
  const n = safeNext(next);
  if (!n) return null;
  const path = n.replace(/^\/v5(?=[/?#])/, ""); // v5 화면(/v5/…)도 같은 이름이에요
  const hit = NEXT_NAMES.find(([re]) => re.test(path));
  return hit ? euro(hit[1]) : null;
}
