"use client";
// C1 집 정보: ① 주소 찾기(입력 1칸 + 결과 3~5줄) → ③ 확인(단지 · 동 · 호 · 면적) 또는 평형만 고르기.
// 동 · 호는 이 카드 칸에만 두고 대화 글 · AI에 넣지 않아요. [맞아요]는 비서가 만든 '집 정보 저장' 제안의 승인이에요(되돌릴 수 있어요).
import { useEffect, useRef, useState } from "react";
import type { AddressHit } from "@/lib/api/assistant";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import c from "./cards.module.css";

export function HomeInfoCard({ card, ctx, old }: CardProps<"home_info">) {
  const d = card.data;
  if (d.phase === "search") return <Search card={card} ctx={ctx} old={old} />;
  if (d.phase === "manual") {
    const done = !!d.picked;
    return (
      <section className={done ? `${k.card} ${k.done}` : k.card} aria-label="평형 고르기">
        <span className={c.lbl}>평형</span>
        <div className={k.chips}>
          {(d.pyeong_options ?? []).map((p) => (
            <button key={p} type="button" className={k.chip} aria-pressed={d.picked === p} disabled={done || ctx.busy} onClick={() => ctx.send(`${p}이에요`, { card_id: card.card_id, choice: p })}>{p}</button>
          ))}
        </div>
      </section>
    );
  }
  return <Confirm card={card} ctx={ctx} old={old} />;
}

function Search({ card, ctx }: CardProps<"home_info">) {
  const d = card.data;
  const picked = d.picked ?? null;
  const [q, setQ] = useState(d.query ?? "");
  const [hits, setHits] = useState<AddressHit[] | null>(d.hits?.length ? d.hits : null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  function onType(v: string) {
    setQ(v);
    if (timer.current) clearTimeout(timer.current);
    if (v.trim().length < 2) return;
    timer.current = setTimeout(async () => {
      setLoading(true);
      try { setHits(await ctx.searchAddress(v)); } catch { setHits([]); } finally { setLoading(false); }
    }, 300);
  }
  const id = `${card.card_id}-q`;
  return (
    <section className={picked ? `${k.card} ${k.done}` : k.card} aria-label="주소 찾기">
      <div className={c.field}>
        <label className={c.lbl} htmlFor={id}>주소나 단지 이름</label>
        <div className={c.search}>
          <I n="search" />
          <input id={id} value={q} onChange={(e) => onType(e.target.value)} placeholder="예: 상계 푸른숲" autoComplete="off" readOnly={!!picked} enterKeyHint="search" />
        </div>
      </div>
      {loading ? <p className={k.muted} role="status">찾고 있어요</p> : null}
      {hits && hits.length ? (
        <ul className={c.addr}>
          {hits.map((h) => (
            <li key={h.id}>
              <button type="button" aria-current={picked === h.id ? "true" : undefined} disabled={!!picked || ctx.busy} onClick={() => ctx.send(h.name, { card_id: card.card_id, choice: h.id })}>
                <b>{h.name}</b><span>{h.road}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : hits && !loading ? (
        <p className={c.none}>찾지 못했어요<button type="button" className={k.text} onClick={() => ctx.send("평형만 알아요")}>직접 넣기</button></p>
      ) : null}
    </section>
  );
}

function Confirm({ card, ctx }: CardProps<"home_info">) {
  const d = card.data;
  const cx = d.complex;
  const [dong, setDong] = useState(d.dongs?.[2] ?? d.dongs?.[0] ?? "");
  const [ho, setHo] = useState("");
  const act = d.action_id ? ctx.actionOf(d.action_id) : null;
  const saved = d.saved || act?.status === "executed";
  const pending = d.action_id ? ctx.pendingOf(d.action_id) : false;
  return (
    <section className={saved ? `${k.card} ${k.done}` : k.card} aria-label="집 확인">
      {cx ? (
        <div className={c.apt}>
          <span className={c.aptIc}><I n="building" /></span>
          <div className={c.aptT}>
            <b>{cx.name}</b>
            <span className={`${k.muted} ${k.num}`}>{cx.households.toLocaleString("ko-KR")}세대 · {cx.approved_year}년 사용승인 · {cx.corridor}</span>
          </div>
        </div>
      ) : null}
      {d.dongs?.length ? (
        <div className={c.field}>
          <span className={c.lbl} id={`${card.card_id}-dh`}>동 · 호</span>
          <div className={c.inpRow} role="group" aria-labelledby={`${card.card_id}-dh`}>
            <select className={c.sel} aria-label="동" value={dong} onChange={(e) => setDong(e.target.value)} disabled={saved}>
              {d.dongs.map((x) => <option key={x}>{x}</option>)}
            </select>
            <span className={c.ho}><input className={`${c.inp} ${k.num}`} value={ho} onChange={(e) => setHo(e.target.value.replace(/\D/g, "").slice(0, 4))} aria-label="호" inputMode="numeric" placeholder="1204" disabled={saved} />호</span>
          </div>
        </div>
      ) : null}
      {d.area ? (
        <div className={c.area}>
          <div className={c.areaL}>
            <span>이 집 면적</span>
            <b className={k.num}>전용 {d.area.exclusive_m2}㎡</b>
            <span className={`${c.sub} ${k.num}`}>공급 {d.area.supply_m2}㎡ · {d.area.pyeong_type}</span>
          </div>
          {d.sources?.[0] ? <span className={k.basis}>{d.sources[0]}</span> : null}
        </div>
      ) : null}
      {saved ? (
        <p className={k.decided}><I n="check" />집 정보를 저장했어요</p>
      ) : (
        <div className={k.row}>
          <button type="button" className={`${k.btn} ${k.pri}`} disabled={!d.action_id || pending || ctx.busy} aria-busy={pending || undefined} onClick={() => d.action_id && ctx.approve(d.action_id)}>맞아요</button>
          <button type="button" className={`${k.text} ${k.gray}`} disabled={ctx.busy} onClick={() => ctx.send("직접 고칠게요")}>직접 고칠게요</button>
        </div>
      )}
    </section>
  );
}
