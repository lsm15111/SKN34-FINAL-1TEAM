"use client";
// 업체 가입 승인 · 반려. 반려는 사유가 꼭 있어야 하고, 업체는 마이페이지에서 사유를 본다.
import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { call, errorText } from "@/lib/backend/client";

export function VendorReview({ id, name, status, compact }: { id: string; name: string; status: string; compact?: boolean }) {
  const router = useRouter();
  const uid = useId();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function act(kind: "approve" | "reject") {
    if (kind === "reject" && !reason.trim()) { setErr("반려 사유를 적어 주세요."); return; }
    setErr(""); setBusy(true);
    try {
      await call("POST", `/admin/vendors/${id}/${kind}`, kind === "reject" ? { reason: reason.trim() } : undefined);
      setRejecting(false); setReason("");
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: compact ? 180 : undefined }}>
      <div className="mj-btn-row">
        {status !== "approved" ? <button type="button" className="mj-btn mj-btn-pri mj-btn-sm" disabled={busy} onClick={() => act("approve")}>승인<span className="mj-sr"> · {name}</span></button> : null}
        {status !== "rejected" && !rejecting ? <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" disabled={busy} onClick={() => setRejecting(true)}>반려<span className="mj-sr"> · {name}</span></button> : null}
      </div>
      {rejecting ? (
        <div className="mj-field">
          <label className="mj-label" htmlFor={`${uid}-r`}>반려 사유</label>
          <input id={`${uid}-r`} className="mj-input" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="예: 사업자등록증 글씨가 흐려요" aria-invalid={err ? true : undefined} aria-describedby={err ? `${uid}-e` : undefined} />
          <div className="mj-btn-row">
            <button type="button" className="mj-btn mj-btn-danger mj-btn-sm" disabled={busy} onClick={() => act("reject")}>반려하기</button>
            <button type="button" className="mj-btn mj-btn-ghost mj-btn-sm" onClick={() => { setRejecting(false); setErr(""); }}>그만두기</button>
          </div>
        </div>
      ) : null}
      {err ? <p id={`${uid}-e`} className="mj-error" role="alert">{err}</p> : null}
    </div>
  );
}
