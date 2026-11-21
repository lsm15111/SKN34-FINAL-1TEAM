"use client";
// 업체 작업함 맨 위 '오늘 브리핑': 새 요청 · 오늘 실측 · 보낼 견적서 · 공사 날짜 낼 공사(줄은 코드가 골라요). 목록이 먼저라 카드 하나로 짧게 둬요.
// 공사 날짜 줄 [공사 날짜 보내기]는 비서에게 고르기(choice 'dates:d#,n#', 이름표는 서버가 대화 표에 넣어 둠)를 보내 승인 카드를 받아요.
// 승인 카드는 아래 '비서 소식'에 붙고, 날짜는 그 카드를 승인할 때 보내져요.
import { useCallback, useEffect, useState } from "react";
import { getVendorToday, newClientKey, streamVendorTurn, VENDOR_ASSISTANT_EVENT, type TodayIcon, type TodayRow, type VendorTodayData } from "@/lib/api/assistant";
import { errorText } from "@/lib/backend/client";
import { dateLong } from "@/lib/format";
import { I, type IconName } from "@/components/assistant/kit/icons";
import k from "@/components/assistant/kit/kit.module.css";
import p from "./pro.module.css";

const ICON: Record<TodayIcon, IconName> = { doc: "doc", calendar: "calendar", file: "file", chat: "chat", bulb: "bulb", inbox: "inbox" };

export function VendorToday() {
  const [d, setD] = useState<VendorTodayData | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const reload = useCallback(() => getVendorToday().then(setD).catch(() => undefined), []);
  useEffect(() => {
    let alive = true;
    getVendorToday().then((x) => { if (alive) setD(x); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  if (!d || !d.rows.length) return null;

  async function pick(r: TodayRow) {
    const choice = r.action?.choice;
    if (!choice || busy) return;
    setBusy(r.id);
    setErr(null);
    try {
      const body = { client_key: newClientKey(), text: r.action?.say ?? r.action?.label ?? r.title, context: { card_id: "today", choice } };
      await streamVendorTurn(body, (e) => { if (e.type === "error") setErr(e.data.message); });
      window.dispatchEvent(new Event(VENDOR_ASSISTANT_EVENT));
      await reload();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className={`${k.card} ${k.today}`} aria-labelledby="vtoday-t">
      <div className={k.todayHead}>
        <span className={k.muted}>{dateLong(d.date)}</span>
        <h3 id="vtoday-t">오늘 할 일 <span className={k.cnt}>{d.rows.length}</span></h3>
      </div>
      <ul className={`${k.tlist} ${p.row3}`}>
        {d.rows.map((r) => (
          <li key={r.id}>
            <span className={r.icon === "calendar" && r.id !== "dates" ? `${k.tic} ${k.ticWait}` : k.tic}><I n={ICON[r.icon]} /></span>
            <div><b>{r.title}</b>{r.sub ? <span className={r.due ? `${k.dueText} ${k.num}` : k.num}>{r.sub}</span> : null}</div>
            {r.action?.choice ? (
              <button type="button" className={r.action.primary ? `${k.btn} ${k.sm} ${k.pri}` : `${k.btn} ${k.sm}`} disabled={busy !== null} aria-busy={busy === r.id} onClick={() => { void pick(r); }}>
                {busy === r.id ? "만드는 중" : r.action.label}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {err ? <p className={k.err} role="alert">{err}</p> : null}
    </section>
  );
}
