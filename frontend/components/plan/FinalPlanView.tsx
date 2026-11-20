// 확정 공정표(C36 폰 · D19 웹): 공사 날짜를 수락하면 생겨요. 날짜 · 기간 · 인원 · 금액은 계산 엔진 · API 값 그대로예요.
// 공정표 칸은 B4 ScheduleChart 두 보기(PlanViewTabs): 날짜별(날마다 오전 · 오후 줄) · 공정별(공정이 줄, 날짜가 열인 반나절 칸 표).
// 처음에는 폰 날짜별 · 웹 공정별이에요. 폰은 아래에 공사 전 할 일 · 캘린더 · 채팅 줄, 웹은 요약 칸 + 오른쪽 칸(할 일 · 채팅 · AI 자리).
import { AiPanel } from "@/components/ai/AiPanel";
import { AsidePanel } from "@/components/site/AsideSlot";
import { gwaWa } from "@/components/vendors/text";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { BigFigure } from "@/components/ui/Money";
import { ScheduleChart } from "@/components/ui/ScheduleChart";
import type { ApiPlan } from "@/lib/api/project";
import { dateLong, dateShort, won } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { planChart } from "./ExpectedPlan";
import { FileLink } from "./FileLink";
import { PlanChecks, type Check } from "./PlanChecks";
import { PlanViewTabs } from "./PlanViewTabs";
import s from "./planv3.module.css";

export function finalHead(plan: ApiPlan) {
  const work = plan.blocks.filter((b) => b.kind === "work");
  const deal = plan.deals[0];
  const vendor = work[0]?.vendor_name ?? deal?.vendor_name ?? "";
  const end = work.reduce((e, b) => (b.end > e ? b.end : e), work[0]?.end ?? plan.end);
  const trades = work.map((b) => `${tradeLabel(b.trade ?? "")} ${b.days}일`).join(" · ");
  return {
    badge: `확정 · ${dateShort(plan.computed_at)}`,
    made: `${dateLong(plan.computed_at)} 공사 날짜를 수락해서 만들어졌어요`,
    big: `${dateLong(plan.start)} 시작`,
    sub: [vendor, trades, `${dateLong(end)} 끝`].filter(Boolean).join(" · "),
  };
}

/** 본문(폰 · 웹 같이): 큰 날짜 · 폰 날 목록 · 웹 표 · 웹 요약 · 폰 할 일 · 폰 캘린더 · 채팅 */
export function FinalPlanBody({ plan, projectId, checks, mock }: { plan: ApiPlan; projectId: string; checks: Check[]; mock: boolean }) {
  const h = finalHead(plan);
  const work = plan.blocks.filter((b) => b.kind === "work");
  const workDays = plan.days.filter((d) => d.kind === "work").sort((x, y) => x.day.localeCompare(y.day));
  const chart = planChart(plan, true);
  const deal = plan.deals[0];
  const crewText = work.map((b) => [b.vendor_name ?? deal?.vendor_name, b.crew ? `${b.crew}명` : ""].filter(Boolean).join(" ")).find(Boolean) ?? "";
  const ics = `/api/projects/${encodeURIComponent(projectId)}/plan.ics`;
  const chat = deal?.thread_id ? `/chat/${encodeURIComponent(deal.thread_id)}` : "/chat";

  return (
    <>
      <section className={s.group} aria-label="공사 기간">
        <BigFigure caption={h.sub}>{h.big}</BigFigure>
      </section>

      {/* 공정표 칸(B4 ScheduleChart) 두 보기: 날짜별(날마다 '오전 도배 · 오후 도배') · 공정별(공정이 줄, 날짜가 열인 반나절 칸 표) */}
      <section className={s.group} aria-label="확정 공정표 칸">
        <PlanViewTabs
          days={<ScheduleChart caption="확정 공정표 · 날짜별" view="list" half days={chart.days} rows={chart.rows} legend={["work", "off"]} note="공휴일은 건너뛰어요." fold />}
          trades={<ScheduleChart caption="확정 공정표 · 공정별" view="table" half days={chart.days} rows={chart.rows} legend={["work", "off"]} note="공휴일은 건너뛰어요." fold />}
        />
        {crewText ? <p className={`${s.sm} ${s.phoneOnly}`}>{crewText}</p> : null}
      </section>

      {/* 웹: 요약 칸 */}
      {deal ? (
        <section className={`${s.group} ${s.webOnly}`} aria-label="확정 요약">
          <dl className={s.kv}>
            <div><dt>공사</dt><dd className="mj-num">{[...workDays.map((d) => dateShort(d.day)), `${workDays.length}일`].join(" · ")}</dd></div>
            {crewText ? <div><dt>업체</dt><dd>{crewText}</dd></div> : null}
            <div><dt>확정 금액 · 부가세 포함</dt><dd className="mj-num">{won(deal.quote.total)}</dd></div>
            <div><dt>견적서</dt><dd>{dateLong(deal.quote.sent_at)} 받은 것</dd></div>
          </dl>
        </section>
      ) : null}

      {/* 폰: 공사 전 할 일 · 캘린더 · 채팅 */}
      <div className={s.phoneOnly}>
        <section className={s.group} aria-labelledby="todo-t">
          <h2 id="todo-t" className={s.eb}>공사 전 할 일</h2>
          <PlanChecks projectId={projectId} checks={checks} mock={mock} />
        </section>
      </div>
      <div className={`${s.row1} ${s.phoneOnly}`}>
        <p className={s.rl}><b>내 캘린더에 넣기</b><span>공사 날이 들어가요</span></p>
        <FileLink href={ics}>캘린더 파일 받기</FileLink>
      </div>
      {deal ? (
        <a className={`${s.row1} ${s.rowLink} ${s.phoneOnly}`} href={chat}>
          <p className={s.rl}><b>날짜를 바꿔야 하면</b><span>채팅으로 {gwaWa(deal.vendor_name)} 이야기해요</span></p>
          <Icon name="chevron-right" size={20} />
        </a>
      ) : null}
    </>
  );
}

/** 웹 오른쪽 칸(D19): 공사 전 할 일 · 날짜 바꾸기 · 캘린더 · 채팅 + AI 칸(B5 AiPanel, 칸 안에 끼움) */
export function FinalPlanAside({ plan, projectId, checks, mock }: { plan: ApiPlan; projectId: string; checks: Check[]; mock: boolean }) {
  const deal = plan.deals[0];
  const ics = `/api/projects/${encodeURIComponent(projectId)}/plan.ics`;
  const chat = deal?.thread_id ? `/chat/${encodeURIComponent(deal.thread_id)}` : "/chat";
  return (
    <AsidePanel title="공사 전 할 일" listLabel="공사 전 할 일 · AI 채팅">
      <PlanChecks projectId={projectId} checks={checks} mock={mock} />
      <p className={s.eb}>날짜를 바꿔야 하면</p>
      <p className={s.sm}>채팅으로 {gwaWa(deal?.vendor_name ?? "업체")} 이야기해요.</p>
      <div className={s.asideBtns}>
        <FileLink href={ics} variant="secondary" size="sm">내 캘린더에 넣기</FileLink>
        <Button size="sm" href={chat}>채팅 열기</Button>
      </div>
      <hr className={s.sep} />
      <p className={s.eb}>AI 채팅</p>
      <AiPanel screen="plan" projectId={projectId} context="확정 공정표 보는 중" embed />
    </AsidePanel>
  );
}
