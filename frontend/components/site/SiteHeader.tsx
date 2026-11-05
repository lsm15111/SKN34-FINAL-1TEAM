// 모든 화면 맨 위 머리. 로그인한 사람의 역할(비로그인 · 고객 · 업체 · 관리자)마다 머리 하나를 쓴다.
// variant="admin"은 관리자 화면 레이아웃이 넘긴다. 고객 화면에는 오른쪽 아래 '공사 상담' 버튼(예시 답변)을 같이 붙인다.
import { getSession } from "@/lib/session";
import { getUnread } from "@/lib/api/notify";
import { AskLauncher } from "./AskLauncher";
import { HeaderBar } from "./HeaderBar";

export async function SiteHeader({ variant = "user" }: { variant?: "user" | "admin" }) {
  const admin = variant === "admin";
  // 알림 종은 고객 · 업체 머리에만 있다. 안 읽은 수는 못 읽으면 0(배지 없음).
  const [session, unread] = await Promise.all([getSession(), admin ? 0 : getUnread()]);
  return (
    <>
      <HeaderBar session={session} admin={admin} unread={session && session.role !== "admin" ? unread : 0} />
      {session?.role === "customer" ? <AskLauncher /> : null}
    </>
  );
}
