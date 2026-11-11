"use client";
// 자재 자세히 · 표로 비교 겹창 (v10 openSheet · openCompare). 가격은 자재 판매가를 글로 보일 뿐이다.
import { type ReactNode, type RefObject, useEffect, useRef } from "react";
import { CAT, type Material, priceText, TIERS } from "@/components/v2/data";
import { F, openOverlay } from "@/components/v2/engine";
import { matOf } from "@/components/v2/flow";
import { matSrcs, Photo } from "@/components/v2/photo";
import { DATA, S, useV2 } from "@/components/v2/store";
import { selectMat, toggleCmp } from "./actions";
import { CMP } from "./state";

type MatMore = Material & { pop_note?: string; pop_src?: string };
const optText = (m: Material) => (typeof m.options === "string" && m.options ? m.options : null);

/** 겹창 공통: 바탕을 누르거나 Esc면 닫고, 열리면 닫기 단추로 포커스 */
function Sheet({ close, label, cls = "sheet", children, x }: { close: () => void; label: string; cls?: string; children: ReactNode; x: RefObject<HTMLButtonElement | null> }) {
  useEffect(() => {
    x.current?.focus();
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [close, x]);
  return (
    <div
      className="sheet-bg"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className={cls} role="dialog" aria-modal="true" aria-label={label}>
        {children}
      </div>
    </div>
  );
}

function MatSheet({ m, close }: { m: MatMore; close: () => void }) {
  useV2();
  const x = useRef<HTMLButtonElement>(null);
  const on = S.picks[m.cat] === m.id;
  const inC = (CMP[m.cat] || []).includes(m.id);
  const credit = [m.img_free_credit ? `무료 사진 ${m.img_free_credit}` : null, m.img_mfg ? `제조사 사진 ${m.brand}` : null, m.img_ai ? "AI 이미지는 참고용" : null].filter(Boolean).join(" · ");
  const opt = optText(m);
  return (
    <Sheet close={close} label={m.name} x={x}>
      <Photo srcs={matSrcs(m)} alt={m.name} />
      <div className="in">
        <button ref={x} type="button" className="x" aria-label="닫기" onClick={close}>×</button>
        <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, color: "var(--ink-mute)" }}>
          <span className={`tier tier-${m.tier}`}>{TIERS[m.tier]}</span>
          {`${CAT[m.cat].ko} · ${m.brand}`}
        </div>
        <h3>{m.name}</h3>
        <p className="pv">{priceText(m.price)}</p>
        {(m.tags || []).length ? <div className="tags">{m.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div> : null}
        {m.trend_note || m.pop_note ? (
          <ul className="proof">
            {m.trend_note ? (
              <li>
                <b>인기 근거</b> {m.trend_note}
                {m.trend_src ? <> <a href={m.trend_src} target="_blank" rel="noopener">기사</a></> : null}
              </li>
            ) : null}
            {m.pop_note ? (
              <li>
                <b>많이 쓰는 근거</b> {m.pop_note}
                {m.pop_src ? <> <a href={m.pop_src} target="_blank" rel="noopener">기사</a></> : null}
              </li>
            ) : null}
          </ul>
        ) : null}
        {m.desc ? <p>{m.desc}</p> : null}
        {m.spec ? <p className="spec">{m.spec}</p> : null}
        {opt || m.life || m.rank ? (
          <dl className="facts">
            {opt ? <><dt>선택지</dt><dd>{opt}</dd></> : null}
            {m.life ? <><dt>수명 · 보증</dt><dd>{m.life}</dd></> : null}
            {m.rank ? <><dt>많이 쓰는 순</dt><dd>{`${CAT[m.cat].ko} ${DATA.materials.filter((v) => v.cat === m.cat).length}개 중 ${m.rank}위`}</dd></> : null}
          </dl>
        ) : null}
        <dl className="gw">
          {m.good ? <div><dt>좋을 때</dt><dd>{m.good}</dd></div> : null}
          {m.watch ? <div><dt>주의</dt><dd>{m.watch}</dd></div> : null}
        </dl>
        <div className="row" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
          <button
            type="button"
            className={on ? "btn" : "btn btn-pri"}
            onClick={() => {
              selectMat(m);
              close();
            }}
          >
            {on ? "고른 자재예요" : "이걸로 할게요"}
          </button>
          <button type="button" className="btn" aria-pressed={inC} onClick={() => toggleCmp(m)}>
            {inC ? "비교에서 빼기" : "비교에 담기"}
          </button>
          {m.url ? <a className="btn" href={m.url} target="_blank" rel="noopener">제품 페이지</a> : null}
        </div>
        <button
          type="button"
          className="btn-text"
          style={{ justifySelf: "start" }}
          onClick={() => {
            close();
            F.askAboutMat(m);
          }}
        >
          <span className="spark" aria-hidden="true">✦</span>우리 집에 괜찮을까요?
        </button>
        <p className="src">
          {[m.price?.note, m.price?.checked ? `확인 ${m.price.checked}` : null].filter(Boolean).join(" · ")}
          {m.price?.source ? <> · <a href={m.price.source} target="_blank" rel="noopener">가격 출처</a></> : null}
        </p>
        {credit ? <p className="src">{credit}</p> : null}
      </div>
    </Sheet>
  );
}

export function openSheet(m: Material) {
  openOverlay((close) => <MatSheet m={m} close={close} />);
}

const ROWS: [string, (m: Material) => ReactNode][] = [
  ["가격", (m) => priceText(m.price)],
  ["등급", (m) => <span className={`tier tier-${m.tier}`}>{TIERS[m.tier]}</span>],
  ["꼬리표", (m) => (m.tags || []).join(" · ") || "—"],
  ["많이 쓰는 순", (m) => (m.rank ? `${m.rank}위` : "—")],
  ["규격", (m) => m.spec || "—"],
  ["선택지", (m) => optText(m) || "—"],
  ["수명 · 보증", (m) => m.life || "—"],
  ["좋을 때", (m) => m.good || "—"],
  ["주의", (m) => m.watch || "—"],
];

function CompareSheet({ ms, close }: { ms: Material[]; close: () => void }) {
  useV2();
  const x = useRef<HTMLButtonElement>(null);
  const title = `${CAT[ms[0].cat].ko} 비교`;
  return (
    <Sheet close={close} label={title} cls="sheet cmp" x={x}>
      <div className="cmp-head">
        <h3>{title}</h3>
        <button ref={x} type="button" className="x" aria-label="닫기" onClick={close}>×</button>
      </div>
      <div className="cmp-scroll">
        <table>
          <thead>
            <tr>
              <th />
              {ms.map((m) => (
                <th key={m.id} scope="col">
                  <Photo srcs={matSrcs(m)} alt={m.name} />
                  <span className="brand">{m.brand}</span>
                  <b>{m.name}</b>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([k, f]) => (
              <tr key={k}>
                <th scope="row">{k}</th>
                {ms.map((m) => <td key={m.id}>{f(m)}</td>)}
              </tr>
            ))}
            <tr>
              <th />
              {ms.map((m) => {
                const on = S.picks[m.cat] === m.id;
                return (
                  <td key={m.id}>
                    <button
                      type="button"
                      className={on ? "btn btn-sm" : "btn btn-pri btn-sm"}
                      onClick={() => {
                        selectMat(m);
                        close();
                      }}
                    >
                      {on ? "고른 자재" : "이걸로"}
                    </button>
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
    </Sheet>
  );
}

export function openCompare(ids: string[]) {
  const ms = ids.map((id) => matOf(id)).filter(Boolean) as Material[];
  if (ms.length < 2) return;
  openOverlay((close) => <CompareSheet ms={ms} close={close} />);
}
