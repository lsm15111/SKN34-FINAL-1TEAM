"use client";
// 우리 집에 칠해 보기 (v10 v7 toneRoom 마지막 판): 고른 느낌의 바닥 · 벽 · 나무 색을 빈 방 사진에 입힌다.
// v10 최종 첫 화면에서는 빠져 있다(v8 덧씌움). 다시 넣을 때 Home에 <ToneRoom />만 더하면 된다.
import { useEffect, useRef, useState } from "react";
import { STYLES } from "../data";
import { LOOKS, TONE_KO } from "../looks";
import { useV2 } from "../store";
import { roomDraw, rrOn, rrPaint, rrReady } from "./room";
import { startWithLook } from "./start";

const Arw = ({ d }: { d: number }) => (
  <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
    <path d={d < 0 ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7"} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export function ToneRoom() {
  useV2();
  const [st, setSt] = useState(STYLES[0]);
  const [k, setK] = useState(0);
  const ls = LOOKS[st.id] || [], lk = ls[k] || ls[0];
  const t = lk?.tone || {};
  const src = rrOn() ? rrPaint(t) || "" : roomDraw({ tone: t, space: "living" });
  const [layers, setLayers] = useState<{ a: string; b: string; front: "a" | "b" }>({ a: src, b: "", front: "a" });
  useEffect(() => {
    rrReady();
  }, []);
  useEffect(() => {
    setLayers((l) => (l[l.front] === src ? l : l.front === "a" ? { ...l, b: src, front: "b" } : { ...l, a: src, front: "a" }));
  }, [src]);
  const move = (d: number) => {
    const n = ls.length || 1;
    setK((x) => (x + d + n) % n);
  };
  const x0 = useRef<number | null>(null);
  if (!lk) return null;
  return (
    <section className="home-sec tr">
      <div className="sec-t">
        <h2>우리 집에 칠해 보기</h2>
        <p className="muted">바닥 · 벽 · 문 색을 바꿔 보세요. 고른 색과 비슷한 자재를 먼저 추천해요.</p>
      </div>
      <div className="tr-box">
        <div
          className="tr-view"
          role="group"
          aria-roledescription="사진 넘기기"
          aria-label="느낌별 색 입힌 방"
          onPointerDown={(e) => {
            if (e.pointerType !== "mouse" && !(e.target as HTMLElement).closest("button")) x0.current = e.clientX;
          }}
          onPointerUp={(e) => {
            if (x0.current == null) return;
            const dx = e.clientX - x0.current;
            x0.current = null;
            if (Math.abs(dx) > 40) move(dx < 0 ? 1 : -1);
          }}
          onPointerCancel={() => {
            x0.current = null;
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") {
              move(-1);
              e.preventDefault();
            }
            if (e.key === "ArrowRight") {
              move(1);
              e.preventDefault();
            }
          }}
        >
          <button type="button" className="tr-nav prev" aria-label="이전 느낌" onClick={() => move(-1)}><Arw d={-1} /></button>
          <button type="button" className="tr-nav next" aria-label="다음 느낌" onClick={() => move(1)}><Arw d={1} /></button>
          <div className="tr-pic" role="img" aria-label={`${st.ko} ${lk.ko}의 바닥 · 벽 · 문 색을 입힌 빈 방 사진`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className={"tr-img" + (layers.front === "a" ? " on" : "")} alt="" src={layers.a || undefined} />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className={"tr-img" + (layers.front === "b" ? " on" : "")} alt="" aria-hidden="true" src={layers.b || undefined} />
          </div>
          <span className="tr-count" aria-live="polite">{`${k + 1} / ${ls.length}`}</span>
        </div>
        <div className="tr-side">
          <div className="tr-styles" role="group" aria-label="스타일">
            {STYLES.map((x) => (
              <button
                key={x.id}
                type="button"
                className="tr-st"
                aria-pressed={x.id === st.id}
                onClick={() => {
                  if (x.id === st.id) return;
                  setSt(x);
                  setK(0);
                }}
              >
                <span className="dot" style={{ background: x.pal[2] }} />
                {x.ko}
              </button>
            ))}
          </div>
          <div className="tr-name">
            <b>{`${st.ko} · ${lk.ko}`}</b>
            <span className="muted">{`많이 고름 ${lk.rank}위 · ${lk.note}`}</span>
          </div>
          <ul className="lk-tones">
            {(["floor", "wall", "wood"] as const).filter((x) => t[x]).map((x) => (
              <li key={x}>
                <i style={{ background: t[x] }} />
                {TONE_KO[x]}
              </li>
            ))}
          </ul>
          <div className="row">
            <button type="button" className="btn btn-pri btn-sm" onClick={() => startWithLook(st, lk)}>이 색으로 시작</button>
          </div>
        </div>
      </div>
    </section>
  );
}
