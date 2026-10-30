import Link from "next/link";
import { SiteHeader } from "@/components/site/SiteHeader";
import { QuoteButton } from "@/components/start/QuoteDialog";
import { DraftCard } from "@/components/my/DraftCard";

export default async function Home({ searchParams }: { searchParams: Promise<{ bye?: string }> }) {
  const { bye } = await searchParams;
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main">
        {bye ? <p className="mj-notice" role="status"><span>탈퇴했어요. 회원 정보와 프로젝트를 모두 지웠어요.</span></p> : null}
        <section style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 720, paddingTop: 16 }}>
          <h1 className="mj-h1" style={{ fontSize: "var(--fs-display)" }}>공공 기준과 비교하면서<br />우리 집 업체를 골라요</h1>
          <p className="mj-sub" style={{ fontSize: "var(--fs-lg)", maxWidth: "34em" }}>표준견적서로 기준 금액을 먼저 보고, 여러 업체의 가견적을 같은 조건으로 받아 비교해요.</p>
          <div className="mj-btn-row">
            <QuoteButton label="견적 받기 시작" className="mj-btn mj-btn-pri" style={{ minHeight: 56 }} />
            <Link href="/my" className="mj-btn mj-btn-sec" style={{ minHeight: 56 }}>내 프로젝트 보기</Link>
          </div>
        </section>
        <DraftCard />
      </main>
    </>
  );
}
