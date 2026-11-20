"use client";
// C7 알아 두기 · 답 · 평면도 받는 곳. 숫자를 만들지 않는 작은 카드들이에요.
// - 알아 두기: 제목 · 3줄 · 출처 · (공사 전날) 준비물 체크. 체크는 이 공사 할 일(PUT /projects/{id}/checks/{key})로 저장해요(목업은 화면 안에서만).
// - 답: 믿집 안내(정해 둔 글) 또는 AI 답변. 링크는 사이트 안 경로만.
// - 평면도: 그림은 믿집이 찾아 넣지 않고 받는 곳 링크만(조사 04).
import Link from "next/link";
import { useState } from "react";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function KnowledgeCard({ card }: CardProps<"knowledge">) {
  const d = card.data;
  const [done, setDone] = useState<Record<string, boolean>>(() => Object.fromEntries((d.checklist ?? []).map((x) => [x.key, x.done])));
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={c.know}>
        <span className={c.knowIc}><I n="bulb" /></span>
        <div>
          <h3 id={`${card.card_id}-t`}>{d.title}</h3>
          <ul>{d.lines.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      </div>
      {d.checklist?.length ? (
        <ul className={c.checks} aria-label="준비물">
          {d.checklist.map((x) => (
            <li key={x.key}><label><input type="checkbox" checked={!!done[x.key]} onChange={(e) => setDone((v) => ({ ...v, [x.key]: e.target.checked }))} />{x.label}</label></li>
          ))}
        </ul>
      ) : null}
      <div className={k.top}>
        <span className={k.basis}>{d.source}</span>
        {d.href ? <Link className={k.text} href={d.href} scroll={false}>더 보기<I n="chev" /></Link> : null}
      </div>
    </section>
  );
}

const inside = (h: string) => h.startsWith("/") && !h.startsWith("//");

export function AnswerCard({ card }: CardProps<"answer">) {
  const d = card.data;
  return (
    <section className={`${k.card} ${c.answer}`} aria-label="답">
      <div className={k.top}><SourceTag src={d.src} /></div>
      <p>{d.text}</p>
      {d.links?.length ? (
        <div className={c.links}>
          {d.links.filter((l) => inside(l.href)).map((l) => (
            l.href.startsWith("/api/") ? <a key={l.href} className={k.text} href={l.href} download>{l.label}<I n="chev" /></a> : <Link key={l.href} className={k.text} href={l.href} scroll={false}>{l.label}<I n="chev" /></Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function FloorplanLinksCard({ card }: CardProps<"floorplan_links">) {
  const d = card.data;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>평면도 받는 곳</h3>
        <SourceTag src="guide" />
      </div>
      <ul className={c.lines}>
        {d.links.filter((l) => l.href.startsWith("https://")).map((l) => (
          <li key={l.href}>
            <a className={k.text} href={l.href} target="_blank" rel="noopener noreferrer">{l.label}<I n="external" /><span className="mj-sr">(새 창)</span></a>
            <span>{l.source}</span>
          </li>
        ))}
      </ul>
      <p className={k.muted}>{d.note}</p>
    </section>
  );
}
