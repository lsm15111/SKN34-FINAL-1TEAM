"use client";
// /start 첫 대화(새로 시작): 단계 띠(우리 집 · 원하는 공사 · 표준견적서)를 [다음]으로 한 걸음씩 가요(2026-11-24 사용자: 바로 표준견적서로 넘어가지 않게).
//   손님은 표준견적서 요약 → 가입 카드, 로그인한 고객은 내 공사를 만들어 그 공사 표준견적서로 가요. 글 입력 칸은 두지 않아요(11-23 사용자).
// - 처음 받는 기본 정보 7개(2026-11-21 사용자 결정): 우리 집(지역 · 면적 · 방 개수 · 공사할 때 집) → 원하는 공사(벽지 · 철거 범위 ·
//   공사 희망 시기). 직접 할 일은 여기서 묻지 않아요(2026-11-24 사용자: 추후에. 공사의 기본 정보 고치기에서 받아요).
// - 처음 고객이 모를 말(공급 · 전용 면적 · 실크 · 합지 · 철거 범위)은 칸 이름 옆 '?'로 그 자리에서 풀어요(TermHelp, 백과 용어는 용어 칸까지).
// - 면적은 고치기 화면(InfoForm)과 같은 칸 · 같은 함수예요: 기준(공급 | 전용) + 넣는 칸 + 단위(㎡ | 평, 평이면 '믿집 계산'으로 ㎡).
//   평형 칩은 두지 않아요(QA r9: 두 입구의 넣는 법을 하나로 · copy-guide U10 ㎡ 기본, 평은 넣을 때 돕기만).
// - 머리는 다른 화면과 같은 사이트 머리예요(siteHeader, 페이지가 그려 넘겨요: 웹 메뉴로 백과 · 자주 묻는 질문, 폰은 ‹ 새 공사 시작).
// - 넣는 중인 답은 마지막 [다음] 전에는 저장하지 않아요. 그 사이 다른 화면으로 가려 하면 '입력한 정보는 저장되지 않아요' 창(useLeaveGuard).
// - AI 글은 쓰지 않아요(로그인 전 · 공사 전). 말은 정해 둔 글('믿집 안내')이고, 금액 · 일수 · 시기 칩 날짜는 계산 엔진 값
//   (POST /guest/standard · GET /guest/start-options)이에요. 방 개수는 면적 기본값(GET /guest/room-rule)을 미리 골라 두고 보이는 값을 보내요.
//   방 개수 표를 못 읽었으면 미리 고르지 않고, 고객이 안 골랐으면 비워 보내요(서버가 면적 기본값으로 세요).
// - 손님: 마지막 [다음]에 답을 이 기기에 둬요(mj_guest_v3) → 표준견적서 요약 → 가입 카드. 가입하면 같은 답으로 내 공사가 만들어져요(auth/after).
//   표준견적서까지 왔는지는 이 탭에 둬서 [견적서 열기] 뒤 뒤로 와도 이어 가요(QA r7 N8). 금액은 두지 않고 다시 물어요.
// - 로그인한 고객: 마지막 [다음]에 POST /projects(Idempotency-Key = 기기 답 key) → /v5/projects/{id}/standard.
// - v5(dev 백엔드 위): 기능 확인(caps.v4, lib/v5/caps.ts)이 꺼져 있으면 방 개수 · 철거 범위 칸을 그리지 않고 몸통에도 넣지 않아요.
//   공사 희망 시기 칩도 없어서(빈 wishes) '아직 몰라요 · 날짜 고르기'만 보여요. 벽지는 dev도 받는 칸이라 '원하는 공사' 카드에 그대로 둬요.
// - 전체 도배 요약은 [견적서 열기](/v5/start/standard)와 같은 시장 단가 표준견적서(POST /v2/market-quote) 금액 · 큰 줄이에요.
//   공사 일수는 표준견적서 값(dev 내 공사 표준견적서와 같은 묶음)이고, 시장 단가를 못 받으면 표준견적서 금액 그대로예요.
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { JoinDialog } from "@/components/v5/auth/JoinDialog";
import { CalcBox } from "@/components/ui/CalcBox";
import { Field as NumField } from "@/components/ui/Field";
import { Segmented } from "@/components/ui/Segmented";
import type { Region } from "@/lib/v5/api/project";
import { call, errorText } from "@/lib/backend/client";
import { toMarketIn, type MqOut } from "@/lib/guest/market";
import type { Schemas } from "@/lib/v5/types";
import { dateShort, decText } from "@/lib/v5/format";
import { calcGuest, sendHome, type GuestStandard } from "@/lib/v5/guest/api";
import {
  areaOfPyeong, checkDraft, DEMOLITION, EMPTY_DRAFT, GRADE_WORD, PYEONG_M2, pyeongError, pyeongOf, pyeongToM2, roomsOf, toHomeInfo, WISH_LABEL,
  type AreaUnit, type HomeBody, type InfoDraft, type RoomRule, type StartWish,
} from "@/lib/v5/guest/info";
import { toQuoteLines } from "@/lib/v5/guest/standard";
import { clearGuest, draftOf, readGuest, writeGuest } from "@/lib/v5/guest/store";
import { DateSheet } from "@/components/start/DateSheet";
import { SourceTag, StandardSummary, type StandardQuoteData } from "./StandardSummary";
import { TermHelp, type StartTip } from "./TermHelp";
import { useLeaveGuard } from "./useLeaveGuard";
import type { Caps } from "@/lib/v5/caps";
import t from "./start.module.css";

type Phase = "home" | "work" | "calc" | "creating" | "done";
/** [다음]으로 넘기는 카드: 우리 집 · 원하는 공사 */
type Step = "home" | "work";
const STEPS = ["우리 집", "원하는 공사", "표준견적서"] as const;
const stepAt = (p: Phase) => (p === "home" ? 0 : p === "done" ? 2 : 1);
/** 개발 예시(mock) 공사: lib/mock/v3a/mode MOCK_PROJECT.full */
const MOCK_PID = "a3a00000-0000-4000-8000-000000000001";
/** 철거 범위는 백과 용어가 없어서 두 줄로 풀어요 */
const DEMOLITION_NOTE = "집 안 마감(벽지 · 바닥 · 몰딩 등)을 뜯어내는 범위예요. 집 전체를 뜯고 새로 고치면 '전체 철거'예요.";

/** 손님 표준견적서 → 요약 카드 값(큰 줄 몇 개는 계산 엔진 줄 금액 그대로 골라 보여요). href가 비면 열기 단추를 빼요.
 *  mq(시장 단가)가 있으면 금액 · 큰 줄은 그 값이에요 */
function summaryOf(g: GuestStandard, d: InfoDraft, href: string, mq: MqOut | null): StandardQuoteData {
  const lines = mq
    ? mq.trades.flatMap((t) => t.lines).filter((l) => l.amount > 0).sort((a, b) => b.amount - a.amount).slice(0, 3).map((l) => ({ name: l.name, won: l.amount }))
    : toQuoteLines(g.lines, g.scope)
      .filter((l) => (l.state === "included" || l.state === "separate") && (l.amount ?? 0) > 0)
      .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
      .slice(0, 3)
      .map((l) => ({ name: l.name, won: l.amount ?? 0 }));
  // 벽지 직접 구매면 '벽지 고객 구매'를 붙여요(도배지 줄은 합계 밖, 계산 엔진)
  const label = [
    "도배", d.grade ? GRADE_WORD[d.grade] : null, `${g.area_basis === "exclusive" ? "전용" : "공급"} ${decText(g.area_m2)}㎡`, g.own_paper ? "벽지 고객 구매" : null,
  ].filter(Boolean).join(" · ");
  return { total_won: mq?.total ?? g.total, label, lines, days: g.days, partial: g.scope === "partial", href };
}

/** 보이는 방 개수: 고른 값, 없으면 면적 기본값. 방 개수 표를 못 읽었으면(기본값 표 없음) 미리 고르지 않아요(null) */
const shownRooms = (d: InfoDraft, rule: RoomRule): number | null => d.rooms ?? (rule.bands.length ? roomsOf(d, rule) : null);
/** 보이는 방 개수를 답에 넣어요(면적 기본값으로 미리 골라 둔 칩도 고객이 보고 넘긴 값이에요). 비었으면 서버가 면적 기본값으로 세요
 *  (표를 못 읽은 fallback 3을 고른 값으로 보내 서버 기본값을 덮지 않게) */
const withRooms = (d: InfoDraft, rule: RoomRule): InfoDraft => ({ ...d, rooms: shownRooms(d, rule) });

/** 손님 첫 대화를 표준견적서까지 했는지(이 탭에만): 그때 기기 답 key(조건이 바뀌면 key도 바뀌어요) */
const STEP_KEY = "mj_start_step";
type StartStep = { key: string };
function readStep(): StartStep | null {
  try {
    const x: unknown = JSON.parse(window.sessionStorage.getItem(STEP_KEY) ?? "null");
    return x && typeof x === "object" && typeof (x as StartStep).key === "string" ? (x as StartStep) : null;
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

type ErrKey = "region" | "area" | "occupied" | "grade" | "demolition" | "when";
type Errors = Partial<Record<ErrKey, string>>;
/** 카드마다 [다음]에서 보는 칸 */
const STEP_KEYS: Record<Step, ErrKey[]> = { home: ["region", "area", "occupied"], work: ["grade", "demolition", "when"] };
function errorsOf(d: InfoDraft, today: string, caps: Caps): Errors {
  const e = checkDraft(d);
  return {
    ...(e.region ? { region: "지역을 골라 주세요." } : {}),
    ...(e.area ? { area: e.area } : {}),
    ...(e.occupied ? { occupied: e.occupied } : {}),
    ...(e.grade ? { grade: e.grade } : {}),
    ...(caps.v4 && !d.demolition ? { demolition: "철거 범위를 골라 주세요." } : {}),
    ...(!d.when ? { when: "공사 희망 시기를 골라 주세요." } : d.when === "date" && (!d.start || d.start < today) ? { when: "오늘 이후 날짜를 골라 주세요." } : {}),
  };
}
const errorsIn = (e: Errors, step: Step): Errors => Object.fromEntries(STEP_KEYS[step].filter((x) => e[x]).map((x) => [x, e[x]]));

export function StartChat({ regions, roomRule, wishes, today, mode, mock, tips, siteHeader, caps }: {
  regions: Region[];
  /** 기능 확인(서버): 꺼져 있으면 방 개수 · 철거 범위를 묻지 않아요 */
  caps: Caps;
  roomRule: RoomRule;
  /** 공사 희망 시기 칩 → 날짜(계산 엔진). 못 읽었으면 빈 목록(아직 몰라요 · 날짜 고르기만) */
  wishes: StartWish[];
  /** 서울 오늘 "2026-11-21" */
  today: string;
  mode: "guest" | "member";
  mock: boolean;
  /** 칸 이름 옆 '?' 풀이(백과 용어 사전 글, 페이지가 골라 넘겨요) */
  tips: { area: StartTip[]; grade: StartTip[] };
  /** 사이트 공통 머리(웹 메뉴 · 폰 ‹ 새 공사 시작, 페이지가 그려 넘겨요) */
  siteHeader: ReactNode;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("home");
  /** 이 기기에 둔 답을 카드에 이어 채웠어요(첫 말이 '넣던 집 정보예요') */
  const [resumed, setResumed] = useState(false);
  const [d, setD] = useState<InfoDraft>(EMPTY_DRAFT);
  /** 저장 전에 고친 답이 있어요(나가기 경고) */
  const [dirty, setDirty] = useState(false);
  const [tried, setTried] = useState<Record<Step, boolean>>({ home: false, work: false });
  const [std, setStd] = useState<GuestStandard | null>(null);
  /** 전체 도배 시장 단가(못 받으면 null, 표준견적서 금액 그대로) */
  const [mq, setMq] = useState<MqOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [join, setJoin] = useState(false);
  /** 면적 칸 단위와 평으로 넣는 글(칸에는 평, 답에는 바꾼 ㎡). 처음은 ㎡(U10) */
  const [unit, setUnit] = useState<AreaUnit>("m2");
  const [py, setPy] = useState("");
  const [dateOpen, setDateOpen] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const restored = useRef(false);
  const homeHead = useRef<HTMLHeadingElement>(null);
  const workHead = useRef<HTMLHeadingElement>(null);
  /** [다음] · [이전] 뒤 초점을 옮길 카드 */
  const focusTo = useRef<Step | null>(null);
  const guard = useLeaveGuard(dirty);

  // 이 기기에 둔 답이 있으면 카드에 이어 채워요(처음 한 번). 칩으로 고른 시기는 오늘 기준 날짜로 다시 맞추고,
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
    setResumed(true);
    // 손님이 [견적서 열기] 뒤 뒤로 왔으면 표준견적서까지 이어 가요(조건이 그대로일 때만, QA r7 N8)
    const step = mode === "guest" ? readStep() : null;
    if (step && step.key === g.key && !Object.keys(errorsOf(next, today, caps)).length) void resume(next);
  }, [wishes, roomRule, today, mode, caps]);
  // 새 말이 붙거나 카드를 되돌리면 그 끝으로
  useEffect(() => { log.current?.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [phase]);
  // [다음] · [이전]으로 넘긴 카드 제목에 초점(화면 읽기 프로그램이 새 카드를 읽어요)
  useEffect(() => {
    const to = focusTo.current;
    if (!to || phase !== to) return;
    focusTo.current = null;
    (to === "home" ? homeHead : workHead).current?.focus({ preventScroll: true });
  }, [phase]);

  const set = (patch: Partial<InfoDraft>) => { setD((p) => ({ ...p, ...patch })); setDirty(true); setErr(null); };
  const all = errorsOf(d, today, caps);
  const eHome = tried.home ? errorsIn(all, "home") : {};
  const eWork = tried.work ? errorsIn(all, "work") : {};
  const sido = regions.find((r) => r.id === d.sido);
  const rooms = shownRooms(d, roomRule);
  // 면적(고치기 화면과 같아요): 평이면 칸 글은 평 그대로 두고 답에는 바꾼 ㎡를 넣어요. 검사는 ㎡로, 오류 글은 평 말로
  const setArea = (v: string) => {
    if (unit === "m2") { set({ area: v }); return; }
    setPy(v);
    set({ area: areaOfPyeong(v) });
  };
  const switchUnit = (v: string) => {
    const next: AreaUnit = v === "py" ? "py" : "m2";
    if (next === unit) return;
    if (next === "py") setPy(pyeongOf(d.area));
    setUnit(next);
  };
  const areaM2 = unit === "py" ? pyeongToM2(py) : null;
  const areaErr = eHome.area && unit === "py" ? pyeongError(py) : eHome.area;
  const unitWord = unit === "py" ? "평" : "㎡";

  function nextHome() {
    setTried((x) => ({ ...x, home: true }));
    if (phase !== "home" || Object.keys(errorsIn(errorsOf(d, today, caps), "home")).length) return;
    focusTo.current = "work";
    setPhase("work");
  }

  function prevWork() {
    if (phase !== "work") return;
    setErr(null);
    focusTo.current = "home";
    setPhase("home");
  }

  /** 마지막 [다음]: 답을 저장하고(나가기 경고를 놓아줘요) 손님은 표준견적서를 세고, 로그인한 고객은 내 공사를 만들어요 */
  async function nextWork() {
    setTried((x) => ({ ...x, work: true }));
    if (phase !== "work" || Object.keys(errorsIn(errorsOf(d, today, caps), "work")).length) return;
    setErr(null);
    setPhase(mode === "member" ? "creating" : "calc");
    await guard.release();
    const body = withRooms(d, roomRule);
    const g = writeGuest(body);
    setDirty(false);
    if (mode === "member") {
      try {
        if (mock) {
          clearGuest();
          router.push(`/v5/projects/${MOCK_PID}/standard`);
          return;
        }
        const p = await sendHome<Schemas["ProjectOut"]>("POST", "/projects", toHomeInfo(body, caps), { "Idempotency-Key": g.key });
        clearGuest();
        router.push(`/v5/projects/${encodeURIComponent(p.id)}/standard`);
      } catch (e) {
        setErr(errorText(e));
        setPhase("work");
      }
      return;
    }
    try {
      await calc(toHomeInfo(body, caps));
      setPhase("done");
      writeStep({ key: g.key });
    } catch (e) {
      setErr(errorText(e));
      setPhase("work");
    }
  }

  /** 손님 표준견적서 계산 + 전체 도배면 시장 단가(견적서 열기와 같은 금액). 시장 단가가 실패해도 표준견적서로 보여요 */
  async function calc(info: HomeBody) {
    const market = info.scope === "full" && !mock ? call<MqOut>("POST", "/v2/market-quote", toMarketIn(info)).catch(() => null) : Promise.resolve(null);
    const [g, m] = await Promise.all([calcGuest(info, mock), market]);
    setStd(g);
    setMq(m);
  }

  /** [견적서 열기] 뒤 뒤로 왔어요: 표준견적서(서버 계산 엔진에 다시 물어요) · 가입 카드까지 이어 그려요. 못 세면 원하는 공사 카드로 */
  async function resume(draft: InfoDraft) {
    setPhase("calc");
    try {
      await calc(toHomeInfo(withRooms(draft, roomRule), caps));
      setPhase("done");
      // 되돌아온 화면은 브라우저가 앞 스크롤 자리를 되살린 뒤에 끝까지 내려요(QA r8 u1 U2: 가입 단추가 화면 밖)
      window.setTimeout(() => log.current?.lastElementChild?.scrollIntoView({ block: "end" }), 120);
    } catch (e) {
      setErr(errorText(e));
      setPhase("work");
    }
  }

  /** 표준견적서 '조건 바꾸기': 원하는 공사 카드로 돌아가요(우리 집은 [이전]) */
  function back() {
    setPhase("work");
    setStd(null);
    setMq(null);
    setErr(null);
    writeStep(null);
    focusTo.current = "work";
  }

  const sgs = sido ? sido.groups.flatMap((g) => g.items.map((x) => ({ key: x, label: g.label ? `${g.prefix} ${x}` : x }))) : [];
  const homeOff = phase !== "home";
  const workOff = phase !== "work";
  const busy = phase === "calc" || phase === "creating";
  const roomNums = Array.from({ length: roomRule.max - roomRule.min + 1 }, (_, i) => roomRule.min + i);
  const nHome = Object.keys(eHome).length;
  const nWork = Object.keys(eWork).length;

  return (
    <div className={t.shell}>
      {siteHeader}
      <div className={t.body}>
        <div className={t.col} id="main">
          <div className={t.thread}>
            <StartSteps now={stepAt(phase)} />
            <div ref={log} className={t.msgs} role="log" aria-label="첫 대화" aria-live="polite" aria-relevant="additions">
              <Bot>
                <span className={t.aiTag}><SourceTag src="guide" /></span>
                <p className={`${t.bubble} ${t.say}`}>
                  안녕하세요. 믿집이에요.{"\n"}{resumed ? "넣던 집 정보예요. 맞는지 확인해 주세요." : "우리 집 정보를 골라 주세요."}
                </p>
                <section className={homeOff ? `${t.card} ${t.done}` : t.card} aria-labelledby="st-home-t">
                  <div className={t.top}><h3 id="st-home-t" ref={homeHead} tabIndex={-1}>우리 집</h3><span className={t.muted}>아파트 · 도배</span></div>
                  <Field label="지역" id="st-region" error={eHome.region}>
                    <div className={t.sels}>
                      <select id="st-region" className={t.sel} aria-label="시 · 도" value={d.sido} disabled={homeOff}
                        onChange={(e) => set({ sido: e.target.value, sgg: "" })}>
                        <option value="">시 · 도</option>
                        {regions.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </select>
                      <select className={t.sel} aria-label="시 · 군 · 구" value={d.sgg} disabled={homeOff || !sido} onChange={(e) => set({ sgg: e.target.value })}>
                        <option value="">시 · 군 · 구</option>
                        {sgs.map((x) => <option key={x.label} value={x.key}>{x.label}</option>)}
                      </select>
                    </div>
                  </Field>
                  <Field label="면적" id="st-area" error={areaErr} help={<TermHelp label="면적" tips={tips.area} />}>
                    <Segmented legend="면적 기준" hideLegend value={d.basis} disabled={homeOff} onChange={(v) => set({ basis: v === "exclusive" ? "exclusive" : "supply" })}
                      options={[{ value: "supply", label: "공급면적" }, { value: "exclusive", label: "전용면적" }]} />
                    <div className={t.areaRow}>
                      <NumField id="st-area" label={`${d.basis === "exclusive" ? "전용" : "공급"}면적(${unitWord})`} hideLabel unit={unitWord} num maxLength={8} disabled={homeOff}
                        value={unit === "py" ? py : d.area} aria-invalid={areaErr ? true : undefined} onChange={(e) => setArea(e.target.value)} />
                      <Segmented legend="면적 단위" hideLegend className={t.unit} value={unit} disabled={homeOff} onChange={switchUnit}
                        options={[{ value: "m2", label: "㎡" }, { value: "py", label: "평" }]} />
                    </div>
                    {areaM2 ? (
                      <CalcBox tone="form" lines={[{ terms: [{ n: py.trim(), unit: "평" }, "×", { n: String(PYEONG_M2) }], result: { n: areaM2, unit: "㎡" } }]} />
                    ) : null}
                  </Field>
                  {caps.v4 ? (
                    <Field label="방 개수" id="st-rooms">
                      <div className={t.chips} id="st-rooms">
                        {roomNums.map((n) => <Chip key={n} on={rooms === n} off={homeOff} onClick={() => set({ rooms: n })}>{n}개</Chip>)}
                      </div>
                    </Field>
                  ) : null}
                  <Field label="공사할 때 집" id="st-occ" error={eHome.occupied}>
                    <div className={t.chips} id="st-occ">
                      <Chip on={d.occupied === true} off={homeOff} onClick={() => set({ occupied: true })}>살면서 공사</Chip>
                      <Chip on={d.occupied === false} off={homeOff} onClick={() => set({ occupied: false })}>빈 집</Chip>
                    </div>
                  </Field>
                  {phase === "home" ? (
                    <>
                      {nHome ? <p className={t.err} role="alert">고를 칸이 {nHome}개 있어요</p> : null}
                      <div className={t.row}>
                        <button type="button" className={`${t.btn} ${t.pri}`} onClick={nextHome}>다음</button>
                      </div>
                    </>
                  ) : null}
                </section>
              </Bot>
              {phase !== "home" ? (
                <Bot>
                  <p className={`${t.bubble} ${t.say}`}>원하는 공사를 골라 주세요.</p>
                  <section className={workOff ? `${t.card} ${t.done}` : t.card} aria-labelledby="st-work-t">
                    <div className={t.top}><h3 id="st-work-t" ref={workHead} tabIndex={-1}>원하는 공사</h3></div>
                    <Field label="벽지" id="st-grade" error={eWork.grade} help={<TermHelp label="벽지" tips={tips.grade} />}>
                      <div className={t.chips} id="st-grade">
                        <Chip on={d.grade === "basic"} off={workOff} onClick={() => set({ grade: "basic" })}>실크</Chip>
                        <Chip on={d.grade === "economy"} off={workOff} onClick={() => set({ grade: "economy" })}>합지</Chip>
                      </div>
                    </Field>
                    {caps.v4 ? (
                      <Field label="철거 범위" id="st-demo" error={eWork.demolition} help={<TermHelp label="철거 범위" note={DEMOLITION_NOTE} />}>
                        <div className={t.chips} id="st-demo">
                          {DEMOLITION.map((x) => <Chip key={x.key} on={d.demolition === x.key} off={workOff} onClick={() => set({ demolition: x.key })}>{x.label}</Chip>)}
                        </div>
                      </Field>
                    ) : null}
                    <Field label="공사 희망 시기" id="st-when" error={eWork.when}>
                      <div className={t.chips} id="st-when">
                        {wishes.map((w) => <Chip key={w.key} on={d.when === w.key} off={workOff} onClick={() => set({ when: w.key, start: w.start_date })}>{WISH_LABEL[w.key]}</Chip>)}
                        <Chip on={d.when === "unknown"} off={workOff} onClick={() => set({ when: "unknown", start: null })}>아직 몰라요</Chip>
                        <Chip on={d.when === "date"} off={workOff} onClick={() => setDateOpen(true)}>{d.when === "date" && d.start ? dateShort(d.start, today) : "날짜 고르기"}</Chip>
                      </div>
                    </Field>
                    {phase !== "done" ? (
                      <>
                        {err ? <p className={t.err} role="alert">{err}</p> : null}
                        {nWork ? <p className={t.err} role="alert">고를 칸이 {nWork}개 있어요</p> : null}
                        <div className={t.row}>
                          <button type="button" className={t.btn} disabled={busy} onClick={prevWork}>이전</button>
                          <button type="button" className={`${t.btn} ${t.pri}`} disabled={busy} aria-busy={busy || undefined} onClick={() => { void nextWork(); }}>
                            {phase === "calc" ? "계산하고 있어요" : phase === "creating" ? "내 공사를 만들고 있어요" : "다음"}
                          </button>
                        </div>
                      </>
                    ) : null}
                  </section>
                </Bot>
              ) : null}
              {phase === "done" && std ? (
                <Bot>
                  <p className={`${t.bubble} ${t.say}`}>표준견적서가 나왔어요.</p>
                  <StandardSummary id="st-std" data={summaryOf(std, d, mode === "guest" ? "/v5/start/standard" : "", mq)}
                    more={<button type="button" className={`${t.text} ${t.gray}`} onClick={back}>조건 바꾸기</button>} />
                </Bot>
              ) : null}
              {phase === "done" && std && mode === "guest" ? (
                <Bot>
                  <section className={t.card} aria-labelledby="st-join-t">
                    <div className={t.top}><h3 id="st-join-t">가입하고 이어서 해요</h3></div>
                    <p className={t.muted}>업체 추천 · 실측 요청은 가입하면 열려요. 넣은 답이 그대로 이어져요</p>
                    <div className={t.row}>
                      <button type="button" className={`${t.btn} ${t.pri}`} onClick={() => setJoin(true)}>가입하고 이어 하기</button>
                    </div>
                  </section>
                </Bot>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      <DateSheet open={dateOpen} value={d.when === "date" ? d.start : null} today={today} onClose={() => setDateOpen(false)}
        onApply={(day) => { set({ when: "date", start: day }); setDateOpen(false); }} />
      <JoinDialog open={join} onClose={() => setJoin(false)} />
      {guard.dialog}
    </div>
  );
}

/** 단계 띠(공사 화면 단계 띠와 같은 모양): 지난 칸 검정 · 지금 칸 파랑 · 앞 칸 흐림. 누르는 칸은 없어요(되돌리기는 [이전] · 조건 바꾸기) */
function StartSteps({ now }: { now: number }) {
  return (
    <div className={t.stepper}>
      <ol className={t.steps} aria-label="견적 받기 단계">
        {STEPS.map((label, i) => (
          <li key={label} className={`${t.step} ${i < now ? t.stepDone : i === now ? t.stepNow : t.stepLater}`} aria-current={i === now ? "step" : undefined}>
            {label}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Bot({ children }: { children: ReactNode }) {
  return (
    <div className={`${t.msg} ${t.enter}`}>
      <div className={t.av} aria-hidden="true">AI</div>
      <div className={t.msgBody}>{children}</div>
    </div>
  );
}
function Field({ label, id, error, help, children }: { label: string; id: string; error?: string; help?: ReactNode; children: ReactNode }) {
  return (
    <div className={t.field} role="group" aria-labelledby={`${id}-l`}>
      <span className={t.lblRow}><span className={t.lbl} id={`${id}-l`}>{label}</span>{help}</span>
      {children}
      {error ? <span className={t.err}>{error}</span> : null}
    </div>
  );
}
function Chip({ on, off, onClick, children }: { on: boolean; off: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" className={t.chip} aria-pressed={on} disabled={off} onClick={onClick}>{children}</button>;
}
