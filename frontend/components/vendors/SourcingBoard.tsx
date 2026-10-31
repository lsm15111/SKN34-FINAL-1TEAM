"use client";
// 가견적 받을 업체 (실제 프로젝트): 공정 탭 → 후보 카드, 옆에는 업체에 건넬 집 정보.
// 후보 · 받는 길 · 비용 · 출처는 API(가견적 에이전트)가 정한 것을 그대로 보인다. 공정 탭은 주소(?trade=)에도 남긴다.
import { useRef, useState } from "react";
import type { Schemas } from "@/lib/backend/client";
import { TRADE_KEYS } from "@/lib/labels";
import { TRADE_LABEL, type TradeKey } from "@/lib/types";
import { CandidateCard } from "./CandidateCard";
import { CopyButton } from "./CopyButton";
import s from "./SourcingBoard.module.css";

type Sourcing = Schemas["SourcingOut"];
const tradeName = (t: string) => TRADE_LABEL[t as TradeKey] ?? t;

export function SourcingBoard({ data, initialTrade }: { data: Sourcing; initialTrade?: string }) {
  // 공정은 다른 화면과 같은 순서로 (모르는 공정은 뒤에)
  const trades = [...TRADE_KEYS.filter((t) => data.trades.includes(t)), ...data.trades.filter((t) => !(t in TRADE_LABEL))];
  const [trade, setTrade] = useState(initialTrade && trades.includes(initialTrade) ? initialTrade : trades[0]);
  const [sent, setSent] = useState<Record<string, string>>({}); // `${업체}:${공정}` → 방금 보낸 요청 상태
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const count = (t: string) => data.candidates.filter((c) => c.trades.includes(t)).length;
  const list = data.candidates.filter((c) => c.trades.includes(trade));
  const tabs = trades.length > 1;

  function pick(t: string) {
    setTrade(t);
    window.history.replaceState(null, "", `?trade=${encodeURIComponent(t)}`);
  }
  function onTabKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const j = (i + (e.key === "ArrowRight" ? 1 : trades.length - 1)) % trades.length;
    pick(trades[j]);
    tabRefs.current[trades[j]]?.focus();
  }

  return (
    <div className="mj-split">
      <div className="mj-col">
        {data.notice ? <p className="mj-notice"><span>{data.notice}</span></p> : null}
        {data.candidates.length ? (
          <>
            {tabs ? (
              <div role="tablist" aria-label="공정" className="mj-tabs">
                {trades.map((t, i) => (
                  <button key={t} ref={(el) => { tabRefs.current[t] = el; }} type="button" role="tab" id={`tab-${t}`} aria-controls="trade-panel" aria-selected={trade === t} tabIndex={trade === t ? 0 : -1} onClick={() => pick(t)} onKeyDown={(e) => onTabKey(e, i)}>
                    {tradeName(t)} <span className="mj-badge mj-b-in mj-num">{count(t)}곳</span>
                  </button>
                ))}
              </div>
            ) : null}
            <section id="trade-panel" role={tabs ? "tabpanel" : undefined} aria-labelledby={tabs ? `tab-${trade}` : "trade-h"} className={s.panel}>
              <h2 id="trade-h" className="mj-h2">{tradeName(trade)} 업체 <span className="mj-num">{list.length}곳</span></h2>
              {list.length ? (
                <>
                  <p className="mj-small">믿집 업체에는 여기서 바로 가견적을 요청해요. 외부 업체는 업체 견적 창구나 전화로 직접 물어봐요.</p>
                  {/* key에 공정을 넣어, 공정을 바꾸면 카드 안 상태(확인 단계 · 복사)를 새로 시작한다 */}
                  <ul className={s.list}>
                    {list.map((c) => (
                      <CandidateCard
                        key={`${c.id}:${trade}`}
                        c={c}
                        trade={trade}
                        projectId={data.project_id}
                        facts={data.facts}
                        sent={sent[`${c.id}:${trade}`]}
                        onSent={(label) => setSent((old) => ({ ...old, [`${c.id}:${trade}`]: label }))}
                      />
                    ))}
                  </ul>
                </>
              ) : (
                <p className="mj-notice"><span>{data.region}에서 {tradeName(trade)} 업체를 아직 찾지 못했어요. 다른 공정을 보거나 나중에 다시 봐 주세요.</span></p>
              )}
            </section>
          </>
        ) : null}
      </div>

      <aside className="mj-aside mj-panel" aria-labelledby="facts-h">
        <h2 id="facts-h" className="mj-h3">업체에 건넬 집 정보</h2>
        <ul id="facts-list" className={s.facts}>
          {data.facts.map((f) => <li key={f}>{f}</li>)}
        </ul>
        <p className="mj-tiny">견적 받기에서 고른 답으로 정리했어요. 이름 · 연락처 · 동 · 호수는 넣지 않았어요.</p>
        <div className={s.copy}><CopyButton text={data.facts.join("\n")} label="집 정보 복사" targetId="facts-list" className="mj-btn mj-btn-sec mj-btn-sm" /></div>
      </aside>
    </div>
  );
}
