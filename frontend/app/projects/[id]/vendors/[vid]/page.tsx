// 업체 자세히 · 전체 화면 (시안 WVendorDetail). 주소로 바로 오거나 오른쪽 창의 '크게 보기', 비교 · 확정 · 알림에서 업체 이름을 누르면 열린다.
// 업체 고르기 목록에서 누르면 같은 주소가 오른쪽 창(@panel/(.)[vid])으로 열린다. 조각은 components/vendors/Detail.tsx를 같이 쓴다.
// 요청은 업체 고르기의 '실측 요청 보내기' 하나로만 보낸다. 여기서는 '실측 요청에 담기'만 한다.
// 요청한 뒤에는 실측 · 연락 카드가 펼쳐진다(연락처는 GET /projects/{id}/visits의 이 업체 요청).
// 이 공정을 확정했으면(GET /projects/{id}/deals) 업체 고르기와 같은 확정 안내를 두고 담기를 막는다.
import Link from "next/link";
import { notFound } from "next/navigation";
import { DealNote } from "@/components/confirm/DealNote";
import { ContactCard } from "@/components/vendors/ContactCard";
import { BizInfo, ContactFacts, Estimate, Faqs, Photos, Verified } from "@/components/vendors/Detail";
import { Lock, VisitState } from "@/components/vendors/icons";
import { PickButton } from "@/components/vendors/PickButton";
import { areasText, declineText, iGa, isLive, isTrade, shutKind, when } from "@/components/vendors/text";
import { getMyProject } from "@/lib/api/project";
import { listDeals } from "@/lib/api/schedule";
import { getProjectVendor, listProjectVisits } from "@/lib/api/visit";
import { projectTitle, tradeLabel, TRADE_ORDER } from "@/lib/labels";
import s from "./page.module.css";

export const metadata = { title: "업체 자세히" };

export default async function VendorDetailPage({ params, searchParams }: { params: Promise<{ id: string; vid: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id, vid } = await params;
  const { trade: asked } = await searchParams;
  const p = await getMyProject(id);
  if (!p) notFound();
  const trades = TRADE_ORDER.filter((t) => p.trades[t]);
  if (!trades.length) notFound();
  const trade = isTrade(asked) && trades.includes(asked) ? asked : trades[0];
  const [d, visits, deals] = await Promise.all([getProjectVendor(id, vid, trade), listProjectVisits(id, trade), listDeals(id, trade)]);
  if (!d) notFound();
  const deal = deals?.[0] ?? null;

  const pr = d.profile;
  const name = pr.biz_name ?? "업체";
  const title = projectTitle(p.region, trades);
  const listHref = `/projects/${id}/vendors?trade=${trade}`;
  const mine = visits?.visits.find((v) => v.vendor_id === vid) ?? null; // 최근 순이라 첫 것이 가장 최근
  const live = mine && isLive(mine.status) ? mine : null;
  const slotsLeft = visits?.slots_left[trade] ?? 0;
  const again = !!mine && shutKind(mine, !!deal) === "past";

  return (
    <main id="main">
      <nav className={`mj-wrap mj-crumb ${s.crumb}`} aria-label="이동 경로">
        <ol>
          <li><Link href="/my">내 공사</Link><span aria-hidden="true">›</span></li>
          <li><Link href={`/projects/${id}`}>{title}</Link><span aria-hidden="true">›</span></li>
          <li><Link href={listHref}>업체 고르기</Link><span aria-hidden="true">›</span></li>
          <li><span aria-current="page">{name}</span></li>
        </ol>
      </nav>

      <div className={`mj-wrap ${s.top}`}>
        <div className={s.hd}>
          <h1 className="mj-h1">{name}</h1>
          <p className={s.meta}>{pr.trades.map((t) => <span key={t} className={s.chip}>{tradeLabel(t)}</span>)}<span className="mj-sub">활동 지역 {areasText(pr.areas, d.area_name)}</span></p>
          <Verified d={d} big />
        </div>

        <section className={s.cc} aria-labelledby="ct-t">
          <h2 id="ct-t" className="mj-h3">실측 · 연락</h2>
          {live ? (
            <ContactCard v={live} projectId={id} trade={trade} allHref={`/projects/${id}/visits?trade=${trade}`} />
          ) : (
            <>
              {mine ? (
                <p className={s.was}>
                  <VisitState status={mine.status} past={shutKind(mine, !!deal) === "past"} />
                  <span className="mj-small mj-num">{[shutKind(mine, !!deal) === "other" ? "다른 업체로 정했어요" : declineText(mine.decline_code), when(mine.closed_at)].filter(Boolean).join(" · ")}</span>
                </p>
              ) : null}
              <ContactFacts d={d} />
              {deal ? <DealNote d={deal} projectId={id} /> : (
                <>
                  <p className={`mj-small ${s.lock}`}><Lock />실측을 요청하면 연락처가 보여요.</p>
                  <PickButton projectId={id} trade={trade} vendorId={vid} name={name} slotsLeft={slotsLeft} again={again} hintId="pk-top-h" />
                  <Link className={`mj-lnk ${s.sm}`} href={listHref}>업체 고르기에서 요청 보내기</Link>
                </>
              )}
            </>
          )}
        </section>
      </div>

      <div className="mj-wrap">
        <section className={`mj-sec ${s.sec}`} aria-labelledby="qt-t">
          <div className="mj-sec-l"><h2 id="qt-t" className="mj-h2">가견적</h2></div>
          <div className="mj-sec-c"><Estimate d={d} big /></div>
        </section>

        <section className={`mj-sec ${s.sec}`} aria-labelledby="pt-t">
          <div className="mj-sec-l">
            <h2 id="pt-t" className="mj-h2">시공 사례</h2>
            {pr.portfolio.length ? <p className="mj-small">사진 {pr.portfolio.length}장</p> : null}
          </div>
          <div className="mj-sec-c"><Photos d={d} projectId={id} /></div>
        </section>

        <section className={`mj-sec ${s.sec}`} aria-labelledby="fq-t">
          <div className="mj-sec-l"><h2 id="fq-t" className="mj-h2">자주 묻는 5가지</h2><p className="mj-small">{iGa(name)} 적은 답이에요.</p></div>
          <div className="mj-sec-c"><Faqs d={d} /></div>
        </section>

        <section className={`mj-sec ${s.sec}`} aria-labelledby="bz-t">
          <div className="mj-sec-l"><h2 id="bz-t" className="mj-h2">사업자 · 자격 정보</h2></div>
          <div className="mj-sec-c"><BizInfo d={d} label="항목 보기" /></div>
        </section>

        <div className={s.end}>
          <div className={s.endRow}>
            {live ? <VisitState status={live.status} /> : deal ? null : (
              <div className={s.pickEnd}><PickButton projectId={id} trade={trade} vendorId={vid} name={name} slotsLeft={slotsLeft} again={again} hintId="pk-end-h" /></div>
            )}
            <Link className={s.gbtn} href={listHref}>업체 고르기로</Link>
          </div>
          <p className="mj-small mj-num">믿집은 공사 계약 당사자가 아니에요. 계약은 업체와 직접 해요.</p>
        </div>
      </div>
    </main>
  );
}
