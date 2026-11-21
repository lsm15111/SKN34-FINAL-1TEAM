// C6 공사 날짜 · 확정 공정표: 업체가 하루씩 고른 날(반나절 칸) · 일하는 날 n일 · 다른 공정과 겹침.
// 날 · 일수는 계산 엔진 값이에요. 수락 전 날짜(phase dates)면 [이 날짜로 수락]이 수락 승인 카드를 만들어요
// (choice '<proposal_kind>:<proposal_ref>': 처음 날짜 dates_accept · 수락한 뒤 바뀐 날짜 delay_accept). 실행은 승인 카드를 눌러야 해요.
// 다른 공정과 겹치면 수락할 수 없어서 단추를 두지 않아요.
// 업체가 날짜를 바꾼 까닭은 '업체가 적은 말' 칸에만 보여요(업체 글 그대로).
import Link from "next/link";
import { dayParts, rangeText } from "@/lib/format";
import { DecidedLine, SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

/** 수락할 공사 날짜 제안 이름표(backend assistant/schemas.py ScheduleData, 수락 전 날짜일 때만) */
type Proposal = { proposal_ref?: string | null; proposal_kind?: "dates_accept" | "delay_accept" | null };

export function ScheduleCard({ card, ctx }: CardProps<"schedule">) {
  const d: typeof card.data & Proposal = card.data;
  const final = d.phase === "final";
  const accept = !final && d.proposal_ref && d.proposal_kind && !d.conflicts.length ? `${d.proposal_kind}:${d.proposal_ref}` : null;
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
      {d.vendor_note ? <blockquote className={c.vnote}><b>업체가 적은 말</b>{d.vendor_note}</blockquote> : null}
      <div className={k.row}>
        {accept ? (
          <button type="button" className={`${k.btn} ${k.sm} ${k.pri}`} disabled={ctx.busy}
            onClick={() => ctx.send("이 날짜로 수락할래요", { card_id: card.card_id, choice: accept })}>
            이 날짜로 수락
          </button>
        ) : null}
        <Link className={`${k.btn} ${k.sm}`} href={d.href} scroll={false}>공정표 열기</Link>
        {d.ics_href ? <a className={`${k.btn} ${k.sm}`} href={d.ics_href} download><I n="calendar" />달력에 넣기</a> : null}
      </div>
    </section>
  );
}
