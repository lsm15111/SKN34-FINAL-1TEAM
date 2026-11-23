"use client";
// 오늘 정할 일(C8): 날짜 · '오늘 정할 일 n' · 줄(아이콘 · 할 일 · 기한 · 단추) · 묶음(정할 일 · 기다리는 일 · 알아 두기).
// 새 알림(서버 news, 이틀 안 안 읽은 알림)은 종 알림과 겹쳐서 이 카드에 두지 않아요(2026-11-23 사용자).
// 줄은 모두 코드 사실이에요(비서 말 한 문장은 카드 위 말로 따로). [오늘은 그만]은 먼저 말 건 카드를 닫아요(같은 일 3일 쉬기).
// 할 일이 끝난 줄의 카드(old)는 보낸 때 줄만 남겨요(줄 단추 · [오늘은 그만] 없음).
import Link from "next/link";
import type { TodayData, TodayIcon, TodayRow } from "@/lib/api/assistant";
import { dateLong } from "@/lib/format";
import type { CardProps } from "../cards/types";
import { I, type IconName } from "./icons";
import k from "./kit.module.css";

const ICON: Record<TodayIcon, IconName> = { doc: "doc", calendar: "calendar", file: "file", chat: "chat", bulb: "bulb", inbox: "inbox" };

export function TodayCard({ card, ctx, old }: CardProps<"today">) {
  const d: TodayData = card.data;
  const n = d.todo.length;
  if (d.dismissed) {
    return (
      <section className={k.fold} aria-label="오늘 정할 일 · 닫음">
        <span className={k.result}><b>오늘 정할 일 {n}</b><span>오늘은 더 알리지 않아요</span></span>
      </section>
    );
  }
  // 끝난 줄의 카드에는 data-today를 두지 않아요(단계 띠 '오늘 정할 일 n ›'이 살아 있는 카드로 가요)
  return (
    <section className={`${k.card} ${k.today}`} aria-labelledby={`${card.card_id}-t`} data-today={old ? undefined : ""}>
      <div className={k.todayHead}>
        <span className={k.muted}>{dateLong(d.date)}</span>
        <h3 id={`${card.card_id}-t`}>{n ? <>오늘 정할 일 <span className={k.cnt}>{n}</span></> : "오늘은 정할 일이 없어요"}</h3>
      </div>
      <Group title="정할 일" rows={d.todo} ctx={ctx} old={old} />
      <Group title="기다리는 일" rows={d.waiting} ctx={ctx} old={old} wait />
      <Group title="알아 두기" rows={d.know ?? []} ctx={ctx} old={old} know />
      {d.nudge_id && !old ? (
        <div className={k.todayFoot}>
          <button type="button" className={`${k.text} ${k.gray}`} onClick={() => ctx.dismissNudge(card.card_id, d.nudge_id!)}>오늘은 그만</button>
        </div>
      ) : null}
    </section>
  );
}

function Group({ title, rows, ctx, old, wait, know }: { title: string; rows: TodayRow[]; ctx: CardProps<"today">["ctx"]; old: boolean; wait?: boolean; know?: boolean }) {
  if (!rows.length) return null;
  const tic = know ? `${k.tic} ${k.ticKnow}` : wait ? `${k.tic} ${k.ticWait}` : k.tic;
  return (
    <div className={k.tsec}>
      <span className={k.tsecT}>{title}</span>
      <ul className={k.tlist}>
        {rows.map((r) => (
          <li key={r.id}>
            <span className={tic}><I n={ICON[r.icon]} /></span>
            <div>
              <b>{r.title}</b>
              {r.sub ? <span className={r.due ? `${k.dueText} ${k.num}` : k.num}>{r.sub}</span> : null}
            </div>
            {r.action && !old ? <RowAction a={r.action} ctx={ctx} /> : null}
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
