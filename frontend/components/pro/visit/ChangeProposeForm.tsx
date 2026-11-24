"use client";
// 일정 바꾸기 요청에 다른 날 내기(V20 [다른 날 제안], 채팅 카드에서 와요): 반나절 1~3개 → POST /vendor/visits/{vid}/changes/{cid}/propose.
// 고객이 그중 하나를 고르면 바뀌고, 고르기 전까지는 지금 실측 날짜 그대로예요. 내일부터 · 지금 날짜와 다른 반나절만 받아요(서버 422).
// 날짜는 고른 것만 보내요(화면이 날짜를 만들지 않아요). 찬 반나절은 고객이 고를 때 서버가 409로 막아요.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { Calendar, type DayMark, type DayNote } from "@/components/ui/Calendar";
import { ChoiceChips } from "@/components/ui/ChoiceChip";
import { HalfDayPicker, type HalfState } from "@/components/ui/HalfDayPicker";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import type { VendorVisitV3 } from "@/lib/api/vendor";
import { errorText } from "@/lib/backend/client";
import { dateLong, dateSeoul, dueText, halfDayText, type Half } from "@/lib/format";
import { enc, send } from "../send";
import { Group, Lead, Small } from "../ui/parts";
import { occ, visitTitle } from "./facts";
import s from "./visit.module.css";

type Change = NonNullable<VendorVisitV3["change"]>;
const MAX = 3;
const key = (d: string, h: Half) => `${d}|${h}`;
const unkey = (k: string) => { const [day, half] = k.split("|"); return { day, half: half as Half }; };

export function ChangeProposeForm({ v, change, now }: { v: VendorVisitV3; change: Change; now: string }) {
  const router = useRouter();
  const toast = useToast();
  const today = dateSeoul(now);
  const [day, setDay] = useState<string | null>(null);
  const [half, setHalf] = useState<Half | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const back = v.thread_id ? `/chat/${enc(v.thread_id)}` : `/vendor/requests/${enc(v.id)}`;

  // 오늘은 고를 수 없어요(서버: 내일부터). 지금 실측 날 · 고객이 바꾸자는 날은 달력에 표시만 해요
  const marks: Record<string, DayMark[]> = { [change.from_day]: ["booked"] };
  marks[today] = [...(marks[today] ?? []), "unavailable"];
  const notes: Record<string, DayNote> = {
    [change.from_day]: { text: "지금", label: "지금 실측 날짜" },
    [change.to_day]: { text: "요청", label: "고객이 바꾸자는 날" },
  };
  // 지금 실측 반나절은 다시 낼 수 없어요(서버 422)
  const slots: Partial<Record<Half, HalfState>> = {};
  for (const h of ["am", "pm"] as Half[]) if (!(day === change.from_day && h === change.from_half)) slots[h] = "open";

  function add() {
    if (!day || !half) { setErr("날짜와 오전 · 오후를 골라 주세요."); return; }
    const k = key(day, half);
    if (picked.includes(k)) { setErr("이미 더한 반나절이에요."); return; }
    if (picked.length >= MAX) { setErr(`반나절은 ${MAX}개까지 낼 수 있어요.`); return; }
    setPicked((x) => [...x, k].sort());
    setDay(null);
    setHalf(null);
    setErr(null);
  }

  async function go() {
    if (busy) return;
    if (!picked.length) { setErr("낼 반나절을 1개 이상 더해 주세요."); return; }
    setErr(null);
    setBusy(true);
    try {
      await send("POST", `/vendor/visits/${enc(v.id)}/changes/${enc(change.id)}/propose`, { slots: picked.map(unkey) });
      toast.show("다른 날을 보냈어요. 고객이 고르면 바뀌어요.");
      router.push(back);
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  }

  return (
    <>
      <Main narrow>
        <PageHead title="다른 날 제안" crumbs={[{ label: "작업함", href: "/vendor" }, { label: visitTitle(v), href: `/vendor/requests/${enc(v.id)}` }, { label: "다른 날 제안" }]} />
        <Lead
          title={`${visitTitle(v)} · ${occ(v)}`}
          sub={`지금 ${halfDayText(change.from_day, change.from_half)} · 고객이 바꾸자는 날 ${halfDayText(change.to_day, change.to_half)}`}
        />
        <Small red>{dueText(change.due_at, { now })} 답해요</Small>
        <Group>
          <Calendar mode="single" label="낼 날짜 고르기" today={today} month={change.to_day} value={day} onChange={(x) => { setDay(x); setHalf(null); setErr(null); }} marks={marks} notes={notes} />
          {day ? (
            <>
              <HalfDayPicker legend={dateLong(day)} value={half} onChange={(h) => { setHalf(h); setErr(null); }} slots={slots} />
              <div><Button variant="secondary" size="sm" icon="plus" onClick={add} disabled={picked.length >= MAX}>이 반나절 더하기</Button></div>
            </>
          ) : null}
        </Group>
        {picked.length ? (
          <Group>
            <ChoiceChips
              multiple
              legend={`낼 반나절 · ${MAX}개까지`}
              options={picked.map((k) => { const x = unkey(k); return { value: k, label: halfDayText(x.day, x.half) }; })}
              value={picked}
              onChange={(next) => { setPicked(next); setErr(null); }}
            />
          </Group>
        ) : null}
        {err ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
      </Main>
      <BottomBar>
        <Button size="lg" block onClick={go} busy={busy}>{busy ? "보내는 중" : picked.length ? `${picked.length}개 보내기` : "다른 날 보내기"}</Button>
      </BottomBar>
    </>
  );
}
