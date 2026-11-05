// 확정 공정표 화면 (시안 WPlanDone). 공사 날짜를 하나라도 수락하면 /projects/[id]/plan이 이 모습이 된다.
// 칸 상태(수락함 · 수락 전 · 예상 자리) · 업체 · 날짜 · 일하는 날 · 새 날짜 미리 보기는 모두 API(계산 엔진) 값이다.
// 공사 중 추가 금액은 공정마다 PlanExtras(확인 기다림이면 머리에 한 줄). 업체가 공사를 끝냈다고 올리면 WorkCheck(확인 · 남은 일 · 끝남, plan.deals)를 머리 아래 둔다.
// 연락처 기한(contact_until)은 plan.deals 값 그대로다. 공사 전에 할 일은 PreWorkCheck(체크 목록 · 시작일은 한 공사 화면 API 값)로 공사 시작 전에만 둔다. 상담 묻기는 넣지 않는다.
import Link from "next/link";
import { Clock } from "@/components/confirm/DealStatus";
import { day, when } from "@/components/confirm/text";
import { PlanTabs } from "@/components/project/PlanTabs";
import { PreWorkCheck } from "@/components/project/PreWorkCheck";
import { ProjectCrumb } from "@/components/project/ProjectCrumb";
import type { TradeDates } from "@/components/schedule/text";
import { Warn } from "@/components/vendors/icons";
import { iGa, telDigits } from "@/components/vendors/text";
import { md, todaySeoul } from "@/lib/format";
import type { Schemas } from "@/lib/backend/client";
import { tradeLabel } from "@/lib/labels";
import { ChangeArea, type ChangeItem } from "./ChangeArea";
import { ChangePreview } from "./ChangePreview";
import { FinalDays } from "./FinalDays";
import { PlanContacts, type PlanContact } from "./PlanContacts";
import { PlanExtras, type ExtraDeal } from "./PlanExtras";
import { StateBars, StateLegend } from "./StateBars";
import { WorkCheck } from "./WorkCheck";
import { blockRows, stateLine, workEnd, type Plan } from "./text";
import s from "./plan.module.css";

type Props = {
  id: string; title: string; plan: Plan; rows: TradeDates[]; contacts: PlanContact[];
  /** 공사 전에 할 일 (GET overview의 checks) · 공사 시작일 (overview.period가 확정일 때) */
  checks: Schemas["ProjectCheckOut"][]; start: string | null;
};

/** 수락한 날짜 바꾸기 요청을 보낸 뒤: 보낸 때 · 업체가 새 날짜를 올릴 기한 (기한 지남이면 그 한 줄) */
function RequestLine({ t }: { t: TradeDates }) {
  const r = t.request;
  if (!r) return null;
  const v = t.deal.vendor_name;
  const tName = tradeLabel(t.deal.trade);
  return r.overdue ? (
    <div className={s.reqLines}>
      <p className={`mj-st mj-st-bad mj-num ${s.stBig}`}><Warn />{tName} 날짜 바꾸기 · 기한 지남 · {when(r.due_at)}</p>
      <p className="mj-small">지금 날짜는 그대로예요. {v}에 전화해 이야기해요.</p>
    </div>
  ) : (
    <div className={s.reqLines}>
      <p className={`mj-st mj-st-wait mj-num ${s.stBig}`}><Clock />{when(r.created_at)}에 {tName} 날짜 바꾸기를 요청했어요 · {iGa(v)} {when(r.due_at)}까지 새 날짜를 올려요</p>
      <p className="mj-small mj-num">고른 날 {r.wish_dates.map((w) => `${day(w)} 시작`).join(" · ")}{r.reason ? ` · 이유: ${r.reason}` : ""}</p>
      <p className="mj-small">새 날짜가 오면 여기에 얹어 보여요. 그전까지 지금 날짜가 그대로예요.</p>
    </div>
  );
}

export function FinalPlan({ id, title, plan, rows, contacts, checks, start }: Props) {
  // 모든 공정을 수락했으면 막대마다 '날짜 수락함'을 쓰지 않는다 (범례 색으로 안다)
  const allOk = plan.blocks.filter((b) => b.kind === "work").every((b) => b.state === "confirmed");
  const bars = blockRows(plan.blocks).map((r) => (allOk && r.tone === "confirmed" ? { ...r, text: "" } : r));
  const end = workEnd(plan);
  const clean = plan.blocks.find((b) => b.kind === "clean");
  const byTrade = (t: string) => rows.find((r) => r.deal.trade === t);
  const tel = (t: string) => telDigits(contacts.find((c) => c.trade === t)?.ct.phone) || null;
  const items: ChangeItem[] = plan.changes.map((c) => ({
    change: c,
    preview: <ChangePreview c={c} now={plan.days} />,
    requestsLeft: byTrade(c.trade)?.requests_left ?? 0,
    requestOpen: !!byTrade(c.trade)?.request,
    tel: tel(c.trade),
  }));
  const asked = rows.filter((r) => r.dates_state === "change_requested" && r.request);
  const pending = plan.blocks.filter((b) => b.kind === "work" && b.state === "pending" && b.trade);
  // 날짜 바꾸기 요청: 수락한 공정 중 아직 요청할 수 있는 것 (하나면 그 공정 탭으로)
  const movable = rows.filter((r) => r.deal.status === "scheduled" && r.dates_state === "scheduled" && r.requests_left > 0);
  // 추가 금액: 확정마다 확정 금액 · 전화 번호, 확인 기다리는 수(API 줄 수)
  const extraDeals: Record<string, ExtraDeal> = Object.fromEntries(rows.map((r) => [r.deal.id, { total: r.deal.quote.total, tel: tel(r.deal.trade) }]));
  const extraWait = plan.extras.reduce((n, g) => n + g.items.filter((x) => x.ack === "pending").length, 0);
  // API 목록 순서가 고정되지 않아 막대와 같은 공정 순서로 늘어놓는다
  const workOrder = plan.blocks.filter((b) => b.kind === "work").map((b) => b.trade);
  const extraGroups = [...plan.extras].sort((a, b) => workOrder.indexOf(a.trade) - workOrder.indexOf(b.trade));
  // 공사 끝냄 확인 · 연락처 기한: 공정마다 확정(plan.deals), 막대와 같은 공정 순서로
  const deals = [...plan.deals].sort((a, b) => workOrder.indexOf(a.trade) - workOrder.indexOf(b.trade));
  const dealTels = Object.fromEntries(deals.map((x) => [x.id, tel(x.trade)]));
  const contactRows = contacts.map((c) => ({ ...c, until: deals.find((x) => x.trade === c.trade)?.contact_until ?? null }));

  return (
    <main id="main">
      <ProjectCrumb id={id} title={title} here="확정 공정표" />
      <div className={`mj-wrap ${s.top}`}>
        <div className={s.topL}>
          <div className={s.h}>
            <h1 className="mj-h1">확정 공정표</h1>
          </div>
          <p className="mj-sub">{stateLine(plan.blocks)}</p>
          <p className={`mj-num ${s.line}`}>일하는 날 <b>{plan.work_days}일</b> · 공사 <b>{md(plan.start)} ~ {md(end)}</b>{clean ? <> · 입주 청소 <b>{md(clean.end)}</b></> : null} · {plan.weekend_work ? "주말에도 공사" : "주말 휴일"}</p>
          {extraWait ? (
            <p className={s.exLead}><span className="mj-st mj-st-now mj-num">업체가 알린 추가 금액 {extraWait}건 · 확인 기다림</span><a className="mj-lnk" href="#extras">추가 금액 보기</a></p>
          ) : null}
        </div>
        <Link className="mj-lnk" href={`/projects/${id}/plan?kind=expected`}>예상 공정표 보기</Link>
      </div>

      <div className={`mj-wrap ${s.workTop}`}><WorkCheck projectId={id} deals={deals} tels={dealTels} /></div>

      <div className="mj-wrap">
        <ChangeArea projectId={id} version={plan.version} items={items} lead={asked.length ? asked.map((t) => <RequestLine key={t.deal.id} t={t} />) : null} />
      </div>

      <section className={`mj-wrap ${s.views}`} aria-labelledby="fp-t">
        <h2 id="fp-t" className="mj-sr">확정 공정표</h2>
        <PlanTabs
          bars={<><StateBars days={plan.days} rows={bars} label="확정 공정표 막대, 옆으로 넘겨 볼 수 있어요. 같은 내용은 날짜별 표에 있어요" /><StateLegend rows={bars} days={plan.days} /></>}
          list={<FinalDays plan={plan} quiet={allOk} />}
        />
        {pending.length || movable.length ? (
          <div className={s.under}>
            {pending.map((b) => <Link key={b.trade} className="mj-btn mj-btn-pri" href={`/projects/${id}/schedule?trade=${b.trade}`}>{tradeLabel(b.trade ?? "")} 날짜 확인하기</Link>)}
            {movable.length ? (
              <Link className="mj-btn mj-btn-sec" href={`/projects/${id}/schedule${movable.length === 1 ? `?trade=${movable[0].deal.trade}` : ""}`}>공사 날짜 바꾸기 요청</Link>
            ) : null}
          </div>
        ) : null}
      </section>

      <div className={`mj-wrap ${s.foot}`}>
        {start && start > todaySeoul() ? <PreWorkCheck projectId={id} checks={checks} start={start} /> : null}
        <PlanExtras projectId={id} groups={extraGroups} deals={extraDeals} multi={rows.length > 1} />
        <PlanContacts rows={contactRows} />
      </div>
    </main>
  );
}
