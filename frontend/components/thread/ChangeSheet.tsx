"use client";
// 일정 바꾸기 요청 시트(C28 앞 단계): 새 날짜는 업체 가능 날 달력(C16과 같은 달력)에서 하나 골라요.
// POST /projects/{id}/visits/{vid}/changes {day, half} → 채팅에 요청 카드 · 업체 알림. 업체가 수락하기 전까지는 원래 날짜 그대로예요.
// 열린 반나절 · 마감은 API 값(days · full)을 그대로 보여요. 화면은 날짜를 계산하지 않아요.
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import type { ThreadVisit } from "@/lib/api/thread";
import { errorText } from "@/lib/backend/client";
import { dateLong, type Half } from "@/lib/format";
import { send } from "@/lib/mock/v3b/client";
import { Button } from "@/components/ui/Button";
import { Calendar, CalendarLegend, type DayMark, type DayNote } from "@/components/ui/Calendar";
import { HalfDayPicker, type HalfState } from "@/components/ui/HalfDayPicker";
import { Icon } from "@/components/ui/Icon";
import { Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import { iGa, slotText } from "@/components/visit/text";
import s from "./thread.module.css";

export function ChangeSheet({ open, onClose, projectId, visit, vendorName, today }: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  visit: ThreadVisit;
  vendorName: string;
  today: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [day, setDay] = useState<string | null>(null);
  const [half, setHalf] = useState<Half | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cur = visit.booked;

  const { only, marks, notes } = useMemo(() => {
    const only: string[] = [];
    const marks: Record<string, DayMark[]> = {};
    const notes: Record<string, DayNote> = {};
    for (const d of visit.days) {
      const am = d.am && !(cur && cur.day === d.day && cur.half === "am");
      const pm = d.pm && !(cur && cur.day === d.day && cur.half === "pm");
      if (!am && !pm) continue;
      only.push(d.day);
      marks[d.day] = ["available"];
      if (am !== pm) notes[d.day] = am ? { text: "오전", label: "오전만 남음" } : { text: "오후", label: "오후만 남음" };
    }
    return { only, marks, notes };
  }, [visit.days, cur]);

  const slots = useMemo((): Partial<Record<Half, HalfState>> => {
    if (!day) return {};
    const d = visit.days.find((x) => x.day === day);
    const out: Partial<Record<Half, HalfState>> = {};
    for (const h of ["am", "pm"] as Half[]) {
      if (cur && cur.day === day && cur.half === h) continue;
      if (d?.[h]) out[h] = "open";
      else if (visit.full.some((f) => f.day === day && f.half === h)) out[h] = "closed";
    }
    return out;
  }, [day, visit.days, visit.full, cur]);

  async function submit() {
    if (!day || !half) { setErr("새 날짜와 오전 · 오후를 골라 주세요."); return; }
    setErr(null);
    setBusy(true);
    try {
      await send("POST", `/projects/${encodeURIComponent(projectId)}/visits/${encodeURIComponent(visit.visitId)}/changes`, { day, half }, { step: "change" });
      toast.show("일정 바꾸기를 요청했어요");
      onClose();
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      open={open}
      onClose={() => !busy && onClose()}
      title="일정 바꾸기 요청"
      dismissible={!busy}
      hideClose
      actions={
        <div className={s.sheetBtns}>
          <Button variant="secondary" size="lg" onClick={onClose} disabled={busy}>닫기</Button>
          <Button size="lg" onClick={submit} busy={busy}>{busy ? "보내는 중" : "요청 보내기"}</Button>
        </div>
      }
    >
      <p className={s.sheetSub}>{cur ? `지금 ${slotText(cur)} · ` : ""}{iGa(vendorName)} 수락하면 바뀌어요</p>
      {only.length ? (
        <>
          <CalendarLegend items={["available", "selected", "unavailable"]} />
          <Calendar mode="single" label={`${vendorName} 새 실측 날짜 고르기`} today={today} month={only[0]} value={day} onChange={(v) => { setDay(v); setHalf(null); setErr(null); }} marks={marks} notes={notes} only={only} />
          {day ? <HalfDayPicker legend={dateLong(day)} value={half} onChange={(h) => { setHalf(h); setErr(null); }} slots={slots} /> : null}
        </>
      ) : (
        <p className={s.sheetSub}>고를 수 있는 날이 없어요. 채팅으로 {vendorName}에 물어봐 주세요.</p>
      )}
      {err ? <p className={s.sheetErr} role="alert"><Icon name="error" size={16} />{err}</p> : null}
    </Sheet>
  );
}
