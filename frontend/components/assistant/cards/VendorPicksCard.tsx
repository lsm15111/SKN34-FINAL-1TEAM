"use client";
// C3 추천 업체 3곳: 시공 사진 · 이름 · 별점 · 끝낸 공사 · 가견적(부가세 포함) · 이유 2줄(점수 항목 템플릿) · 고르기 ✓ · [자세히].
// 추천은 코드 점수예요(에이전트 아님). 고른 업체로 [n곳에 실측 요청하기] → 실측 요청 승인 카드를 받아요(choice visit_request:v…, 무료 모드도).
// 승인 카드가 열려 있으면 고른 업체가 바뀔 때만 [n곳으로 다시 만들기](옛 카드는 접혀요). 희망 기간 카드에서 고른 기간도 같이 보내요.
// 표준견적서와 견준 %는 보이지 않아요(리드 결정 2026-11-21).
import Link from "next/link";
import { useState } from "react";
import { CHOICE } from "@/lib/api/assistant";
import { won } from "@/lib/format";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import { chosenWish, pickedVendors, requestState, vendorsOf } from "./picks";
import type { CardProps } from "./types";
import c from "./cards.module.css";

const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

export function VendorPicksCard({ card, ctx, old }: CardProps<"vendor_picks">) {
  const d = card.data;
  const [basis, setBasis] = useState(false);
  // 할 일이 끝난 줄의 카드(old)는 보낸 때 추천만 남겨요(고르기 · 요청 · 다른 업체 단추 없음)
  const now = old ? [] : pickedVendors(ctx, card);
  const touched = ctx.marks[card.card_id] !== undefined;
  const { live, sent } = requestState(ctx);
  // 보낸 뒤에는 단추를 두지 않아요. 열린 승인 카드가 있으면 고른 업체가 바뀔 때만, 없으면 고른 업체가 있으면 보여요
  const bar = !old && !sent && (live ? touched && !same(now, vendorsOf(card, live)) : now.length > 0 || touched);
  const toggle = (ref: string) => ctx.mark(card.card_id, now.includes(ref) ? now.filter((x) => x !== ref) : [...now, ref]);
  const names = d.picks.filter((p) => now.includes(p.ref)).map((p) => p.name);
  const request = () => {
    ctx.mark(card.card_id, now);
    ctx.send(`${names.join(" · ")}에 요청할래요`, { card_id: card.card_id, choice: CHOICE.visitRequest(now, chosenWish(ctx)) });
  };

  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>추천 업체 {d.picks.length}곳</h3>
        <button type="button" className={`${k.text} ${k.gray}`} aria-expanded={basis} onClick={() => setBasis((v) => !v)}>고른 기준<I n={basis ? "down" : "chev"} /></button>
      </div>
      {basis ? <ul className={c.basisList}>{d.basis.map((b) => <li key={b}>{b}</li>)}</ul> : null}
      <ul className={c.reco}>
        {d.picks.map((p) => {
          const on = now.includes(p.ref);
          return (
            <li key={p.ref} className={p.photo ? c.vc : `${c.vc} ${c.vcBare}`} data-on={on}>
              {/* 사진이 없으면 큰 회색 빈 칸 대신 이름 머리글자 작은 칸(배지 · 고르기 ✓는 같은 줄, QA r3 v1 L6) */}
              <div className={c.ph}>
                {p.photo ? <img src={p.photo} alt={p.photo_alt} loading="lazy" /> : <span className={c.ini} aria-hidden="true">{Array.from(p.name)[0]}</span>}
                {p.badge ? <span className={c.phBadge}>{p.badge}</span> : null}
                {old ? null : <button type="button" className={c.pick} aria-pressed={on} aria-label={`${p.name} 고르기`} onClick={() => toggle(p.ref)}><span><I n="check" /></span></button>}
              </div>
              <div className={c.vcIn}>
                <div className={c.vcName}>
                  <b>{p.name}</b>
                  {p.rating != null ? <span className={`${c.rate} ${k.num}`}><I n="star" />{p.rating.toFixed(1)} · 리뷰 {p.reviews}</span> : null}
                </div>
                <div className={c.vcAmt}><span>가견적 · 부가세 포함</span><b className={k.num}>{won(p.estimate_won)}</b></div>
                <ul className={c.why}>{p.reasons.map((w) => <li key={w}><I n="check" />{w}</li>)}</ul>
              </div>
              <div className={c.vcFoot}>
                <span className={k.num}>끝낸 공사 {p.done_jobs}</span>
                <Link className={k.text} href={p.href} scroll={false}>자세히<I n="chev" /></Link>
              </div>
            </li>
          );
        })}
      </ul>
      {bar ? (
        <div className={c.redo} role="status">
          <span>{names.length ? `${names.join(" · ")}에 보낼게요` : "업체를 한 곳 이상 골라 주세요"}</span>
          <button type="button" className={`${k.btn} ${k.sm} ${k.pri}`} disabled={!names.length || ctx.busy} onClick={request}>
            {live ? `${names.length}곳으로 다시 만들기` : `${names.length}곳에 실측 요청하기`}
          </button>
        </div>
      ) : null}
      {old ? null : (
        <div className={k.row}>
          <Link className={`${k.btn} ${k.sm}`} href={d.more_href} scroll={false}>다른 업체 보기</Link>
        </div>
      )}
    </section>
  );
}
