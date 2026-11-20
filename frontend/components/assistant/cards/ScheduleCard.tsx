// C6 공사 날짜 · 확정 공정표: 업체가 하루씩 고른 날(반나절 칸) · 일하는 날 n일 · 다른 공정과 겹침.
// 날 · 일수는 계산 엔진 값이에요. 수락은 승인 카드가 맡고, 이 카드는 보여 주기만 해요.
import Link from "next/link";
import { dayParts, rangeText } from "@/lib/format";
import { DecidedLine, SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function ScheduleCard({ card }: CardProps<"schedule">) {
  const d = card.data;
  const final = d.phase === "final";
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{final ? "확정 공정표" : "공사 날짜가 왔어요"}</h3>
        {final ? <SourceTag src="calc" /> : <span className={k.muted}>{d.vendor_name}</span>}
      </div>
      <div className={c.span}>
        <span>{final ? `공정표 ${d.plan_version}판` : "업체가 고른 날"}</span>
        <b className={k.num}>{rangeText(d.start, d.end, { weekday: true })}</b>
        <small className={k.num}>일하는 날 {d.work_days}일</small>
      </div>
      <div className={c.halves} style={{ "--n": d.days.length } as React.CSSProperties} role="img" aria-label={`${rangeText(d.start, d.end, { weekday: true })} 도배, 오전 · 오후 칸`}>
        <span />
        {d.days.map((x) => { const p = dayParts(x.day); return <span key={x.day} className={x.off ? `${c.h} ${c.off}` : c.h}><b className={k.num}>{p.d}</b>{p.w}</span>; })}
        <span className={c.lab}>오전</span>
        {d.days.map((x) => <span key={`${x.day}am`} className={x.am ? `${c.cell} ${c.work}` : c.cell}>{x.am ?? ""}</span>)}
        <span className={c.lab}>오후</span>
        {d.days.map((x) => <span key={`${x.day}pm`} className={x.pm ? `${c.cell} ${c.work}` : c.cell}>{x.pm ?? ""}</span>)}
      </div>
      {d.conflicts.length ? (
        <p className={k.err}>{d.conflicts.join(" · ")}과 겹쳐요</p>
      ) : (
        <DecidedLine>다른 공정과 겹치지 않아요</DecidedLine>
      )}
      <div className={k.row}>
        <Link className={`${k.btn} ${k.sm}`} href={d.href} scroll={false}>공정표 열기</Link>
        {d.ics_href ? <a className={`${k.btn} ${k.sm}`} href={d.ics_href} download><I n="calendar" />달력에 넣기</a> : null}
      </div>
    </section>
  );
}
