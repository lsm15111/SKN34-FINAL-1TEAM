"use client";
// 첫 화면 큰 사진: 다섯 스타일이 5초마다 넘어간다 (v10 homeStage). 탭을 누르거나 '사진 n장 보기'를 누르면 멈춘다.
import { useEffect, useRef, useState } from "react";
import { STYLES, type Style } from "../data";
import { F } from "../engine";
import { type Look, lookPhotos } from "../looks";
import { Photo, type Srcs } from "../photo";
import { DATA } from "../store";
import { startWithLook } from "./start";

/* 첫 화면은 늘 가구 있는 사진('시공 직후' 보기 설정과 상관없이) */
const furnished = (st: Style): Srcs => {
  const d = DATA.styles[st.id] || {};
  return { ai: `img/ai/style-${st.id}.jpg`, mfg: (d.img_mfg as string) || null, free: (d.img_free || [])[0] || null, color: st.pal[1] };
};

export function HomeStage() {
  const [i, setI] = useState(0);
  const [stopped, setStopped] = useState(false);
  const [hover, setHover] = useState(false);
  const [reduce] = useState(() => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const hoverRef = useRef(false);
  useEffect(() => {
    if (reduce || stopped) return;
    const t = setInterval(() => {
      if (!hoverRef.current) setI((k) => (k + 1) % STYLES.length);
    }, 5000);
    return () => clearInterval(t);
  }, [reduce, stopped]);
  const stop = () => setStopped(true);
  const st = STYLES[i];
  return (
    <div
      className={"hs" + (stopped || hover ? " paused" : "")}
      onPointerEnter={() => {
        hoverRef.current = true;
        setHover(true);
      }}
      onPointerLeave={() => {
        hoverRef.current = false;
        setHover(false);
      }}
    >
      <div className="hs-frame">
        {STYLES.map((s, k) => <Photo key={s.id} srcs={furnished(s)} alt={`${s.ko} 거실`} cls={"hs-ph" + (k === i ? " on" : "")} />)}
        <div className="hs-cap">
          <b>{st.ko}</b>
          <span>{st.tag}</span>
          <span className="pal">{st.pal.map((c) => <span key={c} style={{ background: c }} />)}</span>
          <button
            type="button"
            className="btn btn-sm hs-more"
            onClick={() => {
              stop();
              F.openLooks?.(st, { onPick: (lk: Look) => startWithLook(st, lk) });
            }}
          >
            {`사진 ${lookPhotos(st.id).length}장 보기`}
          </button>
        </div>
        {reduce ? null : <i className="hs-bar" key={i} />}
      </div>
      <div className="hs-tabs" role="tablist" aria-label="스타일 다섯 가지">
        {STYLES.map((s, k) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={k === i}
            onClick={() => {
              setI(k);
              stop();
            }}
          >
            <span className="dot" style={{ background: s.pal[2] }} />
            {s.ko}
          </button>
        ))}
      </div>
    </div>
  );
}
