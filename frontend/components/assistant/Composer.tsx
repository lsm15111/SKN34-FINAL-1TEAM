"use client";
// 입력 칸(아래에 붙음): 빠른 답 칩(가로 넘김) · 모서리 26 상자 + 40px 파란 원 ↑. 웹 1024 아래는 칩 왼쪽에 '보드' 띠.
// 빠른 답 칩은 고객 말로 남을 뿐 일을 실행하지 않아요(실행은 승인 카드만). 쓰다 만 글만 이 탭에 둬요(편의).
// 비서가 무료 모드(LLM 없이)면 입력 칸 위에 한 줄로 알려요(health: off · budget · breaker).
import { useEffect, useRef, useState } from "react";
import type { HealthOut } from "@/lib/api/assistant";
import { I } from "./kit/icons";
import s from "./assistant.module.css";

const FREE: Record<Exclude<HealthOut["reason"], "ok">, string> = {
  off: "지금은 AI 설명 없이 계산 결과와 믿집 안내로 답해요",
  budget: "오늘은 AI 설명을 쉬어요. 계산 결과와 믿집 안내로 답해요",
  breaker: "AI 연결이 잠시 불안해요. 계산 결과와 믿집 안내로 답해요",
};

export function Composer({ projectId, chips, busy, onSend, band, onBand, health }: {
  projectId: string;
  chips: string[];
  busy: boolean;
  onSend: (text: string) => void;
  /** 보드 띠 오른쪽 수(정할 일) */
  band: number;
  onBand: () => void;
  health: HealthOut | null;
}) {
  const key = `mj_v4_draft:${projectId}`;
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    try { setText(window.sessionStorage.getItem(key) ?? ""); } catch { /* 못 읽어도 빈 칸으로 */ }
  }, [key]);
  useEffect(() => {
    try { if (text) window.sessionStorage.setItem(key, text); else window.sessionStorage.removeItem(key); } catch { /* 편의 기능이라 넘어가요 */ }
    const el = area.current;
    if (el) { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 140)}px`; }
  }, [text, key]);

  function submit() {
    const t = text.trim();
    if (!t || busy) return;
    onSend(t);
    setText("");
  }

  const free = health && health.mode === "free" && health.reason !== "ok" ? FREE[health.reason] : null;
  return (
    <form className={s.composer} onSubmit={(e) => { e.preventDefault(); submit(); }}>
      {free ? <p className={s.free} role="status"><I n="info" />{free}</p> : null}
      <button type="button" className={s.band} onClick={onBand} aria-label={band ? `내 공사 보드, 정할 일 ${band}` : "내 공사 보드"}>
        <b>보드</b>{band ? <><span className={s.muted}>정할 일</span><span className={s.cnt}>{band}</span></> : null}
      </button>
      <div className={s.quick} aria-label="빠른 답">
        {chips.map((c) => <button key={c} type="button" className={s.chip} disabled={busy} onClick={() => onSend(c)}>{c}</button>)}
      </div>
      <div className={s.cbox}>
        <textarea
          ref={area}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, 1000))}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
          placeholder="궁금한 걸 물어보세요"
          aria-label="비서에게 보낼 말"
        />
        <button className={s.send} type="submit" aria-label="보내기" disabled={busy || !text.trim()}><I n="up" /></button>
      </div>
    </form>
  );
}
