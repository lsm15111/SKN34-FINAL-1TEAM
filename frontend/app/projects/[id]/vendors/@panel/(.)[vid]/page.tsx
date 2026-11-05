// 업체 고르기 위 업체 자세히 오른쪽 창 (시안 WVendorsPanel). 목록에서 업체 이름을 누르면 같은 주소(/vendors/[vid])를 이 창으로 연다.
// 창 안 순서: 믿집 확인 → 실측 · 연락 → 가견적 → 사진 3장 → 자주 묻는 5가지(누르면 답) → 사업자 정보(접힘). 아래는 '실측 요청에 담기'.
// 이전 · 다음 업체 순서는 목록과 같은 가견적 낮은 순이다(GET /projects/{id}/vendors).
import Link from "next/link";
import { DealNote } from "@/components/confirm/DealNote";
import { ContactCard } from "@/components/vendors/ContactCard";
import { BizInfo, ContactFacts, Estimate, Faqs, Photos, Verified } from "@/components/vendors/Detail";
import { VisitState } from "@/components/vendors/icons";
import { PickButton } from "@/components/vendors/PickButton";
import { VendorPanel } from "@/components/vendors/VendorPanel";
import { areasText, eunNeun, iGa, isLive, isTrade, shutKind } from "@/components/vendors/text";
import { getMyProject } from "@/lib/api/project";
import { listDeals } from "@/lib/api/schedule";
import { getProjectVendor, listProjectVendors, listProjectVisits } from "@/lib/api/visit";
import { tradeLabel, TRADE_ORDER } from "@/lib/labels";
import s from "@/components/vendors/VendorPanel.module.css";

export const metadata = { title: "업체 고르기" };

const PHOTOS = 3;

export default async function VendorPanelPage({ params, searchParams }: { params: Promise<{ id: string; vid: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id, vid: raw } = await params;
  // 가로채는 경로는 개발 서버에서 업체 번호 앞에 '(.)' 표시가 붙어 올 때가 있어 떼고 쓴다
  const vid = decodeURIComponent(raw).replace(/^(?:\(\.{1,3}\))+/, "");
  const { trade: asked } = await searchParams;
  const p = await getMyProject(id);
  if (!p) return null;
  const trades = TRADE_ORDER.filter((t) => p.trades[t]);
  const trade = isTrade(asked) && trades.includes(asked) ? asked : trades[0];
  if (!trade) return null;
  const [d, visits, deals, list] = await Promise.all([getProjectVendor(id, vid, trade), listProjectVisits(id, trade), listDeals(id, trade), listProjectVendors(id, trade)]);
  if (!d) return null; // 목록 밖 업체면 창을 열지 않는다

  const pr = d.profile;
  const name = pr.biz_name ?? "업체";
  const deal = deals?.[0] ?? null;
  const mine = visits?.visits.find((v) => v.vendor_id === vid) ?? null; // 최근 순이라 첫 것이 가장 최근
  const live = mine && isLive(mine.status) ? mine : null;
  const slotsLeft = visits?.slots_left[trade] ?? 0;
  const order = list?.vendors.map((v) => v.vendor_id) ?? [];
  const at = order.indexOf(vid);
  const href = (vendorId: string) => `/projects/${id}/vendors/${vendorId}?trade=${trade}`;
  const listHref = `/projects/${id}/vendors?trade=${trade}`;
  const visitsHref = `/projects/${id}/visits?trade=${trade}`;

  const foot = live ? (
    <div className={s.state}>
      <VisitState status={live.status} />
      <Link className="mj-lnk" href={visitsHref}>연락처 보기<span className="mj-sr">, {name}</span></Link>
    </div>
  ) : deal ? (
    <p className="mj-small">{eunNeun(tradeLabel(trade))} 업체를 확정했어요.</p>
  ) : (
    <PickButton projectId={id} trade={trade} vendorId={vid} name={name} slotsLeft={slotsLeft} again={!!mine && shutKind(mine, false) === "past"} hintId="vd-pick-h" sendFrom={listHref} />
  );

  return (
    <VendorPanel
      vendorId={vid}
      titleId="vd-t"
      listHref={listHref}
      fullHref={href(vid)}
      prevHref={at > 0 ? href(order[at - 1]) : null}
      nextHref={at >= 0 && at < order.length - 1 ? href(order[at + 1]) : null}
      pos={at + 1}
      total={order.length}
      foot={foot}
    >
      <div className={s.hd}>
        <h2 id="vd-t" className="mj-h2" tabIndex={-1}>{name}</h2>
        <p className={s.meta}>{pr.trades.map((t) => <span key={t} className={s.chip}>{tradeLabel(t)}</span>)}<span className="mj-sub">{areasText(pr.areas, d.area_name)}</span></p>
        <Verified d={d} />
      </div>

      <section className={s.sec} aria-labelledby="vd-ct">
        <h3 id="vd-ct" className="mj-h3">실측 · 연락</h3>
        {live ? (
          <ContactCard v={live} projectId={id} trade={trade} allHref={visitsHref} />
        ) : (
          <>
            <ContactFacts d={d} />
            {deal ? <DealNote d={deal} projectId={id} /> : null}
          </>
        )}
      </section>

      <section className={s.sec} aria-labelledby="vd-qt">
        <h3 id="vd-qt" className="mj-h3">가견적</h3>
        <Estimate d={d} />
      </section>

      {/* 시공 사진이 없으면 칸을 두지 않는다 (빈 칸이 창을 길게 만든다) */}
      {pr.portfolio.length ? (
        <section className={s.sec} aria-labelledby="vd-pt">
          <div className={s.secH}><h3 id="vd-pt" className="mj-h3">시공 사례</h3><span className="mj-small mj-num">{pr.portfolio.length}장</span></div>
          <Photos d={d} projectId={id} max={PHOTOS} />
          {/* 사진을 다 보려면 전체 화면(같은 주소를 새로 연다) */}
          {pr.portfolio.length > PHOTOS ? <a className={`mj-lnk ${s.more}`} href={`${href(vid)}#pt-t`}>사진 {pr.portfolio.length}장 모두 보기</a> : null}
        </section>
      ) : null}

      <section className={s.sec} aria-labelledby="vd-fq">
        <div className={s.secH}><h3 id="vd-fq" className="mj-h3">자주 묻는 5가지</h3><span className="mj-small">{iGa(name)} 적은 답</span></div>
        <Faqs d={d} fold />
      </section>

      <section className={s.sec} aria-label="사업자 · 자격 정보">
        <BizInfo d={d} label="사업자 · 자격 정보" />
        <p className="mj-small mj-num">믿집은 공사 계약 당사자가 아니에요. 계약은 업체와 직접 해요.</p>
      </section>
    </VendorPanel>
  );
}
