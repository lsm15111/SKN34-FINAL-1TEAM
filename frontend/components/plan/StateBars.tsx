// 확정 공정표 막대 (시안 WPlanDone): 하루 한 칸, 줄마다 상태 색(수락함 · 수락 전 · 예상 자리 · 지금)과 막대 안 말.
// 칸은 API가 준 days를 그대로 늘어놓고, 줄의 날(on)이 이어진 칸끼리 막대로 잇는다. 막대 사이가 모두 쉬는 날이면 '휴일'을 적는다.
// 막대 안 말은 첫 조각과 두 칸 이상인 조각에만 적는다(한 칸 조각은 글이 잘린다).
// 날짜 · 기간을 새로 계산하지 않는다. 그림은 보조라 aria-hidden이고, 같은 내용은 날짜별 표 · 목록에 있다.
import { Fragment } from "react";
import { dayParts } from "@/lib/format";
import type { BarRow, Day, Tone } from "./text";
import s from "./plan.module.css";

export const TONE: Record<Tone, string> = { confirmed: s.tOk, pending: s.tPend, expected: s.tExp, now: s.tOk };

/** 줄이 칠할 칸 묶음: [첫 칸, 칸 수] */
function runs(r: BarRow, days: Day[]) {
  const out: [number, number][] = [];
  days.forEach((d, i) => {
    if (!r.on(d)) return;
    const last = out[out.length - 1];
    if (last && last[0] + last[1] === i) last[1]++;
    else out.push([i, 1]);
  });
  return out;
}

/** 막대 사이가 모두 쉬는 날인 틈: [첫 칸, 칸 수] */
function offGaps(rs: [number, number][], days: Day[]) {
  const out: [number, number][] = [];
  for (let j = 1; j < rs.length; j++) {
    const from = rs[j - 1][0] + rs[j - 1][1];
    const n = rs[j][0] - from;
    if (n > 0 && days.slice(from, from + n).every((d) => d.kind === "off")) out.push([from, n]);
  }
  return out;
}

export function StateBars({ days, rows, label }: { days: Day[]; rows: BarRow[]; label: string }) {
  const months = [...new Set(days.map((d) => dayParts(d.day).m))];
  const tall = `1 / ${rows.length + 2}`;
  return (
    <div className={s.scroll} role="region" tabIndex={0} aria-label={label}>
      <div
        className={`mj-num ${s.grid}`}
        aria-hidden="true"
        style={{ gridTemplateColumns: `232px repeat(${days.length}, minmax(48px, 1fr))`, gridTemplateRows: `48px repeat(${rows.length}, 56px)`, minWidth: 232 + days.length * 48 }}
      >
        {days.map((d, i) => (d.kind === "off" ? <span key={`o${d.day}`} className={s.offCol} style={{ gridColumn: i + 2, gridRow: tall }} /> : null))}
        {days.map((d, i) => <span key={`v${d.day}`} className={s.vline} style={{ gridColumn: i + 2, gridRow: tall }} />)}
        {[...rows, null].map((_, r) => <span key={`h${r}`} className={s.hline} style={{ gridRow: r + 1 }} />)}
        <span className={s.name} style={{ gridRow: 1 }}><span className="mj-small">작업 · {months.map((m) => `${m}월`).join(" ~ ")}</span></span>
        {days.map((d, i) => {
          const p = dayParts(d.day);
          return <span key={`d${d.day}`} className={`${s.head}${d.kind === "off" ? ` ${s.headOff}` : ""}`} style={{ gridColumn: i + 2 }}><b>{p.d === 1 && i > 0 ? `${p.m}.${p.d}` : p.d}</b>{p.w}</span>;
        })}
        {rows.map((r, i) => {
          const rs = runs(r, days);
          return (
            <Fragment key={r.key}>
              <span className={s.name} style={{ gridRow: i + 2 }}>
                <b>{r.name}{r.vendor ? <span className={s.vn}> · {r.vendor}</span> : null}</b>
                <span className="mj-small">{r.sub}</span>
              </span>
              {rs.map(([c, n], j) => <span key={c} className={`${s.bar} ${TONE[r.tone]}`} style={{ gridRow: i + 2, gridColumn: `${c + 2} / span ${n}` }}>{j === 0 || n > 1 ? r.text : null}</span>)}
              {offGaps(rs, days).map(([c, n]) => <span key={`g${c}`} className={s.gap} style={{ gridRow: i + 2, gridColumn: `${c + 2} / span ${n}` }}>휴일</span>)}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

const LEGEND: Record<Exclude<Tone, "now">, string> = { confirmed: "날짜 수락함", pending: "수락 전", expected: "예상 자리 · 건조 · 청소" };

/** 범례: 줄에 있는 색만 (수락함 · 수락 전 · 예상 자리 · 건조 · 청소 · 휴일). 미리 보기는 지금 · 새 날짜를 덧붙인다 */
export function StateLegend({ rows, days, change }: { rows: BarRow[]; days: Day[]; change?: boolean }) {
  const has = (t: Tone) => rows.some((r) => r.tone === t);
  const text = (t: Exclude<Tone, "now">) => (change && t === "confirmed" && has("now") ? "날짜 수락함 · 지금 날짜" : change && t === "pending" ? "새 날짜 · 수락 전" : LEGEND[t]);
  const tones = (["confirmed", "pending", "expected"] as const).filter((t) => has(t) || (t === "confirmed" && has("now")));
  return (
    <ul className={s.legend} aria-hidden="true">
      {tones.map((t) => <li key={t}><span className={TONE[t]} />{text(t)}</li>)}
      {days.some((d) => d.kind === "off") ? <li><span className={s.offKey} />휴일 · 공사 없는 날</li> : null}
    </ul>
  );
}
