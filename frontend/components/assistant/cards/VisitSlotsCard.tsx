// C4 실측 시간 후보: 업체가 답한 기간 안의 반나절 2~3개(계산 엔진 recommend) + 근거. 고르면 승인 카드가 그 시간으로 바뀌어요.
// 시각은 실측 전날 채팅으로 정해요(반나절만 보여요). 달력에서 직접 고르기는 실측 일정 전체 화면 카드로 가요.
import Link from "next/link";
import { halfDayText, rangeText } from "@/lib/format";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function VisitSlotsCard({ card, ctx }: CardProps<"visit_slots">) {
  const d = card.data;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>이 시간 어때요?</h3>
        <span className={`${k.muted} ${k.num}`}>{d.vendor_name} · {rangeText(d.window.start, d.window.end)}</span>
      </div>
      <ul className={c.cands} role="radiogroup" aria-label={`${d.vendor_name} 실측 시간 후보`}>
        {d.candidates.map((s) => {
          const on = d.chosen === s.ref;
          return (
            <li key={s.ref}>
              <button type="button" role="radio" aria-checked={on} className={c.cand} disabled={ctx.busy && !on}
                onClick={() => { if (!on) ctx.send(`${halfDayText(s.day, s.half)}로 할래요`, { card_id: card.card_id, choice: s.ref }); }}>
                <span className={c.radio} aria-hidden="true" />
                <b className={k.num}>{halfDayText(s.day, s.half, true)}</b>
                <small>{s.why.join(" · ")}</small>
              </button>
            </li>
          );
        })}
      </ul>
      <p className={k.decided}><I n="info" />{d.instant ? "고르면 바로 확정돼요" : "고르면 업체가 수락할 때 확정돼요"}</p>
      <div className={k.row}>
        <Link className={`${k.btn} ${k.sm}`} href={d.calendar_href} scroll={false}><I n="calendar" />달력에서 고르기</Link>
      </div>
    </section>
  );
}
