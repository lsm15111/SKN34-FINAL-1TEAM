"use client";
// 공사 날짜 아래 단추 띠(C35): [다른 날짜 요청] [수락]. 수락하면 확정 공정표가 생겨요(POST …/dates/{pid}/accept {seen_version}).
// 수락한 뒤(확정): [날짜 바꾸기 요청](DatesChangeBar).
import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorText } from "@/lib/backend/client";
import { send } from "@/lib/mock/v3b/client";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { DateRequestSheet } from "./DateRequestSheet";
import s from "./v3.module.css";

export function DatesActions({ projectId, dealId, proposalId, seenVersion, vendorName, requestsLeft, options, today, requestDue = null }: {
  requestDue?: string | null;
  projectId: string;
  dealId: string;
  proposalId: string;
  seenVersion: number;
  vendorName: string;
  requestsLeft: number;
  options: string[];
  today: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ask, setAsk] = useState(false);
  const pid = encodeURIComponent(projectId);

  async function accept() {
    setBusy(true);
    setErr(null);
    try {
      await send("POST", `/projects/${pid}/deals/${encodeURIComponent(dealId)}/dates/${encodeURIComponent(proposalId)}/accept`, { seen_version: seenVersion }, { step: "scheduled" });
      toast.show("공사 날짜를 수락했어요");
      router.push(`/projects/${pid}/plan`);
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  }

  return (
    <>
      <BottomBar note={err ? <span className={s.err} role="alert">{err}</span> : undefined}>
        <Button variant="secondary" size="lg" onClick={() => setAsk(true)} disabled={busy || requestsLeft <= 0}>다른 날짜 요청</Button>
        <Button size="lg" onClick={accept} busy={busy}>{busy ? "보내는 중" : "수락"}</Button>
      </BottomBar>
      <DateRequestSheet open={ask} onClose={() => setAsk(false)} projectId={projectId} dealId={dealId} vendorName={vendorName} requestsLeft={requestsLeft} requestDue={requestDue} options={options} today={today} />
    </>
  );
}

/** 수락한 뒤(확정) 아래 단추 띠: [날짜 바꾸기 요청] → 이유 + 원하는 시작일(POST …/date-requests, 다른 날짜 요청과 합쳐 2번까지).
 *  업체가 새 날짜를 올리면 이 화면에서 수락하거나 다시 요청해요(change_proposed). 지금 날짜는 그때까지 그대로예요 */
export function DatesChangeBar({ projectId, dealId, vendorName, requestsLeft, options, today, requestDue = null }: {
  requestDue?: string | null;
  projectId: string;
  dealId: string;
  vendorName: string;
  requestsLeft: number;
  options: string[];
  today: string;
}) {
  const [ask, setAsk] = useState(false);
  return (
    <>
      <BottomBar>
        <Button variant="secondary" size="lg" aria-haspopup="dialog" onClick={() => setAsk(true)}>날짜 바꾸기 요청</Button>
      </BottomBar>
      <DateRequestSheet change open={ask} onClose={() => setAsk(false)} projectId={projectId} dealId={dealId} vendorName={vendorName} requestsLeft={requestsLeft} requestDue={requestDue} options={options} today={today} />
    </>
  );
}
