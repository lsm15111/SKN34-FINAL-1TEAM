"use client";
// 0. 첫 인사 · 스타일 고르기 · 1. 공사 순서 (v10 welcome · styleRail · collapseRail · reopenStyles · chooseStyle · afterStyle · chooseLook · guideStep)
import { useRef, useState } from "react";
import { flashBoard } from "../Board";
import { GUIDE, type Style, STYLES } from "../data";
import { bot, clearQuick, F, live, me, quick } from "../engine";
import { autoPick, lookSrcs, resumeStep, setStep, styleOf, styleSrcs } from "../flow";
import { type Look, lookOf, lookPhotos } from "../looks";
import { EmptyToggle, Photo } from "../photo";
import { S, touch, useV2 } from "../store";
import { openLooks } from "./Looks";

type Live<T> = { get: () => T; set: (v: T) => void; use: () => T };
/** 지금 열려 있는 스타일 카드 줄. 접으면 '스타일 다시 보기' 칩이 된다 (v10 railMsg) */
let railMsg: Live<string | null> | null = null;

function StyleRail({ state }: { state: Live<string | null> }) {
  const collapsed = state.use();
  useV2();
  const rail = useRef<HTMLDivElement>(null);
  const [n, setN] = useState(1);
  if (collapsed !== null)
    return (
      <div className="chips">
        <button type="button" className="chip ghost" onClick={() => F.reopenStyles()}>{collapsed}</button>
      </div>
    );
  const step = () => (rail.current?.querySelector(".style-card")?.getBoundingClientRect().width ?? 0) + 12;
  const by = (d: number) => rail.current?.scrollBy({ left: d * step(), behavior: "smooth" });
  return (
    <div className="rail-wrap">
      <div className="rail-top"><EmptyToggle /></div>
      <div
        ref={rail}
        className="rail"
        tabIndex={0}
        aria-label="스타일 다섯 가지"
        onScroll={(e) => setN(Math.min(STYLES.length, Math.round(e.currentTarget.scrollLeft / step()) + 1))}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
            e.preventDefault();
            by(e.key === "ArrowRight" ? 1 : -1);
          }
        }}
      >
        {STYLES.map((st) => (
          <article key={st.id} className="style-card" aria-current={S.style === st.id}>
            <Photo srcs={styleSrcs(st)} alt={`${st.ko} 거실`} />
            <div className="in">
              <h3>{st.ko}</h3>
              <div className="pal" role="img" aria-label={`${st.ko} 대표 색`}>
                {st.pal.map((c) => <span key={c} style={{ background: c }} />)}
              </div>
              <p className="keys">{st.keys.join(" · ")}</p>
              <div className="lk-peek">
                {lookPhotos(st.id).slice(0, 3).map((lk) => (
                  <button
                    key={lk.id}
                    type="button"
                    className="lk-pk"
                    aria-label={`${lk.ko} 크게 보기`}
                    onClick={() => openLooks(st, { start: lk.id, onPick: (x) => chooseLook(st, x) })}
                  >
                    <Photo srcs={lookSrcs(lk)} alt={lk.ko} />
                  </button>
                ))}
                <button type="button" className="btn btn-sm" onClick={() => openLooks(st, { onPick: (lk) => chooseLook(st, lk) })}>
                  {`${lookPhotos(st.id).length}장 보기`}
                </button>
              </div>
            </div>
            <div className="foot">
              <button type="button" className="btn btn-pri btn-sm" onClick={() => chooseStyle(st)}>이걸로</button>
              <button type="button" className="btn-text" onClick={() => F.askAboutStyle(st)}>
                <span className="spark" aria-hidden="true">✦</span>물어보기
              </button>
            </div>
          </article>
        ))}
      </div>
      <div className="rail-nav">
        <span className="count num">{`${n} / ${STYLES.length}`}</span>
        <button type="button" aria-label="이전" onClick={() => by(-1)}>‹</button>
        <button type="button" aria-label="다음" onClick={() => by(1)}>›</button>
      </div>
    </div>
  );
}

function railBox() {
  const state = live<string | null>(null);
  return { state, node: <StyleRail state={state} /> };
}

export async function welcome() {
  const r = railBox();
  await bot("어떤 분위기가 좋아요?", r.node);
  railMsg = r.state;
  quick([["잘 모르겠어요", () => afterStyle()], ["공사 순서가 궁금해요", () => guideStep(true)]]);
}
export function collapseRail() {
  if (!railMsg) return;
  railMsg.set(S.style ? `스타일 다시 보기 · ${styleOf(S.style)?.ko ?? ""}` : "스타일 다시 보기");
  railMsg = null;
}
export async function reopenStyles() {
  setStep("styles");
  const r = railBox();
  await bot("다른 스타일로 바꿀까요?", r.node);
  railMsg = r.state;
}
export function chooseStyle(st: Style) {
  const first = !S.style;
  S.style = st.id;
  if (lookOf(S.look)?.style !== st.id) S.look = null;
  me(S.look ? `${st.ko} · ${lookOf(S.look)?.ko}` : st.ko);
  clearQuick();
  collapseRail();
  touch();
  flashBoard();
  if (!first) {
    if (S.far >= 5) {
      autoPick();
      F.refreshMat?.();
      touch();
    }
    resumeStep();
    bot(S.far >= 5 ? "자재 추천도 다시 맞췄어요." : "보드에 바꿔 담았어요.");
    return;
  }
  bot(st.care).then(() => afterStyle());
}
export function chooseLook(st: Style, lk: Look) {
  S.look = lk.id;
  chooseStyle(st);
}
/** 첫 화면에서 고른 느낌으로 상담 시작 (V2App startFlow의 look) */
export function startLook(styleId: string, lookId: string) {
  const st = STYLES.find((x) => x.id === styleId), lk = lookOf(lookId);
  if (st && lk) {
    chooseLook(st, lk);
    return true;
  }
  return false;
}
export async function afterStyle() {
  collapseRail();
  if (S.guideSeen) return F.infoStep();
  await bot("공사 순서를 먼저 볼까요?");
  quick([
    ["볼게요", () => guideStep(false)],
    ["넘어갈게요", () => {
      S.guideSeen = true;
      F.infoStep();
    }],
  ]);
}

/* 1. 공사 순서 */
function GuideCard({ mine }: { mine: Set<string> }) {
  const [all, setAll] = useState(false);
  return (
    <div className="card">
      <div>
        <h3>공사 순서</h3>
        <p className="muted">30평대 전체 공사 4~6주</p>
      </div>
      <ol className="guide">
        {GUIDE.map((g, i) => (all || i < 3) && (
          <li key={g.n} className={g.cats.some((c) => mine.has(c)) ? "mine" : ""}>
            <span className="n">{String(i + 1).padStart(2, "0")}</span>
            <div>
              <b>{g.n}</b>
              <p>{g.t}</p>
            </div>
            <span className="d">{g.d}</span>
          </li>
        ))}
      </ol>
      {all ? null : (
        <button type="button" className="btn-text" onClick={() => setAll(true)}>{`전체 ${GUIDE.length}단계 보기`}</button>
      )}
      <p className="muted">벽 안의 일 → 보이는 마감, 먼지 나는 일 → 깨끗한 일 순서예요.</p>
    </div>
  );
}
export async function guideStep(fromStart?: boolean) {
  S.guideSeen = true;
  collapseRail();
  await bot(null, <GuideCard mine={new Set(S.scope.cats)} />);
  if (fromStart && !S.style) quick([["스타일 고르기", () => reopenStyles()], ["집 정보부터", () => F.infoStep()]]);
  else quick([["다음", () => F.infoStep()]]);
}

export function resetRail() {
  railMsg = null;
}
