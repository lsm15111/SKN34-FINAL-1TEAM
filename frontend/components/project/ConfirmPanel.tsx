"use client";
// 업체 최종 확정 · 다시 고르기. 확정은 사람이 누를 때만 일어난다.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { euro, md } from "@/lib/format";

export function ConfirmPanel({ projectId, trade, tradeLabel, vendorName, confirmedOn }: { projectId: string; trade: string; tradeLabel: string; vendorName: string; confirmedOn: string | null }) {
  const [confirmed, setConfirmed] = useState(!!confirmedOn);
  const [asking, setAsking] = useState(false);
  const [demo, setDemo] = useState(false);
  const askRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (asking) askRef.current?.focus(); }, [asking]);
  const showConfirmed = confirmed && !demo;

  return (
    <section className="mj-panel" aria-labelledby="cf-h" style={{ borderColor: "var(--accent)", borderWidth: 2 }}>
      <h2 id="cf-h" className="mj-h3">{tradeLabel} 업체 확정</h2>
      {showConfirmed ? (
        <>
          <p role="status"><b>{euro(vendorName)}</b> 확정했어요{confirmedOn ? ` (${md(confirmedOn)})` : ""}.</p>
          <p className="mj-small">확정 업체가 공사기간을 등록하면 확정 공정표에 들어가요.</p>
          <Link href={`/projects/${projectId}/schedule`} className="mj-btn mj-btn-pri">확정 공정표 보기</Link>
        </>
      ) : asking ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <h3 ref={askRef} tabIndex={-1} className="mj-h3">{euro(vendorName)} 확정할까요?</h3>
          <p className="mj-small">확정하면 {tradeLabel} 공정은 이 업체가 진행해요. 계약은 업체와 직접 해요.</p>
          <div className="mj-btn-row">
            <button type="button" className="mj-btn mj-btn-pri" onClick={() => { setConfirmed(true); setAsking(false); setDemo(false); }}>네, 확정할게요</button>
            <button type="button" className="mj-btn mj-btn-sec" onClick={() => setAsking(false)}>아니요</button>
          </div>
        </div>
      ) : (
        <>
          <p className="mj-small">실측 견적이 마음에 들면 이 업체로 확정하고, 아니면 다른 업체를 다시 골라 가견적과 실측을 요청해요.</p>
          <button type="button" className="mj-btn mj-btn-pri" onClick={() => setAsking(true)}>이 업체로 확정</button>
          <Link href={`/projects/${projectId}/vendors?trade=${trade}`} className="mj-btn mj-btn-sec">다른 업체 고르기</Link>
          <p className="mj-tiny">확정 전에는 몇 번이든 다시 고를 수 있어요.</p>
        </>
      )}
      {confirmedOn ? (
        <button type="button" className="mj-btn mj-btn-ghost mj-btn-sm" style={{ border: "1px dashed var(--line-strong)", alignSelf: "flex-start" }} aria-pressed={demo} onClick={() => { setDemo(!demo); setAsking(false); }}>
          데모 · {demo ? "확정 후 화면 보기" : "확정 전 화면 보기"}
        </button>
      ) : null}
    </section>
  );
}
