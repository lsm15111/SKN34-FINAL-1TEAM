"use client";
// 승인 업체의 받은 가견적 요청. 고객 이름 · 연락처 · 동 · 호수는 API가 주지 않는다.
// '확인했어요'는 업체가 누른 요청으로만 바뀐다 (이미 바뀌었으면 409 → 확인한 것으로 보인다).
import { useState } from "react";
import { ApiError, call, errorText, type Schemas } from "@/lib/backend/client";
import { dateSeoul, md } from "@/lib/format";
import s from "./VendorInbox.module.css";

type Item = Schemas["InboxItemOut"];

export function VendorInbox({ items }: { items: Item[] }) {
  const [list, setList] = useState(items);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<Record<string, string>>({});

  async function view(id: string) {
    setBusy(id);
    setErr((old) => ({ ...old, [id]: "" }));
    try {
      const got = await call<Item>("POST", `/vendor/quote-requests/${id}/viewed`);
      setList((old) => old.map((x) => (x.id === id ? got : x)));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setList((old) => old.map((x) => (x.id === id ? { ...x, status: "viewed" as const } : x)));
      else setErr((old) => ({ ...old, [id]: errorText(e) }));
    } finally {
      setBusy(null);
    }
  }

  if (!list.length) return <p className="mj-small">아직 받은 가견적 요청이 없어요. 고객이 요청하면 여기에 보여요.</p>;
  return (
    <ul className={s.list}>
      {list.map((r) => (
        <li key={r.id} className={s.item}>
          <div className={s.head}>
            <span className="mj-badge mj-b-in">{r.trade_label}</span>
            <b>{r.region}</b>
            <span className="mj-tiny mj-num">{md(dateSeoul(r.created_at))} 받음</span>
            <span className={`mj-badge ${r.status === "viewed" ? "mj-b-ok" : "mj-b-wait"}`}>{r.status === "viewed" ? "확인했어요" : "새 요청이에요"}</span>
          </div>
          <ul className={s.facts} aria-label="집 정보">
            {r.facts.map((f) => <li key={f}>{f}</li>)}
          </ul>
          {r.message ? <p className={s.msg}><span className="mj-src">고객이 남긴 말</span>{r.message}</p> : null}
          {r.status === "requested" ? (
            <div className="mj-btn-row">
              <button type="button" className="mj-btn mj-btn-pri mj-btn-sm" disabled={busy === r.id} onClick={() => view(r.id)}>확인했다고 알리기<span className="mj-sr"> · {r.trade_label} {r.region}</span></button>
            </div>
          ) : null}
          {err[r.id] ? <p className="mj-error" role="alert">{err[r.id]}</p> : null}
        </li>
      ))}
    </ul>
  );
}
