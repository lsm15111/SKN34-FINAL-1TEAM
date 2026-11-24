"use client";
// 입력 칸(아래에 붙음): 빠른 답 칩(가로 넘김) · 입력 상자(사이트 입력 칸과 같은 모서리) + 40px 파란 원 ↑. 웹 1024 아래는 칩 왼쪽에 '보드' 띠.
// 빠른 답 칩은 고객 말로 남을 뿐 일을 실행하지 않아요(실행은 승인 카드만). 쓰다 만 글만 이 탭에 둬요(편의).
// 비서가 무료 모드(LLM 없이)면 입력 칸 위에 한 줄로 알려요(health: off · budget · breaker).
// 넘쳐서 끝내 못 보냈으면(onSend가 "busy") 쓴 글 · 붙인 사진을 입력 칸에 되살려요(지우지 않아요).
// 보이지 않는 글자(폭 없는 빈칸 · 한글 채움 등)만 있는 글은 빈 글로 봐요(보내기 단추를 꺼요, canSend).
// 받은 견적서 사진(2a): 사진 단추로 고르면 가리기 창(PhotoMask)이 떠요. 가린 그림만 올리고, 보낼 때 그 id를 턴에 붙여요(세 장까지).
// 글 없이 사진만 보내면 정해 둔 말(PHOTO_SAY)을 남겨요.
import { useEffect, useRef, useState } from "react";
import { canSend, sayable, type HealthOut } from "@/lib/api/assistant";
import { PHOTOS_MAX, sendText } from "@/lib/assistant/mask";
import { I } from "./kit/icons";
import { PhotoMask, type Attached } from "./PhotoMask";
import s from "./assistant.module.css";
import p from "./PhotoMask.module.css";

const FREE: Record<Exclude<HealthOut["reason"], "ok">, string> = {
  off: "지금은 AI 설명 없이 계산 결과와 믿집 안내로 답해요",
  budget: "오늘은 AI 설명을 쉬어요. 계산 결과와 믿집 안내로 답해요",
  breaker: "AI 연결이 잠시 불안해요. 계산 결과와 믿집 안내로 답해요",
};

export function Composer({ projectId, chips, busy, onSend, band, onBand, health }: {
  projectId: string;
  chips: string[];
  busy: boolean;
  /** "busy"를 돌려주면 서버가 받지 못한 말이에요(입력 칸에 되살려요). files는 붙인 사진(가린 그림) id */
  onSend: (text: string, files?: string[]) => Promise<"busy" | void> | void;
  /** 보드 띠 오른쪽 수(정할 일) */
  band: number;
  onBand: () => void;
  health: HealthOut | null;
}) {
  const key = `mj_v4_draft:${projectId}`;
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState<Attached[]>([]);
  const [picked, setPicked] = useState<File | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const photosRef = useRef<Attached[]>([]);
  photosRef.current = photos;

  useEffect(() => {
    try { setText(window.sessionStorage.getItem(key) ?? ""); } catch { /* 못 읽어도 빈 칸으로 */ }
  }, [key]);
  useEffect(() => {
    try { if (text) window.sessionStorage.setItem(key, text); else window.sessionStorage.removeItem(key); } catch { /* 편의 기능이라 넘어가요 */ }
    const el = area.current;
    if (el) { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 140)}px`; }
  }, [text, key]);
  // 미리 보기 주소는 화면을 떠날 때 놓아요
  useEffect(() => () => { photosRef.current.forEach((x) => URL.revokeObjectURL(x.url)); }, []);

  const ready = !busy && (canSend(text, busy) || photos.length > 0);

  async function submit() {
    if (!ready) return;
    const t = sendText(sayable(text) ? text : "", photos.length); // 보이지 않는 글자만 있으면 사진 말로
    if (!t) return;
    const sent = photos;
    setText("");
    setPhotos([]);
    const ids = sent.map((x) => x.id);
    if ((await onSend(t, ids.length ? ids : undefined)) === "busy") {
      setText((cur) => cur || text.trim()); // 그사이 새로 쓴 글이 있으면 그대로 둬요
      setPhotos((cur) => (cur.length ? cur : sent));
      return;
    }
    sent.forEach((x) => URL.revokeObjectURL(x.url));
  }

  function drop(id: string) {
    setPhotos((cur) => {
      cur.filter((x) => x.id === id).forEach((x) => URL.revokeObjectURL(x.url));
      return cur.filter((x) => x.id !== id);
    });
  }

  const free = health && health.mode === "free" && health.reason !== "ok" ? FREE[health.reason] : null;
  return (
    <>
      <form className={s.composer} onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        {free ? <p className={s.free} role="status"><I n="info" />{free}</p> : null}
        <button type="button" className={s.band} onClick={onBand} aria-label={band ? `내 공사 보드, 정할 일 ${band}` : "내 공사 보드"}>
          <b>보드</b>{band ? <><span className={s.muted}>정할 일</span><span className={s.cnt}>{band}</span></> : null}
        </button>
        <div className={s.quick} aria-label="빠른 답">
          {chips.map((c) => <button key={c} type="button" className={s.chip} disabled={busy} onClick={() => { void onSend(c); }}>{c}</button>)}
        </div>
        {photos.length ? (
          <ul className={p.atts} aria-label="붙인 사진">
            {photos.map((x, i) => (
              <li key={x.id}>
                {/* 가린 뒤 올린 그림(이 탭의 object URL) */}
                <img src={x.url} alt="" />
                <span>견적서 사진 {i + 1}</span>
                <button type="button" className={p.drop} aria-label={`견적서 사진 ${i + 1} 빼기`} disabled={busy} onClick={() => drop(x.id)}><I n="x" /></button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className={s.cbox}>
          <button
            type="button"
            className={p.attach}
            aria-label="받은 견적서 사진 붙이기"
            // 무료 모드(LLM 없음)에서는 사진을 읽을 수 없어 꺼요(위 한 줄 안내가 까닭을 말해요)
            disabled={busy || photos.length >= PHOTOS_MAX || !!free}
            onClick={() => fileRef.current?.click()}
          >
            <I n="image" />
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => { const f = e.target.files?.[0] ?? null; e.target.value = ""; if (f) setPicked(f); }}
          />
          <textarea
            ref={area}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, 1000))}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void submit(); } }}
            placeholder="궁금한 걸 물어보세요"
            aria-label="비서에게 보낼 말"
          />
          <button className={s.send} type="submit" aria-label="보내기" disabled={!ready}><I n="up" /></button>
        </div>
      </form>
      <PhotoMask
        file={picked}
        onClose={() => setPicked(null)}
        onDone={(x) => { setPicked(null); setPhotos((cur) => [...cur, x].slice(0, PHOTOS_MAX)); }}
      />
    </>
  );
}
