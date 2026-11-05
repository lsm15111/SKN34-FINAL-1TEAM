// 업체 확정 (시안 WConfirm): 고른 업체의 최신 실측 견적서 · 확정하기(파일 확인 체크 → 확인 창) · 확정하면 일어나는 일 · 다른 공정.
// 읽기는 GET /projects/{id}/quotes?trade= (그 공정의 비교 · 확정), 다른 공정은 GET /projects/{id}/deals.
// 금액 · 표준 대비 % · 유효기간 지남 · 공사 날짜 기한은 API 값 그대로다. 확정한 뒤 날짜 수락 전이면 '다시 고르기'를 둔다(ConfirmBox).
import Link from "next/link";
import { notFound } from "next/navigation";
import { ConfirmBox } from "@/components/confirm/ConfirmBox";
import { OtherTrade } from "@/components/confirm/OtherTrade";
import { QuoteSummary } from "@/components/confirm/QuoteSummary";
import { when } from "@/components/confirm/text";
import { Warn } from "@/components/vendors/icons";
import { iGa, isTrade, shutKind, type VTrade } from "@/components/vendors/text";
import { getMyProject } from "@/lib/api/project";
import { getQuoteCompare, type QuoteCompare } from "@/lib/api/quote";
import { listDeals } from "@/lib/api/schedule";
import { listProjectVisits } from "@/lib/api/visit";
import { euro } from "@/lib/format";
import { projectTitle, tradeLabel, TRADE_ORDER } from "@/lib/labels";
import s from "./page.module.css";

export const metadata = { title: "업체 확정" };

/** 비교에 없는 요청(닫힘)이나 견적서가 아직 없는 요청을 열었을 때 */
const SHUT: Record<string, string> = {
  requested: "아직 견적서가 오지 않았어요.",
  cancelled: "취소된 실측의 견적서라 고를 수 없어요.",
  declined: "업체가 받지 못한 요청이라 고를 수 없어요.",
  closed: "닫힌 실측의 견적서라 고를 수 없어요.",
};

type Params = { params: Promise<{ id: string; visitId: string }>; searchParams: Promise<{ trade?: string }> };

export default async function ConfirmPage({ params, searchParams }: Params) {
  const { id, visitId } = await params;
  const { trade: asked } = await searchParams;
  const p = await getMyProject(id);
  if (!p) notFound();
  const trades = TRADE_ORDER.filter((t) => p.trades[t]);
  if (!trades.length) notFound();

  // 요청이 있는 공정: 주소의 trade를 먼저 보고, 없으면 다른 공정에서 찾는다
  const order = isTrade(asked) && trades.includes(asked) ? [asked, ...trades.filter((t) => t !== asked)] : trades;
  let found: { trade: VTrade; c: QuoteCompare; r: QuoteCompare["vendors"][number] } | null = null;
  for (const t of order) {
    const c = await getQuoteCompare(id, t);
    const r = c?.vendors.find((v) => v.visit_id === visitId);
    if (c && r) { found = { trade: t, c, r }; break; }
  }

  const title = projectTitle(p.region, trades);
  const crumb = (trade: VTrade, here: string) => (
    <nav className={`mj-wrap mj-crumb ${s.crumb}`} aria-label="이동 경로">
      <ol>
        <li><Link href="/my">내 공사</Link><span aria-hidden="true">›</span></li>
        <li><Link href={`/projects/${id}`}>{title}</Link><span aria-hidden="true">›</span></li>
        <li><Link href={`/projects/${id}/quotes?trade=${trade}`}>{tradeLabel(trade)} 실측 견적 비교</Link><span aria-hidden="true">›</span></li>
        <li><span aria-current="page">{here}</span></li>
      </ol>
    </nav>
  );
  const shut = (trade: VTrade, msg: string, extra?: React.ReactNode) => (
    <main id="main">
      {crumb(trade, `${tradeLabel(trade)} 업체 확정`)}
      <div className={`mj-wrap ${s.shut}`}>
        <h1 className="mj-h1">{tradeLabel(trade)} 업체 확정</h1>
        <p className={`mj-error ${s.msg}`}><Warn />{msg}</p>
        {extra}
        <Link className="mj-lnk" href={`/projects/${id}/quotes?trade=${trade}`}>실측 견적 비교로</Link>
      </div>
    </main>
  );

  if (!found) {
    // 비교에는 닫힌 요청이 없다: 이 집 요청 목록에서 찾아 까닭을 보인다
    const all = await listProjectVisits(id);
    const v = all?.visits.find((x) => x.id === visitId);
    if (!v || !isTrade(v.trade)) notFound();
    // 닫힌 요청: 확정이 살아 있고 다른 업체 확정으로 닫혔으면 확정한 업체를, 그 밖(지난 실측)은 업체 고르기로 보낸다
    const done = (await listDeals(id, v.trade))?.[0] ?? null;
    const kind = shutKind(v, !!done);
    if (done && kind === "other") return shut(v.trade, "이미 업체를 확정했어요.", <p className="mj-num">{tradeLabel(v.trade)} · {done.vendor_name} · {when(done.confirmed_at)} 확정</p>);
    if (kind === "past") {
      return shut(v.trade, "지난 실측의 견적서라 고를 수 없어요.", done ? undefined : <Link className="mj-lnk" href={`/projects/${id}/vendors?trade=${v.trade}`}>업체 고르기</Link>);
    }
    return shut(v.trade, SHUT[v.status] ?? "고를 수 없는 견적서예요.");
  }

  const { trade, c, r } = found;
  const tName = tradeLabel(trade);
  const name = r.vendor_name;
  const deal = c.deal;
  // 같은 공정을 다른 업체로 이미 확정했을 때
  if (deal && deal.visit_id !== visitId) {
    return shut(trade, "이미 업체를 확정했어요.", <p className="mj-num">{tName} · {deal.vendor_name} · {when(deal.confirmed_at)} 확정</p>);
  }
  if (!r.latest || r.seen_ver == null) return shut(trade, SHUT.requested);

  const mine = !!deal; // 이 요청으로 확정함
  const others = c.vendors.filter((v) => v.visit_id !== visitId && (v.status === "requested" || v.status === "quoted")).map((v) => v.vendor_name);
  const otherTrade = trades.find((t) => t !== trade);
  const otherDeal = otherTrade ? (await listDeals(id, otherTrade))?.[0] ?? null : null;
  const compareHref = `/projects/${id}/quotes?trade=${trade}`;

  return (
    <main id="main">
      {crumb(trade, `${tName} 업체 확정`)}
      <div className={`mj-wrap ${s.layout}`}>
        <div className={s.main}>
          <div className={s.head}>
            <h1 className="mj-h1">{mine ? `${euro(name)} ${tName} 업체를 확정했어요` : `${euro(name)} ${tName} 업체를 확정할까요?`}</h1>
          </div>

          <QuoteSummary r={r} projectId={id} standardTotal={c.standard_total} title={mine ? "확정한 견적서" : "확정할 견적서"} />

          {/* 확정하면 생기는 일을 확인 체크 · 확정 버튼보다 먼저 읽게 둔다 */}
          {mine ? null : (
            <section aria-labelledby="after-h" className={s.after}>
              <h2 id="after-h" className="mj-h2">확정하면</h2>
              <ol className={s.steps}>
                <li>
                  <span className="mj-code" aria-hidden="true">1</span>
                  <div className={s.stepBody}>
                    <p className={s.stepT}>{iGa(name)} 공사 날짜를 내요</p>
                    <p className="mj-small">날짜가 오면 알림으로 알려 드려요. 기한이 지나면 다른 업체를 고를 수 있어요.</p>
                  </div>
                </li>
                <li>
                  <span className="mj-code" aria-hidden="true">2</span>
                  <div className={s.stepBody}>
                    <p className={s.stepT}>이미 보이는 연락처로 전화해 날짜를 정해도 돼요</p>
                    <p className="mj-small">정한 날짜는 {iGa(name)} 믿집에 올리고, 수락해야 확정돼요.</p>
                  </div>
                </li>
              </ol>
            </section>
          )}

          <ConfirmBox
            projectId={id}
            visitId={visitId}
            trade={trade}
            vendorName={name}
            seenVer={r.seen_ver}
            others={others}
            expired={r.expired}
            validUntil={r.latest.valid_until}
            deal={mine ? deal : null}
            compareHref={compareHref}
            other={otherTrade ? { trade: otherTrade, deal: otherDeal } : null}
          />
        </div>

        {/* 다른 공정 칸은 이 공정을 확정한 뒤, 다른 공정도 확정했을 때만 (확정 전 결정에는 필요 없다) */}
        {otherTrade && mine && otherDeal ? (
          <aside className={s.aside} aria-label="다른 선택">
            <OtherTrade projectId={id} trade={otherTrade} deal={otherDeal} />
          </aside>
        ) : null}
      </div>
    </main>
  );
}
