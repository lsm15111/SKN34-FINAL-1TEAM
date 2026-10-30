"use client";
// 가견적 요청 확인 · 보내기. 업체가 보낸 가견적은 자동으로 등록된다.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { TRADES, TRADE_LABEL } from "@/lib/types";
import { readBasket, writeBasket, emptyBasket, type Basket } from "./basket";

export function RequestConfirm({ projectId, vendors, conditions }: { projectId: string; vendors: { id: string; name: string; response: string }[]; conditions: { k: string; v: string }[] }) {
  const [basket, setBasket] = useState<Basket>(emptyBasket());
  const [sent, setSent] = useState(false);
  const [ready, setReady] = useState(false);
  const doneRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { setBasket(readBasket(projectId)); setReady(true); }, [projectId]);
  useEffect(() => { if (sent) doneRef.current?.focus(); }, [sent]);
  const name = (id: string) => vendors.find((v) => v.id === id)?.name ?? id;
  const total = basket.dobae.length + basket.mokgong.length;

  if (sent) {
    return (
      <section className="mj-panel" aria-labelledby="done-h" style={{ maxWidth: 720 }}>
        <h1 id="done-h" ref={doneRef} tabIndex={-1} className="mj-h1">가견적을 요청했어요</h1>
        <p className="mj-sub">업체가 가견적서를 보내면 프로젝트에 자동으로 등록되고 알림을 드려요. 보통 1~2일 걸려요.</p>
        <div className="mj-btn-row"><Link href={`/projects/${projectId}/quotes`} className="mj-btn mj-btn-pri">가견적 비교로 가기</Link><Link href={`/projects/${projectId}`} className="mj-btn mj-btn-sec">진행 현황</Link></div>
      </section>
    );
  }

  return (
    <div className="mj-split">
      <div className="mj-col">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h1 className="mj-h1">이대로 가견적을 요청할까요?</h1>
          <p className="mj-sub">담은 업체 모두에 같은 조건을 보내요. 업체가 보낸 가견적서는 자동으로 등록돼요.</p>
        </div>
        <section className="mj-panel" aria-labelledby="cond-h">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><h2 id="cond-h" className="mj-h3">보내는 조건</h2><Link href="/start">고치기</Link></div>
          <dl className="mj-kv">{conditions.map((c) => <div key={c.k} style={{ display: "contents" }}><dt>{c.k}</dt><dd>{c.v}</dd></div>)}</dl>
          <p className="mj-small">이름 · 연락처 · 동 · 호수는 보내지 않아요. 실측을 요청할 때만 그 업체에 보여요.</p>
        </section>
      </div>
      <aside className="mj-aside mj-panel" aria-labelledby="to-h">
        <h2 id="to-h" className="mj-h3">받는 업체 {ready ? `${total}곳` : ""}</h2>
        {TRADES.map((t) => (
          <div key={t} style={{ display: "flex", flexDirection: "column", gap: 4, paddingBottom: 10, borderBottom: "1px solid var(--line)" }}>
            <b>{TRADE_LABEL[t]}</b>
            {basket[t].length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{basket[t].map((id) => <li key={id}>{name(id)} <span className="mj-tiny">· 응답 {vendors.find((v) => v.id === id)?.response}</span></li>)}</ul> : <span className="mj-small">담은 업체가 없어요</span>}
          </div>
        ))}
        <Link href={`/projects/${projectId}/vendors`} className="mj-btn mj-btn-ghost mj-btn-sm">업체 더 고르기</Link>
        <button type="button" className="mj-btn mj-btn-pri" disabled={!total} aria-disabled={!total} onClick={() => { writeBasket(projectId, emptyBasket()); setSent(true); }}>
          {total ? `${total}곳에 가견적 요청 보내기` : "업체를 먼저 담아 주세요"}
        </button>
      </aside>
    </div>
  );
}
