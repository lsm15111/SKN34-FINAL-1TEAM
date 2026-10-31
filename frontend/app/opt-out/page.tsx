import { SiteHeader } from "@/components/site/SiteHeader";
import { OptOutForm } from "@/components/vendors/OptOutForm";

export const metadata = { title: "연락 받지 않기", robots: { index: false, follow: false } };

// 믿집이 대신 전한 가견적 요청 메시지 끝의 수신거부 링크(/opt-out?t=…)가 여는 곳. 로그인 없이 쓴다.
export default async function OptOutPage({ searchParams }: { searchParams: Promise<{ t?: string | string[] }> }) {
  const { t } = await searchParams;
  const token = typeof t === "string" && /^[A-Za-z0-9_-]{20,64}$/.test(t) ? t : null;
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 640 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h1 className="mj-h1">믿집 연락 받지 않기</h1>
          <p className="mj-sub">믿집은 고객의 가견적 요청을, 연락을 받겠다고 동의한 업체에만 대신 전해요. 더 받고 싶지 않으면 여기서 멈출 수 있어요.</p>
        </div>
        {token ? (
          <OptOutForm token={token} />
        ) : (
          <p className="mj-notice mj-notice-warn"><span>수신거부 링크가 올바르지 않아요. 받은 메시지의 링크를 그대로 열어 주세요.</span></p>
        )}
      </main>
    </>
  );
}
