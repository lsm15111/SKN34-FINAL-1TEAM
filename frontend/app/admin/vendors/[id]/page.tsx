import Link from "next/link";
import { notFound } from "next/navigation";
import { getVendorApplication } from "@/lib/api/admin";
import { VendorReview } from "@/components/admin/VendorReview";
import { dateSeoul, md } from "@/lib/format";

export const metadata = { title: "업체 가입 신청" };
const STATUS_LABEL: Record<string, string> = { pending: "승인 대기", approved: "승인", rejected: "반려" };

// 업체 가입 신청 상세 (FAD-02 · 03): 신청 정보 + 사업자등록증 + 승인 · 반려.
export default async function AdminVendorDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const v = await getVendorApplication(id);
  if (!v) notFound();
  const lic = `/api/files/${v.license_file_id}`;
  return (
    <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 860 }}>
      <Link href="/admin/vendors">← 업체관리로</Link>
      <h1 className="mj-h1">{v.name}</h1>
      <dl className="mj-kv mj-panel">
        <dt>이메일</dt><dd>{v.email}</dd>
        <dt>신청일</dt><dd className="mj-num">{md(dateSeoul(v.created_at))}</dd>
        <dt>상태</dt><dd>{STATUS_LABEL[v.status] ?? v.status}{v.reviewed_at ? ` · ${md(dateSeoul(v.reviewed_at))} 처리` : ""}</dd>
        {v.reject_reason ? <><dt>반려 사유</dt><dd>{v.reject_reason}</dd></> : null}
      </dl>
      <section className="mj-panel" aria-labelledby="lic-h">
        <h2 id="lic-h" className="mj-h3">사업자등록증</h2>
        <p className="mj-small">이 파일은 관리자와 그 업체만 볼 수 있어요. 상호 · 대표자 · 사업자등록번호 · 개업일을 확인해 주세요.</p>
        <a href={lic} target="_blank" rel="noreferrer" className="mj-btn mj-btn-sec" style={{ alignSelf: "flex-start" }}>새 창에서 보기</a>
      </section>
      <section className="mj-panel" aria-labelledby="rv-h">
        <h2 id="rv-h" className="mj-h3">처리</h2>
        <VendorReview id={v.user_id} name={v.name} status={v.status} />
      </section>
    </main>
  );
}
