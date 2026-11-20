"use client";
// V3 실측 견적서 준비(요청 자세히 · /vendor/requests/{vid}/quote 맨 위): 표준 줄 체크리스트 · 빠지기 쉬운 것 · 칸 4개(낼 금액 · 부가세 방식 · 공사 기간 · 유효기간).
// 비서는 업체 금액을 제안하지 않고 빠진 항목만 짚어요. 합계 · 부가세는 보낼 때 계산 엔진이 만들어요.
import { useEffect, useState } from "react";
import { getQuoteChecklist, type QuoteChecklistData } from "@/lib/api/assistant";
import { won } from "@/lib/format";
import { I } from "@/components/assistant/kit/icons";
import { SourceTag } from "@/components/assistant/kit/StatusTag";
import k from "@/components/assistant/kit/kit.module.css";
import p from "./pro.module.css";

const WORD = { ok: "적었어요", check: "확인해 보세요", missing: "빠졌어요" } as const;

export function QuoteChecklist({ visitId, data }: { visitId: string; data?: QuoteChecklistData }) {
  const [d, setD] = useState<QuoteChecklistData | null>(data ?? null);
  const [fail, setFail] = useState(false);
  useEffect(() => {
    if (data) return;
    let alive = true;
    getQuoteChecklist(visitId).then((x) => { if (alive) setD(x); }).catch(() => { if (alive) setFail(true); });
    return () => { alive = false; };
  }, [visitId, data]);

  if (fail) return null;
  if (!d) return <section className={`${k.card} ${p.skel}`} aria-busy="true" aria-label="견적서 체크리스트를 만들고 있어요"><i /><i /><i /></section>;
  const missing = d.items.filter((x) => x.state !== "ok").length;
  return (
    <section className={k.card} aria-labelledby={`qc-${visitId}`}>
      <div className={k.top}>
        <h3 id={`qc-${visitId}`}>견적서 보내기 전에 볼 것{missing ? <> · <span className={k.num}>{missing}</span>개</> : null}</h3>
        <SourceTag src="guide" />
      </div>
      <ul className={p.check}>
        {d.items.map((x) => (
          <li key={x.key} data-s={x.state}>
            <I n={x.state === "ok" ? "check" : x.state === "check" ? "circle" : "alert"} />
            <span><b>{x.label}</b> · {WORD[x.state]}</span>
            {x.hint ? <small>{x.hint}</small> : null}
          </li>
        ))}
      </ul>
      <div className={p.fields} aria-label="견적서 칸 4개">
        {d.fields.map((f) => (
          <div key={f.label}><span>{f.label}</span><b data-empty={!f.value}>{f.value ?? "아직 비었어요"}</b></div>
        ))}
      </div>
      {d.easy_miss.length ? (
        <div>
          <p className={p.secT}>빠지기 쉬운 것</p>
          <ul className={p.miss}>{d.easy_miss.map((m) => <li key={m}>{m}</li>)}</ul>
        </div>
      ) : null}
      {d.prev ? <p className={k.muted}>앞서 보낸 {d.prev.version}판 {won(d.prev.total_won)} · 다시 보내면 고객에게 차액이 먼저 보여요</p> : null}
    </section>
  );
}
