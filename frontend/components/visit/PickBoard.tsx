"use client";
// 날짜 고르기 한 화면(GET /projects/{id}/visits/{vid}): 상태에 따라 모양이 바뀌어요.
// - offered: 업체 기간 달력 → 반나절 → 바로 확정이면 확인 창(C61 · I5) 뒤 확정(C16 · D15), 아니면 '{업체}에 보내기'(C19 · D16)
// - offered + 겹치는 날 없음: 길 3개(C22)
// - proposed: 업체가 제안한 반나절만 골라 바로 확정, 안 맞으면 '업체 기간에서 고르기'(C21 · D17 · CF-05)
// - booked: 실측 확정됨(C17) · picked: 수락 기다림(C19 덧그림) · 그 밖: 짧은 상태
// - 취소(C30): 서버가 받는 상태마다 상태판과 같은 회색 글자 단추(요청 취소 · 실측 취소, cancelAct)
// 열린 반나절 · 마감 · 내 다른 실측 · 기한은 모두 API(계산 엔진) 값이에요. 같은 반나절을 거의 같이 누르면 늦은 쪽은 409 slot_taken.
// inCard(v4 비서 화면 카드 창 안): 창이 옆 AI 칸을 숨겨서, 웹은 고른 날 칸(반나절 · 보내기)을 본문 오른쪽에 둬요(QA r6 H1).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import type { VisitPick, VisitProject } from "@/lib/api/visit";
import { ApiError, errorText, type Schemas } from "@/lib/backend/client";
import { dateLong, dueText, euro, eulReul, HALF_LABEL, rangeText, type Half } from "@/lib/format";
import { visitState } from "@/lib/labels";
import { MOCK_V3B } from "@/lib/mock/v3b/mode";
import { send } from "@/lib/mock/v3b/client";
import { MQ } from "@/components/site/breakpoints";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { useMedia } from "@/components/site/useMedia";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button, buttonClass } from "@/components/ui/Button";
import { Calendar, CalendarLegend, type DayMark, type DayNote } from "@/components/ui/Calendar";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { HalfDayPicker, type HalfState } from "@/components/ui/HalfDayPicker";
import { Icon } from "@/components/ui/Icon";
import { StateTag } from "@/components/ui/StateTag";
import { useToast } from "@/components/ui/Toast";
import { Eyebrow, Group, GroupHead, Name, Notice, Quote, Row, Rows, Small, Sub, Title } from "@/components/project/Kit";
import { CancelButton } from "./BoardActions";
import { cancelAct, dayOnly, eunNeun, gwaWa, iGa, pickTitle, PROPOSAL_REASON, rangeLong, slotText, windowText } from "./text";
import s from "./visit.module.css";

type PickOut = Schemas["PickOut"];
type Slot = { day: string; half: Half };
const HALVES: Half[] = ["am", "pm"];
const enc = encodeURIComponent;

function Err({ text, id }: { text: string | null; id?: string }) {
  return text ? <p id={id} className={s.err} role="alert"><Icon name="error" size={16} />{text}</p> : null;
}

export function PickBoard({ pick, project, today, aside, inCard = false }: { pick: VisitPick; project: VisitProject; today: string; aside: ReactNode; inCard?: boolean }) {
  const ai = inCard ? undefined : aside;
  const router = useRouter();
  const toast = useToast();
  const web = useMedia(MQ.web);
  const [day, setDay] = useState<string | null>(null);
  const [half, setHalf] = useState<Half | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState<"pick" | "repick" | null>(null);
  const [showCal, setShowCal] = useState(false);
  const [justBooked, setJustBooked] = useState<{ slot: Slot; thread: string | null } | null>(null);

  const v = pick.vendor_name;
  const pid = enc(project.id);
  const vid = enc(pick.visit_id);
  const board = `/projects/${pid}/visits`;
  const status = justBooked ? "booked" : pick.status;
  const proposal = pick.status === "proposed" ? pick.proposal : null;
  const mode = status === "booked" ? "done" : status === "picked" ? "waiting" : proposal ? "proposal" : status === "offered" ? (pick.overlap || showCal ? "pick" : "nooverlap") : "other";
  const title = justBooked ? "실측 일정" : pickTitle(pick);
  const crumbs = [{ label: "내 공사", href: "/my" }, { label: project.name, href: `/projects/${pid}` }, { label: "실측 일정", href: board }, { label: title }];
  const x = cancelAct({ status, booked: justBooked?.slot ?? pick.booked });
  const cancel = x ? <CancelButton projectId={project.id} visitId={pick.visit_id} vendorName={v} act={x} /> : null;

  // ── 달력 값(모두 API 값을 모양으로만 옮겨요)
  const cal = useMemo(() => {
    const days = new Map(pick.days.map((d) => [d.day, d]));
    const full = new Set(pick.full.map((f) => `${f.day}:${f.half}`));
    const marks: Record<string, DayMark[]> = {};
    const notes: Record<string, DayNote> = {};
    let only: string[] = [];
    if (proposal) {
      const byDay = new Map<string, Half[]>();
      proposal.slots.forEach((x) => byDay.set(x.day, [...(byDay.get(x.day) ?? []), x.half]));
      byDay.forEach((hs, d) => {
        marks[d] = ["proposed"];
        notes[d] = { text: hs.length > 1 ? "제안" : HALF_LABEL[hs[0]], label: `제안 ${hs.map((h) => HALF_LABEL[h]).join(" · ")}` };
      });
      only = [...byDay.keys()];
    } else {
      pick.days.forEach((d) => {
        if (d.am || d.pm) {
          marks[d.day] = ["available"];
          only.push(d.day);
          if (d.am !== d.pm) notes[d.day] = { text: web ? `${HALF_LABEL[d.am ? "am" : "pm"]}만` : HALF_LABEL[d.am ? "am" : "pm"], label: `${HALF_LABEL[d.am ? "am" : "pm"]}만 남음` };
        } else marks[d.day] = ["unavailable"];
      });
      pick.window?.excluded.forEach((d) => { marks[d] = ["unavailable"]; });
    }
    pick.mine.forEach((m) => { notes[m.day] = { text: web ? `${m.vendor_name} 실측` : "실측", label: `내 실측 · ${m.vendor_name} ${slotText(m)}` }; });
    const slotsOf = (d: string): Partial<Record<Half, HalfState>> => {
      const out: Partial<Record<Half, HalfState>> = {};
      for (const h of HALVES) {
        if (proposal) { if (proposal.slots.some((x) => x.day === d && x.half === h)) out[h] = "proposed"; continue; }
        if (days.get(d)?.[h]) out[h] = "open";
        else if (full.has(`${d}:${h}`)) out[h] = "closed";
      }
      return out;
    };
    const hasFull = (d: string) => HALVES.some((h) => full.has(`${d}:${h}`));
    return { marks, notes, only, slotsOf, hasFull };
  }, [pick.days, pick.full, pick.mine, pick.window, proposal, web]);

  function chooseDay(d: string | null) {
    setDay(d);
    setErr(null);
    if (!d) { setHalf(null); return; }
    const open = HALVES.filter((h) => { const st = cal.slotsOf(d)[h]; return st === "open" || st === "proposed"; });
    setHalf(open.length === 1 ? open[0] : null);
  }
  function chooseSlot(x: Slot) { setDay(x.day); setHalf(x.half); setErr(null); }

  const sel: Slot | null = day && half ? { day, half } : null;
  const wish = pick.wish_start && pick.wish_end ? { from: pick.wish_start, to: pick.wish_end } : undefined;

  async function send_(kind: "pick" | "proposal") {
    if (!sel) { setErr("날짜와 오전 · 오후를 골라 주세요."); return; }
    setBusy("pick");
    setErr(null);
    const instant = kind === "proposal" || pick.instant;
    try {
      const out = await send<PickOut>(
        "POST",
        `/projects/${pid}/visits/${vid}/${kind === "proposal" ? "proposal/pick" : "pick"}`,
        sel,
        { step: kind === "proposal" ? "both_booked" : instant ? "done" : "picked", result: { visit_id: pick.visit_id, status: instant ? "booked" : "picked", booked: { ...sel, kind: instant ? "booked" : "hold", hold_until: null }, thread_id: pick.thread_id } },
      );
      setConfirmOpen(false);
      if (out.status === "booked") {
        setJustBooked({ slot: { day: out.booked.day, half: out.booked.half }, thread: out.thread_id });
        toast.show("실측 날짜가 정해졌어요");
        router.refresh();
      } else {
        toast.show(`${eulReul(slotText(sel))} ${v}에 보냈어요`);
        router.push(board);
        router.refresh();
      }
    } catch (e) {
      setConfirmOpen(false);
      if (e instanceof ApiError && e.code === "slot_taken") {
        const msg = "방금 다른 고객이 골랐어요. 다른 날을 골라 주세요.";
        toast.show(msg, { tone: "error" });
        setErr(msg);
        setHalf(null);
        router.refresh();
      } else setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  function onMain() {
    if (!sel) { setErr("날짜와 오전 · 오후를 골라 주세요."); return; }
    if (pick.instant) setConfirmOpen(true);
    else void send_("pick");
  }
  async function repick() {
    setBusy("repick");
    setErr(null);
    try {
      await send("POST", `/projects/${pid}/visits/${vid}/repick`, undefined, { step: "pick_off" });
      setDay(null);
      setHalf(null);
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  // ── 확정됨(C17)
  if (mode === "done") {
    const slot = justBooked?.slot ?? (pick.booked ? { day: pick.booked.day, half: pick.booked.half } : null);
    const thread = justBooked?.thread ?? pick.thread_id;
    const ics = `/api/projects/${pid}/visits/${vid}/ics`;
    return (
      <>
        <Main>
          <PageHead title="실측 일정" crumbs={crumbs.slice(0, 3).concat({ label: "실측 확정" })} />
          <WithAside aside={ai}>
            <Group>
              <div className={s.done}>
                <span className={s.okc} aria-hidden="true"><Icon name="check" size={34} strokeWidth={2.6} /></span>
                <Title as="h2">실측 날짜가 정해졌어요</Title>
                {slot ? <p className={`${s.bigText} mj-num`}>{slotText(slot, true)}</p> : null}
                <Sub>{v} · {project.name}</Sub>
              </div>
            </Group>
            <Group list>
              <Rows>
                <Row label="시각" sub={`채팅에서 ${gwaWa(v)} 정해요`} />
                <Row label="알림" sub="전날 18:00에 한 번 알려 드려요" />
                <Row label="동 · 호수 · 연락처" sub="채팅에서 직접 알려 줘요 · 업체에는 동네까지만 보여요" />
                <Row
                  label="내 캘린더에 넣기"
                  sub="폰 · PC 캘린더에 실측 날이 들어가요"
                  value={MOCK_V3B
                    ? <span className={buttonClass({ variant: "text", gray: true })} aria-disabled="true">캘린더 파일 받기</span>
                    : <a className={buttonClass({ variant: "text" })} href={ics} download>캘린더 파일 받기</a>}
                />
              </Rows>
            </Group>
            {cancel ? <div className={s.cardLink}>{cancel}</div> : null}
          </WithAside>
        </Main>
        <BottomBar>
          <Button variant="secondary" size="lg" href={board}>실측 일정 보기</Button>
          {thread ? <Button size="lg" href={`/chat/${enc(thread)}`}>채팅 열기</Button> : <Button size="lg" href="/chat">채팅 열기</Button>}
        </BottomBar>
      </>
    );
  }

  // ── 수락 기다림(C19 보낸 뒤 · D10 잡아 둠)
  if (mode === "waiting") {
    const st = visitState("picked", "customer");
    return (
      <Main>
        <PageHead title="실측 일정" crumbs={crumbs} />
        <WithAside aside={ai}>
          <Group>
            <GroupHead><Name>{v}</Name><StateTag tone={st.tone}>{st.label}</StateTag></GroupHead>
            {pick.booked ? <Sub>{eulReul(slotText(pick.booked))} 보냈어요</Sub> : null}
            {pick.next.due_at ? <Small>{dueText(pick.next.due_at)} {iGa(v)} 답해요 · 그때까지 이 날짜를 잡아 둬요</Small> : null}
            {cancel ? <div className={s.cardFoot}>{cancel}</div> : null}
          </Group>
          <div className={s.cardLink}><Button variant="text" arrow href={board}>실측 일정 보기</Button></div>
        </WithAside>
      </Main>
    );
  }

  // ── 겹치는 날 없음(C22)
  if (mode === "nooverlap" && pick.window) {
    const w = pick.window;
    const late = pick.work_wish_on && pick.work_wish_on < w.start;
    const ways = pick.ways.length ? pick.ways : (["ask_other", "change_wish", "other_vendor"] as const);
    return (
      <Main>
        <PageHead title={title} crumbs={crumbs} />
        <WithAside aside={ai}>
          <Group>
            <Title as="h2">겹치는 날이 없어요</Title>
            <Sub>업체는 {rangeLong(w.start, w.end)}에 돼요.{late && pick.work_wish_on ? <><br />공사 시작({dayOnly(pick.work_wish_on)})보다 늦어요.</> : null}</Sub>
          </Group>
          <Group list label="다음 길">
            <ul className={s.ways}>
              {ways.map((k) => (
                <li key={k}>
                  {k === "ask_other" ? (
                    <button type="button" className={s.way} onClick={() => setShowCal(true)}>
                      <span className={s.wayText}><b>업체 기간에서 고르기</b><span>{dayOnly(w.start)} 뒤 실측 · 공사 시작이 밀릴 수 있어요</span></span>
                      <Icon name="chevron-right" size={18} />
                    </button>
                  ) : (
                    <Link className={s.way} href={k === "change_wish" ? `/projects/${pid}/visits/new` : `/projects/${pid}/vendors`}>
                      <span className={s.wayText}><b>{k === "change_wish" ? "희망 기간 넓혀서 다시 요청" : "다른 업체 담기"}</b></span>
                      <Icon name="chevron-right" size={18} />
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </Group>
          {cancel ? <div className={s.cardLink}>{cancel}</div> : null}
        </WithAside>
      </Main>
    );
  }

  // ── 그 밖(답 기다림 · 답 없음 · 취소 · 실측 뒤): 상태와 돌아갈 길
  if (mode === "other") {
    const st = visitState(status, "customer");
    return (
      <Main>
        <PageHead title={title} crumbs={crumbs} />
        <WithAside aside={ai}>
          <Group>
            <GroupHead><Name>{v}</Name><StateTag tone={st.tone}>{st.label}</StateTag></GroupHead>
            {status === "requested" && pick.next.due_at ? <Sub>{dueText(pick.next.due_at)} 답해요</Sub> : null}
            {status === "expired" && pick.next.due_at ? <Sub>{dueText(pick.next.due_at)} 답하지 않았어요</Sub> : null}
            {cancel ? <div className={s.cardFoot}>{cancel}</div> : null}
          </Group>
          <div className={s.cardLink}><Button variant="text" arrow href={board}>실측 일정 보기</Button></div>
        </WithAside>
      </Main>
    );
  }

  // ── 고르기(offered) · 제안한 날(proposed)
  const isProp = mode === "proposal" && proposal;
  const slots = sel ? cal.slotsOf(sel.day) : day ? cal.slotsOf(day) : {};
  const hint = isProp ? "제안한 날을 고르면 바로 확정돼요." : day && cal.hasFull(day) ? "시각은 확정 뒤 채팅으로 정해요. 마감은 다른 고객이 먼저 고른 때예요." : "시각은 확정 뒤 채팅으로 정해요.";
  const mainLabel = isProp ? "이 날짜로 확정" : pick.instant ? "이 날짜로 확정" : `${v}에 보내기`;
  const why = proposal ? [proposal.reason_code ? PROPOSAL_REASON[proposal.reason_code] : null, proposal.note].filter(Boolean).join(" · ") : "";
  const headLine = isProp
    ? [pick.booked ? `고른 ${eunNeun(slotText(pick.booked, true))} 어렵대요` : null, `${dueText(proposal!.due_at)} 골라요`].filter(Boolean).join(" · ")
    : pick.window ? `${windowText(pick.window)} · ${pick.instant ? "고르면 바로 확정돼요" : `고른 날을 ${iGa(v)} 수락하면 확정돼요`}` : null;
  const onPrimary = () => (isProp ? void send_("proposal") : onMain());

  const halfPicker = (key: string) => (day ? (
    <HalfDayPicker key={key} legend={dateLong(day)} value={half} onChange={(h) => { setHalf(h); setErr(null); }} slots={slots} />
  ) : null);

  const side = (
    <section className={s.pickSide} aria-label="고른 날">
      {!isProp && !pick.instant ? <Notice>{iGa(v)} 수락하면 확정돼요</Notice> : null}
      <Eyebrow>{isProp ? `${iGa(v)} 제안한 날` : `${v} · 고른 날`}</Eyebrow>
      {isProp ? (
        <>
          {why ? <Quote>{why}</Quote> : null}
          <div className={s.slotGrid} role="group" aria-label="제안한 날">
            {proposal!.slots.map((x) => {
              const on = sel?.day === x.day && sel.half === x.half;
              return <button key={`${x.day}${x.half}`} type="button" className={on ? `${s.slotBtn} ${s.slotOn}` : s.slotBtn} aria-pressed={on} onClick={() => chooseSlot(x)}>{slotText(x)}</button>;
            })}
          </div>
          {sel ? <p className={`${s.bigText} mj-num`}>{slotText(sel, true)}</p> : null}
        </>
      ) : day ? halfPicker("side") : <p className={s.sideEmpty}>달력에서 날짜를 골라 주세요</p>}
      <Small>{hint}</Small>
      {isProp ? (
        <div className={s.btnRow}>
          <Button variant="secondary" onClick={repick} busy={busy === "repick"} disabled={busy !== null}>업체 기간에서 고르기</Button>
          <Button onClick={onPrimary} busy={busy === "pick"} disabled={busy !== null}>이 날짜로 확정</Button>
        </div>
      ) : (
        <Button block onClick={onPrimary} busy={busy === "pick"}>{busy === "pick" ? "보내는 중" : mainLabel}</Button>
      )}
      {!isProp && !pick.instant ? <Small>{`보내면 ${iGa(v)} 48시간 안에 답해요 · 그때까지 이 날짜를 잡아 둬요`}</Small> : null}
      <Err text={err} />
    </section>
  );

  const calGroup = (
    <Group label="달력">
      <CalendarLegend items={isProp ? ["wish", "proposed", "selected"] : ["wish", "available", "selected", "unavailable"]} wishText={!isProp && wish ? `내 희망 ${rangeText(wish.from, wish.to)}` : undefined} />
      <Calendar
        mode="single"
        label={title}
        today={today}
        month={proposal?.slots[0]?.day ?? pick.window?.start ?? pick.wish_start ?? today}
        value={day}
        onChange={chooseDay}
        wish={wish}
        marks={cal.marks}
        notes={cal.notes}
        only={cal.only}
        wide={web}
      />
      {web && !isProp && pick.days.some((d) => (d.am || d.pm) && d.am !== d.pm) ? <Small>업체가 된다고 한 날만 고를 수 있어요. 날짜 아래 &apos;오전만 · 오후만&apos;은 그날 고를 수 있는 때예요.</Small> : null}
      {web && pick.mine.length ? <Small>이미 잡힌 내 실측({pick.mine.map((m) => `${Number(m.day.slice(8))}일 ${HALF_LABEL[m.half]} · ${m.vendor_name}`).join(", ")})도 달력에 보여요.</Small> : null}
      {!day ? <div className={s.phoneStack}><Err text={err} /></div> : null}
    </Group>
  );

  return (
    <>
      <Main>
        <PageHead title={title} crumbs={crumbs} />
        {headLine ? <p className={s.headLine}>{headLine}</p> : null}
        <WithAside aside={inCard ? undefined : <div className={s.sideStack}>{side}<div className={s.aiFill}>{aside}</div></div>}>
          {inCard ? <div className={s.pickCols}>{calGroup}{side}</div> : calGroup}
          {day ? (
            <div className={s.phoneStack}>
              <Group label="오전 · 오후">
                {halfPicker("body")}
                <Small>{hint}</Small>
                <Err text={err} />
              </Group>
            </div>
          ) : null}
          {cancel ? <div className={s.cardLink}>{cancel}</div> : null}
        </WithAside>
      </Main>
      <div className={s.phoneOnly}>
        <BottomBar
          note={!isProp && !pick.instant ? `${iGa(v)} 수락하면 확정돼요` : undefined}
          summary={sel ? { label: v, value: slotText(sel) } : undefined}
        >
          {isProp ? <Button variant="secondary" size="lg" onClick={repick} busy={busy === "repick"} disabled={busy !== null}>업체 기간에서 고르기</Button> : null}
          <Button size="lg" onClick={onPrimary} busy={busy === "pick"} disabled={busy === "repick"}>{busy === "pick" ? "보내는 중" : mainLabel}</Button>
        </BottomBar>
      </div>
      {pick.instant && !isProp ? (
        <ConfirmDialog
          open={confirmOpen}
          onClose={() => { if (!busy) setConfirmOpen(false); }}
          title={sel ? `${euro(slotText(sel, true))} 확정할까요?` : "이 날짜로 확정할까요?"}
          confirmLabel="확정"
          onConfirm={() => void send_("pick")}
          busy={busy === "pick"}
        >
          {sel ? (
            <Rows>
              <Row label="업체" value={v} valueSub />
              <Row label="실측" value={slotText(sel)} valueSub />
              <Row label="시각" value="확정 뒤 채팅으로 정해요" valueSub />
            </Rows>
          ) : null}
          <p className={s.sheetNote}>{iGa(v)} &apos;바로 확정&apos;을 켜 둬서 누르면 바로 정해져요. 바꾸려면 채팅에서 일정 바꾸기를 요청해요.</p>
        </ConfirmDialog>
      ) : null}
    </>
  );
}
