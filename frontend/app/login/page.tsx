import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata = { title: "로그인" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 520 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h1 className="mj-h1">로그인</h1>
        </div>
        <LoginForm next={next} />
        <div className="mj-panel mj-panel-tint" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <span>아직 회원이 아니세요?</span>
          <Link href={`/signup${next ? `?next=${encodeURIComponent(next)}` : ""}`} className="mj-btn mj-btn-sec mj-btn-sm">회원가입</Link>
        </div>
      </main>
    </>
  );
}
