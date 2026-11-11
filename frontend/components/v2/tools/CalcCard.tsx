"use client";
// 셀프 계산기 카드 (v10 ROLLS · numIn · calcCard). 수량은 백엔드(CALC7)가 계산하고 여기서는 보여 주기만 한다.
import { type ReactNode, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { CALC7 } from "./calc7";

type Kind = "wall" | "trim" | "paint";
const ROLLS: Record<string, { ko: string; w: number; len: number }> = {
  hapji: { ko: "합지 (폭 0.53m · 길이 12.5m)", w: 0.53, len: 12.5 },
  silk: { ko: "실크 (폭 1.06m · 길이 15.6m)", w: 1.06, len: 15.6 },
};
const KINDS: [Kind, string][] = [["wall", "벽지 롤"], ["trim", "몰딩 · 걸레받이"], ["paint", "페인트"]];

type Field = [key: string, label: string, val: number, step?: string];
const FIELDS: Record<Kind, Field[]> = {
  wall: [["w", "가로(m)", 3.6, "0.1"], ["d", "세로(m)", 3.0, "0.1"], ["hgt", "높이(m)", 2.3, "0.1"], ["doors", "문(개)", 1], ["windows", "창문(개)", 1], ["repeat", "무늬 반복(cm)", 0], ["loss", "여유분(%)", 10]],
  trim: [["w", "가로(m)", 3.6, "0.1"], ["d", "세로(m)", 3.0, "0.1"], ["doors", "문(개)", 1], ["pieceLen", "자재 길이(m)", 2.4, "0.1"], ["loss", "여유분(%)", 10]],
  paint: [["w", "가로(m)", 3.6, "0.1"], ["d", "세로(m)", 3.0, "0.1"], ["hgt", "높이(m)", 2.3, "0.1"], ["doors", "문(개)", 1], ["windows", "창문(개)", 1], ["coats", "칠 횟수", 2], ["cover", "1L당 면적(㎡)", 10, "0.5"]],
};

function CalcBody({ kind, setOut }: { kind: Kind; setOut: (n: ReactNode) => void }) {
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(FIELDS[kind].map(([k, , v]) => [k, String(v)])));
  const [type, setType] = useState("hapji");
  const [ceil, setCeil] = useState(false);
  const [wait, setWait] = useState(false);
  const v = (k: string) => Math.max(0, +vals[k] || 0);
  const run = async () => {
    setWait(true);
    try {
      if (kind === "wall") {
        const r = ROLLS[type], ce = ceil;
        const x = await CALC7.wallpaper({ w: v("w"), d: v("d"), hgt: v("hgt") || 2.3, doors: v("doors"), windows: v("windows"), ceiling: ce, rollW: r.w, rollLen: r.len, repeat: v("repeat"), loss: v("loss") });
        setOut(
          <>
            <p className="c7-big">{`${x.rolls}롤`}</p>
            <p className="muted">{`벽 ${x.wall_m2}㎡ · 벽 ${x.strips}폭${ce ? ` · 천장 ${x.cStrips}폭` : ""} · 한 롤에 ${x.per_roll}폭 · 여유분 포함`}</p>
          </>,
        );
      } else if (kind === "trim") {
        const x = await CALC7.trim({ w: v("w"), d: v("d"), doors: v("doors"), pieceLen: v("pieceLen") || 2.4, loss: v("loss") });
        setOut(
          <>
            <p className="c7-big">{`몰딩 ${x.molding_pcs}개 · 걸레받이 ${x.base_pcs}개`}</p>
            <p className="muted">{`천장 둘레 ${x.molding_m}m · 걸레받이 ${x.base_m}m(문 폭 0.9m씩 뺌) · 여유분 포함`}</p>
          </>,
        );
      } else {
        const x = await CALC7.paint({ w: v("w"), d: v("d"), hgt: v("hgt") || 2.3, doors: v("doors"), windows: v("windows"), ceiling: ceil, coats: v("coats") || 2, cover: v("cover") || 10 });
        setOut(
          <>
            <p className="c7-big">{`${x.liters}L`}</p>
            <p className="muted">{`칠할 면적 ${x.area_m2}㎡ · ${[x.n18 ? `18L ${x.n18}통` : "", x.n4 ? `4L ${x.n4}통` : ""].filter(Boolean).join(" + ") || "4L 1통"}`}</p>
          </>,
        );
      }
    } catch (e) {
      setOut(<p className="muted">{errorText(e)}</p>);
    } finally {
      setWait(false);
    }
  };
  return (
    <>
      <div className="form-grid c7-grid">
        {FIELDS[kind].map(([k, label, , step]) => (
          <label className="fld" key={k}>
            <span>{label}</span>
            <input className="inp sm" type="number" inputMode="decimal" step={step} value={vals[k]} onChange={(e) => setVals((o) => ({ ...o, [k]: e.target.value }))} />
          </label>
        ))}
        {kind === "wall" ? (
          <label className="fld">
            <span>벽지 종류</span>
            <select className="sort" aria-label="벽지 종류" value={type} onChange={(e) => setType(e.target.value)}>
              {Object.entries(ROLLS).map(([k, r]) => <option key={k} value={k}>{r.ko}</option>)}
            </select>
          </label>
        ) : null}
      </div>
      {kind !== "trim" ? (
        <label className="chk">
          <input type="checkbox" checked={ceil} onChange={(e) => setCeil(e.target.checked)} />
          {kind === "wall" ? "천장도 바르기" : "천장도 칠하기"}
        </label>
      ) : null}
      <button type="button" className="btn btn-pri btn-sm" disabled={wait} onClick={run}>계산하기</button>
    </>
  );
}

export function CalcCard({ kind: first = "wall" }: { kind?: Kind }) {
  const [kind, setKind] = useState<Kind>(first);
  const [out, setOut] = useState<ReactNode>(null);
  return (
    <div className="card c7">
      <div>
        <h3>셀프 계산기</h3>
        <p className="muted">방 하나 기준이에요. 문 1.8㎡ · 창문 1.5㎡를 빼고 계산해요.</p>
      </div>
      <div className="seg" role="group" aria-label="계산기">
        {KINDS.map(([k, l]) => (
          <button
            key={k}
            type="button"
            aria-pressed={k === kind}
            onClick={() => {
              setKind(k);
              setOut(null);
            }}
          >
            {l}
          </button>
        ))}
      </div>
      <div className="c7-body">
        <CalcBody key={kind} kind={kind} setOut={setOut} />
      </div>
      <div className="c7-out" aria-live="polite">{out}</div>
      <p className="muted">참고용이에요. 벽지 · 페인트 규격과 1L당 면적은 제품 라벨을 확인해 바꿔 넣으세요.</p>
    </div>
  );
}
