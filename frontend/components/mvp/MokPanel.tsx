"use client";
// 등급 · 목공 자재 고르기. 문 · 천장 몰딩 · 걸레받이만 자재를 고르고, 나머지 목공은 정해진 단가 항목에 수량만 넣는다.
import type { MvpMaterials, MvpMokSel } from "@/lib/api/mvp";
import { won } from "@/lib/format";
import { DOOR_MODES, GRADES, MOLDING_TYPES, type DoorMode, type Grade, type MoldingType } from "./labels";
import s from "./mvp.module.css";

type Product = MvpMaterials["products"][number];

function Seg<K extends string>({ label, items, value, onPick }: { label: string; items: { key: K; label: string; desc?: string }[]; value: K; onPick: (k: K) => void }) {
  return (
    <div className={s.seg} role="group" aria-label={label}>
      {items.map((i) => (
        <button key={i.key} type="button" aria-pressed={value === i.key} onClick={() => onPick(i.key)}>
          <b>{i.label}</b>
          {i.desc ? <span className="mj-small">{i.desc}</span> : null}
        </button>
      ))}
    </div>
  );
}

function Pick({ id, label, items, value, onPick }: { id: string; label: string; items: Product[]; value: string | null | undefined; onPick: (v: string) => void }) {
  return (
    <div className="mj-field">
      <label className="mj-label" htmlFor={id}>{label}</label>
      <select id={id} className="mj-select" value={value ?? ""} onChange={(e) => onPick(e.target.value)}>
        {items.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} · {won(p.price)}
          </option>
        ))}
      </select>
    </div>
  );
}

function Count({ id, label, value, onChange, placeholder }: { id: string; label: string; value: number | null | undefined; onChange: (v: number | null) => void; placeholder?: string }) {
  return (
    <div className="mj-field">
      <label className="mj-label" htmlFor={id}>{label}</label>
      <input
        id={id}
        className={`mj-input ${s.num}`}
        type="number"
        inputMode="numeric"
        min={0}
        max={30}
        placeholder={placeholder}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Math.max(0, Math.min(30, Math.round(Number(e.target.value)))))}
      />
    </div>
  );
}

export function MokPanel({
  materials,
  grade,
  onGrade,
  sel,
  onSel,
  hasMokgong,
}: {
  materials: MvpMaterials;
  grade: Grade;
  onGrade: (g: Grade) => void;
  sel: MvpMokSel;
  onSel: (f: (prev: MvpMokSel) => MvpMokSel) => void;
  hasMokgong: boolean;
}) {
  const of = (kind: string, type?: string) => materials.products.filter((p) => p.kind === kind && (type === undefined || p.type === type));
  const door = sel.door ?? { mode: "none", pick: null, count: null };
  const mode = (door.mode ?? "none") as DoorMode;
  const doorItems = mode === "replace" ? of("door_set") : of("door_leaf");
  const moldingType = (sel.molding_type ?? "none") as MoldingType;
  const extras = sel.extras ?? {};
  const groups = [...new Set(materials.extras.map((x) => x.group))];

  function setDoorMode(m: DoorMode) {
    const g = materials.grades[grade];
    onSel((p) => ({ ...p, door: { ...door, mode: m, pick: m === "none" ? null : m === "replace" ? g.door_set : g.leaf } }));
  }
  function setMoldingType(t: MoldingType) {
    onSel((p) => ({ ...p, molding_type: t, molding: t === "none" ? null : of("molding", t)[0]?.id ?? null }));
  }
  function setExtra(key: string, v: boolean | number | null) {
    onSel((p) => {
      const next = { ...p.extras };
      if (v === null || v === false) delete next[key];
      else next[key] = v;
      return { ...p, extras: next };
    });
  }

  return (
    <section className={s.card} aria-labelledby="mvp-mok-t">
      <h2 id="mvp-mok-t" className="mj-h2">2. 등급 · 자재 고르기</h2>
      <Seg label="등급" items={GRADES} value={grade} onPick={onGrade} />
      <p className="mj-small">등급을 바꾸면 그 등급에 흔한 몰딩 · 걸레받이 · 문 자재로 다시 골라요. 바꿀 것만 아래에서 바꿔 주세요.</p>

      {hasMokgong ? (
        <>
          <h3 className="mj-h3">방문</h3>
          <Seg label="방문 작업" items={DOOR_MODES} value={mode} onPick={setDoorMode} />
          {mode !== "none" ? (
            <div className={s.pair}>
              <Pick id="mvp-door" label={mode === "replace" ? "문틀 + 문짝 세트" : "문짝"} items={doorItems} value={door.pick} onPick={(v) => onSel((p) => ({ ...p, door: { ...door, pick: v } }))} />
              <Count id="mvp-door-n" label="방문 수" placeholder="비우면 자동" value={door.count} onChange={(v) => onSel((p) => ({ ...p, door: { ...door, count: v } }))} />
            </div>
          ) : null}
          <div className={s.pair}>
            <Count id="mvp-slide" label="슬라이딩 도어 수" value={sel.slide?.n ?? 0} onChange={(v) => onSel((p) => ({ ...p, slide: { ...p.slide, n: v ?? 0 } }))} />
            <Count id="mvp-hidden" label="히든도어 수" value={sel.hidden?.n ?? 0} onChange={(v) => onSel((p) => ({ ...p, hidden: { ...p.hidden, n: v ?? 0 } }))} />
          </div>

          <h3 className="mj-h3">천장 몰딩</h3>
          <Seg label="몰딩 종류" items={MOLDING_TYPES} value={moldingType} onPick={setMoldingType} />
          {moldingType !== "none" ? (
            <Pick id="mvp-molding" label="몰딩 자재" items={of("molding", moldingType)} value={sel.molding} onPick={(v) => onSel((p) => ({ ...p, molding: v }))} />
          ) : null}

          <h3 className="mj-h3">걸레받이</h3>
          <div className="mj-field">
            <label className="mj-label" htmlFor="mvp-base">걸레받이 자재</label>
            <select id="mvp-base" className="mj-select" value={sel.base ?? ""} onChange={(e) => onSel((p) => ({ ...p, base: e.target.value || null }))}>
              <option value="">안 함</option>
              {of("base").map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {won(p.price)}
                </option>
              ))}
            </select>
          </div>

          <details className={s.more}>
            <summary>
              그 밖의 목공 (정해진 단가){Object.keys(extras).length ? ` · ${Object.keys(extras).length}개 고름` : ""}
            </summary>
            {groups.map((g) => (
              <fieldset key={g} className={s.extras}>
                <legend className="mj-label">{g}</legend>
                {materials.extras
                  .filter((x) => x.group === g)
                  .map((x) =>
                    x.auto ? (
                      <label key={x.key} className={s.check}>
                        <input type="checkbox" checked={extras[x.key] === true} onChange={(e) => setExtra(x.key, e.target.checked)} />
                        <span>
                          {x.ko} <span className="mj-small">· {won(x.price)}/{x.unit} · 수량은 {x.auto === "ceiling" ? "천장 넓이로" : "창 폭으로"} 자동</span>
                        </span>
                      </label>
                    ) : (
                      <div key={x.key} className={s.extraRow}>
                        <label htmlFor={`mvp-x-${x.key}`}>
                          {x.ko} <span className="mj-small">· {won(x.price)}/{x.unit}</span>
                        </label>
                        <input
                          id={`mvp-x-${x.key}`}
                          className={`mj-input ${s.num}`}
                          type="number"
                          inputMode="decimal"
                          min={0}
                          step={x.unit === "개소" ? 1 : 0.1}
                          placeholder={x.unit}
                          value={typeof extras[x.key] === "number" ? (extras[x.key] as number) : ""}
                          onChange={(e) => setExtra(x.key, e.target.value === "" ? null : Math.max(0, Math.min(10000, Math.round(Number(e.target.value) * 10) / 10)))}
                        />
                      </div>
                    ),
                  )}
              </fieldset>
            ))}
          </details>
        </>
      ) : (
        <p className="mj-small">이 공사는 목공을 고르지 않아서 도배만 계산해요.</p>
      )}
    </section>
  );
}
