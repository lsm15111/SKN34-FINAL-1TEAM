// 예상 공정표(C08): 큰 일수 + 공정표 칸(B4 ScheduleChart, 하루 단위) + '도배 1.4(월)~1.5(화) · 2일'.
// 날짜 · 일수는 계산 엔진 값(GET /projects/{id}/plan)을 그대로 써요. 칸은 첫 공사 날부터 마지막 공사 날까지(사이 쉬는 날 포함)만 보여요.
// 건조 · 청소 칸은 응답에 남고 화면은 숨겨요(D22 B). 반셀프 직접 할 일은 범례 아래 '고객이 직접' 줄로 보여요.
// 시작 · 끝 날 문장은 두지 않고, 확정 공정표 안내는 '!' 도움말에 넣어요(웹은 제목 옆, 폰은 이 칸 위).
import { HelpTip } from "@/components/ui/HelpTip";
import { BigFigure } from "@/components/ui/Money";
import { ScheduleChart, type ChartDay, type ChartRow } from "@/components/ui/ScheduleChart";
import type { ApiPlan } from "@/lib/api/project";
import { dayParts, rangeText } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { SelfRows } from "./SelfRows";
import s from "./planv3.module.css";

/** 공사 날이 있는 줄 · 칸(쉬는 날은 열로만). final이면 하루를 오전 · 오후 두 칸으로 */
export function planChart(plan: ApiPlan, final: boolean): { days: ChartDay[]; rows: ChartRow[] } {
  const sorted = [...plan.days].sort((a, b) => a.day.localeCompare(b.day));
  const first = sorted.findIndex((d) => d.kind === "work");
  const last = sorted.findLastIndex((d) => d.kind === "work");
  const span = first < 0 ? [] : sorted.slice(first, last + 1);
  const deal = plan.deals[0];
  const rows = plan.blocks.filter((b) => b.kind === "work").map((b): ChartRow => ({
    key: `${b.trade ?? b.label}-${b.start}`,
    name: tradeLabel(b.trade ?? "") || b.label,
    // 예상(C08)은 공정 이름만, 확정(D19)은 업체 · 인원을 줄 이름 아래에
    sub: final ? [b.vendor_name ?? deal?.vendor_name, b.crew ? `${b.crew}명` : null].filter(Boolean).join(" · ") || undefined : undefined,
    cells: span
      .filter((d) => d.kind === "work" && (d.trade ?? b.trade) === b.trade && d.day >= b.start && d.day <= b.end)
      .flatMap((d) => (final ? [{ day: d.day, half: "am" as const, note: `${b.days}일` }, { day: d.day, half: "pm" as const, note: `${b.days}일` }] : [{ day: d.day, note: `${b.days}일` }])),
  }));
  return { days: span.map((d) => ({ day: d.day, off: d.kind === "off" || !!d.holiday, holiday: d.holiday })), rows };
}

export function ExpectedPlan({ plan }: { plan: ApiPlan }) {
  const { days, rows } = planChart(plan, false);
  const works = plan.blocks.filter((b) => b.kind === "work");
  const first = days[0] ? dayParts(days[0].day) : null;
  const last = days.at(-1) ? dayParts(days.at(-1)!.day) : null;
  const year = days[0]?.day.slice(0, 4);
  const month = first && last && first.m !== last.m ? `${year}년 ${first.m}월~${last.m}월` : first ? `${year}년 ${first.m}월` : "";

  return (
    <>
      <section className={s.group} aria-label="예상 공사 기간">
        <div className={s.ebRow}>
          <p className={s.eb}>예상 · 업체 확정 전</p>
          <HelpTip only="phone" label="확정 공정표 안내">확정 공정표는 업체를 확정하고 공사 날짜를 수락하면 만들어져요.</HelpTip>
        </div>
        <BigFigure>{plan.work_days}일</BigFigure>
      </section>
      <section className={s.group} aria-labelledby="gt-month">
        <p id="gt-month" className={s.gh}><b>{month}</b></p>
        <ScheduleChart caption="예상 공정표" days={days} rows={rows} legend={["work", "off"]} fold />
        <ul className={s.legend}>
          {works.map((b) => <li key={`${b.trade}-${b.start}`}><i aria-hidden="true" /><b>{tradeLabel(b.trade ?? "")}</b> <span className="mj-num">{rangeText(b.start, b.end, { weekday: true })} · {b.days}일</span></li>)}
          <SelfRows plan={plan} />
        </ul>
      </section>
    </>
  );
}
