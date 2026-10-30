import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { WithdrawForm } from "@/components/my/WithdrawForm";
import { requireRole } from "@/lib/session";

export const metadata = { title: "회원 탈퇴" };

// 회원 탈퇴. 확인 화면 한 장: 지우는 것을 보이고 비밀번호를 다시 받는다.
// 진행 중인 프로젝트가 있어도 막지 않는다 (개인정보 보호법 제38조④: 가입보다 어렵게 하지 않음).
export default async function WithdrawPage() {
  const s = await requireRole(["customer", "vendor"], "/account/withdraw");
  const items = s.role === "vendor"
    ? ["회원 정보 (이름 · 이메일)", "사업자등록증과 업체 정보", "로그인 기록"]
    : ["회원 정보 (이름 · 이메일)", "만든 프로젝트와 답 · 사진 · 도면", "로그인 기록"];
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 560 }}>
        <Link href="/account">← 내 정보 · 설정으로</Link>
        <h1 className="mj-h1">회원 탈퇴</h1>
        <section className="mj-panel" aria-labelledby="del-h">
          <h2 id="del-h" className="mj-h3">바로 지우는 것</h2>
          <ul style={{ margin: 0, paddingLeft: 20 }}>{items.map((t) => <li key={t}>{t}</li>)}</ul>
          <p className="mj-small">진행 중인 프로젝트가 있어도 탈퇴할 수 있어요. 지운 정보는 되살릴 수 없어요.</p>
        </section>
        <WithdrawForm />
      </main>
    </>
  );
}
