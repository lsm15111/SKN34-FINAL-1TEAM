import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { VendorSignupForm } from "@/components/auth/VendorSignupForm";

export const metadata = { title: "업체 회원가입" };

export default function VendorSignupPage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 560 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h1 className="mj-h1">업체 회원가입</h1>
          <p className="mj-sub">사업자등록증을 올려 주세요. 관리자가 확인하고 승인하면 업체 기능을 쓸 수 있어요.</p>
        </div>
        <VendorSignupForm />
        <p className="mj-small">고객으로 가입하려면 <Link href="/signup">일반 회원가입</Link> · 이미 회원이세요? <Link href="/login">로그인</Link></p>
      </main>
    </>
  );
}
