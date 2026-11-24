"use client";
// /start 첫 대화(v4): 집 확인 카드(기본 정보)부터 → 표준견적서 → 직접 할 일 칩(한 번) → 가입 카드 · 내 공사 만들기.
//   글 입력 칸은 두지 않아요(2026-11-23 사용자: 채팅보다 기본 정보를 먼저). 주소 · 단지 이름 글로 미리 채우기는 뺐어요.
// - 처음 받는 기본 정보 8개(2026-11-21 사용자 결정): 집 확인 카드 7칸(지역 · 면적 · 방 개수 · 공사할 때 집 · 벽지 · 철거 범위 ·
//   공사 희망 시기) + 표준견적서 바로 뒤 직접 할 일(반셀프 칩). 그 밖의 조건(편한 요일 · 목공 세부 · 우선순위)은 필요한 단계에서 비서가 물어요.
// - AI 글은 쓰지 않아요(로그인 전 · 공사 전). 말은 정해 둔 글('믿집 안내')이고, 금액 · 일수 · 시기 칩 날짜는 계산 엔진 값
//   (POST /guest/standard · GET /guest/start-options)이에요. 방 개수는 면적 기본값(GET /guest/room-rule)을 미리 골라 두고 보이는 값을 보내요.
//   방 개수 표를 못 읽었으면 미리 고르지 않고, 고객이 안 골랐으면 비워 보내요(서버가 면적 기본값으로 세요).
// - 손님: 답은 이 기기에만(mj_guest_v3) → 표준견적서 요약 · 직접 할 일 → 가입 카드. 가입하면 같은 답으로 내 공사가 만들어져요(auth/after).
//   직접 할 일로 '벽지 직접 구매'를 고르거나 빼면 표준견적서를 다시 세어(서버 계산 엔진) 가입 뒤 공사와 같은 금액을 보여요.
//   어디까지 했는지(표준견적서 · 직접 할 일 답)는 이 탭에 둬서 [견적서 열기] 뒤 뒤로 와도 이어 가요(QA r7 N8). 금액은 두지 않고 다시 물어요.
// - 로그인한 고객: 직접 할 일까지 고르면 POST /projects(Idempotency-Key = 기기 답 key, 직접 할 일도 한 번에) → /projects/{id}/standard.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { JoinDialog } from "@/components/auth/JoinDialog";
import { DateSheet } from "@/components/start/DateSheet";
import { DEMOLITION, resetMock, type StandardQuoteData } from "@/lib/api/assistant";
import type { Region } from "@/lib/api/project";
import { errorText, type Schemas } from "@/lib/backend/client";
import { dateShort, decText } from "@/lib/format";
import { calcGuest, sendHome, type GuestStandard } from "@/lib/guest/api";
import {
  checkDraft, DIY, diyText, EMPTY_DRAFT, GRADE_WORD, pyeongToM2, roomsOf, toHomeInfo, WISH_LABEL,
  type DiyKey, type InfoDraft, type RoomRule, type StartWish,
} from "@/lib/guest/info";
import { toQuoteLines } from "@/lib/guest/standard";
import { clearGuest, draftOf, readGuest, writeGuest } from "@/lib/guest/store";
import { StandardSummary } from "../cards/StandardQuoteCard";
import { SourceTag } from "../kit/StatusTag";
import { I, Logo } from "../kit/icons";
import k from "../kit/kit.module.css";
import c from "../cards/cards.module.css";
import s from "../assistant.module.css";
import t from "./start.module.css";

type Phase = "confirm" | "calc" | "done" | "creating";
const PYEONG = ["24", "32", "34", "40"];
const MOCK_PID = "a3a00000-0000-4000-8000-000000000001";
type DiyPick = DiyKey | "none";

/** 손님 표준견적서 → 요약 카드 값(큰 줄 몇 개는 계산 엔진 줄 금액 그대로 골라 보여요). href가 비면 열기 단추를 빼요 */
function summaryOf(g: GuestStandard, d: InfoDraft, href: string): StandardQuoteData {
  const lines = toQuoteLines(g.lines, g.scope)
    .filter((l) => (l.state === "included" || l.state === "separate") && (l.amount ?? 0) > 0)
    .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
    .slice(0, 3)
    .map((l) => ({ name: l.name, won: l.amount ?? 0 }));
  // 벽지 직접 구매면 비서 표준견적서 카드처럼 '벽지 고객 구매'를 붙여요(도배지 줄은 합계 밖, 계산 엔진)
  const label = [
    "도배", d.grade ? GRADE_WORD[d.grade] : null, `${g.area_basis === "exclusive" ? "전용" : "공급"} ${decText(g.area_m2)}㎡`, g.own_paper ? "벽지 고객 구매" : null,
  ].filter(Boolean).join(" · ");
  return { total_won: g.total, label, lines, days: g.days, partial: g.scope === "partial", href };
}

/** 고른 직접 할 일에 '벽지 직접 구매'가 있나(표준견적서 도배지 줄이 고객 구매로 빠져요, 계산은 서버) */
const buysPaper = (diy: readonly string[] | null | undefined) => !!diy?.includes("paper_buy");

/** 보이는 방 개수: 고른 값, 없으면 면적 기본값. 방 개수 표를 못 읽었으면(기본값 표 없음) 미리 고르지 않아요(null) */
const shownRooms = (d: InfoDraft, rule: RoomRule): number | null => d.rooms ?? (rule.bands.length ? roomsOf(d, rule) : null);
/** 보이는 방 개수를 답에 넣어요(면적 기본값으로 미리 골라 둔 칩도 고객이 보고 넘긴 값이에요). 비었으면 서버가 면적 기본값으로 세요
 *  (표를 못 읽은 fallback 3을 고른 값으로 보내 서버 기본값을 덮지 않게) */
const withRooms = (d: InfoDraft, rule: RoomRule): InfoDraft => ({ ...d, rooms: shownRooms(d, rule) });

/** 손님 첫 대화를 어디까지 했는지(이 탭에만): 그때 기기 답 key(조건이 바뀌면 key도 바뀌어요) · 직접 할 일을 답했는지 */
const STEP_KEY = "mj_start_step";
type StartStep = { key: string; answered: boolean };
function readStep(): StartStep | null {
  try {
    const x: unknown = JSON.parse(window.sessionStorage.getItem(STEP_KEY) ?? "null");
    return x && typeof x === "object" && typeof (x as StartStep).key === "string" && typeof (x as StartStep).answered === "boolean" ? (x as StartStep) : null;
  } catch {
    return null;
  }
}
function writeStep(step: StartStep | null) {
  try {
    if (step) window.sessionStorage.setItem(STEP_KEY, JSON.stringify(step));
    else window.sessionStorage.removeItem(STEP_KEY);
  } catch { /* 편의 기능이라 넘어가요 */ }
}

type Errors = Partial<Record<"region" | "area" | "occupied" | "grade" | "demolition" | "when", string>>;
function errorsOf(d: InfoDraft, today: string): Errors {
  const e = checkDraft(d);
  return {
    ...(e.region ? { region: "지역을 골라 주세요." } : {}),
    ...(e.area ? { area: d.area ? e.area : "평형을 고르거나 ㎡로 넣어 주세요." } : {}),
    ...(e.occupied ? { occupied: e.occupied } : {}),
    ...(e.grade ? { grade: e.grade } : {}),
    ...(!d.demolition ? { demolition: "철거 범위를 골라 주세요." } : {}),
    ...(!d.when ? { when: "공사 희망 시기를 골라 주세요." } : d.when === "date" && (!d.start || d.start < today) ? { when: "오늘 이후 날짜를 골라 주세요." } : {}),
  };
}

export function StartChat({ regions, roomRule, wishes, today, mode, mock }: {
  regions: Region[];
  roomRule: RoomRule;
  /** 공사 희망 시기 칩 → 날짜(계산 엔진). 못 읽었으면 빈 목록(아직 몰라요 · 날짜 고르기만) */
  wishes: StartWish[];
  /** 서울 오늘 "2026-11-21" */
  today: string;
  mode: "guest" | "member";
  mock: boolean;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("confirm");
  /** 이 기기에 넣던 답을 카드에 이어 채웠어요(첫 말이 '넣던 집 정보예요') */
  const [resumed, setResumed] = useState(false);
  const [d, setD] = useState<InfoDraft>(EMPTY_DRAFT);
  const [dirty, setDirty] = useState(false);
  const [tried, setTried] = useState(false);
  const [std, setStd] = useState<GuestStandard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [join, setJoin] = useState(false);
  const [manual, setManual] = useState(false);
  const [dateOpen, setDateOpen] = useState(false);
  const [pick, setPick] = useState<DiyPick[]>([]);
  const [answered, setAnswered] = useState(false);
  /** 직접 할 일로 벽지 직접 구매가 바뀌어 다시 센 표준견적서(손님, 가입 뒤 공사와 같은 값) · 다시 세는 중 · 실패 글 */
  const [again, setAgain] = useState<{ std: GuestStandard | null; busy: boolean; err: string | null } | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const restored = useRef(false);

  // 이 기기에 넣던 답이 있으면 카드에 이어 채워요(처음 한 번). 칩으로 고른 시기는 오늘 기준 날짜로 다시 맞추고,
  // 넣던 방 개수가 면적 기본값과 같으면 면적을 따라가게 비워 둬요
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    const g = readGuest();
    if (!g?.info.sido) return;
    const saved = draftOf(g);
    const rooms = saved.rooms != null && saved.rooms === roomsOf({ ...saved, rooms: null }, roomRule) ? null : saved.rooms;
    // v3 기본 정보 화면에서 넣던 답은 고른 시기가 없어요: 날짜가 있으면 '날짜 고르기'로 봐요
    let when = saved.when ?? (saved.start ? "date" : null);
    let start = saved.start;
    if (when === "date") {
      // 지난 날짜는 비워 다시 고르게 해요
      if (start && start < today) start = null;
    } else if (when && when !== "unknown") {
      // 칩을 못 찾으면(시기 칩을 못 읽음) 칩이 안 보여 고른 게 없어 보이는데 지난 날짜가 가요: 비워 다시 고르게 해요
      const wish = wishes.find((w) => w.key === when);
      if (wish) start = wish.start_date;
      else { when = null; start = null; }
    }
    const next = { ...saved, rooms, when, start };
    setD(next);
    setManual(!!saved.area && !PYEONG.some((p) => pyeongToM2(p) === saved.area && saved.basis === "supply"));
    setResumed(true);
    // 손님이 [견적서 열기] 뒤 뒤로 왔으면 하던 데까지 이어 가요(조건이 그대로일 때만, QA r7 N8)
    const step = mode === "guest" ? readStep() : null;
    if (step && step.key === g.key && !Object.keys(errorsOf(next, today)).length) void resume(next, step.answered);
  }, [wishes, roomRule, today, mode]);
  // 고칠 때마다 이 기기에 저장해요(손님 답 옮기기와 같은 저장소). 방 개수는 보이는 값으로 둬요
  useEffect(() => { if (dirty) writeGuest(withRooms(d, roomRule)); }, [d, dirty, roomRule]);
  // 새 말이 붙으면 아래로
  useEffect(() => { log.current?.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [phase, answered, again]);

  const set = (patch: Partial<InfoDraft>) => { setD((p) => ({ ...p, ...patch })); setDirty(true); setErr(null); };
  const errors = tried ? errorsOf(d, today) : {};
  const sido = regions.find((r) => r.id === d.sido);
  const rooms = shownRooms(d, roomRule);

  async function confirm() {
    setTried(true);
    if (Object.keys(errorsOf(d, today)).length || phase !== "confirm") return;
    setErr(null);
    const g = writeGuest(withRooms(d, roomRule));
    setPhase("calc");
    try {
      setStd(await calcGuest(toHomeInfo(withRooms(d, roomRule)), mock));
      setPick(d.diy ? (d.diy.length ? d.diy : ["none"]) : []);
      setAnswered(false);
      setPhase("done");
      if (mode === "guest") writeStep({ key: g.key, answered: false });
    } catch (e) {
      setErr(errorText(e));
      setPhase("confirm");
    }
  }

  /** [견적서 열기] 뒤 뒤로 왔어요: 표준견적서(서버 계산 엔진에 다시 물어요) · 고른 직접 할 일 · 가입 카드까지 이어 그려요.
   *  못 세면 확인 카드로 돌아가요 */
  async function resume(draft: InfoDraft, answeredBefore: boolean) {
    setPhase("calc");
    try {
      setStd(await calcGuest(toHomeInfo(withRooms(draft, roomRule)), mock));
      setPick(draft.diy ? (draft.diy.length ? draft.diy : ["none"]) : []);
      setAnswered(answeredBefore && !!draft.diy);
      setPhase("done");
      // 되돌아온 화면은 브라우저가 앞 스크롤 자리를 되살린 뒤에 끝까지 내려요(QA r8 u1 U2: 가입 단추가 화면 밖)
      window.setTimeout(() => log.current?.lastElementChild?.scrollIntoView({ block: "end" }), 120);
    } catch (e) {
      setErr(errorText(e));
      setPhase("confirm");
    }
  }

  // 직접 할 일: '없어요'는 다른 칩과 같이 고르지 않아요
  const toggle = (x: DiyPick) => setPick((p) => (p.includes(x) ? p.filter((y) => y !== x) : x === "none" ? ["none"] : [...p.filter((y) => y !== "none"), x]));

  /** 손님: 직접 할 일 답으로 표준견적서를 다시 세요(벽지 직접 구매면 도배지 줄 고객 구매). 가입 창 '표준견적서가 그대로 이어져요'가
   *  맞게, 가입 뒤 만드는 공사와 같은 답 · 같은 계산 엔진 값이에요(QA r3 v1 L8) */
  async function recount(next: InfoDraft) {
    setAgain({ std: null, busy: true, err: null });
    try {
      setAgain({ std: await calcGuest(toHomeInfo(withRooms(next, roomRule)), mock), busy: false, err: null });
    } catch (e) {
      setAgain({ std: null, busy: false, err: errorText(e) });
    }
  }

  async function answerDiy() {
    if (!pick.length || phase !== "done") return;
    const next: InfoDraft = { ...d, diy: DIY.map((x) => x.key).filter((key) => pick.includes(key)) };
    setD(next);
    const g = writeGuest(withRooms(next, roomRule));
    setAnswered(true);
    if (mode === "guest") {
      writeStep({ key: g.key, answered: true });
      // 예시(mock)는 직접 할 일을 계산하지 않아요
      if (!mock && std && buysPaper(next.diy) !== !!std.own_paper) void recount(next);
      return;
    }
    setPhase("creating");
    setErr(null);
    try {
      if (mock) {
        await resetMock(MOCK_PID, "f1");
        clearGuest();
        router.push(`/projects/${MOCK_PID}/standard`);
        return;
      }
      const p = await sendHome<Schemas["ProjectOut"]>("POST", "/projects", toHomeInfo(withRooms(next, roomRule)), { "Idempotency-Key": g.key });
      clearGuest();
      router.push(`/projects/${encodeURIComponent(p.id)}/standard`);
    } catch (e) {
      setErr(errorText(e));
      setPhase("done");
    }
  }

  function back() {
    setPhase("confirm");
    setStd(null);
    setAgain(null);
    setAnswered(false);
    setErr(null);
    writeStep(null);
  }

  const sgs = sido ? sido.groups.flatMap((g) => g.items.map((x) => ({ key: x, label: g.label ? `${g.prefix} ${x}` : x }))) : [];
  const locked = phase !== "confirm";
  const roomNums = Array.from({ length: roomRule.max - roomRule.min + 1 }, (_, i) => roomRule.min + i);

  return (
    <div className={s.shell}>
      <header className={s.top}>
        <div className={s.topIn}>
          <span className={s.webOnly}>
            <Link className={s.logo} href="/"><Logo />믿집</Link>
            <span className={s.pill}>AI 비서</span>
          </span>
          <span className={s.phoneOnly}>
            <Link className={s.iconBtn} href="/" aria-label="처음으로"><I n="back" /></Link>
            <h1 className={s.title}>새 공사 시작</h1>
          </span>
          <span className={s.spacer} />
          {mode === "guest" ? <Link className={s.textBtn} href="/login?next=%2Fstart">로그인</Link> : <Link className={s.textBtn} href="/my">내 공사</Link>}
        </div>
      </header>
      <div className={`${s.body} ${t.body}`}>
        <div className={s.col} id="main">
          <div className={s.thread}>
            <div ref={log} className={s.msgs} role="log" aria-label="첫 대화" aria-live="polite" aria-relevant="additions">
              <Bot>
                <span className={s.aiTag}><SourceTag src="guide" /></span>
                <p className={`${s.bubble} ${s.say}`}>
                  안녕하세요. 공사를 끝까지 챙기는 믿집 비서예요.{"\n"}{resumed ? "넣던 집 정보예요. 맞는지 확인해 주세요." : "우리 집 정보를 골라 주세요."}
                </p>
                <section className={locked ? `${k.card} ${k.done}` : k.card} aria-label="집 확인">
                  <div className={k.top}><h3>우리 집</h3><span className={k.muted}>아파트 · 도배</span></div>
                  <Field label="지역" id="st-region" error={errors.region}>
                    <div className={t.sels}>
                      <select id="st-region" className={c.sel} aria-label="시 · 도" value={d.sido} disabled={locked}
                        onChange={(e) => set({ sido: e.target.value, sgg: "" })}>
                        <option value="">시 · 도</option>
                        {regions.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </select>
                      <select className={c.sel} aria-label="시 · 군 · 구" value={d.sgg} disabled={locked || !sido} onChange={(e) => set({ sgg: e.target.value })}>
                        <option value="">시 · 군 · 구</option>
                        {sgs.map((x) => <option key={x.label} value={x.key}>{x.label}</option>)}
                      </select>
                    </div>
                  </Field>
                  <Field label="면적" id="st-area" error={errors.area}>
                    <div className={k.chips} id="st-area">
                      {PYEONG.map((p) => {
                        const m2 = pyeongToM2(p);
                        const on = !manual && d.basis === "supply" && d.area === m2;
                        return <button key={p} type="button" className={k.chip} aria-pressed={on} disabled={locked} onClick={() => { setManual(false); set({ area: m2 ?? "", basis: "supply" }); }}>{p}평형</button>;
                      })}
                      <button type="button" className={k.chip} aria-pressed={manual} disabled={locked} onClick={() => setManual(true)}>㎡로 넣기</button>
                    </div>
                    {manual ? (
                      <div className={t.sels}>
                        <select className={c.sel} aria-label="면적 기준" value={d.basis} disabled={locked} onChange={(e) => set({ basis: e.target.value === "exclusive" ? "exclusive" : "supply" })}>
                          <option value="supply">공급</option>
                          <option value="exclusive">전용</option>
                        </select>
                        <span className={c.ho}>
                          <input className={`${c.inp} ${k.num}`} inputMode="decimal" aria-label="면적(㎡)" placeholder="84.9" value={d.area} disabled={locked}
                            onChange={(e) => set({ area: e.target.value.replace(/[^\d.]/g, "").slice(0, 6) })} />㎡
                        </span>
                      </div>
                    ) : null}
                  </Field>
                  <Field label="방 개수" id="st-rooms">
                    <div className={k.chips} id="st-rooms">
                      {roomNums.map((n) => <Chip key={n} on={rooms === n} off={locked} onClick={() => set({ rooms: n })}>{n}개</Chip>)}
                    </div>
                  </Field>
                  <Field label="공사할 때 집" id="st-occ" error={errors.occupied}>
                    <div className={k.chips} id="st-occ">
                      <Chip on={d.occupied === true} off={locked} onClick={() => set({ occupied: true })}>살면서 공사</Chip>
                      <Chip on={d.occupied === false} off={locked} onClick={() => set({ occupied: false })}>빈 집</Chip>
                    </div>
                  </Field>
                  <Field label="벽지" id="st-grade" error={errors.grade}>
                    <div className={k.chips} id="st-grade">
                      <Chip on={d.grade === "basic"} off={locked} onClick={() => set({ grade: "basic" })}>실크</Chip>
                      <Chip on={d.grade === "economy"} off={locked} onClick={() => set({ grade: "economy" })}>합지</Chip>
                    </div>
                  </Field>
                  <Field label="철거 범위" id="st-demo" error={errors.demolition}>
                    <div className={k.chips} id="st-demo">
                      {DEMOLITION.map((x) => <Chip key={x.key} on={d.demolition === x.key} off={locked} onClick={() => set({ demolition: x.key })}>{x.label}</Chip>)}
                    </div>
                  </Field>
                  <Field label="공사 희망 시기" id="st-when" error={errors.when}>
                    <div className={k.chips} id="st-when">
                      {wishes.map((w) => <Chip key={w.key} on={d.when === w.key} off={locked} onClick={() => set({ when: w.key, start: w.start_date })}>{WISH_LABEL[w.key]}</Chip>)}
                      <Chip on={d.when === "unknown"} off={locked} onClick={() => set({ when: "unknown", start: null })}>아직 몰라요</Chip>
                      <Chip on={d.when === "date"} off={locked} onClick={() => setDateOpen(true)}>{d.when === "date" && d.start ? dateShort(d.start, today) : "날짜 고르기"}</Chip>
                    </div>
                  </Field>
                  {err && phase !== "done" && phase !== "creating" ? <p className={k.err} role="alert">{err}</p> : null}
                  {tried && Object.keys(errors).length ? <p className={k.err} role="alert">고를 칸이 {Object.keys(errors).length}개 있어요</p> : null}
                  {phase === "confirm" || phase === "calc" ? (
                    <div className={k.row}>
                      <button type="button" className={`${k.btn} ${k.pri}`} disabled={locked} aria-busy={phase === "calc" || undefined} onClick={() => { void confirm(); }}>
                        {phase === "calc" ? "계산하고 있어요" : "표준견적서 보기"}
                      </button>
                    </div>
                  ) : null}
                </section>
              </Bot>
              {(phase === "done" || phase === "creating") && std ? (
                <>
                  <Me>표준견적서 보여 주세요</Me>
                  <Bot>
                    <p className={`${s.bubble} ${s.say}`}>표준견적서가 나왔어요.</p>
                    <StandardSummary id="st-std" data={summaryOf(std, d, mode === "guest" ? "/start/standard" : "")}
                      more={<button type="button" className={`${k.text} ${k.gray}`} disabled={phase === "creating"} onClick={back}>조건 바꾸기</button>} />
                  </Bot>
                  <Bot>
                    <p className={`${s.bubble} ${s.say}`}>업체에 맡기지 않고 직접 할 일이 있어요? 여러 개 골라도 돼요.</p>
                    <section className={answered ? `${k.card} ${k.done}` : k.card} aria-labelledby="st-diy-t">
                      <div className={k.top}><h3 id="st-diy-t">직접 할 일</h3></div>
                      <div className={k.chips} role="group" aria-labelledby="st-diy-t">
                        {DIY.map((x) => <Chip key={x.key} on={pick.includes(x.key)} off={answered} onClick={() => toggle(x.key)}>{x.label}</Chip>)}
                        <Chip on={pick.includes("none")} off={answered} onClick={() => toggle("none")}>없어요</Chip>
                      </div>
                      {answered ? null : (
                        <div className={k.row}>
                          <button type="button" className={`${k.btn} ${k.pri}`} disabled={!pick.length} onClick={() => { void answerDiy(); }}>골랐어요</button>
                        </div>
                      )}
                    </section>
                  </Bot>
                  {answered && d.diy ? <Me>{diyText(d.diy)}</Me> : null}
                  {answered && mode === "guest" && again ? (
                    <Bot>
                      {again.std ? (
                        <>
                          <p className={`${s.bubble} ${s.say}`}>{again.std.own_paper ? "벽지를 직접 사시니 벽지 값을 빼고 다시 셌어요." : "벽지 값을 넣어 다시 셌어요."}</p>
                          <StandardSummary id="st-std2" data={summaryOf(again.std, d, "/start/standard")} />
                        </>
                      ) : again.busy ? (
                        <p className={`${s.bubble} ${s.say}`} role="status">표준견적서를 다시 계산하고 있어요.</p>
                      ) : (
                        <div className={k.row}>
                          <p className={k.err} role="alert">{again.err}</p>
                          <button type="button" className={`${k.btn} ${k.sm}`} onClick={() => { void recount(d); }}>다시 해 보기</button>
                        </div>
                      )}
                    </Bot>
                  ) : null}
                  {answered && mode === "guest" && !again?.busy ? (
                    <Bot>
                      <section className={k.card} aria-labelledby="st-join-t">
                        <div className={k.top}><h3 id="st-join-t">가입하고 이어서 해요</h3></div>
                        <p className={k.muted}>업체 추천 · 실측 요청은 가입하면 열려요. 넣은 답이 그대로 이어져요</p>
                        <div className={k.row}>
                          <button type="button" className={`${k.btn} ${k.pri}`} onClick={() => setJoin(true)}>가입하고 이어 하기</button>
                          {mock ? (
                            <button type="button" className={`${k.btn} ${k.sm}`} onClick={() => { void resetMock(MOCK_PID, "f1").then(() => router.push(`/projects/${MOCK_PID}`)); }}>예시 공사로 이어 보기</button>
                          ) : null}
                        </div>
                      </section>
                    </Bot>
                  ) : null}
                  {mode === "member" && (phase === "creating" || err) ? (
                    <Bot>
                      {phase === "creating" ? (
                        <p className={`${s.bubble} ${s.say}`} role="status">내 공사를 만들고 있어요.</p>
                      ) : (
                        <div className={k.row}>
                          <p className={k.err} role="alert">{err}</p>
                          <button type="button" className={`${k.btn} ${k.sm}`} onClick={() => { setAnswered(false); setErr(null); }}>다시 해 보기</button>
                        </div>
                      )}
                    </Bot>
                  ) : null}
                </>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      <DateSheet open={dateOpen} value={d.when === "date" ? d.start : null} today={today} onClose={() => setDateOpen(false)}
        onApply={(day) => { set({ when: "date", start: day }); setDateOpen(false); }} />
      <JoinDialog open={join} onClose={() => setJoin(false)} />
    </div>
  );
}

function Bot({ children }: { children: React.ReactNode }) {
  return (
    <div className={`${s.msg} ${s.enter}`}>
      <div className={s.av} aria-hidden="true">AI</div>
      <div className={s.msgBody}>{children}</div>
    </div>
  );
}
function Me({ children }: { children: React.ReactNode }) {
  return <div className={`${s.msg} ${s.me}`}><div className={s.msgBody}><p className={s.bubble}>{children}</p></div></div>;
}
function Field({ label, id, error, children }: { label: string; id: string; error?: string; children: React.ReactNode }) {
  return (
    <div className={c.field} role="group" aria-labelledby={`${id}-l`}>
      <span className={c.lbl} id={`${id}-l`}>{label}</span>
      {children}
      {error ? <span className={k.err}>{error}</span> : null}
    </div>
  );
}
function Chip({ on, off, onClick, children }: { on: boolean; off: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" className={k.chip} aria-pressed={on} disabled={off} onClick={onClick}>{children}</button>;
}
