// 실측 견적 비교 (시안 WCompare): 공정 탭(받은 수) · 표준견적서 합계 · 업체마다 보낸 최신 실측 견적서(파일 · 낼 금액 · 칸 · 이전 버전).
// 읽기는 GET /projects/{id}/quotes?trade= 하나. 금액 · 표준 대비 % · 바뀐 칸 · 유효기간 지남은 API 값을 그대로 보인다.
// 확정 전에는 견적서가 온 업체마다 '이 업체로 확정하기'(확정 화면), 확정한 뒤에는 확정 · 공사 날짜 기한 줄(시안 WConfirm '확정한 뒤')을 보인다.
// '업체 다시 고르기'는 확정 전이면 이 공정의 요청을 모두 닫고(POST visits/reselect), 확정 뒤 날짜 수락 전이면 확정을 푼다(POST deals/{id}/reselect).
import Link from "next/link";
import { notFound } from "next/navigation";
import { CompareTabs } from "@/components/compare/CompareTabs";
import { QuoteCard } from "@/components/compare/QuoteCard";
import { DealStatus } from "@/components/confirm/DealStatus";
import { Reselect } from "@/components/confirm/Reselect";
import { ReselectNote } from "@/components/confirm/ReselectNote";
import { canReselect, dealReselectText, visitsReselectBody } from "@/components/confirm/text";
import { ProjectCrumb } from "@/components/project/ProjectCrumb";
import { isReselected, isTrade } from "@/components/vendors/text";
import { getMyProject } from "@/lib/api/project";
import { getQuoteCompare } from "@/lib/api/quote";
import { listDeals } from "@/lib/api/schedule";
import { listProjectVisits } from "@/lib/api/visit";
import { projectTitle, tradeLabel, TRADE_ORDER } from "@/lib/labels";
import { won } from "@/lib/format";
import s from "./page.module.css";

export const metadata = { title: "실측 견적 비교" };

export default async function QuotesPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  const { trade: asked } = await searchParams;
  const p = await getMyProject(id);
  if (!p) notFound();
  const trades = TRADE_ORDER.filter((t) => p.trades[t]);
  if (!trades.length) notFound();
  const trade = isTrade(asked) && trades.includes(asked) ? asked : trades[0];
  const c = await getQuoteCompare(id, trade);
  if (!c) notFound();

  const tName = tradeLabel(trade);
  const here = `${tName} 실측 견적 비교`;
  const pickHref = `/projects/${id}/vendors?trade=${trade}`;
  const deal = c.deal;
  const chosen = !!deal || c.vendors.some((v) => v.status === "chosen");
  const confirmHref = (r: (typeof c.vendors)[number]) =>
    !chosen && r.status === "quoted" && r.latest && r.seen_ver != null ? `/projects/${id}/quotes/${r.visit_id}/confirm?trade=${trade}` : null;
  // 확정 전 다시 고르기: 요청함 · 견적서 옴을 모두 닫는다
  const live = chosen ? [] : c.vendors.filter((v) => v.status === "requested" || v.status === "quoted");
  // 확정 뒤 다시 고르기 창의 '다른 공정은 그대로예요'
  const otherTrade = trades.find((t) => t !== trade);
  const dealText = deal && canReselect(deal)
    ? dealReselectText(deal, otherTrade ? { trade: otherTrade, deal: (await listDeals(id, otherTrade))?.[0] ?? null } : null)
    : null;
  // 요청이 하나도 없으면 다시 고르기로 닫혔는지 본다
  const again = !c.vendors.length && !deal ? !!(await listProjectVisits(id, trade))?.visits.some(isReselected) : false;

  return (
    <main id="main">
      <ProjectCrumb id={id} title={projectTitle(p.region, trades)} here={here} />
      <div className={`mj-wrap ${s.title}`}>
        <h1 className="mj-h1">{here}</h1>
      </div>

      <div className={`mj-wrap ${s.body}`}>
        <div className={s.top}>
          <CompareTabs base={`/projects/${id}/quotes`} trades={trades} current={trade} counts={c.sent_counts} />
          <section className={s.std} aria-labelledby="std-t">
            <div className={s.stdMain}>
              <h2 id="std-t" className={`mj-h2 ${s.stdH}`}>표준견적서</h2>
              <p className="mj-num"><span className={s.big}>{won(c.standard_total)}</span></p>
              <p className="mj-small">참고 금액이에요.</p>
            </div>
            <Link className="mj-lnk" href={`/projects/${id}/standard`}>표준견적서 보기</Link>
          </section>
        </div>

        <section aria-labelledby="vq-t" className={s.sec}>
          <div className={s.secHead}>
            <h2 id="vq-t" className="mj-h2">업체가 보낸 실측 견적서</h2>
            <p className="mj-small">업체 양식 파일 그대로예요. 파일을 열어 보고 비교해 주세요.</p>
          </div>
          {deal ? (
            <div className={s.deal}>
              <DealStatus d={deal} />
              <Link className="mj-lnk" href={`/projects/${id}/schedule?trade=${trade}`}>공사 날짜 보기</Link>
              {dealText ? <Reselect projectId={id} trade={trade} dealId={deal.id} {...dealText} /> : null}
            </div>
          ) : null}
          {c.vendors.length ? (
            <ul role="list" className={s.cards}>
              {c.vendors.map((r) => <QuoteCard key={r.visit_id} r={r} projectId={id} trade={trade} confirmHref={confirmHref(r)} />)}
            </ul>
          ) : (
            <div className={s.empty}>
              {again ? <ReselectNote trade={trade} /> : <p>아직 {tName} 실측을 요청한 업체가 없어요.</p>}
              <Link className="mj-btn mj-btn-pri" href={pickHref}>업체 고르기</Link>
            </div>
          )}
          {c.vendors.length && !chosen ? (
            <div className={s.after}>
              {live.length ? (
                <Reselect
                  projectId={id}
                  trade={trade}
                  title={`${tName} 업체를 다시 고를까요?`}
                  body={visitsReselectBody(live.map((v) => v.vendor_name), live.filter((v) => v.latest).length)}
                />
              ) : null}
              <Link className="mj-lnk" href={pickHref}>업체 더 담기</Link>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
