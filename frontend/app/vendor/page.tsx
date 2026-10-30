import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { requireRole } from "@/lib/session";

export const metadata = { title: "업체 홈" };

// 업체 홈. 가입 신청 뒤 승인 상태를 보이고, 승인되면 업체 기능으로 들어간다.
export default async function VendorHome() {
  const s = await requireRole("vendor", "/vendor");
  const st = s.vendorStatus;
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 760 }}>
        <h1 className="mj-h1">업체 홈</h1>
        {st === "approved" ? (
          <section className="mj-panel" aria-labelledby="st-h" style={{ borderColor: "var(--accent)", borderWidth: 2 }}>
            <h2 id="st-h" className="mj-h2">승인됐어요</h2>
            <p className="mj-sub">이제 업체 기능을 쓸 수 있어요. 견적 요청 받기 · 가견적서 쓰기 화면은 다음에 열려요.</p>
          </section>
        ) : st === "rejected" ? (
          <section className="mj-panel" aria-labelledby="st-h">
            <h2 id="st-h" className="mj-h2">가입이 반려됐어요</h2>
            {s.vendorRejectReason ? <p><b>사유</b> · {s.vendorRejectReason}</p> : null}
            <p className="mj-sub">다시 신청하려면 탈퇴한 뒤 사업자등록증을 새로 올려 가입해 주세요.</p>
            <Link href="/account/withdraw" className="mj-btn mj-btn-sec" style={{ alignSelf: "flex-start" }}>탈퇴하기</Link>
          </section>
        ) : (
          <section className="mj-panel" aria-labelledby="st-h">
            <h2 id="st-h" className="mj-h2">가입 신청을 받았어요</h2>
            <p className="mj-sub">관리자가 사업자등록증을 확인하고 승인하면 업체 기능을 쓸 수 있어요.</p>
          </section>
        )}
      </main>
    </>
  );
}
