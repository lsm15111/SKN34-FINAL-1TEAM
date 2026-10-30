import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { SignupForm } from "@/components/auth/SignupForm";

export const metadata = { title: "회원가입" };

export default async function SignupPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 560 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h1 className="mj-h1">회원가입</h1>
        </div>
        <SignupForm next={next} />
        <p className="mj-small">이미 회원이세요? <Link href={`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`}>로그인</Link> · 시공 업체세요? <Link href="/signup/vendor">업체로 가입하기</Link></p>
      </main>
    </>
  );
}
