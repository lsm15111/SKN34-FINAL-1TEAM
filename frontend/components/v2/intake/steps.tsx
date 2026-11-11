"use client";
// 2. 집 정보 · 3. 범위 · 4. 예산 · 등급 · 5. 사진 (v10 infoStep · scopeStep · budgetStep · uploader · photoStep)
// 카드는 제출하면 done이 되어 잠긴다(v10 doneCard). 금액은 만들지 않는다: 예산은 고객이 넣은 값, 등급은 고르기만.
import { DateCalendar } from "@/components/start/DateCalendar";
import { useEffect, useId, useRef, useState } from "react";
import { flashBoard } from "../Board";
import { CATS, manwon, SPACES, TIER_NOTE, TIER_ORDER, TIERS } from "../data";
import { md, moveDay, moveLabel, todaySeoul } from "../dates";
import { bot, clearQuick, F, me } from "../engine";
import { autoPick, proceed, setStep, tierFromBudget } from "../flow";
import { type PhotoItem, S, touch, useV2 } from "../store";

/* 버튼을 누르면 아래에 달력을 펼치는 날짜 칸 (v10 dateField8). 달력은 팀 DateCalendar */
function DateField({ id, labelId, label, value, onChange, disabled }: { id: string; labelId: string; label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const set = (v: string) => {
    onChange(v);
    setOpen(false);
    setTimeout(() => btn.current?.focus(), 0);
  };
  return (
    <div
      className="df8"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          e.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <div className="df8-row">
        <button
          ref={btn}
          type="button"
          id={id}
          className="btn df8-btn"
          aria-expanded={open}
          aria-controls={id + "-cal"}
          aria-labelledby={`${labelId} ${id}`}
          disabled={disabled}
          onClick={() => setOpen(!open)}
        >
          <span className="df8-ic" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
              <rect x="2" y="3" width="12" height="11" rx="1.5" />
              <path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" />
            </svg>
          </span>
          <span className="num">{value ? md(value) : "날짜 고르기"}</span>
        </button>
        {value ? (
          <button type="button" className="btn-text df8-clear" disabled={disabled} onClick={() => set("")}>
            지우기<span className="sr">{", " + label}</span>
          </button>
        ) : null}
      </div>
      {open ? (
        <div className="df8-box" id={id + "-cal"}>
          <DateCalendar today={todaySeoul()} label={`${label} 고르기`} value={value} onChange={set} />
        </div>
      ) : null}
    </div>
  );
}

/* 2. 집 정보 */
function InfoCard() {
  const [done, setDone] = useState(false);
  const [py, setPy] = useState(S.info.pyeong != null ? String(S.info.pyeong) : "");
  const [region, setRegion] = useState(S.info.region);
  const [living, setLiving] = useState(S.info.living);
  const [move, setMove] = useState(moveDay(S.info.move));
  const [err, setErr] = useState(false);
  const pyRef = useRef<HTMLInputElement>(null);
  function submit(skip?: boolean) {
    const v = +py;
    if (!skip && py && !(v >= 10 && v <= 90)) {
      setErr(true);
      pyRef.current?.focus();
      return;
    }
    S.info = { pyeong: !skip && v ? v : S.info.pyeong, region: region.trim(), living: living || null, move };
    setDone(true);
    touch();
    flashBoard();
    me(
      skip
        ? "건너뛸게요"
        : [S.info.pyeong ? `${S.info.pyeong}평` : "", S.info.region, S.info.living === "living" ? "살면서 공사" : S.info.living === "vacant" ? "빈집" : "", S.info.move ? `${moveLabel(S.info.move)} 입주` : ""]
            .filter(Boolean)
            .join(" · ") || "다음",
    );
    proceed(() => F.scopeStep());
  }
  return (
    <form
      className={`card${done ? " done" : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="field">
        <label className="lbl" htmlFor="f-py">평형 (분양)</label>
        <div className="inp-row">
          <input ref={pyRef} className="inp" id="f-py" type="number" inputMode="numeric" min="10" max="90" placeholder="평" style={{ maxWidth: 100 }} value={py} disabled={done} onChange={(e) => setPy(e.target.value)} />
          <div className="chips">
            {[24, 32, 34, 40].map((v) => (
              <button key={v} type="button" className="chip" aria-pressed={py === String(v)} disabled={done} onClick={() => setPy(String(v))}>{`${v}평`}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="field">
        <label className="lbl" htmlFor="f-region">지역</label>
        <input className="inp" id="f-region" placeholder="예: 서울 노원구" autoComplete="address-level2" value={region} disabled={done} onChange={(e) => setRegion(e.target.value)} />
      </div>
      <div className="field">
        <span className="lbl">공사 중에</span>
        <div className="chips">
          {([["vacant", "빈집"], ["living", "살면서"]] as const).map(([v, l]) => (
            <button key={v} type="button" className="chip" aria-pressed={living === v} disabled={done} onClick={() => setLiving(v)}>{l}</button>
          ))}
        </div>
      </div>
      <div className="field">
        <span className="lbl" id="f-move-l">입주 희망</span>
        <DateField id="f-move" labelId="f-move-l" label="입주 희망" value={move} onChange={setMove} disabled={done} />
      </div>
      {err ? <p className="err">10~90평 사이로 적어 주세요.</p> : null}
      <div className="row">
        <button className="btn btn-pri" type="submit" disabled={done}>다음</button>
        <button className="btn-text gray" type="button" disabled={done} onClick={() => submit(true)}>건너뛰기</button>
      </div>
    </form>
  );
}
export async function infoStep() {
  setStep("info");
  await bot("집 정보를 알려 주세요.", <InfoCard />);
  clearQuick();
}

/* 3. 범위 */
const catsOfSpaces = (spaces: string[]) => {
  const cats = new Set(SPACES.filter((s) => spaces.includes(s.id)).flatMap((s) => s.cats));
  return CATS.filter((c) => cats.has(c.id)).map((c) => c.id);
};
function ScopeCard() {
  const [done, setDone] = useState(false);
  const [kind, setKind] = useState(S.scope.kind);
  const [spaces, setSpaces] = useState<string[]>(() => SPACES.filter((s) => S.scope.spaces.includes(s.id)).map((s) => s.id));
  const [cats, setCats] = useState<string[]>(() => (S.scope.kind === "part" ? catsOfSpaces(S.scope.spaces) : S.scope.cats));
  const [err, setErr] = useState(false);
  // v10처럼 고르는 동안 S.scope에 바로 적는다 (보드는 [다음]에서 다시 그림)
  useEffect(() => {
    if (done) return;
    S.scope.kind = kind;
    S.scope.spaces = kind === "part" ? spaces : [];
    S.scope.cats = kind === "part" ? cats : [];
  }, [kind, spaces, cats, done]);
  const shown = catsOfSpaces(spaces);
  const sync = (next: string[]) => {
    const on = SPACES.filter((s) => next.includes(s.id)).map((s) => s.id);
    setSpaces(on);
    setCats(catsOfSpaces(on));
  };
  return (
    <div className={`card${done ? " done" : ""}`}>
      <div className="chips" role="group" aria-label="공사 범위">
        {([["all", "집 전체"], ["part", "일부만"]] as const).map(([k, l]) => (
          <button
            key={k}
            type="button"
            className="chip"
            aria-pressed={kind === k}
            disabled={done}
            onClick={() => {
              setKind(k);
              if (k === "part") sync(spaces);
            }}
          >
            {l}
          </button>
        ))}
      </div>
      {kind === "part" ? (
        <div className="chips">
          {SPACES.map((sp) => (
            <button
              key={sp.id}
              type="button"
              className="chip"
              aria-pressed={spaces.includes(sp.id)}
              disabled={done}
              onClick={() => sync(spaces.includes(sp.id) ? spaces.filter((x) => x !== sp.id) : [...spaces, sp.id])}
            >
              {sp.ko}
            </button>
          ))}
        </div>
      ) : null}
      {kind === "part" && spaces.length ? (
        <div className="chips">
          {CATS.filter((c) => shown.includes(c.id)).map((c) => (
            <button
              key={c.id}
              type="button"
              className="chip"
              aria-pressed={cats.includes(c.id)}
              disabled={done}
              onClick={() => setCats(cats.includes(c.id) ? cats.filter((x) => x !== c.id) : [...new Set([...cats, c.id])])}
            >
              {c.ko}
            </button>
          ))}
        </div>
      ) : null}
      {err ? <p className="err">범위를 골라 주세요.</p> : null}
      <div className="row">
        <button
          className="btn btn-pri"
          type="button"
          disabled={done}
          onClick={() => {
            if (!kind || (kind === "part" && !cats.length)) {
              setErr(true);
              return;
            }
            Object.assign(S.scope, { kind, spaces: kind === "part" ? spaces : [], cats: kind === "part" ? cats : [] });
            setDone(true);
            touch();
            flashBoard();
            me(kind === "all" ? "집 전체" : S.scope.spaces.map((s) => SPACES.find((x) => x.id === s)?.ko).join(", "));
            proceed(() => F.budgetStep());
          }}
        >
          다음
        </button>
      </div>
    </div>
  );
}
export async function scopeStep() {
  setStep("scope");
  if (S.scope.kind === "part") S.scope.cats = catsOfSpaces(S.scope.spaces);
  await bot("어디까지 할까요?", <ScopeCard />);
}

/* 4. 예산 · 등급 */
/** 예산 값을 넣고 등급을 맞춘다 (v10 upd). 고객이 등급을 직접 골랐으면 그대로 둔다 */
function applyBudget(v: number) {
  S.budget = v;
  S.budgetUnknown = false;
  const t = tierFromBudget();
  if (S.tierBy !== "me") S.tier = t;
  return t;
}
const clampBudget = (raw: string) => Math.max(100, Math.min(30000, +raw || 0));
function BudgetCard({ tier0, start }: { tier0: string; start: number }) {
  useV2();
  const [done, setDone] = useState(false);
  const [num, setNum] = useState(String(start));
  const [range, setRange] = useState(String(start));
  const [rec, setRec] = useState(() => tierFromBudget());
  const upd = (raw: string, fromNum: boolean) => {
    const v = clampBudget(raw);
    if (fromNum) {
      setNum(raw);
      setRange(String(Math.min(15000, v)));
    } else {
      setRange(raw);
      setNum(String(v));
    }
    setRec(applyBudget(v));
  };
  const finish = (unknown: boolean) => {
    if (unknown) {
      S.budgetUnknown = true;
      S.budget = null;
      if (S.tierBy !== "me") S.tier = "basic";
    }
    if (S.tier !== tier0 && S.far >= 5) autoPick();
    setDone(true);
    touch();
    flashBoard();
    me(unknown ? `예산 미정 · ${TIERS[S.tier]}` : `${manwon(S.budget ?? 0)} · ${TIERS[S.tier]}`);
    proceed(() => F.photoStep());
  };
  return (
    <div className={`card${done ? " done" : ""}`}>
      <div className="field">
        <span className="lbl">총 예산</span>
        <div className="budget-row">
          <input className="inp" id="f-budget-n" type="number" inputMode="numeric" min="100" max="30000" step="100" aria-label="예산(만 원)" value={num} disabled={done} onChange={(e) => upd(e.target.value, true)} />
          <span>만 원</span>
        </div>
        <input className="range" id="f-budget" type="range" min="500" max="15000" step="100" aria-label="예산" value={range} disabled={done} onChange={(e) => upd(e.target.value, false)} />
        <div className="chips">
          {[3000, 5000, 8000, 10000].map((v) => (
            <button key={v} type="button" className="chip" disabled={done} onClick={() => upd(String(v), false)}>{manwon(v).replace(" 원", "")}</button>
          ))}
        </div>
      </div>
      <div className="field">
        <span className="lbl">자재 등급</span>
        <div className="tier-pick" role="group" aria-label="자재 등급">
          {TIER_ORDER.map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={S.tier === t}
              disabled={done}
              onClick={() => {
                S.tier = t;
                S.tierBy = "me";
                touch();
              }}
            >
              {t === rec ? <span className="rec">추천</span> : null}
              <b>{TIERS[t]}</b>
              <small>{TIER_NOTE[t]}</small>
            </button>
          ))}
        </div>
        <p className="muted">{`${S.info.pyeong || 32}평 기준이에요.`}</p>
      </div>
      <div className="row">
        <button className="btn btn-pri" type="button" disabled={done} onClick={() => finish(false)}>다음</button>
        <button className="btn-text gray" type="button" disabled={done} onClick={() => finish(true)}>아직 몰라요</button>
      </div>
    </div>
  );
}
export async function budgetStep() {
  setStep("budget");
  const tier0 = S.tier;
  const start = S.budget || (S.scope.kind === "part" ? 2000 : 5000);
  applyBudget(clampBudget(String(start)));
  await bot("예산은 어느 정도예요?", <BudgetCard tier0={tier0} start={start} />);
}

/* 5. 사진 (이 브라우저에만 둔다. 서버로 보내지 않음) */
function Uploader({ list, label, disabled }: { list: PhotoItem[]; label: string; disabled?: boolean }) {
  useV2();
  const id = "up-" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [over, setOver] = useState(false);
  const add = (files: FileList | null) => {
    for (const f of Array.from(files || [])) if (f.type.startsWith("image/") && list.length < 12) list.push({ name: f.name, url: URL.createObjectURL(f), file: f });
    touch();
  };
  return (
    <div
      className={`drop${over ? " over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) add(e.dataTransfer.files);
      }}
    >
      <b>{label}</b>
      <label className="btn btn-sm" htmlFor={id}>사진 올리기</label>
      <input
        type="file"
        id={id}
        accept="image/*"
        multiple
        className="sr"
        disabled={disabled}
        onChange={(e) => {
          add(e.target.files);
          e.target.value = "";
        }}
      />
      <div className="thumbs">
        {list.map((p, i) => (
          <div className="t" key={p.url}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={p.url} alt={p.name} />
            <button
              type="button"
              aria-label={p.name + " 빼기"}
              disabled={disabled}
              onClick={() => {
                URL.revokeObjectURL(p.url);
                list.splice(i, 1);
                touch();
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
function PhotoCard() {
  useV2();
  const [done, setDone] = useState(false);
  const has = !!(S.photos.length || S.refs.length);
  return (
    <div className={`card${done ? " done" : ""}`}>
      <div className="drops">
        <Uploader list={S.photos} label="지금 우리 집" disabled={done} />
        <Uploader list={S.refs} label="마음에 드는 사진" disabled={done} />
      </div>
      <div className="row">
        <button
          className="btn btn-pri"
          type="button"
          disabled={done}
          onClick={() => {
            setDone(true);
            me(S.photos.length + S.refs.length ? `사진 ${S.photos.length + S.refs.length}장` : "다음");
            proceed(() => F.planStep());
          }}
        >
          다음
        </button>
        <button
          className="btn-text gray"
          type="button"
          disabled={done}
          onClick={() => {
            setDone(true);
            me("건너뛸게요");
            proceed(() => F.planStep());
          }}
        >
          건너뛰기
        </button>
        {has ? (
          <button type="button" className="btn-text" disabled={done} onClick={() => F.askPhotos()}>
            <span className="spark" aria-hidden="true">✦</span>사진 보고 조언 받기
          </button>
        ) : null}
      </div>
    </div>
  );
}
export async function photoStep() {
  setStep("photo");
  await bot("사진이 있으면 올려 주세요.", <PhotoCard />);
}
