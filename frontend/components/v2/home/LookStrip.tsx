"use client";
// 흐르는 사진 줄 (v10 lookStrip 마지막 판): 실제 사진이 있는 느낌만, 스타일마다 많이 고르는 순 6장을 번갈아 한 줄로.
import type { CSSProperties } from "react";
import { STYLES } from "../data";
import { F } from "../engine";
import { lookSrcs } from "../flow";
import { type Look, LOOKS } from "../looks";
import { Photo } from "../photo";
import { useV2 } from "../store";
import { startWithLook } from "./start";

type L = Look & { style: string };

function Tile({ lk, dup }: { lk: L; dup: boolean }) {
  const st = STYLES.find((s) => s.id === lk.style);
  if (!st) return null;
  return (
    <button
      type="button"
      className="ls-tile"
      aria-hidden={dup || undefined}
      tabIndex={dup ? -1 : undefined}
      onClick={() => F.openLooks?.(st, { start: lk.id, onPick: (x: Look) => startWithLook(st, x) })}
    >
      <Photo srcs={lookSrcs(lk)} alt={`${st.ko} · ${lk.ko}`} cls="ls-ph" />
      <span>
        <b>{lk.ko}</b>
        <small>{st.ko}</small>
      </span>
    </button>
  );
}

export function LookStrip() {
  useV2();
  const per = Object.entries(LOOKS).map(([sid, ls]) => ls.filter((l) => l.img).slice(0, 6).map((l) => ({ ...l, style: sid })));
  const pick: L[] = [];
  for (let i = 0; i < 6; i++) for (const l of per) if (l[i]) pick.push(l[i]); // 스타일을 번갈아
  return (
    <section className="home-sec ls">
      <div className="sec-t">
        <h2>마음에 드는 집이 있나요?</h2>
        <p className="muted">사진을 누르면 크게 보고, 그 느낌 그대로 상담을 시작할 수 있어요.</p>
      </div>
      <div className="ls-row ls10-row">
        <div className="ls-track ls10" style={{ "--ls-dur": `${Math.round(pick.length * 7)}s` } as CSSProperties}>
          {[...pick, ...pick].map((lk, n) => <Tile key={`${lk.id}-${n}`} lk={lk} dup={n >= pick.length} />)}
        </div>
      </div>
    </section>
  );
}
