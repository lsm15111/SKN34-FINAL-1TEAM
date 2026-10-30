// 공정표: 작업 × 날짜(하루 한 칸). 위 줄에 월, 아래 줄에 일을 쓰고, 일하는 날이 아닌 날은 휴무로 칠한다.
// 날짜 칸은 API가 준 '일하는 날'의 첫날부터 끝날까지 늘어놓을 뿐이고 일정을 새로 계산하지 않는다.
import type { SlotRef } from "@/lib/types";
import { calendarSpan, md, todaySeoul } from "@/lib/format";

export type GanttRow = { label: string; sub: string; from: SlotRef; to: SlotRef; tone?: "a" | "b" };

const dayOf = (iso: string) => Number(iso.slice(8, 10));
const monthOf = (iso: string) => Number(iso.slice(5, 7));
export const period = (r: GanttRow) => (r.from.date === r.to.date ? md(r.from.date) : `${md(r.from.date)} ~ ${md(r.to.date)}`);

/** 월 머리줄: 같은 달이 이어지는 칸 수 */
export function monthGroups(cal: string[]) {
  const out: { m: number; n: number }[] = [];
  cal.forEach((d) => {
    const m = monthOf(d);
    const last = out[out.length - 1];
    if (last && last.m === m) last.n++;
    else out.push({ m, n: 1 });
  });
  return out;
}

export function Gantt({ caption, days, rows }: { caption: string; days: string[]; rows: GanttRow[] }) {
  const cal = calendarSpan(days);
  const work = new Set(days);
  const today = todaySeoul();
  const on = (r: GanttRow, d: string | undefined) => !!d && work.has(d) && d >= r.from.date && d <= r.to.date;
  const cls = (d: string, extra = "") => [extra, work.has(d) ? "" : "off", d === today ? "today" : ""].filter(Boolean).join(" ") || undefined;

  return (
    <div className="mj-table-box mj-gantt-box">
      <table className="mj-gantt" style={{ minWidth: 260 + cal.length * 44 }}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col" rowSpan={2} className="mj-gantt-task">작업</th>
            {monthGroups(cal).map((g, i) => <th key={i} scope="colgroup" colSpan={g.n} className="mj-gantt-month">{g.m}월</th>)}
          </tr>
          <tr>
            {cal.map((d) => (
              <th key={d} scope="col" className={cls(d, "mj-gantt-day")}>
                <span aria-hidden="true">{dayOf(d)}</span>
                <span className="mj-sr">{md(d)}{work.has(d) ? "" : " 휴무"}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, j) => (
            <tr key={r.label + r.sub}>
              <th scope="row" className="mj-gantt-task">
                <span className="in">
                  <span className="mj-gantt-no mj-num">{j + 1}</span>
                  <span><b>{r.label}</b><span className="mj-tiny">{r.sub} · {period(r)}</span></span>
                </span>
              </th>
              {cal.map((d, i) => {
                const now = on(r, d);
                const inRange = d >= r.from.date && d <= r.to.date;
                const bar = ["mj-gantt-bar", r.tone === "b" ? "b" : "a", on(r, cal[i - 1]) ? "cont-l" : "", on(r, cal[i + 1]) ? "cont-r" : ""].filter(Boolean).join(" ");
                return (
                  <td key={d} className={cls(d)}>
                    {now ? <span className={bar} aria-hidden="true" /> : null}
                    {now || inRange ? <span className="mj-sr">{now ? "작업" : "휴무"}</span> : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
