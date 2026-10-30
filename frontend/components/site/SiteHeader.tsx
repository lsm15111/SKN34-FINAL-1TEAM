import Link from "next/link";
import { getSession } from "@/lib/session";
import { NavLinks } from "./NavLinks";
import { AccountMenu } from "./AccountMenu";
import { QuoteButton } from "@/components/start/QuoteDialog";

const NAV = {
  customer: [{ href: "/my", label: "내 프로젝트" }, { href: "/faq", label: "자주 묻는 질문" }],
  vendor: [{ href: "/vendor", label: "업체 홈" }],
  admin: [{ href: "/admin/members", label: "회원관리" }, { href: "/admin/vendors", label: "업체관리" }],
};

export async function SiteHeader({ variant = "user" }: { variant?: "user" | "admin" }) {
  const session = await getSession();
  const links = variant === "admin" ? NAV.admin : session?.role === "vendor" ? NAV.vendor : NAV.customer;
  const home = variant === "admin" ? "/admin/members" : session?.role === "vendor" ? "/vendor" : "/";
  return (
    <header className="mj-header">
      <div className="mj-wrap mj-header-in">
        <Link href={home} className="mj-logo">믿집{variant === "admin" ? <span className="mj-small" style={{ marginLeft: 8, fontWeight: 500 }}>관리자</span> : null}</Link>
        <nav aria-label={variant === "admin" ? "관리자 메뉴" : "주 메뉴"} className="mj-nav"><NavLinks links={links} /></nav>
        <div className="mj-user">
          {session ? null : <Link href="/login" className="mj-btn mj-btn-sec mj-btn-sm">로그인 · 회원가입</Link>}
          {variant === "user" && session?.role !== "vendor" && session?.role !== "admin" ? <QuoteButton /> : null}
          {session ? <AccountMenu name={session.name} email={session.email} role={session.role} /> : null}
        </div>
      </div>
    </header>
  );
}
