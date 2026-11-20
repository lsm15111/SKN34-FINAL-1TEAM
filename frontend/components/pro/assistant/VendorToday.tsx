"use client";
// 업체 작업함 맨 위 '오늘 브리핑': 새 요청 · 오늘 실측 · 보낼 견적서(줄은 코드가 골라요). 목록이 먼저라 카드 하나로 짧게 둬요.
import { useEffect, useState } from "react";
import { getVendorToday, type TodayIcon, type VendorTodayData } from "@/lib/api/assistant";
import { dateLong } from "@/lib/format";
import { I, type IconName } from "@/components/assistant/kit/icons";
import k from "@/components/assistant/kit/kit.module.css";
import p from "./pro.module.css";

const ICON: Record<TodayIcon, IconName> = { doc: "doc", calendar: "calendar", file: "file", chat: "chat", bulb: "bulb", inbox: "inbox" };

export function VendorToday() {
  const [d, setD] = useState<VendorTodayData | null>(null);
  useEffect(() => {
    let alive = true;
    getVendorToday().then((x) => { if (alive) setD(x); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  if (!d || !d.rows.length) return null;
  return (
    <section className={`${k.card} ${k.today}`} aria-labelledby="vtoday-t">
      <div className={k.todayHead}>
        <span className={k.muted}>{dateLong(d.date)}</span>
        <h3 id="vtoday-t">오늘 할 일 <span className={k.cnt}>{d.rows.length}</span></h3>
      </div>
      <ul className={`${k.tlist} ${p.row3}`}>
        {d.rows.map((r) => (
          <li key={r.id}>
            <span className={r.icon === "calendar" ? `${k.tic} ${k.ticWait}` : k.tic}><I n={ICON[r.icon]} /></span>
            <div><b>{r.title}</b>{r.sub ? <span className={r.due ? `${k.dueText} ${k.num}` : k.num}>{r.sub}</span> : null}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
