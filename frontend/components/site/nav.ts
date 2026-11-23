// 머리 메뉴 · 폰 아래 탭 바 · 이름 ▾ 펼침 목록. 역할마다 9판 그대로(design-system 3.1 · routes.md 1장).
// 서버(AppHeader · TabBar)와 브라우저(NavLinks · TabBarNav · MobileMenu · error.tsx) 양쪽에서 써요.
// /chat · /admin/reports는 B2 · B3가 화면을 만들기 전까지 404일 수 있어요(9판 메뉴를 먼저 맞췄어요).
import type { Role, Session } from "@/lib/types";
import type { IconName } from "@/components/ui/Icon";

export type HeaderKind = "guest" | Role;
export type NavItem = { id: string; href: string; label: string };
export type TabItem = NavItem & { icon: IconName; count?: "notify" };

/** 웹 머리 메뉴(≥768). '표준견적서 받기'는 copy-fixes CF-09(믿집 견적이 셋이라 업체 견적으로 읽히지 않게) */
export const NAV: Record<HeaderKind, NavItem[]> = {
  guest: [
    { id: "start", href: "/start", label: "표준견적서 받기" },
    { id: "guide", href: "/guide", label: "백과" },
    { id: "faq", href: "/faq", label: "자주 묻는 질문" },
  ],
  customer: [
    { id: "start", href: "/start", label: "표준견적서 받기" },
    { id: "my", href: "/my", label: "내 공사" },
    { id: "chat", href: "/chat", label: "채팅" },
    { id: "guide", href: "/guide", label: "백과" },
  ],
  // W6 B: 일정은 작업함 탭이라 머리에 따로 두지 않아요
  vendor: [
    { id: "inbox", href: "/vendor", label: "작업함" },
    { id: "chat", href: "/chat", label: "채팅" },
    { id: "profile", href: "/vendor/profile", label: "업체 정보" },
  ],
  admin: [
    { id: "review", href: "/admin/vendors", label: "업체 심사" },
    { id: "reports", href: "/admin/reports", label: "신고 · 링크" },
    { id: "members", href: "/admin/members", label: "회원" },
  ],
};

/** 폰 아래 탭 바(< 768). 손님 · 관리자는 없어요 */
export const TABS: Partial<Record<HeaderKind, TabItem[]>> = {
  customer: [
    { id: "home", href: "/", label: "홈", icon: "home" },
    { id: "my", href: "/my", label: "내 공사", icon: "doc" },
    { id: "chat", href: "/chat", label: "채팅", icon: "chat" },
    { id: "notifications", href: "/notifications", label: "알림", icon: "bell", count: "notify" },
    { id: "account", href: "/account", label: "내 정보", icon: "user" },
  ],
  vendor: [
    { id: "inbox", href: "/vendor", label: "작업함", icon: "box" },
    { id: "chat", href: "/chat", label: "채팅", icon: "chat" },
    { id: "profile", href: "/vendor/profile", label: "업체 정보", icon: "store" },
    { id: "notifications", href: "/notifications", label: "알림", icon: "bell", count: "notify" },
  ],
};

/** 웹 머리 '이름 ▾' 펼침(로그아웃은 따로 붙여요) */
export const ACCOUNT: Record<Role, NavItem[]> = {
  customer: [
    { id: "account", href: "/account", label: "내 정보" },
    { id: "guide", href: "/guide", label: "믿집 백과" },
    { id: "faq", href: "/faq", label: "자주 묻는 질문" },
  ],
  vendor: [{ id: "account", href: "/account", label: "내 정보" }],
  admin: [],
};

// 승인 전 업체는 작업함 · 채팅을 잠가요(업체 정보는 열어요). 9판 V02 · 시안 WVHome
export const VENDOR_LOCKED = ["inbox", "chat"];
/** 승인 전 업체의 잠금 문구. 승인됐으면 null */
export function vendorLock(status: string | null | undefined): string | null {
  if (status === "approved") return null;
  return status === "rejected" ? "다시 신청해서 승인되면 열려요" : "심사 중이라 승인 뒤 열려요";
}

export const LOGO_HREF: Record<HeaderKind, string> = { guest: "/", customer: "/", vendor: "/vendor", admin: "/admin/vendors" };
export const LOGO_TAG: Partial<Record<HeaderKind, string>> = { vendor: "업체", admin: "관리자" };

/** 머리 이름 ▾ 단추 글: 고객 · 업체 '김하늘 님', 관리자 '관리자' */
export function accountLabel(s: Pick<Session, "name" | "role">): string {
  return s.role === "admin" ? "관리자" : `${s.name} 님`;
}

/** 지금 보는 화면이 이 메뉴 · 탭인지(aria-current="page") */
export function isCurrent(item: NavItem, path: string): boolean {
  switch (item.id) {
    case "home":
      return path === "/";
    case "my": // 한 공사 화면도 '내 공사'
      return path === "/my" || path.startsWith("/projects/");
    case "inbox":
      return path === "/vendor" || path.startsWith("/vendor/requests") || path.startsWith("/vendor/jobs");
    case "profile":
      return path.startsWith("/vendor/profile") || path.startsWith("/vendor/prices") || path.startsWith("/vendor/reviews");
    default:
      return path === item.href || path.startsWith(item.href + "/");
  }
}
