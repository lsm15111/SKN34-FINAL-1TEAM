import Link from "next/link";
import { listVendorApplications, type VendorStatus } from "@/lib/api/admin";
import { VendorReview } from "@/components/admin/VendorReview";
import { dateSeoul, md } from "@/lib/format";

export const metadata = { title: "업체관리" };

const TABS: { v: VendorStatus | "all"; t: string }[] = [
  { v: "pending", t: "승인 대기" }, { v: "approved", t: "승인" }, { v: "rejected", t: "반려" }, { v: "all", t: "전체" },
];
const STATUS_LABEL: Record<string, string> = { pending: "승인 대기", approved: "승인", rejected: "반려" };

// 업체관리 · 가입 승인 (FAD-02 · FAD-03). 업체는 기본 정보와 사업자등록증만 내고, 관리자가 등록증을 보고 승인한다.
export default async function AdminVendors({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status: raw } = await searchParams;
  const status = (TABS.find((x) => x.v === raw)?.v ?? "pending") as VendorStatus | "all";
  const list = await listVendorApplications(status === "all" ? undefined : status);
  return (
    <main id="main" className="mj-wrap mj-main">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1 className="mj-h1">업체관리</h1>
        <p className="mj-sub">사업자등록증을 확인하고 가입을 승인하거나 반려해요. 승인한 업체만 업체 기능을 써요.</p>
      </div>
      <nav aria-label="상태" className="mj-mynav">
        {TABS.map((x) => <Link key={x.v} href={`/admin/vendors?status=${x.v}`} aria-current={x.v === status ? "page" : undefined}>{x.t}</Link>)}
      </nav>
      {list.length ? (
        <div className="mj-table-box">
          <table className="mj-table">
            <caption className="mj-sr">업체 가입 신청 목록</caption>
            <thead><tr><th scope="col">담당자 · 이메일</th><th scope="col">신청일</th><th scope="col">상태</th><th scope="col">사업자등록증</th><th scope="col">처리</th></tr></thead>
            <tbody>
              {list.map((v) => (
                <tr key={v.user_id}>
                  <th scope="row"><Link href={`/admin/vendors/${v.user_id}`}>{v.name}</Link><br /><span className="mj-small">{v.email}</span></th>
                  <td className="mj-num">{md(dateSeoul(v.created_at))}</td>
                  <td>{STATUS_LABEL[v.status] ?? v.status}{v.reject_reason ? <><br /><span className="mj-small">{v.reject_reason}</span></> : null}</td>
                  <td><a href={`/api/files/${v.license_file_id}`} target="_blank" rel="noreferrer">보기<span className="mj-sr"> · {v.name} 사업자등록증 (새 창)</span></a></td>
                  <td><VendorReview id={v.user_id} name={v.name} status={v.status} compact /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="mj-sub">{status === "pending" ? "승인을 기다리는 업체가 없어요." : "해당하는 업체가 없어요."}</p>}
    </main>
  );
}
