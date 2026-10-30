"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, call, errorText } from "@/lib/backend/client";

type Errors = Partial<Record<"form" | "name" | "email" | "password" | "password2" | "terms", string>>;
const FIELDS = ["name", "email", "password"] as const;
// 오류가 나면 이 순서로 첫 칸에 초점을 옮긴다. 칸 아래 문장이 오류를 알려서 위쪽 요약 상자는 두지 않는다.
const ORDER = ["name", "email", "password", "password2", "terms"] as const;

export function SignupForm({ next }: { next?: string }) {
  const router = useRouter();
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  function focusFirst(err: Errors) {
    const k = ORDER.find((x) => err[x]);
    setTimeout(() => {
      const el = k === "terms" ? formRef.current?.querySelector<HTMLInputElement>('input[name="terms"]') : k ? document.getElementById(k) : null;
      (el ?? formRef.current?.querySelector<HTMLElement>("[data-form-error]"))?.focus();
    }, 0);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const name = String(f.get("name") ?? "").trim();
    const email = String(f.get("email") ?? "").trim();
    const password = String(f.get("password") ?? "");
    const password2 = String(f.get("password2") ?? "");
    const err: Errors = {};
    if (!name) err.name = "이름을 적어 주세요.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) err.email = "이메일 형식을 확인해 주세요. 예: name@example.com";
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) err.password = "영문과 숫자를 섞어 8자 이상으로 적어 주세요.";
    if (password2 !== password) err.password2 = "비밀번호가 서로 달라요.";
    if (!f.get("terms") || !f.get("privacy")) err.terms = "필수 동의 두 가지에 체크해 주세요.";
    setErrors(err);
    if (Object.keys(err).length) { focusFirst(err); return; }
    setBusy(true);
    try {
      // 가입하면 바로 로그인된다(API가 세션 쿠키를 심는다).
      // 약관 동의는 아직 API가 받아 남기지 않는다 (정할 것).
      await call("POST", "/auth/signup", { name, email, password });
      router.push(next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/admin") ? next : "/my");
      router.refresh();
    } catch (er) {
      const got: Errors = {};
      if (er instanceof ApiError && er.code === "email_taken") got.email = er.message;
      else if (er instanceof ApiError && er.fields?.length) {
        for (const f of er.fields) {
          const k = FIELDS.find((x) => x === f.loc[0]);
          if (k && !got[k]) got[k] = f.msg;
        }
      }
      if (!Object.keys(got).length) got.form = errorText(er);
      setErrors(got);
      setBusy(false);
      focusFirst(got);
    }
  }

  const f = (k: keyof Errors) => ({ "aria-invalid": errors[k] ? true : undefined, "aria-describedby": errors[k] ? `${k}-err` : undefined });

  return (
    <form ref={formRef} className="mj-panel" onSubmit={onSubmit} noValidate style={{ gap: 18 }}>
      {errors.form ? <p data-form-error tabIndex={-1} role="alert" className="mj-error">{errors.form}</p> : null}
      <div className="mj-field">
        <label className="mj-label" htmlFor="name">이름</label>
        <input id="name" name="name" autoComplete="name" className="mj-input" {...f("name")} />
        {errors.name ? <p id="name-err" className="mj-error">{errors.name}</p> : null}
      </div>
      <div className="mj-field">
        <label className="mj-label" htmlFor="email">이메일</label>
        <input id="email" name="email" type="email" autoComplete="email" className="mj-input" {...f("email")} />
        {errors.email ? <p id="email-err" className="mj-error">{errors.email}</p> : null}
      </div>
      <div className="mj-field">
        <label className="mj-label" htmlFor="password">비밀번호</label>
        <input id="password" name="password" type="password" autoComplete="new-password" className="mj-input" aria-invalid={errors.password ? true : undefined} aria-describedby={errors.password ? "pw-hint password-err" : "pw-hint"} />
        <p id="pw-hint" className="mj-hint">영문, 숫자, 8자 이상</p>
        {errors.password ? <p id="password-err" className="mj-error">{errors.password}</p> : null}
      </div>
      <div className="mj-field">
        <label className="mj-label" htmlFor="password2">비밀번호 확인</label>
        <input id="password2" name="password2" type="password" autoComplete="new-password" className="mj-input" {...f("password2")} />
        {errors.password2 ? <p id="password2-err" className="mj-error">{errors.password2}</p> : null}
      </div>
      <fieldset className="mj-fieldset" id="terms" aria-describedby={errors.terms ? "terms-err" : undefined}>
        <legend className="mj-label" style={{ marginBottom: 8 }}>약관 동의</legend>
        <label className="mj-choice"><input type="checkbox" name="terms" /><span className="mj-choice-main"><span className="mj-choice-title">이용약관 동의 (필수)</span></span></label>
        <label className="mj-choice"><input type="checkbox" name="privacy" /><span className="mj-choice-main"><span className="mj-choice-title">개인정보 수집 · 이용 동의 (필수)</span><span className="mj-choice-desc">이름 · 이메일 · 집 정보를 견적 요청에만 써요</span></span></label>
        {errors.terms ? <p id="terms-err" className="mj-error">{errors.terms}</p> : null}
      </fieldset>
      <button type="submit" className="mj-btn mj-btn-pri" disabled={busy}>{busy ? "가입하는 중…" : "가입하기"}</button>
    </form>
  );
}
