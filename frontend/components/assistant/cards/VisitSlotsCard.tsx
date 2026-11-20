// C4 실측 시간 후보. 두 모양이에요(계산 엔진 calc.slots 값 그대로):
// - 요청 전(window 없음): 희망 기간 후보 1~2개(업체 빈 반나절 수) → 고르면 실측 요청 승인 카드가 그 기간으로 바뀌어요.
// - 요청 뒤: 업체가 답한 기간 안의 반나절 2~3개 + 근거 → 고르면 승인 카드가 그 시간으로 바뀌어요.
// 근거는 코드라 화면 말로 바꿔요(whyText). 시각은 실측 전날 채팅으로 정해요(반나절만 보여요).
import Link from "next/link";
import { whyText } from "@/lib/api/assistant";
import { halfDayText, rangeText } from "@/lib/format";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function VisitSlotsCard({ card, ctx }: CardProps<"visit_slots">) {
  const d = card.data;
  const before = !d.window && d.wishes.length > 0;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{before ? "희망 기간 어때요?" : "이 시간 어때요?"}</h3>
        <span className={`${k.muted} ${k.num}`}>{d.vendor_name}{d.window ? ` · ${rangeText(d.window.start, d.window.end)}` : ""}</span>
      </div>
      {before ? (
        <ul className={c.cands} role="radiogroup" aria-label={`${d.vendor_name} 실측 희망 기간 후보`}>
          {d.wishes.map((w) => {
            const on = d.chosen === w.ref;
            const range = rangeText(w.start, w.end, { weekday: true });
            return (
              <li key={w.ref}>
                <button type="button" role="radio" aria-checked={on} className={c.cand} disabled={ctx.busy && !on}
                  onClick={() => { if (!on) ctx.send(`${range}로 할래요`, { card_id: card.card_id, choice: w.ref }); }}>
                  <span className={c.radio} aria-hidden="true" />
                  <b className={k.num}>{range}</b>
                  <small className={k.num}>업체 빈 반나절 {w.open_count}칸</small>
                </button>
              </li>
            );
          })}
        </ul>
      ) : d.candidates.length ? (
        <ul className={c.cands} role="radiogroup" aria-label={`${d.vendor_name} 실측 시간 후보`}>
          {d.candidates.map((s) => {
            const on = d.chosen === s.ref;
            const why = whyText(s.why);
            return (
              <li key={s.ref}>
                <button type="button" role="radio" aria-checked={on} className={c.cand} disabled={ctx.busy && !on}
                  onClick={() => { if (!on) ctx.send(`${halfDayText(s.day, s.half)}로 할래요`, { card_id: card.card_id, choice: s.ref }); }}>
                  <span className={c.radio} aria-hidden="true" />
                  <b className={k.num}>{halfDayText(s.day, s.half, true)}</b>
                  {why.length ? <small>{why.join(" · ")}</small> : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className={k.muted}>지금 고를 수 있는 시간이 없어요</p>
      )}
      {!before ? <p className={k.decided}><I n="info" />{d.instant ? "고르면 바로 확정돼요" : "고르면 업체가 수락할 때 확정돼요"}</p> : null}
      <div className={k.row}>
        <Link className={`${k.btn} ${k.sm}`} href={d.calendar_href} scroll={false}><I n="calendar" />달력에서 고르기</Link>
      </div>
    </section>
  );
}
