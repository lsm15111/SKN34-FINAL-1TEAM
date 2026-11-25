"use client";
// 공사 다른 날짜 요청(C52): 이유 + 원하는 시작일 3개까지 → POST /projects/{id}/deals/{did}/date-requests {wish_dates, reason}.
// 열린 요청은 하나 · 2번까지(서버 규칙). 업체가 새 날짜를 올리는 기한(요청 + 48시간)은 보낸 뒤 서버 값으로 보여요.
// change: 수락한 뒤 날짜 바꾸기 요청(같은 API, 이유 필수 · 요청 수는 다른 날짜 요청과 합쳐 2번). 업체가 새 날짜를 올려 고객이
// 수락하기 전까지 지금 날짜는 그대로예요. 예시 데이터(목업)에는 이 단계가 없어 보내지 않았다고 알려요.
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { dateShort, dueText } from "@/lib/v5/format";
import { send } from "@/lib/mock/v3b/client";
import { Button } from "@/components/ui/Button";
import { Calendar } from "@/components/ui/Calendar";
import { ChoiceChips } from "@/components/v5/ui/ChoiceChip";
import { Icon } from "@/components/ui/Icon";
import { Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import { Btns } from "@/components/project/Kit";
import { iGa } from "@/components/v5/visit/text";
import { DATE_REASONS } from "@/components/schedule/v3text";
import s from "@/components/schedule/v3.module.css";

const MAX = 3;

export function DateRequestSheet({ open, onClose, projectId, dealId, vendorName, requestsLeft, options, today, requestDue = null, change = false }: {
  /** 지금 보내면 업체가 새 날짜를 올릴 기한(서버 계산 request_due_preview) */
  requestDue?: string | null;
  /** 수락한 공사 날짜 바꾸기 요청이에요(확정 뒤) */
  change?: boolean;
  open: boolean;
  onClose: () => void;
  projectId: string;
  dealId: string;
  vendorName: string;
  /** 남은 요청 수(2번까지) */
  requestsLeft: number;
  /** 서버가 권한 시작일 */
  options: string[];
  today: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const errId = useId();
  const [reason, setReason] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [extra, setExtra] = useState<string[]>([]);
  const [cal, setCal] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const order = requestsLeft >= 2 ? "첫 번째" : "두 번째";
  const all = [...options, ...extra.filter((d) => !options.includes(d))].sort();

  function choose(next: string[]) {
    if (next.length > MAX) { setErr(`시작일은 ${MAX}개까지 고를 수 있어요.`); return; }
    setErr(null);
    setPicked(next);
  }
  function fromCalendar(days: string[]) {
    const added = days.filter((d) => !picked.includes(d));
    const kept = picked.filter((d) => days.includes(d) || options.includes(d));
    const next = [...new Set([...kept, ...added])].sort();
    if (next.length > MAX) { setErr(`시작일은 ${MAX}개까지 고를 수 있어요.`); return; }
    setErr(null);
    setExtra((x) => [...new Set([...x, ...added])]);
    setPicked(next);
  }

  async function submit() {
    if (!reason) { setErr("이유를 골라 주세요."); return; }
    if (!picked.length) { setErr("원하는 시작일을 하나 이상 골라 주세요."); return; }
    setErr(null);
    setBusy(true);
    try {
      await send("POST", `/projects/${encodeURIComponent(projectId)}/deals/${encodeURIComponent(dealId)}/date-requests`, { wish_dates: picked, reason }, change ? undefined : { step: "date_req" });
      toast.show(change ? "날짜 바꾸기를 요청했어요" : "다른 날짜를 요청했어요");
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
      title={change ? "공사 날짜 바꾸기를 요청할까요?" : "다른 날짜를 요청할까요?"}
      dismissible={!busy}
      hideClose
      actions={
        <Btns>
          <Button variant="secondary" size="lg" onClick={onClose} disabled={busy}>닫기</Button>
          <Button size="lg" onClick={submit} busy={busy}>{busy ? "보내는 중" : "요청 보내기"}</Button>
        </Btns>
      }
    >
      <div className={s.sheetBody}>
        <p className={s.sheetSub}>2번까지 요청할 수 있어요. 이번이 {order}예요.</p>
        <ChoiceChips legend="이유" options={DATE_REASONS.map((r) => ({ value: r, label: r }))} value={reason} onChange={(v) => { setReason(v); setErr(null); }} />
        <ChoiceChips
          multiple
          legend={`원하는 시작일 · ${MAX}개까지`}
          options={all.map((d) => ({ value: d, label: dateShort(d) }))}
          value={picked}
          onChange={choose}
        />
        <Button variant="text" className={s.textBtn} aria-expanded={cal} onClick={() => setCal((v) => !v)}>{cal ? "달력 접기" : "달력에서 고르기"}</Button>
        {cal ? (
          <div className={s.pickCal}>
            <Calendar mode="multiple" label="원하는 시작일 고르기" today={today} month={all[0] ?? today} value={picked} onChange={fromCalendar} />
          </div>
        ) : null}
        {err ? <p id={errId} className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
        <p className={s.sheetNote}>{requestDue ? `${iGa(vendorName)} ${dueText(requestDue)} 새 날짜를 올려요.` : `보내고 48시간 안에 ${iGa(vendorName)} 새 날짜를 올려요.`}</p>
      </div>
    </Sheet>
  );
}
