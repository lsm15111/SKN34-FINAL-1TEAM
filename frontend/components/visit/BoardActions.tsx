"use client";
// 실측 일정 카드 · 표의 단추(C14 · C30 요청 취소 · 실측 취소 · C18 한 번 더 요청 · C32 실측 받았어요 · 업체가 안 왔어요)와 실시간 다시 읽기.
// 쓰기는 lib/mock/v3b/client send()(진짜면 POST /api, 예시면 9판 이야기 다음 단계). 결과는 서버가 다시 그린 상태판으로 보여요.
import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorText } from "@/lib/backend/client";
import { useStream } from "@/lib/backend/stream";
import { send } from "@/lib/mock/v3b/client";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { CancelSheet } from "./CancelSheet";
import type { CancelAct } from "./text";
import s from "./visit.module.css";

const path = (projectId: string, visitId: string, tail: string) => `/projects/${encodeURIComponent(projectId)}/visits/${encodeURIComponent(visitId)}/${tail}`;

function ErrLine({ text }: { text: string | null }) {
  return text ? <p className={s.err} role="alert"><Icon name="error" size={16} />{text}</p> : null;
}

/** 요청 취소 · 실측 취소(C30, 회색 글자 단추). 무엇을 보일지는 cancelAct(text.ts)가 골라요 */
export function CancelButton({ projectId, visitId, vendorName, act }: { projectId: string; visitId: string; vendorName: string; act: CancelAct }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="text" gray onClick={() => setOpen(true)} aria-haspopup="dialog">{act.label}</Button>
      <CancelSheet open={open} onClose={() => setOpen(false)} projectId={projectId} visitId={visitId} vendorName={vendorName} request={act.request} slot={act.slot} />
    </>
  );
}

/** 답이 없던 업체에 한 번 더(C18). 두 번째도 답이 없으면 서버가 409 blocked_retry를 줘요 */
export function AgainButton({ projectId, visitId, vendorName }: { projectId: string; visitId: string; vendorName: string }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true);
    setErr(null);
    try {
      await send("POST", path(projectId, visitId, "again"), undefined, { step: "pick_off" });
      toast.show(`${vendorName}에 한 번 더 요청했어요`);
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button size="sm" onClick={go} busy={busy}>{busy ? "보내는 중" : "한 번 더 요청"}</Button>
      <ErrLine text={err} />
    </>
  );
}

/** 실측 시각이 지난 뒤(C32): 실측 받았어요 → 견적서 기다림 · 업체가 안 왔어요 → 기록하고 담은 업체에서 빼요 */
export function VisitedButtons({ projectId, visitId }: { projectId: string; visitId: string }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<"visited" | "no_show" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function tell(result: "visited" | "no_show") {
    setBusy(result);
    setErr(null);
    try {
      await send("POST", path(projectId, visitId, "visited"), { result }, result === "visited" ? { step: "waiting_quote" } : undefined);
      toast.show(result === "visited" ? "실측 받았다고 알렸어요" : "업체가 안 왔다고 기록했어요");
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      <div className={s.btnRow}>
        <Button variant="secondary" size="sm" onClick={() => tell("no_show")} busy={busy === "no_show"} disabled={busy !== null}>업체가 안 왔어요</Button>
        <Button size="sm" onClick={() => tell("visited")} busy={busy === "visited"} disabled={busy !== null}>실측 받았어요</Button>
      </div>
      <ErrLine text={err} />
    </>
  );
}

/** 실시간: 이 공사의 실측 상태가 바뀌면(state) · 줄기를 다시 이으면(resync) 상태판을 다시 읽어요 */
export function BoardLive({ projectId }: { projectId: string }) {
  const router = useRouter();
  useStream(["state", "resync"], (e) => {
    if (e.type === "resync" || (e.type === "state" && (e.data.project_id === projectId || e.data.project_id === null))) router.refresh();
  });
  return null;
}
