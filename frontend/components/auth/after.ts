// 가입 · 로그인 뒤 갈 곳(브라우저). C06: 가려던 화면 → 진행 중 공사 → 홈. 기기에 둔 손님 답이 있으면 내 공사로 옮겨요(dev-03).
// - 옮기기는 POST /projects + Idempotency-Key(기기 답의 key)라 두 번 눌러도 공사는 하나예요. 성공하면 기기 답을 지우고 업체 보기로 가요.
// - 이미 진행 중인 공사가 있으면 홈(/?resume=1)에서 이어 하기 / 새 집을 물어요(C41, B2b components/my/ResumeDialog). 새 집이면 기본 정보에 그 답이 그대로 들어가 있어요.
import { guestBody, moveGuest, myOngoing } from "@/lib/guest/api";
import { HOME, safeNext } from "./next";

export type After =
  | { kind: "go"; href: string }
  | { kind: "error"; message: string };

/** 옮길 손님 답이 있는지(가입 단추 글 '가입하고 업체 보기'를 고를 때) */
export const hasGuestAnswers = () => guestBody() !== null;

/** 손님 답을 새 공사로 옮기고 그 공사 업체 보기로. base: v5 화면에서 왔으면 '/v5' */
export async function moveAndGo(mock: boolean, to: "vendors" | "assistant" = "vendors", base = ""): Promise<After> {
  try {
    const p = await moveGuest(mock);
    return { kind: "go", href: p ? `${base}/projects/${p.id}/${to}` : base || "/" };
  } catch (e) {
    return { kind: "error", message: e instanceof Error && e.message ? e.message : "잠시 문제가 생겼어요. 다시 해 주세요." };
  }
}

export async function afterAuth(role: string, next: string | null | undefined, mock: boolean, opts: { fresh?: boolean } = {}): Promise<After> {
  const n = safeNext(next);
  // 돌아올 곳이 v5 화면(/v5…)이면 손님 답을 옮긴 뒤에도 v5 화면으로 가요
  const v5 = n && /^\/v5(?=[/?#]|$)/.test(n) ? "/v5" : "";
  if (role === "customer" && hasGuestAnswers()) {
    // 재재 대화에서 가입 · 로그인하면 옮긴 공사의 재재 화면으로 돌아가요(새로 시작한 집이라 진행 중 공사를 묻지 않아요)
    if (n === "/assistant") return moveAndGo(mock, "assistant");
    if (!opts.fresh) {
      const ongoing = await myOngoing();
      if (ongoing.length) return { kind: "go", href: v5 ? "/v5?resume=1" : "/?resume=1" };
    }
    return moveAndGo(mock, "vendors", v5);
  }
  if (n) return { kind: "go", href: n };
  if (role === "customer") {
    const ongoing = opts.fresh ? [] : await myOngoing();
    return { kind: "go", href: ongoing.length ? `/projects/${ongoing[0].id}` : "/" };
  }
  return { kind: "go", href: HOME[role as keyof typeof HOME] ?? "/" };
}
