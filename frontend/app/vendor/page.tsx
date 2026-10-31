import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { VendorInbox } from "@/components/vendors/VendorInbox";
import { getVendorInbox } from "@/lib/api/quote";
import { requireRole } from "@/lib/session";

export const metadata = { title: "업체 홈" };

// 업체 홈. 가입 신청 뒤 승인 상태를 보이고, 승인되면 받은 가견적 요청을 보인다.
export default async function VendorHome() {
  const s = await requireRole("vendor", "/vendor");
  const st = s.vendorStatus;
  const inbox = st === "approved" ? await getVendorInbox() : null;
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 760 }}>
        <h1 className="mj-h1">업체 홈</h1>
        {st === "approved" ? (
          <>
            <section className="mj-panel" aria-labelledby="st-h" style={{ borderColor: "var(--accent)", borderWidth: 2 }}>
              <h2 id="st-h" className="mj-h2">승인됐어요</h2>
              <p className="mj-sub">믿집 고객이 보낸 가견적 요청을 아래에서 볼 수 있어요. 가견적서 쓰기 화면은 다음에 열려요.</p>
            </section>
            <section aria-labelledby="in-h" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <h2 id="in-h" className="mj-h2">받은 가견적 요청{inbox ? <span className="mj-num"> {inbox.length}건</span> : null}</h2>
              <p className="mj-small">고객 이름 · 연락처 · 동 · 호수는 보이지 않아요. 집 정보는 고객이 견적 받기에서 고른 답이에요.</p>
              {inbox ? <VendorInbox items={inbox} /> : <p className="mj-notice"><span>받은 요청을 불러오지 못했어요. 잠시 뒤에 다시 열어 주세요.</span></p>}
            </section>
          </>
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
