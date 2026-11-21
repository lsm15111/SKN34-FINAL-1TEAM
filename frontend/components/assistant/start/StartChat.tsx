"use client";
// /start 첫 대화(v4): 주소 · 단지 이름(글) → 집 확인 카드 → 표준견적서 → 직접 할 일 칩(한 번) → 가입 카드 · 내 공사 만들기.
// - 처음 받는 기본 정보 8개(2026-11-21 사용자 결정): 집 확인 카드 7칸(지역 · 면적 · 방 개수 · 공사할 때 집 · 벽지 · 철거 범위 ·
//   공사 희망 시기) + 표준견적서 바로 뒤 직접 할 일(반셀프 칩). 그 밖의 조건(편한 요일 · 목공 세부 · 우선순위)은 필요한 단계에서 비서가 물어요.
// - AI 글은 쓰지 않아요(로그인 전 · 공사 전). 말은 정해 둔 글('믿집 안내')이고, 금액 · 일수 · 시기 칩 날짜는 계산 엔진 값
//   (POST /guest/standard · GET /guest/start-options)이에요. 방 개수는 면적 기본값(GET /guest/room-rule)을 미리 골라 두고 보이는 값을 보내요.
// - 주소 찾기 API는 범위 밖이라 적은 글에서 시 · 군 · 구 · 평형 · 방 개수 · 공사할 때 집 · 시기만 찾아 채워요(lib/guest/guess, 못 찾으면 골라요).
//   적은 글 · 단지 이름 · 동 · 호는 저장하지 않아요.
// - 손님: 답은 이 기기에만(mj_guest_v3) → 표준견적서 요약 · 직접 할 일 → 가입 카드. 가입하면 같은 답으로 내 공사가 만들어져요(auth/after).
// - 로그인한 고객: 직접 할 일까지 고르면 POST /projects(Idempotency-Key = 기기 답 key, 직접 할 일도 한 번에) → /projects/{id}/standard.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { JoinDialog } from "@/components/auth/JoinDialog";
import { DateSheet } from "@/components/start/DateSheet";
import { DEMOLITION, resetMock, type StandardQuoteData } from "@/lib/api/assistant";
import type { Region } from "@/lib/api/project";
import { errorText, type Schemas } from "@/lib/backend/client";
import { dateShort, decText, euro } from "@/lib/format";
import { calcGuest, sendHome, type GuestStandard } from "@/lib/guest/api";
import { guessArea, guessOccupied, guessRooms, guessWhen } from "@/lib/guest/guess";
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

type Phase = "ask" | "confirm" | "calc" | "done" | "creating";
const PYEONG = ["24", "32", "34", "40"];
const MOCK_PID = "a3a00000-0000-4000-8000-000000000001";
type DiyPick = DiyKey | "none";

/** 적은 글에서 시 · 군 · 구 찾기(시 · 도 이름이 같이 있으면 그쪽). 둘 이상이 같은 점수면 고르게 해요 */
export function guessRegion(text: string, regions: Region[]): { sido: string; sgg: string } | null {
  const q = text.replace(/\s+/g, "");
  const hits: { sido: string; sgg: string; score: number }[] = [];
  for (const r of regions) {
    for (const g of r.groups) {
      for (const sgg of g.items) {
        const short = sgg.length > 2 ? sgg.slice(0, -1) : "";
        let score = q.includes(sgg) ? 2 : short && q.includes(short) ? 1 : 0;
        if (!score) continue;
        if ((g.prefix && q.includes(g.prefix)) || q.includes(r.name) || q.includes(r.full)) score += 2;
        hits.push({ sido: r.id, sgg, score });
      }
    }
  }
  hits.sort((a, b) => b.score - a.score);
  if (!hits.length || (hits[1] && hits[1].score === hits[0].score)) return null;
  return { sido: hits[0].sido, sgg: hits[0].sgg };
}

/** 손님 표준견적서 → 요약 카드 값(큰 줄 몇 개는 계산 엔진 줄 금액 그대로 골라 보여요). href가 비면 열기 단추를 빼요 */
function summaryOf(g: GuestStandard, d: InfoDraft, href: string): StandardQuoteData {
  const lines = toQuoteLines(g.lines, g.scope)
    .filter((l) => (l.state === "included" || l.state === "separate") && (l.amount ?? 0) > 0)
    .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
    .slice(0, 3)
    .map((l) => ({ name: l.name, won: l.amount ?? 0 }));
  const label = ["도배", d.grade ? GRADE_WORD[d.grade] : null, `${g.area_basis === "exclusive" ? "전용" : "공급"} ${decText(g.area_m2)}㎡`].filter(Boolean).join(" · ");
  return { total_won: g.total, label, lines, days: g.days, partial: g.scope === "partial", href };
}

/** 보이는 방 개수를 답에 넣어요(면적 기본값으로 미리 골라 둔 칩도 고객이 보고 넘긴 값이에요) */
const withRooms = (d: InfoDraft, rule: RoomRule): InfoDraft => ({ ...d, rooms: roomsOf(d, rule) });

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
  const [phase, setPhase] = useState<Phase>("ask");
  const [said, setSaid] = useState<string | null>(null);
  const [found, setFound] = useState<boolean | null>(null);
  const [d, setD] = useState<InfoDraft>(EMPTY_DRAFT);
  const [dirty, setDirty] = useState(false);
  const [tried, setTried] = useState(false);
  const [std, setStd] = useState<GuestStandard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [join, setJoin] = useState(false);
  const [manual, setManual] = useState(false);
  const [dateOpen, setDateOpen] = useState(false);
  const [pick, setPick] = useState<DiyPick[]>([]);
  const [answered, setAnswered] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const restored = useRef(false);

  // 이 기기에 넣던 답이 있으면 확인 카드부터 이어요(처음 한 번). 칩으로 고른 시기는 오늘 기준 날짜로 다시 맞추고,
  // 넣던 방 개수가 면적 기본값과 같으면 면적을 따라가게 비워 둬요
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    const g = readGuest();
    if (!g?.info.sido) return;
    const saved = draftOf(g);
    const wish = wishes.find((w) => w.key === saved.when);
    const rooms = saved.rooms != null && saved.rooms === roomsOf({ ...saved, rooms: null }, roomRule) ? null : saved.rooms;
    // v3 기본 정보 화면에서 넣던 답은 고른 시기가 없어요: 날짜가 있으면 '날짜 고르기'로 봐요
    const when = saved.when ?? (saved.start ? "date" : null);
    setD({ ...saved, rooms, when, ...(wish ? { start: wish.start_date } : {}) });
    setManual(!!saved.area && !PYEONG.some((p) => pyeongToM2(p) === saved.area && saved.basis === "supply"));
    setPhase("confirm");
  }, [wishes, roomRule]);
  // 고칠 때마다 이 기기에 저장해요(손님 답 옮기기와 같은 저장소). 방 개수는 보이는 값으로 둬요
  useEffect(() => { if (dirty) writeGuest(withRooms(d, roomRule)); }, [d, dirty, roomRule]);
  // 새 말이 붙으면 아래로
  useEffect(() => { log.current?.lastElementChild?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [phase, said, answered]);

  const set = (patch: Partial<InfoDraft>) => { setD((p) => ({ ...p, ...patch })); setDirty(true); setErr(null); };
  const errors = tried ? errorsOf(d, today) : {};
  const sido = regions.find((r) => r.id === d.sido);
  const place = sido ? [sido.groups.find((g) => g.items.includes(d.sgg))?.prefix || sido.name, d.sgg].filter(Boolean).join(" ") : "";
  const rooms = roomsOf(d, roomRule);

  function sendAddress(raw: string) {
    const v = raw.trim().slice(0, 80);
    if (!v) return;
    const r = guessRegion(v, regions);
    // 같이 적은 평형 · 방 개수 · 공사할 때 집 · 시기도 미리 골라요(못 찾은 칸은 그대로 둬요)
    const a = guessArea(v, PYEONG);
    const o = guessOccupied(v);
    const n = guessRooms(v);
    const wish = wishes.find((w) => w.key === guessWhen(v));
    setSaid(v);
    setFound(!!r);
    const patch: Partial<InfoDraft> = {
      ...(r ? { sido: r.sido, sgg: r.sgg } : {}),
      ...(a ? { area: a.area, basis: a.basis } : {}),
      ...(o !== null ? { occupied: o } : {}),
      ...(n !== null && n >= roomRule.min && n <= roomRule.max ? { rooms: n } : {}),
      ...(wish ? { when: wish.key, start: wish.start_date } : {}),
    };
    if (a) setManual(!a.chip);
    if (Object.keys(patch).length) set(patch);
    setText("");
    setPhase("confirm");
  }

  async function confirm() {
    setTried(true);
    if (Object.keys(errorsOf(d, today)).length || phase !== "confirm") return;
    setErr(null);
    writeGuest(withRooms(d, roomRule));
    setPhase("calc");
    try {
      setStd(await calcGuest(toHomeInfo(withRooms(d, roomRule)), mock));
      setPick(d.diy ? (d.diy.length ? d.diy : ["none"]) : []);
      setAnswered(false);
      setPhase("done");
    } catch (e) {
      setErr(errorText(e));
      setPhase("confirm");
    }
  }

  // 직접 할 일: '없어요'는 다른 칩과 같이 고르지 않아요
  const toggle = (x: DiyPick) => setPick((p) => (p.includes(x) ? p.filter((y) => y !== x) : x === "none" ? ["none"] : [...p.filter((y) => y !== "none"), x]));

  async function answerDiy() {
    if (!pick.length || phase !== "done") return;
    const next: InfoDraft = { ...d, diy: DIY.map((x) => x.key).filter((key) => pick.includes(key)) };
    setD(next);
    const g = writeGuest(withRooms(next, roomRule));
    setAnswered(true);
    if (mode === "guest") return;
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
    setAnswered(false);
    setErr(null);
  }

  const sgs = sido ? sido.groups.flatMap((g) => g.items.map((x) => ({ key: x, label: g.label ? `${g.prefix} ${x}` : x }))) : [];
  const showCard = phase !== "ask";
  const locked = phase !== "ask" && phase !== "confirm";
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
                <p className={`${s.bubble} ${s.say}`}>안녕하세요. 공사를 끝까지 챙기는 믿집 비서예요.{"\n"}어느 아파트예요? 주소나 단지 이름을 적어 주세요.</p>
              </Bot>
              {said ? <Me>{said}</Me> : null}
              {showCard ? (
                <Bot>
                  <p className={`${s.bubble} ${s.say}`}>
                    {said == null ? "넣던 집 정보예요. 맞는지 확인해 주세요." : found ? `${euro(place)} 찾았어요. 이 집이 맞는지 확인해 주세요.` : "지역을 찾지 못했어요. 지역을 골라 주세요."}
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
                          {phase === "calc" ? "계산하고 있어요" : "맞아요, 표준견적서 보기"}
                        </button>
                      </div>
                    ) : null}
                  </section>
                </Bot>
              ) : null}
              {(phase === "done" || phase === "creating") && std ? (
                <>
                  <Me>맞아요</Me>
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
                  {answered && mode === "guest" ? (
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
            {phase === "ask" || phase === "confirm" ? (
              <form className={s.composer} onSubmit={(e) => { e.preventDefault(); sendAddress(text); }}>
                <div className={s.cbox}>
                  <input
                    className={t.input}
                    value={text}
                    onChange={(e) => setText(e.target.value.slice(0, 80))}
                    placeholder={phase === "ask" ? "예: 노원구 상계동 푸른숲아파트" : "다른 집이면 주소를 다시 적어 주세요"}
                    aria-label="주소나 단지 이름"
                    autoComplete="off"
                    enterKeyHint="send"
                  />
                  <button className={s.send} type="submit" aria-label="보내기" disabled={!text.trim()}><I n="up" /></button>
                </div>
              </form>
            ) : null}
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
