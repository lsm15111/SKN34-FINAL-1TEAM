// C4 실측 시간 후보. 두 모양이에요(계산 엔진 calc.slots 값 그대로):
// - 요청 전(window 없음): 희망 기간 후보 1~2개(업체 빈 반나절 수) → 고르면 실측 요청 승인 카드가 그 기간으로 바뀌어요
//   (choice visit_request:<업체 추천 카드에서 고른 업체>,r…).
// - 요청 뒤: 업체가 답한 기간 안의 반나절 2~3개 + 근거 → 고르면 승인 카드가 그 시간으로 바뀌어요(choice visit_slot:s…).
// 근거는 코드라 화면 말로 바꿔요(whyText). 시각은 실측 전날 채팅으로 정해요(반나절만 보여요).
// 업체가 다른 날을 내며 적은 메모는 '업체가 적은 말' 칸에만 보여요(업체 글 그대로, 다른 글에 섞지 않아요).
import Link from "next/link";
import { CHOICE, whyText } from "@/lib/api/assistant";
import { euro, halfDayText, rangeText } from "@/lib/format";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import { chosenVendors, isWish } from "./picks";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function VisitSlotsCard({ card, ctx, old }: CardProps<"visit_slots">) {
  const d = card.data;
  const before = isWish(d);
  // 고른 것: 화면에서 고른 것(이 카드 안 이름표일 때) → 서버가 고른 것
  const refs = before ? d.wishes.map((w) => w.ref) : d.candidates.map((s) => s.ref);
  const mine = ctx.marks[card.card_id]?.[0];
  const chosen = mine && refs.includes(mine) ? mine : d.chosen;
  const pick = (ref: string, text: string, choice: string) => {
    if (d.chosen === ref) return;
    ctx.mark(card.card_id, [ref]);
    ctx.send(text, { card_id: card.card_id, choice });
  };
  const title = before ? "희망 기간 어때요?" : "이 시간 어때요?";
  const sub = `${d.vendor_name}${d.window ? ` · ${rangeText(d.window.start, d.window.end)}` : ""}`;
  if (old) {
    // 할 일이 끝난 줄의 카드: 보낸 때 후보만 글로 남겨요(고르기 · 달력 단추 없음)
    const rows = before
      ? d.wishes.map((w) => ({ ref: w.ref, main: rangeText(w.start, w.end, { weekday: true }), sub: `업체 빈 반나절 ${w.open_count}칸` }))
      : d.candidates.map((s) => ({ ref: s.ref, main: halfDayText(s.day, s.half, true), sub: whyText(s.why).join(" · ") }));
    return (
      <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
        <div className={k.top}>
          <h3 id={`${card.card_id}-t`}>{title}</h3>
          <span className={`${k.muted} ${k.num}`}>{sub}</span>
        </div>
        {rows.length ? (
          <ul className={c.cands} aria-label={`${d.vendor_name} ${before ? "실측 희망 기간 후보" : "실측 시간 후보"}`}>
            {rows.map((r) => <li key={r.ref} className={c.candOld}><b className={k.num}>{r.main}</b>{r.sub ? <small className={k.num}>{r.sub}</small> : null}</li>)}
          </ul>
        ) : null}
        {d.vendor_note ? <blockquote className={c.vnote}><b>업체가 적은 말</b>{d.vendor_note}</blockquote> : null}
      </section>
    );
  }
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{title}</h3>
        <span className={`${k.muted} ${k.num}`}>{sub}</span>
      </div>
      {before ? (
        <ul className={c.cands} role="radiogroup" aria-label={`${d.vendor_name} 실측 희망 기간 후보`}>
          {d.wishes.map((w) => {
            const on = chosen === w.ref;
            const range = rangeText(w.start, w.end, { weekday: true });
            return (
              <li key={w.ref}>
                <button type="button" role="radio" aria-checked={on} className={c.cand} disabled={ctx.busy && !on}
                  onClick={() => pick(w.ref, `${euro(range)} 할래요`, CHOICE.visitRequest(chosenVendors(ctx), w.ref))}>
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
            const on = chosen === s.ref;
            const why = whyText(s.why);
            return (
              <li key={s.ref}>
                <button type="button" role="radio" aria-checked={on} className={c.cand} disabled={ctx.busy && !on}
                  onClick={() => pick(s.ref, `${euro(halfDayText(s.day, s.half))} 할래요`, CHOICE.visitSlot(s.ref))}>
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
      {d.vendor_note ? <blockquote className={c.vnote}><b>업체가 적은 말</b>{d.vendor_note}</blockquote> : null}
      {!before ? <p className={k.decided}><I n="info" />{d.instant ? "고르면 바로 확정돼요" : "고르면 업체가 수락할 때 확정돼요"}</p> : null}
      <div className={k.row}>
        <Link className={`${k.btn} ${k.sm}`} href={d.calendar_href} scroll={false}><I n="calendar" />달력에서 고르기</Link>
      </div>
    </section>
  );
}
