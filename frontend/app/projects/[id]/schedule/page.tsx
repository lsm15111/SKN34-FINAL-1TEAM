// 공사 날짜 (시안 WSchedule): 공정 탭 · 확정 업체가 낸 날짜를 보고 수락하거나 다른 날짜를 요청한다.
// 읽기는 GET /projects/{id}/schedule 하나(공정마다 확정 · 낸 날짜 · 요청 · 겹침 · 요청 후보), 연락처는 GET /projects/{id}/visits?trade=.
// 날짜 · 일하는 날 · 기한 · 겹침은 API 값 그대로다. 수락한 뒤에는 날짜 바꾸기(요청 · 업체가 올린 새 날짜 수락)를 여기서 하고 확정 공정표로 잇는다.
// 공사 중 추가 금액(공정마다 extras)은 맨 아래 PlanExtras로 보이고 답한다(확정 공정표와 같은 칸).
// 업체가 공사를 끝냈다고 올리면 WorkCheck(확인했어요 · 아직 남은 일이 있어요 · 남은 일 기다림 · 끝남)를 확정 공정표와 같이 쓰고, 날짜 바꾸기는 막는다.
import Link from "next/link";
import { notFound } from "next/navigation";
import { Check } from "@/components/vendors/icons";
import { dealReselectText, canReselect } from "@/components/confirm/text";
import { PlanExtras } from "@/components/plan/PlanExtras";
import { WorkCheck } from "@/components/plan/WorkCheck";
import { ProjectCrumb } from "@/components/project/ProjectCrumb";
import { ContactStrip } from "@/components/schedule/ContactStrip";
import { DatesBox } from "@/components/schedule/DatesBox";
import { DatesFacts } from "@/components/schedule/DatesFacts";
import { Overlay } from "@/components/schedule/Overlay";
import { ScheduleTabs } from "@/components/schedule/ScheduleTabs";
import { ChangedLine, MoveLine, RequestLines, WaitLines } from "@/components/schedule/StateLines";
import { isAccepted, isFinished, span, type TradeDates } from "@/components/schedule/text";
import { iGa, isTrade, telDigits, type VTrade } from "@/components/vendors/text";
import { getMyProject } from "@/lib/api/project";
import { getSchedule } from "@/lib/api/schedule";
import { listProjectVisits } from "@/lib/api/visit";
import { projectTitle, tradeLabel, TRADE_ORDER } from "@/lib/labels";
import s from "./page.module.css";

export const metadata = { title: "공사 날짜" };

/** 주소에 공정이 없으면 고객이 할 일이 있는 공정(날짜 옴 · 요청함)을 먼저 연다 */
function pick(trades: VTrade[], rows: TradeDates[], asked: string | undefined): VTrade {
  if (isTrade(asked) && trades.includes(asked)) return asked;
  const has = (st: string[]) => trades.find((t) => rows.some((r) => r.deal.trade === t && st.includes(r.dates_state)));
  return has(["proposed", "requested"]) ?? has(["waiting", "scheduled"]) ?? trades[0];
}

function heading(t: TradeDates | undefined, tName: string) {
  if (!t) return { h: `${tName} 업체를 아직 확정하지 않았어요`, sub: "실측 견적서를 비교해 업체를 확정하면 업체가 공사 날짜를 내요." };
  const v = t.deal.vendor_name;
  const x = t.proposal;
  if (isAccepted(t)) {
    if (t.deal.status === "checking") return { h: `${tName} 공사가 끝났는지 확인해 주세요`, sub: `${iGa(v)} 공사를 끝냈다고 알렸어요.` };
    if (t.deal.status === "fixing") return { h: `${tName} 남은 일을 기다려요`, sub: `${iGa(v)} 남은 일을 마치고 다시 올리면 확인해요.` };
    if (t.deal.status === "done") return { h: `${tName} 공사가 끝났어요`, sub: null };
    if (t.deal.status !== "scheduled") return { h: `${tName} 공사 날짜를 수락했어요`, sub: null };
    // 수락한 뒤 날짜 바꾸기: 업체가 새 날짜를 올림(요청에 답함 · 스스로 바꾸자고 함) · 고객이 요청함
    if (x) return { h: x.request_id ? `${iGa(v)} 새 ${tName} 날짜를 올렸어요` : `${iGa(v)} ${tName} 날짜를 바꾸자고 했어요`, sub: "내 공정표에 얹어 보고 수락하면 바뀌어요." };
    if (t.request) return { h: `${tName} 공사 날짜 바꾸기를 요청했어요`, sub: `${v} 답을 기다려요. 그동안 수락한 날짜는 그대로예요.` };
    return { h: `${tName} 공사 날짜를 수락했어요`, sub: null };
  }
  if (t.dates_state === "requested") return { h: `${tName} 공사 날짜를 다른 날로 요청했어요`, sub: `${v} 답을 기다려요. 그동안 지금 날짜는 그대로 남아 있어요.` };
  if (!x) return { h: `${tName} 공사 날짜를 기다려요`, sub: "날짜가 오면 내 공정표에 얹어 보고 수락해요. 수락해야 확정돼요." };
  if (x.changed) return { h: `${iGa(v)} ${tName} 공사 날짜를 다시 냈어요`, sub: "내 공정표에 얹어 보고 수락해야 확정돼요." };
  return { h: x.method === "call" ? `${iGa(v)} 통화로 정한 ${tName} 공사 날짜를 냈어요` : `${iGa(v)} ${tName} 공사 날짜를 냈어요`, sub: "내 공정표에 얹어 보고 수락해야 확정돼요." };
}

export default async function SchedulePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ trade?: string }> }) {
  const { id } = await params;
  const { trade: asked } = await searchParams;
  const [p, sch] = await Promise.all([getMyProject(id), getSchedule(id)]);
  if (!p || !sch) notFound();
  const trades = TRADE_ORDER.filter((t) => p.trades[t]);
  if (!trades.length) notFound();
  const trade = pick(trades, sch.trades, asked);
  const tName = tradeLabel(trade);
  const t = sch.trades.find((r) => r.deal.trade === trade);
  const deal = t?.deal ?? null;
  const x = t?.proposal ?? null;
  const { h, sub } = heading(t, tName);

  // 연락처: 확정한 요청(chosen)이 공개 규칙대로 준 것만
  const visit = deal ? (await listProjectVisits(id, trade))?.visits.find((v) => v.id === deal.visit_id) : undefined;
  const ct = visit?.contact_visible ? visit.contact : null;
  const tel = ct?.phone ? telDigits(ct.phone) || null : null;
  const finished = !!deal && isFinished(deal.status);

  // 다시 고르기 확인 창: 업체가 낸 날짜 · 보낸 요청도 없어진다는 말을 더한다
  const otherTrade = trades.find((o) => o !== trade);
  const otherDeal = otherTrade ? sch.trades.find((r) => r.deal.trade === otherTrade)?.deal ?? null : null;
  const base = deal && canReselect(deal) ? dealReselectText(deal, otherTrade ? { trade: otherTrade, deal: otherDeal } : null) : null;
  const gone = deal && x ? ` ${iGa(deal.vendor_name)} 낸 공사 날짜${t?.request ? "와 보낸 다른 날짜 요청" : ""}도 없어져요.` : "";
  // 다음 할 일(주 버튼): 다른 공정에 수락할 날짜가 왔으면 그 공정 날짜 확인, 모든 공정을 수락했으면 확정 공정표
  const waitingOther = trades.find((o) => o !== trade && sch.trades.some((r) => r.deal.trade === o && !isAccepted(r) && !!r.proposal));
  const allAccepted = trades.every((o) => sch.trades.some((r) => r.deal.trade === o && isAccepted(r)));
  const next = waitingOther
    ? { href: `/projects/${id}/schedule?trade=${waitingOther}`, label: `${tradeLabel(waitingOther)} 날짜 확인하기` }
    : allAccepted ? { href: `/projects/${id}/plan`, label: "확정 공정표 보기" } : null;
  const reselect = base && deal
    ? { ...base, body: `${deal.vendor_name} 견적서가 닫히고 서로 보이던 연락처 · 주소가 바로 가려져요.${gone} 되돌릴 수 없어요.` }
    : null;

  return (
    <main id="main">
      <ProjectCrumb id={id} title={projectTitle(p.region, trades)} here="공사 날짜" />
      <div className={`mj-wrap ${s.body}`}>
        <ScheduleTabs base={`/projects/${id}/schedule`} trades={trades} current={trade} rows={sch.trades} />

        <div className={s.head}>
          <p className="mj-small"><span className={s.tn}>{tName}</span>{deal ? ` · ${deal.vendor_name}` : ""}</p>
          <h1 className="mj-h1">{h}</h1>
          {sub ? <p className="mj-sub">{sub}</p> : null}
        </div>

        {!t || !deal ? (
          <div className={s.empty}>
            <Link className="mj-btn mj-btn-pri" href={`/projects/${id}/quotes?trade=${trade}`}>{tName} 실측 견적 비교</Link>
            <Link className="mj-lnk" href={`/projects/${id}/plan?kind=expected`}>예상 공정표 보기</Link>
          </div>
        ) : (
          <>
            {isAccepted(t) ? (
              <>
                <div className={s.lines}>
                  {deal.start_date && deal.end_date ? <p className={`mj-st mj-st-ok mj-num ${s.st}`}><Check size={16} />{x || t.request ? "지금 공사 날짜" : "공사 날짜"} {span(deal.start_date, deal.end_date)}</p> : null}
                  <p className="mj-small">업체 확정 · {deal.vendor_name}</p>
                </div>
                {t.request ? <RequestLines r={t.request} vendorName={deal.vendor_name} left={t.requests_left} after /> : null}
                {x && deal.start_date && deal.end_date ? (
                  <>
                    <MoveLine x={x} vendorName={deal.vendor_name} start={deal.start_date} end={deal.end_date} />
                    <DatesFacts x={x} vendorName={deal.vendor_name} weekendWork={sch.weekend_work} holidays={sch.holidays} dateLabel="새 날짜" />
                  </>
                ) : null}
                {finished ? <WorkCheck key={deal.id} projectId={id} deals={[deal]} tels={{ [deal.id]: tel }} /> : null}
              </>
            ) : x ? (
              <>
                {t.request ? <RequestLines r={t.request} vendorName={deal.vendor_name} left={t.requests_left} /> : null}
                {t.request ? null : <ChangedLine x={x} vendorName={deal.vendor_name} />}
                <DatesFacts x={x} vendorName={deal.vendor_name} weekendWork={sch.weekend_work} holidays={sch.holidays} />
              </>
            ) : (
              <WaitLines vendorName={deal.vendor_name} dueAt={deal.dates_due_at} overdue={deal.overdue} />
            )}

            {ct ? <ContactStrip trade={trade} vendorName={deal.vendor_name} ct={ct} until={deal.contact_until} /> : null}

            <Overlay trades={trades} rows={sch.trades} current={trade} />

            <DatesBox
              key={deal.id}
              projectId={id}
              dealId={deal.id}
              trade={trade}
              vendorName={deal.vendor_name}
              accepted={isAccepted(t)}
              finished={finished}
              proposal={x}
              requested={!!t.request}
              request={t.request}
              multi={trades.length > 1}
              requestsLeft={t.requests_left}
              conflict={!!t.fit?.conflicts.length}
              options={t.start_options}
              weekendWork={sch.weekend_work}
              overdue={deal.overdue && !x}
              tel={tel}
              seenVersion={sch.final_version}
              reselect={reselect}
              finalHref={`/projects/${id}/plan`}
              next={next}
            />

            <PlanExtras projectId={id} groups={[t.extras]} deals={{ [deal.id]: { total: deal.quote.total, tel } }} multi={false} />
          </>
        )}
      </div>
    </main>
  );
}
