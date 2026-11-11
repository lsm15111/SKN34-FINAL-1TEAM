"use client";
// 목공 패널 (v10 mok10Panel · mok10Card): 문 · 천장 몰딩 · 걸레받이 자재 고르기 + 정해진 가격 항목.
// 고른 값은 S.mok10에만 둔다. 길이 · 자동 수량 · 소계는 견적 API(/mvp/v2/quote)의 정밀 목공 결과를 그대로 보인다.
import { useEffect, useRef, type ComponentProps } from "react";
import { matSrcs, Photo } from "@/components/v2/photo";
import { DATA, type MokSt, S, useV2 } from "@/components/v2/store";
import { openSheet } from "./Sheets";
import {
  dataName,
  DOOR_MODES,
  loadMok,
  MOK,
  mok10AutoDoors,
  mok10DefaultPick,
  mok10Doors,
  mok10Set,
  mok10St,
  MOLDING_TYPES,
  mokQuote,
  mokQuoteBody,
  type MokExtra,
  type QLine,
  requestMokQuote,
} from "./state";

const won10 = (n: number | string | null | undefined) => (n == null ? "—" : Number(n).toLocaleString("ko-KR") + "원");
const BASIS10: Record<string, string> = { public: "공공", market: "실견적", pick: "자재", assumed: "팀 가정값" };
const perOf = (kind: string, len: string | number | null) => (kind === "door_set" || kind === "door_leaf" ? "짝" : kind === "slide" || kind === "hidden" ? "세트" : `${len}m 1개`);

/** 숫자 칸: 바꾼 값을 다 넣은 뒤(change)에만 알린다 (v10 onchange와 같게) */
function NumIn({ value, onCommit, ...rest }: { value: number | string | null; onCommit: (v: string) => void } & Omit<ComponentProps<"input">, "value" | "onChange">) {
  const ref = useRef<HTMLInputElement>(null);
  const cb = useRef(onCommit);
  const cur = useRef(value);
  useEffect(() => {
    cb.current = onCommit;
    cur.current = value;
    const el = ref.current;
    if (el && document.activeElement !== el) el.value = value == null ? "" : String(value);
  });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const f = () => {
      cb.current(el.value);
      requestAnimationFrame(() => {
        el.value = cur.current == null ? "" : String(cur.current);
      });
    };
    el.addEventListener("change", f);
    return () => el.removeEventListener("change", f);
  }, []);
  return <input ref={ref} type="number" defaultValue={value ?? ""} {...rest} />;
}

function MokCard({ id, on, onPick, label }: { id: string; on: boolean; onPick: () => void; label?: string }) {
  const m = DATA.materials.find((x) => x.id === id);
  const p = MOK.prod[id];
  if (!m || !p) return null;
  return (
    <div
      className="mcard mk-card"
      role="button"
      tabIndex={0}
      aria-pressed={on}
      aria-label={`${m.name} ${won10(p.price)} ${on ? "고름" : "고르기"}`}
      onClick={onPick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onPick();
        }
      }}
    >
      <Photo srcs={matSrcs(m)} alt={m.name}>
        <span className="sel" aria-hidden="true">✓</span>
      </Photo>
      <div className="in">
        <span className="brand">{m.brand}</span>
        <span className="nm">{m.name}</span>
        <div className="meta">
          <span className="price">{won10(p.price)}</span>
          <span className="flag">{label || `/ ${perOf(p.kind, p.len_m)}`}</span>
        </div>
        <div className="meta">
          <span className="flag">{p.why}</span>
          <button
            type="button"
            className="btn-text"
            style={{ minHeight: 40 }}
            onClick={(e) => {
              e.stopPropagation();
              openSheet(m);
            }}
          >
            자세히
          </button>
        </div>
      </div>
    </div>
  );
}

function Seg<K extends string>({ items, cur, on, label }: { items: [K, string][]; cur: K; on: (k: K) => void; label: string }) {
  return (
    <div className="seg mk-seg" role="group" aria-label={label}>
      {items.map(([k, ko]) => (
        <button key={k} type="button" aria-pressed={cur === k} onClick={() => on(k)}>{ko}</button>
      ))}
    </div>
  );
}

const idsOf = (kind: string, type?: string) => (MOK.data?.products || []).filter((p) => p.kind === kind && (type == null || p.type === type)).map((p) => p.id);

export function MokPanel() {
  useV2();
  const q = mokQuote.use();
  const ready = !!MOK.data;
  useEffect(() => {
    if (!MOK.data && !MOK.err) loadMok();
  }, []);
  const key = ready ? JSON.stringify(mokQuoteBody()) : "";
  useEffect(() => {
    if (key) requestMokQuote();
  }, [key]);

  if (!ready)
    return (
      <div className="mat-body mk" role="tabpanel">
        <p className="muted mk-lead">{MOK.err ? "목공 자재를 불러오지 못했어요. 잠시 뒤 다시 열어 주세요." : "목공 자재를 불러오는 중이에요…"}</p>
      </div>
    );

  const s = mok10St();
  const data = q.key === key ? q.data : null;
  const r = data?.precise.find((t) => t.trade === "mokgong") || null;
  const line = (k: string): QLine | undefined => r?.lines.find((l) => l.key === k);
  const pl = data?.inp.measured ?? null;
  /** 길이 글: 도면이면 도면에서 잰 둘레, 아니면 견적 API 목공 줄의 수량 · 근거 */
  const len = (k: "molding" | "base") => {
    if (pl) return `길이 ${pl[k === "molding" ? "molding_m" : "base_m"]}m · 도면에서 잰 둘레`;
    const l = line(k);
    return l ? `길이 약 ${l.qty}m · ${l.calc}` : q.err && q.key === key ? "길이를 계산하지 못했어요" : "길이 계산 중이에요…";
  };
  const fromPlan = S.plan?.kind === "apt";

  /* 문 */
  const ad = mok10AutoDoors();
  const doorBody =
    s.door.mode === "none" ? null : (
      <div className="mk-sub">
        <div className="mgrid">
          {idsOf(s.door.mode === "replace" ? "door_set" : "door_leaf").map((id) => (
            <MokCard key={id} id={id} on={s.door.pick === id} onPick={() => mok10Set((x) => void (x.door.pick = id))} label="/ 짝" />
          ))}
        </div>
        <div className="mk-row">
          <label className="chk">
            방문
            <NumIn
              className="inp sm"
              min="0"
              max="12"
              value={mok10Doors()}
              aria-label="방문 개수"
              onCommit={(v) => mok10Set((x) => void (x.door.count = Math.max(0, Math.min(12, Math.round(+v || 0)))))}
            />
            개
          </label>
          <small className="muted">
            {s.door.count == null ? ad.how : `처음 값 ${ad.n}개(${ad.how})`}
            {s.door.count != null ? (
              <button type="button" className="btn-text" onClick={() => mok10Set((x) => void (x.door.count = null))}>처음 값으로</button>
            ) : null}
          </small>
        </div>
        <p className="muted mk-note">
          {s.door.mode === "leaf" ? "문짝만 바꾸고 문틀 · 문선은 그대로 둬요. 손잡이는 기본으로 넣어요." : "문선(문 둘레 테두리)과 손잡이는 기본 자재 · 정해진 가격으로 함께 넣어요."}
        </p>
      </div>
    );
  const extraDoor = (k: "slide" | "hidden", ko: string) => {
    const x = s[k], p = x.pick ? MOK.prod[x.pick] : undefined;
    return (
      <label className="chk mk-extra-door">
        {ko}
        <NumIn
          className="inp sm"
          min="0"
          max="6"
          value={x.n}
          aria-label={`${ko} 개수`}
          onCommit={(v) => mok10Set((y) => void (y[k].n = Math.max(0, Math.min(6, Math.round(+v || 0)))))}
        />
        개
        <small className="muted">{` · ${dataName(x.pick)} ${won10(p?.price)}/세트`}</small>
      </label>
    );
  };

  /* 천장 몰딩 */
  const moldBody =
    s.molding.type === "none" ? null : (
      <div className="mk-sub">
        <div className="mgrid">
          {idsOf("molding", s.molding.type).map((id) => (
            <MokCard key={id} id={id} on={s.molding.pick === id} onPick={() => mok10Set((x) => void (x.molding.pick = id))} />
          ))}
        </div>
        <p className="muted mk-note">
          {len("molding")}
          {s.molding.type === "minus" ? " · 무몰딩은 석고 마감 손이 더 가서 시공 단가를 2배로 잡았어요." : ""}
        </p>
      </div>
    );

  /* 걸레받이 */
  const baseBody = (
    <div className="mk-sub">
      <div className="mgrid">
        {idsOf("base").map((id) => (
          <MokCard key={id} id={id} on={s.base.pick === id} onPick={() => mok10Set((x) => void (x.base.pick = x.base.pick === id ? null : id))} />
        ))}
      </div>
      <p className="muted mk-note">{s.base.pick ? len("base") : "걸레받이를 하지 않아요. 고르려면 자재를 눌러 주세요."}</p>
    </div>
  );

  /* 정해진 가격 항목 */
  const extras = MOK.data?.extras || [];
  const groups = [...new Set(extras.map((x) => x.group))];
  const nOn = extras.filter((x) => s.extras[x.key] != null && s.extras[x.key] !== false).length;
  /** 자동 수량을 쓸 수 있나: 천장은 늘(도면 또는 전용면적), 창 폭은 도면을 골랐을 때만 */
  const hasAuto = (x: MokExtra) => x.auto === "ceiling" || (x.auto === "windows" && fromPlan);
  const exRow = (x: MokExtra) => {
    const v = s.extras[x.key], on = v != null && v !== false;
    const qty = on ? (v === true ? (line(x.key)?.qty ?? "") : v) : "";
    return (
      <li key={x.key} className={"mk-ex" + (on ? " on" : "")}>
        <label className="chk">
          <input
            type="checkbox"
            checked={on}
            onChange={(e) =>
              mok10Set((y) => {
                if (e.target.checked) y.extras[x.key] = hasAuto(x) ? true : x.unit === "개소" ? 1 : 0;
                else delete y.extras[x.key];
              })
            }
          />
          <span><b>{x.ko}</b><small>{x.what}</small></span>
        </label>
        <span className="mk-ex-q">
          <NumIn
            className="inp sm"
            min="0"
            step={x.unit === "개소" ? "1" : "0.1"}
            value={qty as number | string}
            aria-label={`${x.ko} 수량(${x.unit})`}
            disabled={!on}
            onCommit={(val) => mok10Set((y) => void (y.extras[x.key] = Math.max(0, +val || 0)))}
          />
          <small>{x.unit}</small>
          {on && v === true ? <small className="muted">{x.auto === "ceiling" ? (fromPlan ? " 도면 천장" : " 전용면적") : " 도면 창 폭"}</small> : null}
        </span>
        <span className="mk-ex-p">
          <b className="num">{`${won10(x.price)}/${x.unit}`}</b>
          <small className={"basis b-" + x.basis} title={x.src}>{BASIS10[x.basis]}</small>
        </span>
      </li>
    );
  };

  /* 소계(견적 API 결과) */
  const sum = r ? (
    <>
      <span>목공 예상 (공공 기준 · 부가세 별도)</span>
      <b className="num">{won10(r.supply)}</b>
      <small>{`부가세 포함 ${won10(r.total)} · 품 ${r.man_days} · 약 ${r.days}일`}</small>
    </>
  ) : data ? (
    <span className="muted">고른 목공이 없어요.</span>
  ) : (
    <span className="muted">{q.err && q.key === key ? "목공 금액을 계산하지 못했어요. 잠시 뒤 다시 해 주세요." : "목공 금액을 계산하는 중이에요…"}</span>
  );

  const setMode = (k: MokSt["door"]["mode"]) =>
    mok10Set((x) => {
      x.door.mode = k;
      if (k !== "none") {
        const want = k === "replace" ? "door_set" : "door_leaf";
        if (!x.door.pick || MOK.prod[x.door.pick]?.kind !== want) x.door.pick = mok10DefaultPick(k);
      }
    });
  const setMold = (k: MokSt["molding"]["type"]) =>
    mok10Set((x) => {
      x.molding.type = k;
      if (k !== "none" && (!x.molding.pick || MOK.prod[x.molding.pick]?.type !== k)) x.molding.pick = idsOf("molding", k)[0] ?? null;
    });

  return (
    <div className="mat-body mk" role="tabpanel">
      <p className="muted mk-lead">문 · 천장 몰딩 · 걸레받이만 자재를 골라요. 나머지 목공은 정해진 가격으로 계산해요.</p>
      <section className="mk-sec">
        <h4>문<small>방문 · 욕실문</small></h4>
        <Seg items={DOOR_MODES} cur={s.door.mode} on={setMode} label="문 작업 방식" />
        {doorBody}
        <div className="mk-row">
          {extraDoor("slide", "슬라이딩 도어")}
          {extraDoor("hidden", "히든도어")}
        </div>
      </section>
      <section className="mk-sec">
        <h4>천장 몰딩<small>천장과 벽이 만나는 곳</small></h4>
        <Seg items={MOLDING_TYPES} cur={s.molding.type} on={setMold} label="천장 몰딩 종류" />
        {moldBody}
      </section>
      <section className="mk-sec">
        <h4>걸레받이<small>벽 아래 마감</small></h4>
        {baseBody}
      </section>
      <details className="mk-sec mk-extras" open={nOn > 0 || undefined}>
        <summary><b>그 밖의 목공 · 정해진 가격</b><small>{nOn ? `${nOn}개 넣음` : "필요한 것만 체크"}</small></summary>
        {groups.map((g) => (
          <div key={g} className="mk-grp">
            <h5>{g}</h5>
            <ul>{extras.filter((x) => x.group === g).map(exRow)}</ul>
          </div>
        ))}
        <p className="muted mk-note">단가 근거: 공공 = 표준시장단가 2026 하반기, 실견적 = 2025~2026 실견적 줄별 내역, 팀 가정값 = 공개 단가가 없어 팀이 정한 값(이름에 마우스를 올리면 근거가 보여요).</p>
      </details>
      <div className="mk-sum">{sum}</div>
    </div>
  );
}
