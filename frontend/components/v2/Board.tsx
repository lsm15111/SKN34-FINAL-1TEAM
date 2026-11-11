"use client";
// 내 집 보드 (v10 renderBoard · openBoard · closeBoard + 도구 칸 · 도면으로 수량). 고른 것이 쌓이는 오른쪽 칸.
// 좁은 화면에서는 아래 띠(BoardBand)를 누르면 겹창처럼 열린다.
import { useEffect, useRef, useState } from "react";
import { type Cat, manwon, PLANS, SPACES, TIERS } from "./data";
import { moveLabel } from "./dates";
import { F } from "./engine";
import { matOf, scopeCats, styleOf, styleSrcs } from "./flow";
import { matSrcs, Photo } from "./photo";
import { S, useV2 } from "./store";

export const boardUi = { open: false, setOpen: (_v: boolean) => {}, flash: 0 };
/** 보드가 반짝이게 (v10 renderBoard(true)) */
export function flashBoard() {
  boardUi.flash++;
}

function facts() {
  return [
    S.info.pyeong ? `${S.info.pyeong}평` : null,
    S.info.region || null,
    S.info.living ? (S.info.living === "living" ? "살면서 공사" : "빈집") : null,
    S.info.move ? `${moveLabel(S.info.move)} 입주` : null,
    S.scope.kind
      ? S.scope.kind === "all"
        ? "집 전체"
        : S.scope.spaces.length
          ? S.scope.spaces.map((s) => SPACES.find((x) => x.id === s)?.ko).filter(Boolean).join(", ")
          : `공정 ${S.scope.cats.length}개`
      : null,
    S.budget ? manwon(S.budget) : S.budgetUnknown ? "예산 미정" : null,
    S.far >= 3 || S.tierBy ? TIERS[S.tier] : null,
    S.plan ? (S.plan.kind === "file" ? "도면 올림" : S.plan.name) : null,
  ].filter(Boolean) as string[];
}

function Swatch({ c }: { c: Cat }) {
  const m = matOf(S.picks[c.id]);
  if (!m)
    return (
      <div className="sw">
        <div className="sw-empty">{c.ko}</div>
        <span><em>{c.ko}</em>아직이에요</span>
      </div>
    );
  return (
    <div className="sw">
      <Photo srcs={matSrcs(m)} alt={m.name} />
      <span><em>{c.ko}</em>{m.name}</span>
    </div>
  );
}

const Pal = ({ pal }: { pal: string[] }) => (
  <div className="pal">{pal.map((c) => <span key={c} style={{ background: c }} />)}</div>
);

export function Board() {
  useV2();
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState(false);
  const seen = useRef(boardUi.flash);
  const close = useRef<HTMLButtonElement>(null);
  boardUi.open = open;
  boardUi.setOpen = setOpen;
  useEffect(() => {
    if (boardUi.flash !== seen.current) {
      seen.current = boardUi.flash;
      setFlash(false);
      requestAnimationFrame(() => setFlash(true));
    }
  });
  useEffect(() => {
    if (!open) return;
    close.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open]);

  const st = styleOf(S.style);
  const fs = facts();
  const cats = S.far >= 5 ? scopeCats() : [];
  const picked = cats.filter((c) => S.picks[c.id]).length;
  const photos = [...S.photos, ...S.refs];
  const plan = S.plan?.kind === "type" ? PLANS.find((p) => p.id === S.plan?.id) : null;
  const go = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };
  return (
    <>
      {open ? <div className="board-scrim" onClick={() => setOpen(false)} /> : null}
      <aside className={`board${open ? " open" : ""}${flash ? " flash" : ""}`} id="board" aria-label="내 집 보드" onAnimationEnd={() => setFlash(false)}>
        <div className="board-head">
          <h2>내 집 보드</h2>
          <button ref={close} type="button" className="btn btn-sm board-close" onClick={() => setOpen(false)} aria-label="보드 닫기">닫기</button>
        </div>
        <div className="bsec">
          <span className="t">분위기</span>
          {st ? (
            <>
              <Photo srcs={styleSrcs(st)} alt={st.ko} cls="hero-ph" />
              <div className="mood-name"><strong>{st.ko}</strong><Pal pal={st.pal} /></div>
            </>
          ) : (
            <p className="empty">스타일을 고르면 여기에 담겨요.</p>
          )}
        </div>
        {fs.length ? (
          <div className="bsec">
            <span className="t">우리 집</span>
            <div className="facts">{fs.map((f) => <span key={f}>{f}</span>)}</div>
          </div>
        ) : null}
        {photos.length ? (
          <div className="bsec">
            <span className="t">사진 {photos.length}</span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <div className="mini-thumbs">{photos.slice(0, 8).map((p) => <img key={p.url} src={p.url} alt={p.name} />)}</div>
          </div>
        ) : null}
        {plan ? (
          <div className="bsec">
            <span className="t">도면</span>
            <svg className="plan-svg" viewBox="0 0 160 100" role="img" aria-label={`${plan.ko} 평면`} dangerouslySetInnerHTML={{ __html: plan.svg }} />
          </div>
        ) : S.plan?.url ? (
          <div className="bsec">
            <span className="t">도면</span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={S.plan.url} alt="올린 도면" style={{ borderRadius: 8 }} />
          </div>
        ) : null}
        <div className="bsec">
          <span className="t">{cats.length ? `고른 자재 ${picked}/${cats.length}` : "고른 자재"}</span>
          {cats.length ? <div className="swatches">{cats.map((c) => <Swatch key={c.id} c={c} />)}</div> : <p className="empty">자재를 고르면 견본이 쌓여요.</p>}
        </div>
        <div className="bsec bsec-tools">
          <span className="t">도구</span>
          <div className="row">
            <button type="button" className="btn btn-sm" onClick={go(() => F.calcStep())}>셀프 계산기</button>
            <button type="button" className="btn btn-sm" onClick={go(() => F.checkStep())}>체크리스트</button>
            <button type="button" className="btn btn-sm pp9-tool" onClick={go(() => F.planQtyTool?.())}>도면으로 수량</button>
          </div>
        </div>
      </aside>
    </>
  );
}

/** 좁은 화면 대화 아래 띠: 누르면 보드가 열린다 */
export function BoardBand() {
  useV2();
  const st = styleOf(S.style);
  const fs = facts();
  const cats = S.far >= 5 ? scopeCats() : [];
  const picked = cats.filter((c) => S.picks[c.id]).length;
  return (
    <button type="button" className="board-band" onClick={() => boardUi.setOpen(true)}>
      <b>내 집 보드</b>
      <span className="muted num">{cats.length ? `${picked}/${cats.length}` : fs.length ? `${fs.length}개` : ""}</span>
      {st ? <span className="pal">{st.pal.map((c) => <span key={c} style={{ background: c }} />)}</span> : null}
    </button>
  );
}
