"use client";
// 실측 취소 · 요청 취소(C30). 채팅 ⋯ 메뉴 · 실측 일정 카드 · 표 · 날짜 고르기 화면이 같은 창을 열어요. 취소는 기록에 남아요.
// POST /projects/{id}/visits/{vid}/cancel {code} → 업체에 알림 · 담은 업체에서 빠짐 · 대화는 읽기만(서버). 되돌리지 않아요.
// 아래 글은 copy-guide W11(무엇이 바뀌는지 · 누구에게 알리는지 · 되돌릴 수 있는지). '한 번 더 요청'은 두 번째 요청이면 못 해서 쓰지 않아요.
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { send } from "@/lib/mock/v3b/client";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { OptionRow, Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import { Btns } from "@/components/project/Kit";
import { CANCEL_REASONS, slotText } from "./text";
import s from "./visit.module.css";

export function CancelSheet({ open, onClose, projectId, visitId, vendorName, slot, request = false, onDone }: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  visitId: string;
  vendorName: string;
  /** 확정된 반나절(실측 취소). 없으면 요청 취소 */
  slot?: { day: string; half: "am" | "pm" } | null;
  /** 답 전 요청을 거둬요(제목 · 단추가 '요청 취소') */
  request?: boolean;
  onDone?: () => void;
}) {
  const router = useRouter();
  const toast = useToast();
  const [why, setWhy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const errId = useId();
  const what = request ? "요청" : "실측";

  async function submit() {
    if (!why) { setErr("취소 이유를 골라 주세요."); return; }
    setErr(null);
    setBusy(true);
    try {
      await send("POST", `/projects/${encodeURIComponent(projectId)}/visits/${encodeURIComponent(visitId)}/cancel`, { code: why });
      toast.show(`${what}을 취소했어요`);
      onClose();
      if (onDone) onDone(); else router.refresh();
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
      title={`${what}을 취소할까요?`}
      dismissible={!busy}
      hideClose
      actions={
        <Btns>
          <Button variant="secondary" size="lg" onClick={onClose} disabled={busy}>닫기</Button>
          <Button variant="danger" size="lg" onClick={submit} busy={busy}>{busy ? "보내는 중" : `${what} 취소`}</Button>
        </Btns>
      }
    >
      <p className={s.sheetSub}>{vendorName}{slot ? ` · ${slotText(slot, true)}` : ""}</p>
      <div role="radiogroup" aria-label="취소 이유" aria-describedby={err ? errId : undefined}>
        {CANCEL_REASONS.map((r) => (
          <OptionRow key={r.key} selected={why === r.key} onClick={() => { setWhy(r.key); setErr(null); }}>{r.label}</OptionRow>
        ))}
      </div>
      {err ? <p id={errId} className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
      <p className={s.sheetNote}>{vendorName}에 알려요. 담은 업체에서 빠지고 되돌릴 수 없어요.</p>
    </Sheet>
  );
}
