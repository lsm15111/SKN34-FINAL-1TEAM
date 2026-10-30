"use client";
// 탈퇴 확인: 비밀번호를 다시 받아 POST /me/withdraw. 끝나면 이 브라우저에 남은 쓰던 요청서도 지운다.
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { call, errorText } from "@/lib/backend/client";
import { writeDraft } from "@/components/start/draft";

export function WithdrawForm() {
  const router = useRouter();
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const pw = useRef<HTMLInputElement>(null);
  return (
    <form
      className="mj-panel"
      aria-labelledby="wd-h"
      noValidate
      onSubmit={async (e) => {
        e.preventDefault();
        const password = pw.current?.value ?? "";
        if (!password) { setErr("비밀번호를 적어 주세요."); pw.current?.focus(); return; }
        setErr(""); setBusy(true);
        try {
          await call("POST", "/me/withdraw", { password });
          writeDraft(null);
          router.push("/?bye=1");
          router.refresh();
        } catch (er) {
          setErr(errorText(er));
          setBusy(false);
          pw.current?.focus();
        }
      }}
    >
      <h2 id="wd-h" className="mj-h3">비밀번호 확인</h2>
      <div className="mj-field">
        <label className="mj-label" htmlFor="wd-pw">지금 비밀번호</label>
        <input ref={pw} id="wd-pw" type="password" autoComplete="current-password" className="mj-input" aria-invalid={err ? true : undefined} aria-describedby={err ? "wd-err" : undefined} />
        {err ? <p id="wd-err" className="mj-error" role="alert">{err}</p> : null}
      </div>
      <button type="submit" className="mj-btn mj-btn-danger" disabled={busy}>{busy ? "지우는 중…" : "탈퇴하고 모두 지우기"}</button>
    </form>
  );
}
