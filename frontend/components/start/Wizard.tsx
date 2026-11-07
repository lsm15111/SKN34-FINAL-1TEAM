"use client";
// 견적 받기 (시안 WWizard): 왼쪽 목차 + 긴 폼 한 장 + 오른쪽 요약. 좁은 화면에서는 한 줄로 쌓는다.
// 새로 만들기: 답은 브라우저에 자동 저장한다(draft.ts). 로그인 전이면 저장하고 가입으로 보냈다가, 돌아오면 이어서 계산한다.
// 고치기(project가 있을 때): 그 프로젝트 값을 채우고 PATCH로 저장한다. 브라우저 초안은 건드리지 않는다. 실측을 요청했으면 막는다.
// 계산하기: 사진 · 도면을 POST /files로 하나씩 올림 → POST(고치기는 PATCH) /projects → 표준견적서로 간다.
// 오류는 칸 아래에만 보인다. 처음 누른 뒤부터는 고칠 때마다 다시 확인한다.
// 시연 고객(demo)이면 맨 위에 '예시 값 채우기'가 보인다. 시연 데이터(app/demo.py)와 같은 집이다.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FieldError } from "@/components/auth/parts";
import type { ApiProject, Region } from "@/lib/api/project";
import { ApiError, call, errorText, type Schemas } from "@/lib/backend/client";
import { BUDGETS, DOBAE_GRADES, MOK_ITEMS, WHEN_LABEL, type Budget, type DobaeGrade, type MokItem } from "@/lib/labels";
import { eulReul, md, stampSeoul } from "@/lib/format";
import type { Role } from "@/lib/types";
import { DateCalendar } from "./DateCalendar";
import { PhotoDrop, toPhotos, type Photo } from "./PhotoDrop";
import { PHOTO_MEMO, clearPhotoMemo, readDraft, writeDraft } from "./draft";
import s from "./Wizard.module.css";

type Band = "10" | "20" | "30" | "40" | "50";
type When = "date" | "movein" | "months" | "unknown";
type Space = { id: string; name: string; custom?: boolean };
// size: 평형대("10"~"50") 또는 "manual"(㎡로 적음). 쓰던 요청서 카드(draft.ts draftLine)가 같은 이름을 읽는다.
type Answers = {
  sido?: string; sgg?: string; builtYear: string;
  bandMode: boolean; size?: Band | "manual"; manualBasis?: "supply" | "jeon"; manualM2: string; balconyExt: boolean;
  occupied?: "yes" | "no";
  trades: { dobae: boolean; mokgong: boolean }; grade?: DobaeGrade; items: MokItem[];
  spaces: Space[]; picked: string[];
  when?: When; whenDate: string; whenEnd: string; budget: Budget;
};
type Key = "region" | "area" | "basis" | "band" | "year" | "live" | "trades" | "grade" | "items" | "spaces" | "when" | "photos" | "form";
type Errs = Partial<Record<Key, string>>;

const DEFAULT_SPACES: Space[] = ["거실", "주방", "안방", "작은방 1", "작은방 2", "복도"].map((name, i) => ({ id: `sp-d${i}`, name }));
const EMPTY: Answers = {
  builtYear: "", bandMode: false, manualM2: "", balconyExt: false,
  trades: { dobae: false, mokgong: false }, items: [], spaces: DEFAULT_SPACES, picked: [],
  whenDate: "", whenEnd: "", budget: "undecided",
};
const BANDS: { v: Band; t: string }[] = [{ v: "10", t: "10평대" }, { v: "20", t: "20평대" }, { v: "30", t: "30평대" }, { v: "40", t: "40평대" }, { v: "50", t: "50평 이상" }];
const WHEN_DESC: Record<When, string> = { date: "시작하는 날과 끝나는 날을 골라요", movein: "잔금일 · 입주일 전에 끝나게 맞춰요", months: "업체 일정에 맞춰 정해요", unknown: "견적부터 받아 볼게요" };
const BUDGET_ORDER: Budget[] = ["undecided", "u300", "300-500", "500-700", "700-1000", "o1000"];
const PHOTO_TYPES = "image/jpeg,image/png,image/webp,image/heic"; // API가 받는 형식 (backend/app/files/service.py)
const MAX_SPACES = 30;
const SECTIONS = [
  { id: "s-home", no: 1, title: "집" },
  { id: "s-trade", no: 2, title: "공정" },
  { id: "s-space", no: 3, title: "공간" },
  { id: "s-when", no: 4, title: "일정 · 예산" },
  { id: "s-photo", no: 5, title: "사진 · 도면" },
] as const;
const ORDER: Key[] = ["region", "area", "basis", "band", "year", "live", "trades", "grade", "items", "spaces", "when", "photos", "form"];
const SECTION_KEYS: Record<(typeof SECTIONS)[number]["id"], Key[]> = {
  "s-home": ["region", "area", "basis", "band", "year", "live"],
  "s-trade": ["trades", "grade", "items"],
  "s-space": ["spaces"],
  "s-when": ["when"],
  "s-photo": [],
};

function check(a: Answers, thisYear: number): Errs {
  const e: Errs = {};
  if (!a.sido) e.region = "시 · 도를 골라 주세요.";
  else if (!a.sgg) e.region = "시 · 군 · 구를 골라 주세요.";
  if (a.bandMode) {
    if (!a.size || a.size === "manual") e.band = "평형대를 골라 주세요. 대략 골라도 돼요.";
  } else {
    const n = Number(a.manualM2);
    if (!a.manualM2) e.area = "면적을 ㎡로 적어 주세요. 모르면 아래에서 평형대로 골라요.";
    else if (!/^\d{1,3}(\.\d)?$/.test(a.manualM2) || !(n > 10 && n < 400)) e.area = "면적은 10㎡보다 크고 400㎡보다 작게, 소수점은 한 자리까지 적어 주세요. 예: 84.9";
    if (!a.manualBasis) e.basis = "공급면적인지 전용면적인지 골라 주세요.";
  }
  if (a.builtYear && !(Number(a.builtYear) >= 1900 && Number(a.builtYear) <= thisYear)) e.year = "준공연도를 4자리로 적어 주세요. 예: 1998";
  if (!a.occupied) e.live = "공사할 때 집에 사는지 골라 주세요.";
  if (!a.trades.dobae && !a.trades.mokgong) e.trades = "공정을 하나 이상 골라 주세요.";
  if (a.trades.dobae && !a.grade) e.grade = "도배 유형을 골라 주세요.";
  if (a.trades.mokgong && !a.items.length) e.items = "목공에서 할 일을 하나 이상 골라 주세요.";
  if (!a.picked.length) e.spaces = "도배 · 목공할 공간을 하나 이상 골라 주세요.";
  if (!a.when) e.when = "공사 시기를 골라 주세요. 모르면 '아직 몰라요'를 골라요.";
  else if (a.when === "date" && !a.whenDate) e.when = "시작하는 날을 골라 주세요.";
  else if (a.when === "movein" && !a.whenDate) e.when = "이사하는 날을 골라 주세요.";
  return e;
}

/** 오류가 난 칸으로 초점을 옮긴다 */
function focusKey(k: Key, a: Answers) {
  const sel: Record<Key, string> = {
    region: a.sido ? "#wz-sgg" : "#wz-sido", area: "#wz-area", basis: "#wz-basis-supply", band: "#wz-band-10", year: "#wz-year", live: "#wz-live-no",
    trades: "#wz-t-dobae", grade: "#wz-grade-economy", items: "#wz-item-molding", spaces: "[name='wz-sp']",
    when: (a.when === "date" || a.when === "movein") && !a.whenDate ? "#wz-cal button[tabindex='0']" : "[name='wz-when']",
    photos: "#s-photo input[type='file']", form: "#wz-go",
  };
  document.querySelector<HTMLElement>(sel[k])?.focus();
}

// API 오류 → 칸. code는 backend/app/project/service.py, 422 fields의 loc은 본문 칸 이름
const CODE_KEY: Record<string, Key> = { region: "region", built_year: "year", past_date: "when", far_date: "when", file: "photos", file_used: "photos" };
const LOC_KEY: Record<string, Key> = { sido: "region", sgg: "region", built_year: "year", size: "area", when: "when", occupied: "live", spaces: "spaces", trades: "trades", photos: "photos", plans: "photos" };
function apiErrs(e: unknown, bandMode: boolean): Errs {
  if (!(e instanceof ApiError)) return { form: errorText(e) };
  if (CODE_KEY[e.code]) return { [CODE_KEY[e.code]]: e.message };
  const out: Errs = {};
  for (const f of e.fields ?? []) {
    let k = LOC_KEY[String(f.loc[0])] ?? "form";
    if (k === "area" && bandMode) k = "band";
    out[k] ??= /[가-힣]/.test(f.msg) ? f.msg : e.message;
  }
  return Object.keys(out).length ? out : { form: e.message };
}

// 같은 이름이 있으면 번호를 붙인다: 주방 → 주방 2, 작은방 1 · 작은방 2 → 작은방 3
function nextName(base: string, names: string[]) {
  const root = base.trim().replace(/\s*\d+$/, "");
  const esc = root.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const family = names.filter((n) => n === root || new RegExp(`^${esc} \\d+$`).test(n));
  if (!family.length && !names.includes(base.trim())) return base.trim();
  let k = family.length + 1;
  while (names.includes(`${root} ${k}`)) k++;
  return `${root} ${k}`;
}

/** 저장된 프로젝트 → 폼 값 · 올려 둔 사진 */
function fromProject(p: ApiProject) {
  const inTrade = new Set([...(p.trades.dobae?.spaces ?? []), ...(p.trades.mokgong?.spaces ?? [])]);
  const own: Space[] = p.spaces.map((sp) => ({ id: sp.id, name: sp.name, custom: !DEFAULT_SPACES.some((d) => d.name === sp.name) }));
  const a: Answers = {
    sido: p.sido, sgg: p.sgg, builtYear: p.built_year ? String(p.built_year) : "",
    bandMode: !!p.size.band, size: p.size.band ?? "manual",
    manualBasis: p.size.band ? undefined : p.size.basis === "exclusive" ? "jeon" : "supply", manualM2: p.size.m2 ?? "",
    balconyExt: p.balcony_ext, occupied: p.occupied ? "yes" : "no",
    trades: { dobae: !!p.trades.dobae, mokgong: !!p.trades.mokgong },
    grade: p.trades.dobae?.grade ?? undefined, items: p.trades.mokgong?.items ?? [],
    spaces: [...own, ...DEFAULT_SPACES.filter((d) => !own.some((o) => o.name === d.name))],
    picked: own.filter((o) => inTrade.has(o.id)).map((o) => o.id),
    when: p.when.kind, whenDate: p.when.start ?? "", whenEnd: p.when.end ?? "",
    budget: BUDGETS.find((b) => b.key === p.budget)?.key ?? "undecided",
  };
  const photos: Record<string, Photo[]> = {};
  for (const ph of p.photos) {
    const list = (photos[ph.space_id] ??= []);
    list.push({ id: `f-${ph.file_id}`, name: `사진 ${list.length + 1}`, type: "image/*", fileId: ph.file_id });
  }
  const plan: Photo[] = p.plans.map((fid, i) => ({ id: `f-${fid}`, name: `도면 ${i + 1}`, type: "", fileId: fid }));
  return { a, photos, plan };
}

/** 폼 값 → POST · PATCH /projects 본문. 고른 공간만 보내고, 두 공정이 같은 공간을 쓴다. */
function toBody(a: Answers, photoIds: { space: string; file_id: string }[], planIds: string[]): Schemas["ProjectCreate"] {
  const chosen = a.spaces.filter((sp) => a.picked.includes(sp.id));
  const keys = chosen.map((sp) => sp.id);
  const dated = a.when === "date" || a.when === "movein";
  return {
    sido: a.sido!, sgg: a.sgg!, house_type: "apt",
    built_year: a.builtYear ? Number(a.builtYear) : null,
    size: a.bandMode ? { band: a.size as Band } : { basis: a.manualBasis === "jeon" ? "exclusive" : "supply", m2: a.manualM2 },
    balcony_ext: a.balconyExt,
    when: { kind: a.when!, start: dated ? a.whenDate : null, end: a.when === "date" && a.whenEnd ? a.whenEnd : null },
    occupied: a.occupied === "yes",
    budget: a.budget,
    spaces: chosen.map((sp) => ({ key: sp.id, name: sp.name })),
    trades: {
      dobae: a.trades.dobae ? { spaces: keys, grade: a.grade! } : null,
      mokgong: a.trades.mokgong ? { spaces: keys, items: a.items } : null,
    },
    photos: photoIds,
    plans: planIds,
  };
}

/** 시연용 예시 답: 노원구 공급 105.8㎡(32평) 빈 집 · 도배 기본형 + 목공(몰딩 · 걸레받이) · 기본 공간 6곳(집 전체) */
function demoAnswers(today: string): Answers {
  const after = (n: number) => { const d = new Date(`${today}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  return {
    ...EMPTY, sido: "seoul", sgg: "노원구", builtYear: "2009",
    size: "manual", manualBasis: "supply", manualM2: "105.8", occupied: "no",
    trades: { dobae: true, mokgong: true }, grade: "basic", items: ["molding", "base"],
    picked: DEFAULT_SPACES.map((sp) => sp.id),
    when: "date", whenDate: after(28), whenEnd: after(42), budget: "500-700",
  };
}

const touched = (a: Answers) => !!(a.sido || a.size || a.trades.dobae || a.trades.mokgong || a.picked.length || a.when || a.occupied || a.builtYear);

type Props = { regions: Region[]; today: string; role: Role | null; project?: ApiProject | null; demo?: boolean };

export function Wizard({ regions, today, role, project = null, demo = false }: Props) {
  const router = useRouter();
  const edit = project;
  const [init] = useState(() => (edit ? fromProject(edit) : null));
  const [a, setA] = useState<Answers>(init?.a ?? EMPTY);
  const [photos, setPhotos] = useState<Record<string, Photo[]>>(() => init?.photos ?? PHOTO_MEMO.bySpace);
  const [plan, setPlan] = useState<Photo[]>(() => init?.plan ?? PHOTO_MEMO.plan);
  const [ready, setReady] = useState(!!edit);
  const [tried, setTried] = useState(false);
  const [serverErr, setServerErr] = useState<Errs>({});
  const [sending, setSending] = useState<string | null>(null); // 계산 중 안내. 있으면 버튼을 막는다
  const [savedAt, setSavedAt] = useState("");
  const [locked, setLocked] = useState(!!edit?.locked);
  const [newSpace, setNewSpace] = useState("");
  const [spaceMsg, setSpaceMsg] = useState("");
  const [cur, setCur] = useState<string>(SECTIONS[0].id);
  const [filled, setFilled] = useState(false);
  const goAfterLogin = useRef(false);
  const autoRan = useRef(false);
  const editUploaded = useRef<Record<string, string>>({});
  const thisYear = Number(today.slice(0, 4));

  // 새로 만들기: 저장해 둔 답을 불러온다. 가입 · 로그인 전에 '계산하기'를 눌렀으면 이어서 계산할 표시를 기억한다.
  useEffect(() => {
    if (edit) return;
    const d = readDraft();
    if (d) { setA({ ...EMPTY, ...(d.a as Partial<Answers>) }); goAfterLogin.current = !!d.go; }
    setReady(true);
  }, [edit]);
  useEffect(() => {
    if (!ready || edit) return;
    writeDraft(touched(a) ? { a, step: "form" } : null);
  }, [a, ready, edit]);
  useEffect(() => { if (!edit) { PHOTO_MEMO.bySpace = photos; PHOTO_MEMO.plan = plan; } }, [photos, plan, edit]);
  // 사진 칸 밖에 떨어뜨려도 브라우저가 사진을 열며 화면을 떠나지 않게 막는다.
  useEffect(() => {
    const stop = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  }, []);
  // 목차의 '작성 중': 화면 위쪽에 걸린 구역
  useEffect(() => {
    if (!ready) return;
    const io = new IntersectionObserver((es) => es.forEach((en) => { if (en.isIntersecting) setCur(en.target.id); }), { rootMargin: "-15% 0px -75% 0px" });
    SECTIONS.forEach((x) => { const el = document.getElementById(x.id); if (el) io.observe(el); });
    return () => io.disconnect();
  }, [ready]);
  // 가입 · 로그인하고 돌아왔으면 이어서 계산한다(한 번만).
  useEffect(() => {
    if (!ready || edit || autoRan.current || !goAfterLogin.current || role !== "customer") return;
    autoRan.current = true;
    goAfterLogin.current = false;
    submit();
  });

  const found = check(a, thisYear);
  const errs: Errs = { ...(tried ? found : {}), ...serverErr };
  const set = (p: Partial<Answers>) => { setA((x) => ({ ...x, ...p })); setServerErr({}); setSavedAt(""); };
  const err = (k: Key) => (errs[k] ? <FieldError id={`e-${k}`}>{errs[k]}</FieldError> : null);
  const inv = (k: Key) => (errs[k] ? { "aria-invalid": true as const, "aria-describedby": `e-${k}` } : {});
  const desc = (k: Key) => (errs[k] ? `e-${k}` : undefined);
  const sido = regions.find((r) => r.id === a.sido);
  const chosen = a.spaces.filter((sp) => a.picked.includes(sp.id));
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  function pickSido(id: string) {
    const r = regions.find((x) => x.id === id);
    const only = r && r.groups.length === 1 && r.groups[0].items.length === 1 ? r.groups[0].items[0] : undefined;
    set({ sido: id || undefined, sgg: only });
  }
  function toggleBand() {
    if (a.bandMode) set({ bandMode: false, size: a.manualM2 || a.manualBasis ? "manual" : undefined });
    else set({ bandMode: true, size: a.size === "manual" ? undefined : a.size });
  }
  function addSpace() {
    const base = newSpace.trim();
    if (!base) return;
    if (a.spaces.length >= MAX_SPACES) { setSpaceMsg(`공간은 ${MAX_SPACES}곳까지 넣을 수 있어요.`); return; }
    const name = nextName(base, a.spaces.map((x) => x.name)).slice(0, 20);
    const id = `sp-${Date.now().toString(36)}`;
    set({ spaces: [...a.spaces, { id, name, custom: true }], picked: [...a.picked, id] });
    setSpaceMsg(`${eulReul(name)} 넣고 골랐어요.`);
    setNewSpace("");
  }
  function removeSpace(id: string) {
    const sp = a.spaces.find((x) => x.id === id);
    set({ spaces: a.spaces.filter((x) => x.id !== id), picked: a.picked.filter((x) => x !== id) });
    setPhotos((m) => { const n = { ...m }; delete n[id]; return n; });
    setSpaceMsg(`${eulReul(sp?.name ?? "공간")} 뺐어요.`);
  }
  function fillDemo() {
    set(demoAnswers(today));
    setTried(false);
    setFilled(true);
  }
  function saveNow() {
    if (!touched(a)) { setSavedAt("넣은 내용이 아직 없어요."); return; }
    writeDraft({ a, step: "form" });
    setSavedAt(`${stampSeoul(new Date())}에 임시 저장했어요`);
  }

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (sending || locked) return;
    setTried(true);
    const first = ORDER.find((k) => found[k]);
    if (first) { setTimeout(() => focusKey(first, a), 0); return; }
    void finish();
  }

  async function finish() {
    setServerErr({});
    const fail = (x: Errs) => { setSending(null); setServerErr(x); const k = ORDER.find((o) => x[o]); if (k) setTimeout(() => focusKey(k, a), 0); };
    // 1. 새로 만들 때는 로그인 확인. 안 했으면 답은 그대로 두고 가입 뒤 이 화면으로 돌아와 이어서 계산한다.
    if (!edit) {
      let me: Schemas["MeOut"];
      try { me = await call<Schemas["MeOut"]>("GET", "/me"); } catch (er) {
        if (er instanceof ApiError && er.status === 401) {
          writeDraft({ a, step: "form", go: true });
          router.push(`/signup?next=${encodeURIComponent("/start")}`);
          return;
        }
        fail({ form: errorText(er) }); return;
      }
      if (me.role !== "customer") { fail({ form: "고객 계정으로 로그인해야 계산할 수 있어요." }); return; }
    }

    // 2. 사진 · 도면 올리기. 이미 올린 것(고치기로 불러온 것 · 다시 누른 것)은 다시 올리지 않는다.
    const uploaded = edit ? editUploaded.current : PHOTO_MEMO.uploaded;
    const jobs = [
      ...chosen.flatMap((sp) => (photos[sp.id] ?? []).map((ph) => ({ ph, kind: "photo" as const, space: sp.id }))),
      ...plan.map((ph) => ({ ph, kind: "plan" as const, space: "" })),
    ];
    const photoIds: { space: string; file_id: string }[] = [];
    const planIds: string[] = [];
    for (const [i, j] of jobs.entries()) {
      let fid = j.ph.fileId ?? uploaded[j.ph.id];
      if (!fid && j.ph.file) {
        setSending(`사진 · 도면을 올리고 있어요 (${i + 1}/${jobs.length})`);
        const fd = new FormData();
        fd.append("kind", j.kind);
        fd.append("file", j.ph.file, j.ph.name);
        try { fid = (await call<Schemas["FileOut"]>("POST", "/files", fd)).id; } catch (er) {
          fail({ photos: `${j.ph.name}: ${errorText(er)}` }); return;
        }
        uploaded[j.ph.id] = fid;
      }
      if (!fid) continue;
      if (j.kind === "photo") photoIds.push({ space: j.space, file_id: fid }); else planIds.push(fid);
    }

    // 3. 만들기 · 고치기
    setSending(edit ? "고친 집 정보로 다시 계산하고 있어요" : "표준견적서를 계산하고 있어요");
    try {
      const body = toBody(a, photoIds, planIds);
      const p = edit
        ? await call<Schemas["ProjectOut"]>("PATCH", `/projects/${edit.id}`, body)
        : await call<Schemas["ProjectOut"]>("POST", "/projects", body);
      if (!edit) { writeDraft(null); clearPhotoMemo(); }
      router.push(`/projects/${p.id}/standard?done=${edit ? "edit" : "new"}`);
      router.refresh();
    } catch (er) {
      if (er instanceof ApiError && er.code === "locked") { setSending(null); setLocked(true); return; }
      fail(apiErrs(er, a.bandMode));
    }
  }

  if (!ready) return <main id="main" className={`mj-wrap ${s.page}`} aria-busy="true"><p className="mj-sub">불러오는 중이에요…</p></main>;

  const done = (id: (typeof SECTIONS)[number]["id"]) =>
    id === "s-photo" ? chosen.some((sp) => photos[sp.id]?.length) || plan.length > 0 : SECTION_KEYS[id].every((k) => !found[k]);
  const curNo = SECTIONS.find((x) => x.id === cur)?.no ?? 1;
  const goLabel = edit ? "고친 내용으로 다시 계산하기" : role ? "계산하기" : "가입하고 계산하기";
  const check20 = (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3.5 8.4l3 3 6-6.6" /></svg>
  );

  return (
    <main id="main" className={`mj-wrap ${s.page}`}>
      <nav className={s.toc} aria-label="견적 받기 단계">
        <p className={s.tocNow}>5단계 중 {curNo}단계</p>
        <ol className={s.tocList}>
          {SECTIONS.map((x) => {
            const ok = done(x.id);
            const now = cur === x.id;
            return (
              <li key={x.id}>
                <a href={`#${x.id}`} className={s.tocA} aria-current={now ? "step" : undefined} onClick={() => setCur(x.id)}>
                  <span className="mj-code" aria-hidden="true">{x.no}</span>
                  <span className={s.tocT}>{x.title}</span>
                  {ok ? <span className="mj-st mj-st-ok">{check20}<span className="mj-sr">작성 끝남</span></span>
                    : now ? <span className="mj-st mj-st-now"><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="4" fill="currentColor" /></svg><span className="mj-sr">작성 중</span></span>
                    : null}
                </a>
              </li>
            );
          })}
        </ol>
      </nav>

      <form id="wz-form" className={s.form} onSubmit={submit} noValidate aria-labelledby="wz-t">
        <div className={s.head}>
          <h1 id="wz-t" className="mj-h1">{edit ? "집 정보 고치기" : "견적 받기"}</h1>
          <p className="mj-sub">{edit ? "고친 내용으로 표준견적서와 예상 공정표를 다시 계산해요." : "집 정보와 공정을 넣으면 표준견적서와 예상 공정표가 나와요."}</p>
          {demo && !edit ? (
            <div className={s.demo}>
              <button type="button" className="mj-btn mj-btn-sec" onClick={fillDemo} disabled={!!sending}>예시 값 채우기</button>
              <p className="mj-small" role="status">{filled ? "예시 값을 채웠어요. 맨 아래 계산하기를 눌러 주세요." : "시연 계정이에요. 노원구 32평 · 도배와 목공 예시로 한 번에 채워요."}</p>
            </div>
          ) : null}
          {locked ? (
            <p className="mj-notice mj-notice-warn" role="status">
              <span>실측을 요청한 뒤에는 집 정보를 고칠 수 없어요. 다른 조건으로 보려면 <Link href="/my">내 공사 목록</Link>에서 새 견적을 받아요.</span>
            </p>
          ) : null}
        </div>

        <fieldset className={s.all} disabled={locked}>
          {/* 1 집 */}
          <section id="s-home" className={s.sec} aria-labelledby="s-home-t">
            <div className={s.secH}><span className="mj-code" aria-hidden="true">1</span><h2 id="s-home-t" className="mj-h2">집</h2></div>

            <fieldset aria-describedby={desc("region")}>
              <legend className={s.lab}>지역 <span className={s.req}>(필수)</span></legend>
              <div className={s.opts}>
                <select id="wz-sido" className={`mj-select ${s.sel}`} aria-label="시 · 도" autoComplete="address-level1" value={a.sido ?? ""} onChange={(e) => pickSido(e.target.value)} {...(!a.sido ? inv("region") : {})}>
                  <option value="">시 · 도 고르기</option>
                  {regions.map((r) => <option key={r.id} value={r.id}>{r.full}</option>)}
                </select>
                <select id="wz-sgg" className={`mj-select ${s.sel}`} aria-label="시 · 군 · 구" autoComplete="address-level2" disabled={!sido} value={a.sgg ?? ""} onChange={(e) => set({ sgg: e.target.value || undefined })} {...(a.sido ? inv("region") : {})}>
                  <option value="">시 · 군 · 구 고르기</option>
                  {sido?.groups.map((g, gi) => g.label
                    ? <optgroup key={g.prefix || gi} label={g.label}>{g.items.map((n) => <option key={n} value={n}>{n}</option>)}</optgroup>
                    : g.items.map((n) => <option key={n} value={n}>{n}</option>))}
                </select>
              </div>
              {regions.length ? null : <p className="mj-small">지역 목록을 불러오지 못했어요. 새로 고쳐 주세요.</p>}
              {err("region")}
            </fieldset>

            <fieldset>
              <legend className={s.lab}>집 종류 <span className={s.req}>(필수)</span></legend>
              <div className={s.opts}>
                <label className={`${s.opt} ${s.grow}`}><input className={s.ck} type="radio" name="wz-kind" value="apt" defaultChecked />아파트</label>
                <label className={`${s.opt} ${s.grow}`}><input className={s.ck} type="radio" name="wz-kind" value="villa" disabled />빌라 · 다세대 <span className="mj-small">준비 중</span></label>
                <label className={`${s.opt} ${s.grow}`}><input className={s.ck} type="radio" name="wz-kind" value="officetel" disabled />오피스텔 <span className="mj-small">준비 중</span></label>
              </div>
            </fieldset>

            <fieldset>
              <legend className={s.lab}>면적 <span className={s.req}>(필수)</span></legend>
              {a.bandMode ? (
                <fieldset id="wz-band" aria-describedby={desc("band")}>
                  <legend className={s.lab}>평형대</legend>
                  <div className={s.opts}>
                    {BANDS.map((b) => (
                      <label key={b.v} className={s.opt}><input id={`wz-band-${b.v}`} className={s.ck} type="radio" name="wz-band" checked={a.size === b.v} onChange={() => set({ size: b.v })} /><span className="mj-num">{b.t}</span></label>
                    ))}
                  </div>
                </fieldset>
              ) : (
                <div className={s.areaRow}>
                  <div className={s.m2}>
                    <label htmlFor="wz-area" className="mj-sr">면적, 제곱미터</label>
                    <input id="wz-area" className={`mj-input mj-num ${s.m2In}`} inputMode="decimal" placeholder="예: 84.9" value={a.manualM2}
                      onChange={(e) => set({ manualM2: e.target.value.replace(/[^\d.]/g, "").replace(/^(\d*\.?\d?).*$/, "$1"), size: "manual" })} {...inv("area")} />
                    <span aria-hidden="true" className={s.unit}>㎡</span>
                  </div>
                  <fieldset className={s.opts} aria-describedby={desc("basis")}>
                    <legend className="mj-sr">면적 기준</legend>
                    <label className={s.opt}><input id="wz-basis-supply" className={s.ck} type="radio" name="wz-basis" checked={a.manualBasis === "supply"} onChange={() => set({ manualBasis: "supply", size: "manual" })} />공급면적</label>
                    <label className={s.opt}><input id="wz-basis-jeon" className={s.ck} type="radio" name="wz-basis" checked={a.manualBasis === "jeon"} onChange={() => set({ manualBasis: "jeon", size: "manual" })} />전용면적</label>
                  </fieldset>
                </div>
              )}
              {err("area")}{err("basis")}{err("band")}
              {a.bandMode ? null : <p className={s.hint}>공급면적은 분양 평형, 전용면적은 실제로 쓰는 면적이에요.</p>}
              <p><button type="button" className="mj-lnk" aria-expanded={a.bandMode} aria-controls="wz-band" onClick={toggleBand}>{a.bandMode ? "면적을 알아요 · ㎡로 적기" : "면적을 몰라요 · 평형대로 고르기"}</button></p>
            </fieldset>

            <label className={s.ckrow}><input className={s.ck} type="checkbox" checked={a.balconyExt} onChange={(e) => set({ balconyExt: e.target.checked })} />발코니를 확장했어요</label>

            <div className={s.row2}>
              <div className={s.year}>
                <label htmlFor="wz-year" className={s.lab}>준공연도 <span className={s.req}>(선택)</span></label>
                <div className={s.m2}><input id="wz-year" className={`mj-input mj-num ${s.yearIn}`} inputMode="numeric" placeholder="예: 1998" value={a.builtYear} onChange={(e) => set({ builtYear: e.target.value.replace(/\D/g, "").slice(0, 4) })} {...inv("year")} /><span aria-hidden="true">년</span></div>
                {err("year")}
              </div>
              <fieldset className={s.live} aria-describedby={desc("live")}>
                <legend className={s.lab}>공사할 때 집에 사나요? <span className={s.req}>(필수)</span></legend>
                <div className={s.opts}>
                  <label className={`${s.opt} ${s.grow}`}><input id="wz-live-no" className={s.ck} type="radio" name="wz-live" checked={a.occupied === "no"} onChange={() => set({ occupied: "no" })} />빈 집 · 이사 전 공사</label>
                  <label className={`${s.opt} ${s.grow}`}><input id="wz-live-yes" className={s.ck} type="radio" name="wz-live" checked={a.occupied === "yes"} onChange={() => set({ occupied: "yes" })} />살면서 공사</label>
                </div>
                {err("live")}
              </fieldset>
            </div>
          </section>

          {/* 2 공정 */}
          <section id="s-trade" className={s.sec} aria-labelledby="s-trade-t">
            <div className={s.secH}><span className="mj-code" aria-hidden="true">2</span><h2 id="s-trade-t" className="mj-h2">공정</h2></div>
            <fieldset aria-describedby={desc("trades")}>
              <legend className={s.lab}>할 공정 <span className={s.req}>(필수 · 하나 이상)</span></legend>
              <div className={s.trades}>
                <div className={s.trade}>
                  <label className={`${s.ckrow} ${s.tradeT}`}><input id="wz-t-dobae" className={s.ck} type="checkbox" checked={a.trades.dobae} aria-controls="wz-dobae" onChange={(e) => set({ trades: { ...a.trades, dobae: e.target.checked } })} {...inv("trades")} />도배</label>
                  <div id="wz-dobae" className={s.tradeIn} hidden={!a.trades.dobae}>
                    <fieldset aria-describedby={desc("grade")}>
                      <legend className={s.lab}>도배 유형</legend>
                      <div className={s.grades}>
                        {DOBAE_GRADES.map((g) => (
                          <label key={g.key} className={`${s.opt} ${s.gradeOpt}`}>
                            <input id={`wz-grade-${g.key}`} className={s.ck} type="radio" name="wz-grade" checked={a.grade === g.key} onChange={() => set({ grade: g.key })} />
                            <span className={`${s.sw} ${g.key === "economy" ? s.swEco : s.swBasic}`} aria-hidden="true" />
                            <span className={s.ot}><span className={s.otl}>{g.label}</span><span className="mj-small">{g.desc}</span></span>
                          </label>
                        ))}
                      </div>
                      {err("grade")}
                    </fieldset>
                  </div>
                </div>
                <div className={s.trade}>
                  <label className={`${s.ckrow} ${s.tradeT}`}><input id="wz-t-mokgong" className={s.ck} type="checkbox" checked={a.trades.mokgong} aria-controls="wz-wood" onChange={(e) => set({ trades: { ...a.trades, mokgong: e.target.checked } })} {...inv("trades")} />목공</label>
                  <div id="wz-wood" className={s.tradeIn} hidden={!a.trades.mokgong}>
                    <fieldset aria-describedby={desc("items")}>
                      <legend className={s.lab}>목공에서 할 일</legend>
                      <div className={s.items}>
                        {MOK_ITEMS.map((m) => (
                          <label key={m.key} className={s.opt}><input id={`wz-item-${m.key}`} className={s.ck} type="checkbox" checked={a.items.includes(m.key)} onChange={() => set({ items: toggle(a.items, m.key) })} /><span>{m.label} <span className="mj-small">· {m.desc}</span></span></label>
                        ))}
                      </div>
                      {a.items.includes("door") ? <p className={s.hint}>문 개수는 실측 때 다시 세요.</p> : null}
                      {err("items")}
                    </fieldset>
                  </div>
                </div>
              </div>
              {err("trades")}
            </fieldset>
          </section>

          {/* 3 공간 */}
          <section id="s-space" className={s.sec} aria-labelledby="s-space-t">
            <div className={s.secH}><span className="mj-code" aria-hidden="true">3</span><h2 id="s-space-t" className="mj-h2">공간</h2></div>
            <div className={s.spaceCols}>
              <fieldset className={s.spaces} aria-describedby={desc("spaces")}>
                <legend className={s.lab}>도배 · 목공할 공간 <span className={s.req}>(필수)</span></legend>
                <ul className={s.spaceList}>
                  {a.spaces.map((sp) => (
                    <li key={sp.id}>
                      <label className={s.ckrow}><input className={s.ck} type="checkbox" name="wz-sp" checked={a.picked.includes(sp.id)} onChange={() => set({ picked: toggle(a.picked, sp.id) })} />{sp.name}</label>
                      {sp.custom ? <button type="button" className="mj-btn mj-btn-ghost mj-btn-sm" onClick={() => removeSpace(sp.id)} aria-label={`${sp.name} 빼기`}>빼기</button> : null}
                    </li>
                  ))}
                </ul>
                {err("spaces")}
              </fieldset>
              <div className={s.add}>
                <label htmlFor="wz-sp-new" className={s.lab}>공간 더하기 <span className={s.req}>(목록에 없을 때)</span></label>
                <div className={s.addRow}>
                  <input id="wz-sp-new" className="mj-input" placeholder="예: 드레스룸" maxLength={20} value={newSpace} onChange={(e) => setNewSpace(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSpace(); } }} />
                  <button type="button" className="mj-btn mj-btn-sec" onClick={addSpace} disabled={!newSpace.trim()}>더하기</button>
                </div>
                <p className="mj-small" aria-live="polite">{spaceMsg}</p>
              </div>
            </div>
          </section>

          {/* 4 일정 · 예산 */}
          <section id="s-when" className={s.sec} aria-labelledby="s-when-t">
            <div className={s.secH}><span className="mj-code" aria-hidden="true">4</span><h2 id="s-when-t" className="mj-h2">일정 · 예산</h2></div>
            <fieldset aria-describedby={a.when === "date" || a.when === "movein" ? undefined : desc("when")}>
              <legend className={s.lab}>공사 시기 <span className={s.req}>(필수)</span></legend>
              <div className={s.whenList}>
                {(Object.keys(WHEN_DESC) as When[]).map((w) => {
                  const open = a.when === w && (w === "date" || w === "movein");
                  return (
                    <div key={w} className={s.whenItem}>
                      <label className={s.opt}>
                        <input className={s.ck} type="radio" name="wz-when" checked={a.when === w} aria-controls={w === "date" || w === "movein" ? `wz-when-${w}` : undefined}
                          onChange={() => set({ when: w, ...(w === "movein" ? { whenEnd: "" } : {}) })} />
                        <span className={s.ot}><span className={s.otm}>{WHEN_LABEL[w]}</span><span className="mj-small">{WHEN_DESC[w]}</span></span>
                      </label>
                      {open ? (
                        <div id={`wz-when-${w}`} className="mj-reveal">
                          {w === "date"
                            ? <DateCalendar id="wz-cal" range value={{ from: a.whenDate, to: a.whenEnd }} onChange={(r) => set({ whenDate: r.from, whenEnd: r.to })} today={today} label="시작하는 날과 끝나는 날" describedBy={desc("when")} />
                            : <DateCalendar id="wz-cal" value={a.whenDate} onChange={(v) => set({ whenDate: v, whenEnd: "" })} today={today} label="이사하는 날" describedBy={desc("when")} />}
                          {a.whenDate ? <p className="mj-small" aria-live="polite">고른 날: <b className="mj-num">{md(a.whenDate)}{w === "date" && a.whenEnd && a.whenEnd !== a.whenDate ? ` ~ ${md(a.whenEnd)}` : ""}</b></p> : null}
                          {err("when")}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              {(a.when === "date" || a.when === "movein") ? null : err("when")}
            </fieldset>

            <div className={s.budget}>
              <label htmlFor="wz-budget" className={s.lab}>예산 <span className={s.req}>(선택 · 부가세 포함)</span></label>
              <select id="wz-budget" className="mj-select" value={a.budget} onChange={(e) => set({ budget: e.target.value as Budget })}>
                {BUDGET_ORDER.map((k) => <option key={k} value={k}>{BUDGETS.find((b) => b.key === k)?.label}</option>)}
              </select>
            </div>
          </section>

          {/* 5 사진 · 도면 */}
          <section id="s-photo" className={s.sec} aria-labelledby="s-photo-t">
            <div className={s.secH}><span className="mj-code" aria-hidden="true">5</span><h2 id="s-photo-t" className="mj-h2">사진 · 도면</h2><span className={s.req}>(선택)</span></div>
            <div className={s.photoBox}>
              <p id="wz-ph-f" className="mj-small">사진 JPG · PNG · WebP · HEIC · 한 장 10MB · 공간마다 10장</p>
              {chosen.length ? (
                <div className={s.photoList}>
                  {chosen.map((sp) => (
                    <PhotoDrop key={sp.id} variant="list" id={`ph-${sp.id}`} title={sp.name} label={`${sp.name} 사진`} photos={photos[sp.id] ?? []} accept={PHOTO_TYPES} maxMB={10} hint="" describedBy="wz-ph-f"
                      onAdd={(files) => setPhotos((m) => ({ ...m, [sp.id]: [...(m[sp.id] ?? []), ...toPhotos(files)] }))}
                      onRemove={(pid) => setPhotos((m) => ({ ...m, [sp.id]: (m[sp.id] ?? []).filter((x) => x.id !== pid) }))} />
                  ))}
                </div>
              ) : <p className="mj-sub">공간을 고르면 공간마다 사진을 넣을 수 있어요.</p>}
            </div>
            <div className={s.photoBox}>
              <PhotoDrop variant="list" id="wz-plan" title="도면" label="도면" photos={plan} max={5} accept={`${PHOTO_TYPES},application/pdf`} maxMB={20} hint="PDF · 그림 · 한 개 20MB · 5개까지"
                onAdd={(files) => setPlan((old) => [...old, ...toPhotos(files)])}
                onRemove={(pid) => setPlan((old) => old.filter((x) => x.id !== pid))} />
            </div>
            {err("photos")}
          </section>
        </fieldset>

        <div className={s.go}>
          <button id="wz-go" type="submit" className={`mj-btn mj-btn-pri ${s.goBtn}`} disabled={!!sending || locked} aria-describedby={desc("form")}>{goLabel}</button>
          {edit
            ? <Link className={`mj-btn mj-btn-sec ${s.goBtn}`} href={`/projects/${edit.id}/standard`}>고치지 않고 돌아가기</Link>
            : <button type="button" className={`mj-btn mj-btn-sec ${s.goBtn}`} onClick={saveNow} disabled={!!sending}>임시 저장</button>}
          <p className="mj-small mj-num" role="status">{sending ?? savedAt}</p>
          <div className={s.full}>{err("form")}</div>
          {!edit && !role ? <p className={`mj-small ${s.full}`}>가입해도 넣은 집 정보 · 사진은 그대로 이어져요.</p> : null}
          {edit ? <p className={`mj-small ${s.full}`}>다시 계산하면 표준견적서와 예상 공정표가 바뀌어요.</p> : null}
        </div>
      </form>
    </main>
  );
}
