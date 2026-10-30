"use client";
// 견적 받기 질문 흐름 (기본정보 → 공간 · 공정).
// 한 화면에 질문 하나. 고르기만 해서는 넘어가지 않고 '다음'을 눌러야 넘어간다(입력만으로 화면이 바뀌지 않게).
// 답은 브라우저에 자동 저장되고, 다시 열면 묻지 않고 이어서 보여 준다. 프로젝트를 만들면 지운다.
// 만들기: 로그인 확인 → 사진 · 도면을 POST /files로 하나씩 올림 → POST /projects. 실패하면 답과 사진은 그대로 남는다.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { SIDO, regionLabel } from "@/lib/mock/regions";
import { eulReul, md, todaySeoul } from "@/lib/format";
import { ApiError, call, errorText, type Schemas } from "@/lib/backend/client";
import { BUDGETS, DOBAE_GRADES, MOK_ITEMS, type DobaeGrade } from "@/lib/labels";
import { DateCalendar } from "./DateCalendar";
import { PhotoDrop, toPhotos, type Photo } from "./PhotoDrop";
import { PHOTO_MEMO, clearPhotoMemo, readDraft, writeDraft } from "./draft";

type Step = "region" | "house" | "size" | "when" | "living" | "budget" | "trades" | "dobae" | "mokgong" | "photos" | "plan" | "review";
type Size = "10" | "20" | "30" | "40" | "50" | "manual";
type Answers = {
  sido?: string; sgg?: string;
  house?: "apt"; builtYear: string;
  size?: Size; manualBasis?: "supply" | "jeon"; manualM2: string; balconyExt: boolean;
  when?: "date" | "movein" | "months" | "unknown"; whenDate: string; whenEnd: string; occupied?: "yes" | "no"; budget?: string;
  trades: { dobae: boolean; mokgong: boolean };
  dobae: { spaces: string[]; grade?: DobaeGrade };
  mokgong: { spaces: string[]; items: string[] };
  spaces: Space[];
};
type Space = { id: string; name: string; custom?: boolean };
const EMPTY: Answers = {
  builtYear: "", manualM2: "", balconyExt: false, whenDate: "", whenEnd: "",
  trades: { dobae: false, mokgong: false }, dobae: { spaces: [] }, mokgong: { spaces: [], items: [] },
  spaces: [],
};
const QUICK_SPACES = ["방", "주방", "거실", "현관"];
const PHOTO_TYPES = "image/jpeg,image/png,image/webp,image/heic"; // API가 받는 형식 (backend/app/files/service.py)

const HOUSES = [
  { v: "apt", t: "아파트", ready: true },
  { v: "villa", t: "빌라 · 연립", ready: false },
  { v: "house", t: "단독주택", ready: false },
  { v: "officetel", t: "오피스텔", ready: false },
] as const;
const SIZES: { v: Size; t: string }[] = [
  { v: "10", t: "10평대" }, { v: "20", t: "20평대" }, { v: "30", t: "30평대" }, { v: "40", t: "40평대" }, { v: "50", t: "50평 이상" },
];
const WHEN = [
  { v: "date", t: "날짜가 정해졌어요", d: "시작하는 날과 끝나는 날을 골라요" },
  { v: "movein", t: "이사하는 날만 정해졌어요", d: "잔금일 · 입주일 전에 끝나게 맞춰요" },
  { v: "months", t: "1~2달 안에", d: "업체 일정에 맞춰 정해요" },
  { v: "unknown", t: "아직 몰라요", d: "견적부터 받아 볼게요" },
] as const;
// 저장된 답은 화면 말로 두고, 보낼 때 API 코드값으로 바꾼다 (예전 임시 저장과 맞추려고).
const BUDGET = BUDGETS.map((b) => b.label);

/** 답 → POST /projects 본문. 공정에 고른 공간만 보낸다. */
function toRequest(a: Answers, picked: Space[], photoIds: { space: string; file_id: string }[], planIds: string[]): Schemas["ProjectCreate"] {
  const dated = a.when === "date" || a.when === "movein";
  return {
    sido: a.sido!, sgg: a.sgg!, house_type: "apt",
    built_year: a.builtYear ? Number(a.builtYear) : null,
    size: a.size === "manual" ? { basis: a.manualBasis === "jeon" ? "exclusive" : "supply", m2: a.manualM2 } : { band: a.size as "10" | "20" | "30" | "40" | "50" },
    balcony_ext: a.balconyExt,
    when: { kind: a.when!, start: dated ? a.whenDate : null, end: a.when === "date" && a.whenEnd ? a.whenEnd : null },
    occupied: a.occupied === "yes",
    budget: BUDGETS.find((b) => b.label === a.budget)?.key ?? null,
    spaces: picked.map((sp) => ({ key: sp.id, name: sp.name })),
    trades: {
      dobae: a.trades.dobae ? { spaces: a.dobae.spaces, grade: a.dobae.grade! } : null,
      mokgong: a.trades.mokgong ? { spaces: a.mokgong.spaces, items: a.mokgong.items.map((v) => MOK_ITEMS.find((m) => m.label === v)!.key) } : null,
    },
    photos: photoIds,
    plans: planIds,
  };
}

// 같은 이름이 있으면 번호를 붙인다: 주방 → 주방 2, 방 1 · 방 2 → 방 3
function nextName(base: string, names: string[]) {
  const root = base.trim().replace(/\s*\d+$/, "");
  const esc = root.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const family = names.filter((n) => n === root || new RegExp(`^${esc} \\d+$`).test(n));
  if (!family.length && !names.includes(base.trim())) return base.trim();
  let k = family.length + 1;
  while (names.includes(`${root} ${k}`)) k++;
  return `${root} ${k}`;
}


// mode: page는 /start 화면, dialog는 헤더 '견적 받기' 버튼이 띄우는 창.
export function Wizard({ mode = "page", onClose }: { mode?: "page" | "dialog"; onClose?: () => void }) {
  const dialog = mode === "dialog";
  const router = useRouter();
  const [a, setA] = useState<Answers>(EMPTY);
  const [stepId, setStepId] = useState<Step>("region");
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const h1 = useRef<HTMLHeadingElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const moved = useRef(false);
  const [photos, setPhotos] = useState<Record<string, Photo[]>>(() => PHOTO_MEMO.bySpace);
  const [plan, setPlan] = useState<Photo[]>(() => PHOTO_MEMO.plan);
  const [photoSpace, setPhotoSpace] = useState<string>();
  const [newSpace, setNewSpace] = useState("");
  const [spaceMsg, setSpaceMsg] = useState("");
  const [sending, setSending] = useState<string | null>(null); // 만드는 중 안내. 있으면 버튼을 막는다
  const [today] = useState(todaySeoul);
  const thisYear = Number(today.slice(0, 4));

  useEffect(() => {
    const d = readDraft();
    if (d) { const saved = d.a as Partial<Answers>; setA({ ...EMPTY, ...saved, spaces: saved.spaces?.length ? saved.spaces : EMPTY.spaces }); setStepId(d.step as Step); }
    setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    writeDraft(a.sido ? { a, step: stepId } : null);
  }, [a, stepId, ready]);
  useEffect(() => { PHOTO_MEMO.bySpace = photos; PHOTO_MEMO.plan = plan; }, [photos, plan]);
  // 사진 칸 밖에 떨어뜨려도 브라우저가 사진을 열며 화면을 떠나지 않게 막는다.
  useEffect(() => {
    if (stepId !== "photos" && stepId !== "plan") return;
    const stop = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  }, [stepId]);
  // 질문이 바뀌면 제목으로 초점을 옮긴다. 창으로 열 때는 처음부터 제목에 둔다.
  useEffect(() => {
    if (!ready) return;
    if (moved.current || dialog) h1.current?.focus();
    moved.current = true;
  }, [stepId, ready, dialog]);

  const sido = SIDO.find((s) => s.id === a.sido);
  const spaces = a.spaces;
  // 지금 고른 공정에 들어간 공간만 (공정을 껐다면 그 공정의 공간은 뺀다)
  const picked = spaces.filter((sp) => (a.trades.dobae && a.dobae.spaces.includes(sp.id)) || (a.trades.mokgong && a.mokgong.spaces.includes(sp.id)));
  const steps: Step[] = ["region", "house", "size", "when", "living", "budget", "trades", ...(a.trades.dobae ? ["dobae" as Step] : []), ...(a.trades.mokgong ? ["mokgong" as Step] : []), "photos", "plan", "review"];
  const idx = Math.max(0, steps.indexOf(stepId));
  const set = (p: Partial<Answers>) => { setA((x) => ({ ...x, ...p })); setError(null); };

  function validate(s: Step): string | null {
    if (s === "region" && !a.sido) return "시 · 도를 골라 주세요.";
    if (s === "region" && !a.sgg) return "시 · 군 · 구를 골라 주세요.";
    if (s === "house" && !a.house) return "집 종류를 골라 주세요.";
    if (s === "house" && a.builtYear && !(Number(a.builtYear) >= 1960 && Number(a.builtYear) <= thisYear)) return "준공 연도를 4자리로 적어 주세요. 예: 2009";
    if (s === "size" && !a.size) return "평수를 골라 주세요. 대략 골라도 돼요.";
    if (s === "size" && a.size === "manual" && !a.manualBasis) return "공급면적인지 전용면적인지 골라 주세요.";
    if (s === "size" && a.size === "manual" && !(Number(a.manualM2) > 10 && Number(a.manualM2) < 400)) return "면적을 ㎡로 적어 주세요. 소수점은 한 자리까지예요. 예: 84.9";
    if (s === "when" && !a.when) return "공사 시기를 골라 주세요. 모르면 ‘아직 몰라요’를 고르세요.";
    if (s === "when" && a.when === "date" && !a.whenDate) return "시작하는 날을 골라 주세요.";
    if (s === "when" && a.when === "movein" && !a.whenDate) return "이사하는 날을 골라 주세요.";
    if (s === "living" && !a.occupied) return "공사할 때 집 상태를 골라 주세요.";
    if (s === "trades" && !a.trades.dobae && !a.trades.mokgong) return "공정을 하나 이상 골라 주세요.";
    if (s === "dobae" && !a.dobae.spaces.length) return a.spaces.length ? "도배할 공간을 하나 이상 골라 주세요." : "도배할 공간을 하나 이상 넣어 주세요.";
    if (s === "dobae" && !a.dobae.grade) return "도배 유형을 골라 주세요.";
    if (s === "mokgong" && (!a.mokgong.spaces.length || !a.mokgong.items.length)) return !a.mokgong.spaces.length ? (a.spaces.length ? "목공할 공간을 하나 이상 골라 주세요." : "목공할 공간을 하나 이상 넣어 주세요.") : "목공 항목을 하나 이상 골라 주세요.";
    return null;
  }
  function go(to: Step) {
    setError(null);
    setStepId(to);
    if (dialog) body.current?.scrollTo({ top: 0 }); else window.scrollTo({ top: 0 });
  }
  function next(e?: React.FormEvent) {
    e?.preventDefault();
    const err = validate(stepId);
    if (err) {
      setError(err);
      const dateMissing = stepId === "when" && (a.when === "date" || a.when === "movein") && !a.whenDate;
      setTimeout(() => (form.current?.querySelector(dateMissing ? ".mj-cal button[tabindex=\"0\"]" : "[data-first]") as HTMLElement | null)?.focus(), 0);
      return;
    }
    if (stepId === "review") { if (!sending) void finish(); return; }
    go(steps[idx + 1]);
  }
  function addSpace(base: string, t: "dobae" | "mokgong") {
    if (!base.trim()) return;
    const name = nextName(base, spaces.map((x) => x.name));
    const id = `sp-${Date.now().toString(36)}`;
    set({ spaces: [...spaces, { id, name, custom: true }], [t]: { ...a[t], spaces: [...a[t].spaces, id] } } as Partial<Answers>);
    setSpaceMsg(`${eulReul(name)} 넣고 골랐어요.`);
    setNewSpace("");
  }
  function removeSpace(id: string) {
    const sp = spaces.find((x) => x.id === id);
    set({ spaces: spaces.filter((x) => x.id !== id), dobae: { ...a.dobae, spaces: a.dobae.spaces.filter((x) => x !== id) }, mokgong: { ...a.mokgong, spaces: a.mokgong.spaces.filter((x) => x !== id) } });
    (photos[id] ?? []).forEach((ph) => URL.revokeObjectURL(ph.url));
    setPhotos((m) => { const n = { ...m }; delete n[id]; return n; });
    setSpaceMsg(`${eulReul(sp?.name ?? "공간")} 뺐어요.`);
  }
  async function finish() {
    setError(null);
    // 1. 로그인 확인. 안 했으면 답은 그대로 두고 로그인 뒤 이 화면으로 돌아온다.
    let me: Schemas["MeOut"];
    try { me = await call<Schemas["MeOut"]>("GET", "/me"); } catch (e) {
      if (e instanceof ApiError && e.status === 401) { router.push(`/login?next=${encodeURIComponent("/start")}`); onClose?.(); return; }
      setError(errorText(e)); return;
    }
    if (me.role !== "customer") { setError("일반 회원으로 로그인해야 프로젝트를 만들 수 있어요."); return; }

    // 2. 사진 · 도면 올리기. 이미 올린 것은 다시 올리지 않는다(다시 누를 때).
    const jobs = [
      ...picked.flatMap((sp) => (photos[sp.id] ?? []).map((ph) => ({ ph, kind: "photo" as const, space: sp.id }))),
      ...plan.map((ph) => ({ ph, kind: "plan" as const, space: "" })),
    ];
    const photoIds: { space: string; file_id: string }[] = [];
    const planIds: string[] = [];
    for (const [i, j] of jobs.entries()) {
      setSending(`사진 · 도면을 올리고 있어요 (${i + 1}/${jobs.length})`);
      let fid = PHOTO_MEMO.uploaded[j.ph.id];
      if (!fid) {
        const fd = new FormData();
        fd.append("kind", j.kind);
        fd.append("file", j.ph.file, j.ph.name);
        try { fid = (await call<Schemas["FileOut"]>("POST", "/files", fd)).id; } catch (e) {
          setSending(null); setError(`${j.ph.name}: ${errorText(e)}`); return;
        }
        PHOTO_MEMO.uploaded[j.ph.id] = fid;
      }
      if (j.kind === "photo") photoIds.push({ space: j.space, file_id: fid }); else planIds.push(fid);
    }

    // 3. 프로젝트 만들기
    setSending("프로젝트를 만들고 있어요");
    try {
      const p = await call<Schemas["ProjectOut"]>("POST", "/projects", toRequest(a, picked, photoIds, planIds));
      writeDraft(null);
      clearPhotoMemo();
      router.push(`/projects/${p.id}`);
      router.refresh();
      onClose?.();
    } catch (e) {
      setSending(null);
      setError(errorText(e));
    }
  }

  // 페이지에서는 main으로 감싸고, 창에서는 그대로 둔다(창 뒤 화면에 이미 main이 있다).
  const wrap = (node: React.ReactNode) => (dialog ? node : <main id="main" className="mj-wrap mj-main">{node}</main>);
  const cardClass = dialog ? "mj-wiz" : "mj-wiz mj-wiz-card";
  const closeBtn = dialog ? (
    <button type="button" className="mj-wiz-x" onClick={onClose} aria-label="닫기">
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 20 20"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
    </button>
  ) : null;

  if (!ready) return wrap(<div className={cardClass} aria-busy="true"><div className="mj-wiz-body"><p className="mj-sub">불러오는 중이에요…</p></div></div>);

  const Q = ({ title, sub, optional }: { title: string; sub?: string; optional?: boolean }) => (
    <legend style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14, padding: 0 }}>
      <h1 ref={h1} tabIndex={-1} className="mj-h1">{title}{optional ? <span className="mj-opt"> (선택)</span> : null}</h1>
      {sub ? <span className="mj-sub">{sub}</span> : null}
    </legend>
  );
  const err = error ? <p id="step-err" className="mj-error" role="alert">{error}</p> : null;
  const dateErr = !!error && stepId === "when" && (a.when === "date" || a.when === "movein") && !a.whenDate;
  const desc = error ? "step-err" : undefined;
  const optional = stepId === "budget" || stepId === "photos" || stepId === "plan";
  const tradeSpaces = (t: "dobae" | "mokgong") => a[t].spaces;
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const sizeText = a.size === "manual" ? `${a.manualBasis === "supply" ? "공급" : "전용"} ${a.manualM2}㎡` : SIZES.find((s) => s.v === a.size)?.t ?? "";

  const summary: { label: string; value: string; step: Step }[] = [];
  if (a.sido && a.sgg) summary.push({ label: "지역", value: regionLabel(a.sido, a.sgg), step: "region" });
  if (a.house) summary.push({ label: "집 종류", value: `아파트${a.builtYear ? ` · ${a.builtYear}년 준공` : ""}`, step: "house" });
  if (a.size) summary.push({ label: "평수", value: `${sizeText}${a.balconyExt ? " · 발코니 확장" : ""}`, step: "size" });
  if (a.when) summary.push({ label: "시기", value: `${WHEN.find((w) => w.v === a.when)?.t}${a.when === "date" && a.whenDate ? ` · ${md(a.whenDate)}${a.whenEnd && a.whenEnd !== a.whenDate ? ` ~ ${md(a.whenEnd)}` : ""}` : a.when === "movein" && a.whenDate ? ` · ${md(a.whenDate)}` : ""}`, step: "when" });
  if (a.occupied) summary.push({ label: "집 상태", value: a.occupied === "yes" ? "살면서 공사" : "빈집", step: "living" });
  if (a.budget) summary.push({ label: "예산", value: a.budget, step: "budget" });
  if (a.trades.dobae || a.trades.mokgong) summary.push({ label: "공정", value: [a.trades.dobae && "도배", a.trades.mokgong && "목공"].filter(Boolean).join(" · "), step: "trades" });
  if (a.trades.dobae && a.dobae.spaces.length) summary.push({ label: "도배", value: [DOBAE_GRADES.find((g) => g.key === a.dobae.grade)?.label, ...a.dobae.spaces.map((id) => spaces.find((x) => x.id === id)?.name)].filter(Boolean).join(" · "), step: "dobae" });
  if (a.trades.mokgong && a.mokgong.spaces.length) summary.push({ label: "목공", value: `${a.mokgong.spaces.map((id) => spaces.find((x) => x.id === id)?.name).filter(Boolean).join(" · ")} · ${a.mokgong.items.join(" · ")}`, step: "mokgong" });
  const photoCount = picked.reduce((n, sp) => n + (photos[sp.id]?.length ?? 0), 0);
  if (photoCount) summary.push({ label: "사진", value: `${photoCount}장`, step: "photos" });
  if (plan.length) summary.push({ label: "도면", value: `${plan.length}개`, step: "plan" });

  return wrap(
    <form ref={form} className={cardClass} onSubmit={next} noValidate>
      <div className="mj-wiz-head">
        <div className="mj-progress" style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: "var(--fs-sm)" }}>
            <span className="mj-sub">견적 받기</span>
            <span className="mj-num" aria-live="polite"><b>{idx + 1}</b> / {steps.length}<span className="mj-sr">번째 질문</span></span>
          </div>
          <div className="mj-progress-bar" role="progressbar" aria-label="질문 진행" aria-valuemin={1} aria-valuemax={steps.length} aria-valuenow={idx + 1}><span style={{ width: `${((idx + 1) / steps.length) * 100}%` }} /></div>
        </div>
        {closeBtn}
      </div>

      <div className="mj-wiz-body" ref={body}>
        {stepId === "region" && (
          <fieldset className="mj-fieldset" aria-describedby={desc}>
            {Q({ title: "공사할 집은 어디인가요?" })}
            <fieldset className="mj-fieldset">
              <legend className="mj-label">시 · 도</legend>
              <div className="mj-pick">
                {SIDO.map((s, i) => (
                  <label key={s.id} className="mj-pick-i">
                    <input type="radio" name="sido" checked={a.sido === s.id} onChange={() => { const only = s.groups.length === 1 && s.groups[0].items.length === 1 ? s.groups[0].items[0] : undefined; set({ sido: s.id, sgg: only }); }} data-first={!a.sido && i === 0 ? true : undefined} />
                    <span>{s.name}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            {sido && !(sido.groups.length === 1 && sido.groups[0].items.length === 1) ? (
              <fieldset className="mj-fieldset">
                <legend className="mj-label">시 · 군 · 구</legend>
                {sido.id === "jeonnam-gwangju" ? <p className="mj-small">2026년 7월 광주와 전남이 전남광주통합특별시로 합쳐졌어요.</p> : null}
                {sido.groups.map((g, gi) => (
                  <div key={g.prefix || gi} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {g.label ? <span className="mj-tiny" style={{ fontWeight: 700 }}>{g.label}</span> : null}
                    <div className="mj-pick">
                      {g.items.map((name, i) => (
                        <label key={name} className="mj-pick-i">
                          <input type="radio" name="sgg" checked={a.sgg === name} onChange={() => set({ sgg: name })} data-first={a.sido && gi === 0 && i === 0 ? true : undefined} />
                          <span>{name}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </fieldset>
            ) : null}
            {err}
          </fieldset>
        )}

        {stepId === "house" && (
          <fieldset className="mj-fieldset" aria-describedby={desc}>
            {Q({ title: "어떤 집인가요?" })}
            <div className="mj-choices mj-choices-2">
              {HOUSES.map((h, i) => (
                <label key={h.v} className="mj-choice">
                  <input type="radio" name="house" value={h.v} disabled={!h.ready} checked={h.ready && a.house === h.v} onChange={() => set({ house: "apt" })} data-first={!a.house && i === 0 ? true : undefined} />
                  <span className="mj-choice-main"><span className="mj-choice-title">{h.t}</span>{h.ready ? null : <span className="mj-choice-desc">준비 중이에요</span>}</span>
                </label>
              ))}
            </div>
            <div className="mj-field" style={{ maxWidth: 260 }}>
              <label className="mj-label" htmlFor="built">준공 연도 (선택)</label>
              <input id="built" className="mj-input mj-num" inputMode="numeric" placeholder="예: 2009" value={a.builtYear} onChange={(e) => set({ builtYear: e.target.value.replace(/\D/g, "").slice(0, 4) })} aria-invalid={error && a.builtYear ? true : undefined} aria-describedby={desc} data-first={a.house ? true : undefined} />
            </div>
            {err}
          </fieldset>
        )}

        {stepId === "size" && (
          <fieldset className="mj-fieldset" aria-describedby={desc}>
            {Q({ title: "집은 몇 평인가요?" })}
            <div className="mj-pick mj-pick-wide">
              {SIZES.map((s, i) => (
                <label key={s.v} className="mj-pick-i">
                  <input type="radio" name="size" checked={a.size === s.v} onChange={() => set({ size: s.v })} data-first={a.size !== "manual" && i === 0 ? true : undefined} />
                  <span className="mj-num">{s.t}</span>
                </label>
              ))}
              <label className="mj-pick-i">
                <input type="radio" name="size" checked={a.size === "manual"} onChange={() => set({ size: "manual" })} />
                <span>정확히 적을게요</span>
              </label>
            </div>
            {a.size === "manual" && (
              <div className="mj-panel mj-panel-tint" style={{ gap: 12 }}>
                <fieldset className="mj-fieldset">
                  <legend className="mj-label">어떤 면적인가요?</legend>
                  <div className="mj-choices mj-choices-2">
                    {(["supply", "jeon"] as const).map((b) => (
                      <label key={b} className="mj-choice"><input type="radio" name="basis" checked={a.manualBasis === b} onChange={() => set({ manualBasis: b })} data-first={!a.manualBasis && b === "supply" ? true : undefined} /><span className="mj-choice-main"><span className="mj-choice-title">{b === "supply" ? "공급면적 (평형)" : "전용면적 (실평수)"}</span></span></label>
                    ))}
                  </div>
                </fieldset>
                <div className="mj-field" style={{ maxWidth: 260 }}>
                  <label className="mj-label" htmlFor="m2">면적 (㎡)</label>
                  <input id="m2" className="mj-input mj-num" inputMode="decimal" data-first={a.manualBasis ? true : undefined} value={a.manualM2} onChange={(e) => set({ manualM2: e.target.value.replace(/[^\d.]/g, "").replace(/^(\d*\.?\d?).*$/, "$1") })} aria-invalid={error ? true : undefined} aria-describedby={desc} />
                </div>
              </div>
            )}
            <label className="mj-choice"><input type="checkbox" checked={a.balconyExt} onChange={(e) => set({ balconyExt: e.target.checked })} /><span className="mj-choice-main"><span className="mj-choice-title">발코니를 확장했어요</span></span></label>
            {err}
          </fieldset>
        )}

        {stepId === "when" && (
          <fieldset className="mj-fieldset" aria-describedby={desc}>
            {Q({ title: "언제쯤 공사하고 싶으세요?" })}
            <div className="mj-choices">
              {WHEN.map((w, i) => {
                const open = a.when === w.v && (w.v === "date" || w.v === "movein");
                return (
                  <div key={w.v} style={{ display: "contents" }}>
                    <label className="mj-choice"><input type="radio" name="when" checked={a.when === w.v} onChange={() => set({ when: w.v })} aria-controls={w.v === "date" || w.v === "movein" ? `when-${w.v}` : undefined} data-first={!a.when && i === 0 ? true : undefined} /><span className="mj-choice-main"><span className="mj-choice-title">{w.t}</span><span className="mj-choice-desc">{w.d}</span></span></label>
                    {open ? (
                      <div id={`when-${w.v}`} className="mj-reveal">
                        {w.v === "date"
                          ? <DateCalendar range value={{ from: a.whenDate, to: a.whenEnd }} onChange={(r) => set({ whenDate: r.from, whenEnd: r.to })} today={today} label="시작하는 날과 끝나는 날" />
                          : <DateCalendar value={a.whenDate} onChange={(v) => set({ whenDate: v, whenEnd: "" })} today={today} label="이사하는 날" />}
                        {a.whenDate ? <span className="mj-small" aria-live="polite">고른 날: <b>{md(a.whenDate)}{w.v === "date" && a.whenEnd && a.whenEnd !== a.whenDate ? ` ~ ${md(a.whenEnd)}` : ""}</b></span> : null}
                        {dateErr ? err : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            {dateErr ? null : err}
          </fieldset>
        )}

        {stepId === "living" && (
          <fieldset className="mj-fieldset" aria-describedby={desc}>
            {Q({ title: "공사할 때 집은 어떤가요?" })}
            <div className="mj-choices">
              <label className="mj-choice"><input type="radio" name="occ" checked={a.occupied === "yes"} onChange={() => set({ occupied: "yes" })} data-first /><span className="mj-choice-main"><span className="mj-choice-title">살면서 공사해요</span><span className="mj-choice-desc">짐을 방마다 옮기며 진행해요</span></span></label>
              <label className="mj-choice"><input type="radio" name="occ" checked={a.occupied === "no"} onChange={() => set({ occupied: "no" })} /><span className="mj-choice-main"><span className="mj-choice-title">빈집이에요</span><span className="mj-choice-desc">이사 전이거나 짐을 모두 뺐어요</span></span></label>
            </div>
            {err}
          </fieldset>
        )}

        {stepId === "budget" && (
          <fieldset className="mj-fieldset">
            {Q({ title: "생각하는 예산이 있나요?", optional: true })}
            <div className="mj-choices mj-choices-2">
              {BUDGET.map((b, i) => (
                <label key={b} className="mj-choice"><input type="radio" name="budget" checked={a.budget === b} onChange={() => set({ budget: b })} data-first={i === 0 ? true : undefined} /><span className="mj-choice-main"><span className="mj-choice-title mj-num">{b}</span></span></label>
              ))}
            </div>
          </fieldset>
        )}

        {stepId === "trades" && (
          <fieldset className="mj-fieldset" aria-describedby={desc}>
            {Q({ title: "어떤 공사가 필요한가요?" })}
            <div className="mj-choices mj-choices-2">
              <label className="mj-choice"><input type="checkbox" checked={a.trades.dobae} onChange={(e) => set({ trades: { ...a.trades, dobae: e.target.checked } })} data-first /><span className="mj-choice-main"><span className="mj-choice-title">도배</span><span className="mj-choice-desc">벽지 · 천장지</span></span></label>
              <label className="mj-choice"><input type="checkbox" checked={a.trades.mokgong} onChange={(e) => set({ trades: { ...a.trades, mokgong: e.target.checked } })} /><span className="mj-choice-main"><span className="mj-choice-title">목공</span><span className="mj-choice-desc">몰딩 · 걸레받이 · 문 · 천장</span></span></label>
            </div>
            {err}
          </fieldset>
        )}

        {(stepId === "dobae" || stepId === "mokgong") && (() => {
          const t = stepId;
          const sel = tradeSpaces(t);
          return (
            <fieldset className="mj-fieldset" aria-describedby={desc}>
              {Q({ title: t === "dobae" ? "도배할 공간과 유형을 골라 주세요" : "목공할 공간과 항목을 골라 주세요" })}
              <fieldset className="mj-fieldset">
                <legend className="mj-label">공간</legend>
                <div className="mj-btn-row" style={{ gap: 8 }}>
                  {QUICK_SPACES.map((q, i) => <button key={q} type="button" className="mj-btn mj-btn-sec mj-btn-sm" onClick={() => addSpace(q, t)} data-first={!spaces.length && i === 0 ? true : undefined}>+ {q}</button>)}
                </div>
                <div className="mj-space-add">
                  <label className="mj-label" htmlFor={`add-${t}`}>공간 추가</label>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input id={`add-${t}`} className="mj-input" style={{ flex: 1, minWidth: 0 }} placeholder="직접 적기 · 예: 복도" value={newSpace} maxLength={20} onChange={(e) => setNewSpace(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSpace(newSpace, t); } }} />
                    <button type="button" className="mj-btn mj-btn-sec" onClick={() => addSpace(newSpace, t)} disabled={!newSpace.trim()}>추가</button>
                  </div>
                </div>
                <p className="mj-sr" aria-live="polite">{spaceMsg}</p>
                {spaces.length ? (
                  <div className="mj-choices mj-choices-2" role="group" aria-label={t === "dobae" ? "도배할 공간" : "목공할 공간"}>
                    {spaces.map((s, i) => (
                      <div key={s.id} className="mj-space">
                        <label className="mj-choice"><input type="checkbox" checked={sel.includes(s.id)} onChange={() => set({ [t]: { ...a[t], spaces: toggle(sel, s.id) } } as Partial<Answers>)} data-first={!sel.length && i === 0 ? true : undefined} /><span className="mj-choice-main"><span className="mj-choice-title">{s.name}</span></span></label>
                        <button type="button" className="mj-space-x" onClick={() => removeSpace(s.id)} aria-label={`${s.name} 빼기`}><svg aria-hidden="true" width="16" height="16" viewBox="0 0 20 20"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg></button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </fieldset>
              {t === "dobae" ? (
                <fieldset className="mj-fieldset">
                  <legend className="mj-label">도배 유형</legend>
                  <div className="mj-choices mj-choices-2">
                    {DOBAE_GRADES.map((g) => (
                      <label key={g.key} className="mj-choice"><input type="radio" name="grade" checked={a.dobae.grade === g.key} onChange={() => set({ dobae: { ...a.dobae, grade: g.key } })} data-first={a.dobae.spaces.length && !a.dobae.grade && g.key === "economy" ? true : undefined} /><span className="mj-choice-main"><span className="mj-choice-title">{g.label}</span></span></label>
                    ))}
                  </div>
                </fieldset>
              ) : (
                <fieldset className="mj-fieldset">
                  <legend className="mj-label">목공 항목</legend>
                  <div className="mj-choices mj-choices-2">
                    {MOK_ITEMS.map((m) => (
                      <label key={m.key} className="mj-choice"><input type="checkbox" data-first={sel.length && !a.mokgong.items.length && m.key === "molding" ? true : undefined} checked={a.mokgong.items.includes(m.label)} onChange={() => set({ mokgong: { ...a.mokgong, items: toggle(a.mokgong.items, m.label) } })} /><span className="mj-choice-main"><span className="mj-choice-title">{m.label}</span><span className="mj-choice-desc">{m.desc}</span></span></label>
                    ))}
                  </div>
                </fieldset>
              )}
              {err}
            </fieldset>
          );
        })()}

        {stepId === "photos" && (() => {
          const active = picked.find((sp) => sp.id === photoSpace) ?? picked[0];
          return (
            <fieldset className="mj-fieldset">
              {Q({ title: "공간별 사진이 있나요?", optional: true })}
              {active ? (
                <>
                  <div className="mj-pick" role="group" aria-label="사진 넣을 공간">
                    {picked.map((sp) => (
                      <button key={sp.id} type="button" className="mj-pick-i mj-pick-btn" aria-pressed={sp.id === active.id} onClick={() => setPhotoSpace(sp.id)}>
                        {sp.name}<span className="mj-tiny mj-num" style={{ marginLeft: 4 }}>{photos[sp.id]?.length ? `${photos[sp.id].length}장` : ""}</span>
                      </button>
                    ))}
                  </div>
                  <PhotoDrop key={active.id} id={`ph-${active.id}`} label={`${active.name} 사진`} photos={photos[active.id] ?? []} accept={PHOTO_TYPES} maxMB={10} hint="여러 장 · 10장까지 · 한 장 10MB까지"
                    onAdd={(files) => setPhotos((m) => ({ ...m, [active.id]: [...(m[active.id] ?? []), ...toPhotos(files)] }))}
                    onRemove={(pid) => setPhotos((m) => { const gone = (m[active.id] ?? []).find((x) => x.id === pid); if (gone) URL.revokeObjectURL(gone.url); return { ...m, [active.id]: (m[active.id] ?? []).filter((x) => x.id !== pid) }; })} />
                </>
              ) : null}
            </fieldset>
          );
        })()}

        {stepId === "plan" && (
          <fieldset className="mj-fieldset">
            {Q({ title: "아파트 도면이 있나요?", optional: true })}
            <PhotoDrop id="plan" label="아파트 도면" photos={plan} max={5} accept={`${PHOTO_TYPES},application/pdf`} maxMB={20} hint="사진이나 PDF · 5개까지 · 하나 20MB까지"
              onAdd={(files) => setPlan((old) => [...old, ...toPhotos(files)])}
              onRemove={(pid) => setPlan((old) => { const gone = old.find((x) => x.id === pid); if (gone) URL.revokeObjectURL(gone.url); return old.filter((x) => x.id !== pid); })} />
          </fieldset>
        )}

        {stepId === "review" && (
          <fieldset className="mj-fieldset">
            {Q({ title: "이대로 프로젝트를 만들까요?" })}
            <dl className="mj-kv mj-panel" style={{ display: "grid", gap: 0 }}>
              {summary.map((r) => (
                <div key={r.label} style={{ display: "contents" }}>
                  <dt>{r.label}</dt>
                  <dd style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}><span>{r.value}</span><button type="button" className="mj-btn mj-btn-ghost mj-btn-sm" onClick={() => go(r.step)}>고치기<span className="mj-sr"> · {r.label}</span></button></dd>
                </div>
              ))}
            </dl>
            {sending ? <p className="mj-small" role="status">{sending}</p> : null}
            {err}
          </fieldset>
        )}
      </div>

      <div className="mj-wiz-foot">
        <button type="button" className="mj-btn mj-btn-sec" onClick={() => (idx > 0 ? go(steps[idx - 1]) : dialog ? onClose?.() : router.push("/"))}>{idx > 0 ? "이전" : dialog ? "닫기" : "처음으로"}</button>
        <div className="mj-btn-row">
          {optional ? <button type="button" className="mj-btn mj-btn-ghost" onClick={() => go(steps[idx + 1])}>건너뛰기</button> : null}
          <button type="submit" className="mj-btn mj-btn-pri" disabled={!!sending}>{stepId === "review" ? (sending ? "만드는 중…" : "프로젝트 만들기") : "다음"}</button>
        </div>
      </div>
    </form>
  );
}
