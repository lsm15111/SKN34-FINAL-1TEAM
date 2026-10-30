"use client";
// 내 정보 관리 (FFW-17). 이름은 PATCH /me로 바꾼다. 이메일은 로그인 아이디라 글자로만 보인다.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { call, errorText } from "@/lib/backend/client";

export function ProfileForm({ name, email, labelledBy }: { name: string; email: string; labelledBy: string }) {
  const router = useRouter();
  const [n, setN] = useState(name);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="mj-panel mj-rows"
      aria-labelledby={labelledBy}
      noValidate
      onSubmit={async (e) => {
        e.preventDefault();
        if (!n.trim()) { setErr("이름을 적어 주세요."); setMsg(""); return; }
        setErr(""); setMsg(""); setBusy(true);
        try {
          await call("PATCH", "/me", { name: n.trim() });
          setMsg("저장했어요.");
          router.refresh();
        } catch (er) {
          setErr(errorText(er));
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="mj-row">
        <label className="mj-label" htmlFor="pf-name">이름</label>
        <div className="mj-row-v">
          <div className="mj-inline">
            <input id="pf-name" className="mj-input" value={n} onChange={(e) => setN(e.target.value)} autoComplete="name" aria-invalid={err ? true : undefined} aria-describedby={err ? "pf-err" : undefined} />
            <button type="submit" className="mj-btn mj-btn-sec" disabled={busy}>저장</button>
          </div>
          {err ? <p id="pf-err" className="mj-error">{err}</p> : null}
          <p className="mj-small" role="status">{msg}</p>
        </div>
      </div>
      <div className="mj-row">
        <span className="mj-label">이메일</span>
        <span className="mj-row-v">{email}</span>
      </div>
    </form>
  );
}
