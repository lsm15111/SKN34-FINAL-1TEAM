// 지금 로그인한 사람. FastAPI GET /me로 확인한다(세션 쿠키는 API가 주고, 화면 스크립트는 못 읽는다).
import { cache } from "react";
import { redirect } from "next/navigation";
import { hasSessionCookie, serverGet, type Schemas } from "./backend/server";
import type { Role, Session } from "./types";

const ROLES: Role[] = ["customer", "vendor", "admin"];

/** 한 요청 안에서는 한 번만 부른다(헤더와 화면이 함께 써도). */
export const getSession = cache(async (): Promise<Session | null> => {
  if (!(await hasSessionCookie())) return null;
  try {
    const me = await serverGet<Schemas["MeOut"]>("/me");
    if (!me || !ROLES.includes(me.role as Role)) return null;
    return { id: me.id, email: me.email, name: me.name, role: me.role as Role, vendorStatus: me.vendor_status ?? null, vendorRejectReason: me.vendor_reject_reason ?? null };
  } catch (e) {
    console.error("로그인 확인 실패 (API에 연결되지 않음)", e);
    return null;
  }
});

/** 권한별 첫 화면 */
export const HOME: Record<Role, string> = { customer: "/my", admin: "/admin/members", vendor: "/vendor" };

/** 권한이 맞지 않으면 로그인 화면이나 그 권한의 첫 화면으로 보낸다 (권한별 화면 분기) */
export async function requireRole(role: Role | Role[], next: string): Promise<Session> {
  const s = await getSession();
  if (!s) redirect(`/login?next=${encodeURIComponent(next)}`);
  if (!(Array.isArray(role) ? role : [role]).includes(s.role)) redirect(HOME[s.role]);
  return s;
}
