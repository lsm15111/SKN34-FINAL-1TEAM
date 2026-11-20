"use client";
// 오늘 정할 일(C8): 날짜 · '오늘 정할 일 n' · 줄(아이콘 · 할 일 · 기한 · 단추) · 묶음(정할 일 · 기다리는 일 · 밤사이 소식 · 알아 두기).
// 줄은 모두 코드 사실이에요(비서 말 한 문장은 카드 위 말로 따로). [오늘은 그만]은 먼저 말 건 카드를 닫아요(같은 일 3일 쉬기).
import Link from "next/link";
import type { TodayData, TodayIcon, TodayRow } from "@/lib/api/assistant";
import { dateLong } from "@/lib/format";
import type { CardProps } from "../cards/types";
import { I, type IconName } from "./icons";
import k from "./kit.module.css";

const ICON: Record<TodayIcon, IconName> = { doc: "doc", calendar: "calendar", file: "file", chat: "chat", bulb: "bulb", inbox: "inbox" };

export function TodayCard({ card, ctx }: CardProps<"today">) {
  const d: TodayData = card.data;
  const n = d.todo.length;
  if (d.dismissed) {
    return (
      <section className={k.fold} aria-label="오늘 정할 일 · 닫음">
        <span className={k.result}><b>오늘 정할 일 {n}</b><span>오늘은 더 알리지 않아요</span></span>
      </section>
    );
  }
  return (
    <section className={`${k.card} ${k.today}`} aria-labelledby={`${card.card_id}-t`} data-today="">
      <div className={k.todayHead}>
        <span className={k.muted}>{dateLong(d.date)}</span>
        <h3 id={`${card.card_id}-t`}>{n ? <>오늘 정할 일 <span className={k.cnt}>{n}</span></> : "오늘은 정할 일이 없어요"}</h3>
      </div>
      <Group title="정할 일" rows={d.todo} ctx={ctx} />
      <Group title="기다리는 일" rows={d.waiting} ctx={ctx} wait />
      <Group title="밤사이 소식" rows={d.news} ctx={ctx} news />
      <Group title="알아 두기" rows={d.know} ctx={ctx} know />
      {d.nudge_id ? (
        <div className={k.todayFoot}>
          <button type="button" className={`${k.text} ${k.gray}`} onClick={() => ctx.dismissNudge(card.card_id, d.nudge_id!)}>오늘은 그만</button>
        </div>
      ) : null}
    </section>
  );
}

function Group({ title, rows, ctx, wait, news, know }: { title: string; rows: TodayRow[]; ctx: CardProps<"today">["ctx"]; wait?: boolean; news?: boolean; know?: boolean }) {
  if (!rows.length) return null;
  const tic = know ? `${k.tic} ${k.ticKnow}` : news ? `${k.tic} ${k.ticNews}` : wait ? `${k.tic} ${k.ticWait}` : k.tic;
  return (
    <div className={k.tsec}>
      <span className={k.tsecT}>{title}</span>
      <ul className={news ? `${k.tlist} ${k.tlistNews}` : k.tlist}>
        {rows.map((r) => (
          <li key={r.id}>
            <span className={tic}><I n={ICON[r.icon]} /></span>
            <div>
              <b>{r.title}</b>
              {r.sub ? <span className={r.due ? `${k.dueText} ${k.num}` : k.num}>{r.sub}</span> : null}
            </div>
            {r.action ? <RowAction a={r.action} ctx={ctx} /> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function RowAction({ a, ctx }: { a: NonNullable<TodayRow["action"]>; ctx: CardProps<"today">["ctx"] }) {
  const cls = a.primary ? `${k.btn} ${k.sm} ${k.pri}` : a.href || a.say ? `${k.btn} ${k.sm}` : k.text;
  if (a.href) return <Link className={cls} href={a.href} scroll={false}>{a.label}</Link>;
  return <button type="button" className={cls} disabled={ctx.busy} onClick={() => a.say && ctx.send(a.say)}>{a.label}</button>;
}
