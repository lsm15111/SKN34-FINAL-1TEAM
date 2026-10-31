import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { VendorProfileForm } from "@/components/vendors/VendorProfileForm";
import { getVendorProfile } from "@/lib/api/vendor";
import { requireRole } from "@/lib/session";

export const metadata = { title: "업체 정보 관리" };

// 승인 업체의 업체 정보 관리: 상호 · 맡는 공정 · 일하는 지역 · 포트폴리오 링크.
// 공정 · 지역을 넣어야 고객 가견적 후보에 나온다. 승인 전 · 반려면 안내만 보인다.
export default async function VendorProfilePage() {
  const s = await requireRole("vendor", "/vendor/profile");
  const p = s.vendorStatus === "approved" ? await getVendorProfile() : null;
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 760 }}>
        <Link href="/vendor">← 업체 홈으로</Link>
        <h1 className="mj-h1">업체 정보 관리</h1>
        {p === "error" ? (
          <p className="mj-notice"><span>업체 정보를 불러오지 못했어요. 잠시 뒤에 다시 열어 주세요.</span></p>
        ) : p ? (
          <>
            <p className="mj-sub">맡는 공정과 일하는 지역을 넣으면, 그 공정 · 지역의 고객이 가견적 후보에서 이 업체를 보고 믿집 안에서 무료로 가견적을 요청할 수 있어요.</p>
            <VendorProfileForm initial={p} />
          </>
        ) : (
          <section className="mj-panel" aria-labelledby="wait-h">
            <h2 id="wait-h" className="mj-h2">승인 뒤에 쓸 수 있어요</h2>
            <p className="mj-sub">관리자가 사업자등록증을 확인하고 승인하면 맡는 공정 · 일하는 지역 · 포트폴리오를 넣을 수 있어요.</p>
          </section>
        )}
      </main>
    </>
  );
}
