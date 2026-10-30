import { listMembers } from "@/lib/api/admin";
import { MemberTable } from "@/components/admin/MemberTable";

export const metadata = { title: "회원관리" };

export default async function MembersPage() {
  const members = await listMembers();
  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">회원관리</h1>
        <p className="mj-sub">일반 회원의 기본정보, 가입일, 계정 상태를 보고 관리해요.</p>
      </div>
      <MemberTable initial={members} />
    </main>
  );
}
