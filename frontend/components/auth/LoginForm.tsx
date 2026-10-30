"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { call, errorText, type Schemas } from "@/lib/backend/client";

// 권한별 첫 화면 (lib/session.ts HOME과 같게)
const HOME: Record<string, string> = { customer: "/my", admin: "/admin/members", vendor: "/vendor" };

export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email") ?? "").trim().toLowerCase();
    const password = String(f.get("password") ?? "");
    if (!email || !password) { setError("이메일과 비밀번호를 모두 적어 주세요."); emailRef.current?.focus(); return; }
    setBusy(true);
    try {
      // 성공하면 API가 세션 쿠키를 심는다 (화면 스크립트는 못 읽는 쿠키).
      const me = await call<Schemas["MeOut"]>("POST", "/auth/login", { email, password });
      const safeNext = next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/admin") ? next : null;
      router.push(me.role === "customer" && safeNext ? safeNext : HOME[me.role] ?? "/");
      router.refresh();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
      emailRef.current?.focus();
    }
  }

  return (
    <form className="mj-panel" onSubmit={onSubmit} noValidate style={{ gap: 18 }}>
      {error ? <p id="login-error" className="mj-error" role="alert">{error}</p> : null}
      <div className="mj-field">
        <label className="mj-label" htmlFor="email">이메일</label>
        <input ref={emailRef} id="email" name="email" type="email" autoComplete="email" className="mj-input" aria-invalid={error ? true : undefined} aria-describedby={error ? "login-error" : undefined} />
      </div>
      <div className="mj-field">
        <label className="mj-label" htmlFor="password">비밀번호</label>
        <input id="password" name="password" type="password" autoComplete="current-password" className="mj-input" aria-invalid={error ? true : undefined} aria-describedby={error ? "login-error" : undefined} />
      </div>
      <button type="submit" className="mj-btn mj-btn-pri" disabled={busy}>{busy ? "확인하는 중…" : "로그인"}</button>
    </form>
  );
}
