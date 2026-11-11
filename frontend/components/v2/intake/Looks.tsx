"use client";
// 느낌 사진 모음 겹창 (v10 openLooks · SPACE_FILTERS · inFilter). onPick(lk)를 넘기면 [이 사진으로 할게요] 버튼이 생긴다.
import { useEffect, useRef, useState } from "react";
import type { Style } from "../data";
import { F, openOverlay } from "../engine";
import { lookSrcs } from "../flow";
import { type Look, lookOf, lookPhotos, TONE_KO } from "../looks";
import { Photo } from "../photo";
import { useV2 } from "../store";

export const SPACE_FILTERS: [string, string][] = [["all", "전체"], ["living", "거실"], ["kitchen", "주방 · 다이닝"], ["bed", "침실 · 아이방"], ["bath", "욕실"], ["etc", "현관 · 서재 · 옷방"]];
export const inFilter = (lk: Look, f: string) =>
  f === "all" || lk.space === f || (f === "kitchen" && lk.space === "dining") || (f === "bed" && lk.space === "kid") || (f === "etc" && ["entry", "study", "dress"].includes(lk.space));

type Opts = { start?: string | null; onPick?: (lk: Look) => void };

function LooksSheet({ st, start, onPick, close }: Opts & { st: Style; close: () => void }) {
  const S = useV2();
  const list = lookPhotos(st.id);
  const [filter, setFilter] = useState("all");
  const [cur, setCur] = useState<Look | null>(() => {
    const first = lookOf(start);
    return first && first.style === st.id && first.img ? first : null;
  });
  const x = useRef<HTMLButtonElement>(null);
  const x0 = useRef<number | null>(null);
  const shown = list.filter((l) => inFilter(l, filter));
  const step = (d: number) => {
    if (!cur) return;
    const i = shown.findIndex((v) => v.id === cur.id);
    setCur(shown[(i + d + shown.length) % shown.length]);
  };
  const stepRef = useRef(step);
  stepRef.current = step;
  const curRef = useRef(cur);
  curRef.current = cur;

  useEffect(() => {
    x.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (curRef.current) setCur(null);
        else close();
      } else if (curRef.current && (e.key === "ArrowRight" || e.key === "ArrowLeft")) stepRef.current(e.key === "ArrowRight" ? 1 : -1);
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [close]);

  const title = cur ? `${shown.findIndex((v) => v.id === cur.id) + 1} / ${shown.length}` : `${st.ko} · ${list.length}가지`;
  return (
    <div
      className="sheet-bg lk-bg"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="sheet lk-sheet" role="dialog" aria-modal="true" aria-label={`${st.ko} 사진 모음`}>
        <div className="lk-head">
          <h3>{title}</h3>
          <button ref={x} type="button" className="x" aria-label="닫기" onClick={close}>×</button>
        </div>
        <div className="lk-body">
          {cur ? (
            <>
              <div className="lk-stage">
                <div
                  style={{ display: "contents" }}
                  onPointerDown={(e) => {
                    x0.current = e.clientX;
                  }}
                  onPointerUp={(e) => {
                    if (x0.current != null && Math.abs(e.clientX - x0.current) > 40) step(e.clientX < x0.current ? 1 : -1);
                    x0.current = null;
                  }}
                >
                  <Photo key={cur.id} srcs={lookSrcs(cur)} alt={`${cur.ko} ${cur.space_ko}`} cls="lk-big" />
                </div>
                <button type="button" className="lk-nav prev" aria-label="이전 사진" onClick={() => step(-1)}>‹</button>
                <button type="button" className="lk-nav next" aria-label="다음 사진" onClick={() => step(1)}>›</button>
              </div>
              <div className="lk-info">
                <div>
                  <h4>{cur.ko}</h4>
                  <p className="muted">{`${cur.space_ko} · ${cur.note}`}</p>
                </div>
                <ul className="lk-tones" aria-label="이 느낌의 색">
                  {Object.entries(cur.tone).map(([k, c]) => (
                    <li key={k}>
                      <i style={{ background: c }} />
                      {TONE_KO[k]}
                    </li>
                  ))}
                </ul>
                <p className="src">{F.lookCredit?.(cur) ?? ""}</p>
                <div className="row">
                  {onPick ? (
                    <button
                      type="button"
                      className="btn btn-pri"
                      onClick={() => {
                        close();
                        onPick(cur);
                      }}
                    >
                      이 사진으로 할게요
                    </button>
                  ) : null}
                  <button type="button" className="btn" onClick={() => setCur(null)}>목록으로</button>
                </div>
              </div>
            </>
          ) : (
            <>
              <p className="muted">많이 고르는 순이에요.</p>
              <div className="chips lk-filter" role="group" aria-label="공간">
                {SPACE_FILTERS.filter(([f]) => f === "all" || list.some((l) => inFilter(l, f))).map(([f, ko]) => (
                  <button key={f} type="button" className="chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                    {ko}
                  </button>
                ))}
              </div>
              <ul className="lk-grid">
                {shown.map((lk) => (
                  <li key={lk.id}>
                    <button type="button" className="lk-tile" aria-current={S.look === lk.id} onClick={() => setCur(lk)}>
                      <Photo srcs={lookSrcs(lk)} alt={`${lk.ko} ${lk.space_ko}`} cls="lk-ph" />
                      {lk.rank <= 3 ? <span className="lk-rank">{`많이 고름 ${lk.rank}`}</span> : null}
                      <span className="lk-cap">
                        <b>{lk.ko}</b>
                        <small>{lk.space_ko}</small>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** 느낌 사진 모음(많이 고르는 순)을 연다 */
export function openLooks(st: Style, { start, onPick }: Opts = {}) {
  openOverlay((close) => <LooksSheet st={st} start={start} onPick={onPick} close={close} />);
}
