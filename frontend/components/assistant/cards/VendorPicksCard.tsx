"use client";
// C3 추천 업체 3곳: 시공 사진 · 이름 · 별점 · 끝낸 공사 · 가견적(부가세 포함) · 이유 2줄(점수 항목 템플릿) · 고르기 ✓ · [자세히].
// 추천은 코드 점수예요(에이전트 아님). 고른 업체가 바뀌면 [n곳으로 다시 만들기]로 실측 요청 승인 카드를 새로 받아요(옛 카드는 접혀요).
// 표준견적서와 견준 %는 보이지 않아요(리드 결정 2026-11-21).
import Link from "next/link";
import { useMemo, useState } from "react";
import { won } from "@/lib/format";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function VendorPicksCard({ card, ctx }: CardProps<"vendor_picks">) {
  const d = card.data;
  const server = useMemo(() => d.picks.filter((p) => p.picked).map((p) => p.ref), [d.picks]);
  const [sel, setSel] = useState<string[] | null>(null);
  const [basis, setBasis] = useState(false);
  const now = sel ?? server;
  const changed = sel !== null && (sel.length !== server.length || sel.some((x) => !server.includes(x)));
  const toggle = (ref: string) => setSel((cur) => { const base = cur ?? server; return base.includes(ref) ? base.filter((x) => x !== ref) : [...base, ref]; });
  const names = d.picks.filter((p) => now.includes(p.ref)).map((p) => p.name);

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
            <li key={p.ref} className={c.vc} data-on={on}>
              <div className={c.ph}>
                {p.photo ? <img src={p.photo} alt={p.photo_alt} loading="lazy" /> : null}
                {p.badge ? <span className={c.phBadge}>{p.badge}</span> : null}
                <button type="button" className={c.pick} aria-pressed={on} aria-label={`${p.name} 고르기`} onClick={() => toggle(p.ref)}><span><I n="check" /></span></button>
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
      {changed ? (
        <div className={c.redo} role="status">
          <span>{names.length ? `${names.join(" · ")}에 보낼게요` : "업체를 한 곳 이상 골라 주세요"}</span>
          <button type="button" className={`${k.btn} ${k.sm} ${k.pri}`} disabled={!names.length || ctx.busy} onClick={() => { ctx.send(`${names.join(" · ")}에 요청할래요`, { card_id: card.card_id, choice: now }); setSel(null); }}>
            {names.length}곳으로 다시 만들기
          </button>
        </div>
      ) : null}
      <div className={k.row}>
        <Link className={`${k.btn} ${k.sm}`} href={d.more_href} scroll={false}>다른 업체 보기</Link>
      </div>
    </section>
  );
}
