"use client";
// C7 알아 두기 · 답 · 평면도 받는 곳. 숫자를 만들지 않는 작은 카드들이에요.
// - 알아 두기: 제목 · 3줄 · 출처 · (공사 전날) 준비물 체크. 체크는 서버에 저장하지 않고 이 기기에만 둬요(서버가 주는 항목 key는
//   공사 할 일 key가 아니라 PUT /projects/{id}/checks/{key}로 저장할 수 없어요). 새로고침 · 다시 읽기에도 풀리지 않아요.
// - 답: 믿집 안내(정해 둔 글) 또는 AI 답변(굵게 · 줄바꿈 · 목록만 화면 꼴로). 링크는 사이트 안 경로만(insideHref).
// - 평면도: 그림은 믿집이 찾아 넣지 않고 받는 곳 링크만(조사 04).
// 긴 링크 제목 · 출처 · 발췌는 카드 안에서 줄을 바꿔요(폰 360 · 375에서 대화 칸이 가로로 밀리지 않게).
import Link from "next/link";
import { useEffect, useState } from "react";
import { insideHref } from "@/lib/api/assistant";
import { RichText } from "../kit/RichText";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

/** 체크를 둘 이 기기 자리(공사 · 카드마다). 끝난 줄의 카드 id 꼬리('@줄 id')는 떼요 */
const checkKey = (projectId: string, cardId: string) => `mj_v4_checks:${projectId}:${cardId.split("@")[0]}`;
function readChecks(key: string): Record<string, boolean> {
  try {
    const v: unknown = JSON.parse(window.localStorage.getItem(key) ?? "null");
    return v && typeof v === "object" ? Object.fromEntries(Object.entries(v).filter(([, x]) => typeof x === "boolean")) : {};
  } catch {
    return {};
  }
}

export function KnowledgeCard({ card, ctx, old }: CardProps<"knowledge">) {
  const d = card.data;
  const key = checkKey(ctx.projectId, card.card_id);
  const [done, setDone] = useState<Record<string, boolean>>(() => Object.fromEntries((d.checklist ?? []).map((x) => [x.key, x.done])));
  // 이 기기에 둔 체크를 덮어 보여요
  useEffect(() => {
    const saved = readChecks(key);
    if (Object.keys(saved).length) setDone((v) => ({ ...v, ...saved }));
  }, [key]);
  const check = (item: string, on: boolean) => {
    const next = { ...done, [item]: on };
    setDone(next);
    try { window.localStorage.setItem(key, JSON.stringify(next)); } catch { /* 저장소를 못 쓰면 이 화면에서만 */ }
  };
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={c.know}>
        <span className={c.knowIc}><I n="bulb" /></span>
        <div>
          <h3 id={`${card.card_id}-t`}>{d.title}</h3>
          <ul>{d.lines.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      </div>
      {/* 할 일이 끝난 줄의 카드(old)는 체크 항목을 글로만 남겨요(체크 칸 없음). 목록 이름은 카드 제목(준비물 · 점검표 · 공사 전 할 일) */}
      {d.checklist?.length ? (old ? (
        <ul className={c.basisList} aria-label={d.title}>{d.checklist.map((x) => <li key={x.key}>{x.label}</li>)}</ul>
      ) : (
        <ul className={c.checks} aria-label={d.title}>
          {d.checklist.map((x) => (
            <li key={x.key}><label><input type="checkbox" checked={!!done[x.key]} onChange={(e) => check(x.key, e.target.checked)} />{x.label}</label></li>
          ))}
        </ul>
      )) : null}
      <div className={c.knowFoot}>
        <span className={c.srcText}>{d.source}</span>
        {d.href ? <Link className={k.text} href={d.href} scroll={false}>더 보기<I n="chev" /></Link> : null}
      </div>
    </section>
  );
}

export function AnswerCard({ card }: CardProps<"answer">) {
  const d = card.data;
  return (
    <section className={`${k.card} ${c.answer}`} aria-label="답">
      <div className={k.top}><SourceTag src={d.src} /></div>
      <RichText text={d.text} />
      {d.links?.length ? (
        <div className={c.links}>
          {d.links.filter((l) => insideHref(l.href)).map((l) => (
            l.href.startsWith("/api/")
              ? <a key={l.href} className={c.lnk} href={l.href} download><span>{l.label}</span><I n="chev" /></a>
              : <Link key={l.href} className={c.lnk} href={l.href} scroll={false}><span>{l.label}</span><I n="chev" /></Link>
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
      <ul className={c.flist}>
        {d.links.filter((l) => l.href.startsWith("https://")).map((l) => (
          <li key={l.href}>
            <a className={c.lnk} href={l.href} target="_blank" rel="noopener noreferrer"><span>{l.label}</span><I n="external" /><span className="mj-sr">(새 창)</span></a>
            <small>{l.source}</small>
          </li>
        ))}
      </ul>
      <p className={k.muted}>{d.note}</p>
    </section>
  );
}
