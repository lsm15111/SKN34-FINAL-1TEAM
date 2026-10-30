import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { ProfileForm } from "@/components/my/ProfileForm";
import { requireRole } from "@/lib/session";

export const metadata = { title: "내 정보 · 설정" };

// 마이페이지 · 내 정보 · 설정. 헤더 계정 메뉴에서 들어온다. 고객과 업체가 함께 쓴다.
// 비밀번호 바꾸기 · 알림 · 동의 내역은 API가 생기면 이 쪽에 묶음으로 더한다.
// 탈퇴는 빨간 글씨 링크 하나만 두고, 지우는 것 · 비밀번호 확인은 탈퇴 화면에서 보인다.
export default async function AccountPage() {
  const s = await requireRole(["customer", "vendor"], "/account");
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 760 }}>
        <h1 id="acc-h" className="mj-h1">내 정보 · 설정</h1>
        <ProfileForm name={s.name} email={s.email} labelledBy="acc-h" />
        <Link href="/account/withdraw" className="mj-link-danger">회원 탈퇴</Link>
      </main>
    </>
  );
}
