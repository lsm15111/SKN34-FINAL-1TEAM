// 업체 고르기 (시안 WVendors): 이 집 공정의 업체 · 가견적(업체가 확인한 단가 × 표준견적서 수량, 믿집 계산) · 실측 요청에 담기.
// 업체 이름을 누르면 업체 자세히가 오른쪽 창으로 열린다(./@panel/(.)[vid]).
// 목록 · 남은 칸 · 동의 문구 버전은 GET /projects/{id}/vendors, 못 받은 시각은 GET /projects/{id}/visits에서 읽는다.
// 이 공정을 확정했으면(GET /projects/{id}/deals) 확정 안내를 두고 담기 · 요청을 막는다.
// 확정 없이 다시 고르기로 닫힌 요청(close_reason reselected)이 있으면 '다시 고르는 중' 안내를 둔다.
import Link from "next/link";
import { notFound } from "next/navigation";
import { DealNote } from "@/components/confirm/DealNote";
import { ReselectNote } from "@/components/confirm/ReselectNote";
import { ProjectCrumb } from "@/components/project/ProjectCrumb";
import { VendorBoard } from "@/components/vendors/VendorBoard";
import { VTabs } from "@/components/vendors/VTabs";
import { isLive, isReselected, isTrade } from "@/components/vendors/text";
import { getMyProject } from "@/lib/api/project";
import { listDeals } from "@/lib/api/schedule";
import { listProjectVendors, listProjectVisits } from "@/lib/api/visit";
import { projectTitle, tradeLabel, TRADE_ORDER } from "@/lib/labels";
import { eulReul, won } from "@/lib/format";
import s from "./page.module.css";

export const metadata = { title: "업체 고르기" };

export default async function VendorsPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  const { trade: asked } = await searchParams;
  const p = await getMyProject(id);
  if (!p) notFound();
  const trades = TRADE_ORDER.filter((t) => p.trades[t]);
  if (!trades.length) notFound();
  const trade = isTrade(asked) && trades.includes(asked) ? asked : trades[0];

  const [lists, visits, deals] = await Promise.all([Promise.all(trades.map((t) => listProjectVendors(id, t))), listProjectVisits(id, trade), listDeals(id, trade)]);
  const cur = lists[trades.indexOf(trade)];
  if (!cur) notFound();
  const counts = Object.fromEntries(trades.map((t, i) => [t, lists[i]?.vendors.length ?? 0]));
  const closedAt = Object.fromEntries((visits?.visits ?? []).filter((v) => v.closed_at).map((v) => [v.id, v.closed_at as string]));
  const tName = tradeLabel(trade);
  const deal = deals?.[0] ?? null;
  const mine = visits?.visits ?? [];
  const again = !deal && mine.some(isReselected);

  const head = (
    <>
      <VTabs base={`/projects/${id}/vendors`} trades={trades} current={trade} counts={counts} />
      <div className={s.std}>
        <p>{tName} 표준견적서 <strong className="mj-num">{won(cur.standard_total)}</strong></p>
        <Link className={`mj-lnk ${s.sm}`} href={`/projects/${id}/standard?trade=${trade}#t-${trade}`}>표준견적서 보기</Link>
      </div>
      {deal ? <div className={s.deal}><DealNote d={deal} projectId={id} /></div> : null}
      {again ? <div className={s.deal}><ReselectNote trade={trade} again={!mine.some((v) => isLive(v.status))} /></div> : null}
    </>
  );

  return (
    <main id="main">
      <ProjectCrumb id={id} title={projectTitle(p.region, trades)} here="업체 고르기" />
      <div className={`mj-wrap ${s.title}`}>
        <h1 className="mj-h1">업체 고르기</h1>
      </div>
      <div className={`mj-wrap ${s.body}`}>
        {cur.vendors.length ? (
          <VendorBoard
            key={trade}
            head={head}
            projectId={id}
            trade={trade}
            areaName={cur.area_name}
            slotsLeft={cur.slots_left}
            consentVer={cur.consent_ver}
            vendors={cur.vendors}
            closedAt={closedAt}
            locked={!!deal}
          />
        ) : (
          <div className={s.none}>
            {head}
            <div className={s.empty}>
              <p>{cur.area_name}에서 {eulReul(tName)} 하는 믿집 업체가 아직 없어요.</p>
              <Link className={`mj-lnk ${s.sm}`} href={`/projects/${id}/standard?trade=${trade}#t-${trade}`}>표준견적서 보기</Link>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
