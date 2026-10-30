"use client";
// 업체 회원가입 (FFV-01): 기본 회원정보 + 사업자등록증만 받는다. 관리자가 승인하면 업체 기능을 쓴다.
// 상호 · 공정 · 시공 지역 같은 업체 정보는 승인 뒤 업체 정보 관리(FFV-08)에서 받는다.
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, call, errorText } from "@/lib/backend/client";
import { PhotoDrop, toPhotos, type Photo } from "@/components/start/PhotoDrop";

type Key = "form" | "name" | "email" | "password" | "password2" | "license" | "terms";
type Errors = Partial<Record<Key, string>>;
const MAX_MB = 10;
const TYPES = ["image/jpeg", "image/png", "application/pdf"];
// 오류가 나면 이 순서로 첫 칸에 초점을 옮긴다. 칸 아래 문장이 오류를 알려서 위쪽 요약 상자는 두지 않는다.
const ORDER: { k: Key; id: string }[] = [{ k: "name", id: "name" }, { k: "email", id: "email" }, { k: "password", id: "password" }, { k: "password2", id: "password2" }, { k: "license", id: "license_file" }];

export function VendorSignupForm() {
  const router = useRouter();
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [license, setLicense] = useState<Photo[]>([]); // 사업자등록증 한 장 (도면 칸과 같은 끌어다 놓는 영역)
  const formRef = useRef<HTMLFormElement>(null);

  function focusFirst(err: Errors) {
    const hit = ORDER.find((x) => err[x.k]);
    setTimeout(() => {
      const el = hit ? document.getElementById(hit.id) : err.terms ? formRef.current?.querySelector<HTMLInputElement>('input[name="terms"]') : null;
      (el ?? formRef.current?.querySelector<HTMLElement>("[data-form-error]"))?.focus();
    }, 0);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const name = String(f.get("name") ?? "").trim();
    const email = String(f.get("email") ?? "").trim();
    const password = String(f.get("password") ?? "");
    const file = license[0]?.file;
    const err: Errors = {};
    if (!name) err.name = "담당자 이름을 적어 주세요.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) err.email = "이메일 형식을 확인해 주세요. 예: name@example.com";
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) err.password = "영문과 숫자를 섞어 8자 이상으로 적어 주세요.";
    if (String(f.get("password2") ?? "") !== password) err.password2 = "비밀번호가 서로 달라요.";
    if (!file || !file.size) err.license = "사업자등록증 파일을 올려 주세요.";
    else if (file.type && !TYPES.includes(file.type)) err.license = "JPG · PNG · PDF 파일만 올릴 수 있어요.";
    else if (file.size > MAX_MB * 1024 * 1024) err.license = `${MAX_MB}MB까지 올릴 수 있어요.`;
    if (!f.get("terms") || !f.get("privacy")) err.terms = "필수 동의 두 가지에 체크해 주세요.";
    setErrors(err);
    if (Object.keys(err).length) { focusFirst(err); return; }

    const body = new FormData();
    body.append("name", name);
    body.append("email", email);
    body.append("password", password);
    body.append("license_file", file as File, (file as File).name);
    setBusy(true);
    try {
      await call("POST", "/auth/vendor-signup", body);
      router.push("/vendor");
      router.refresh();
    } catch (er) {
      const got: Errors = {};
      if (er instanceof ApiError && er.code === "email_taken") got.email = er.message;
      else if (er instanceof ApiError && ["file_type", "file_too_big", "file_broken", "file_empty"].includes(er.code)) got.license = er.message;
      else if (er instanceof ApiError && er.fields?.length) {
        for (const fe of er.fields) {
          const k = fe.loc[0] === "license_file" ? "license" : (["name", "email", "password"] as const).find((x) => x === fe.loc[0]);
          if (k && !got[k]) got[k] = fe.msg;
        }
      }
      if (!Object.keys(got).length) got.form = errorText(er);
      setErrors(got);
      setBusy(false);
      focusFirst(got);
    }
  }

  const a = (k: Key, hint?: string) => ({ "aria-invalid": errors[k] ? true : undefined, "aria-describedby": [hint, errors[k] ? `${k}-err` : ""].filter(Boolean).join(" ") || undefined });
  const msg = (k: Key) => (errors[k] ? <p id={`${k}-err`} className="mj-error">{errors[k]}</p> : null);

  return (
    <form ref={formRef} className="mj-panel" onSubmit={onSubmit} noValidate style={{ gap: 18 }}>
      {errors.form ? <p data-form-error tabIndex={-1} role="alert" className="mj-error">{errors.form}</p> : null}
      <div className="mj-field">
        <label className="mj-label" htmlFor="name">담당자 이름</label>
        <input id="name" name="name" autoComplete="name" className="mj-input" {...a("name")} />
        {msg("name")}
      </div>
      <div className="mj-field">
        <label className="mj-label" htmlFor="email">이메일</label>
        <p id="email-hint" className="mj-hint">로그인 아이디로 써요</p>
        <input id="email" name="email" type="email" autoComplete="email" className="mj-input" {...a("email", "email-hint")} />
        {msg("email")}
      </div>
      <div className="mj-field">
        <label className="mj-label" htmlFor="password">비밀번호</label>
        <input id="password" name="password" type="password" autoComplete="new-password" className="mj-input" {...a("password", "pw-hint")} />
        <p id="pw-hint" className="mj-hint">영문, 숫자, 8자 이상</p>
        {msg("password")}
      </div>
      <div className="mj-field">
        <label className="mj-label" htmlFor="password2">비밀번호 확인</label>
        <input id="password2" name="password2" type="password" autoComplete="new-password" className="mj-input" {...a("password2")} />
        {msg("password2")}
      </div>
      <div className="mj-field">
        <PhotoDrop id="license_file" label="사업자등록증" photos={license} max={1} accept={TYPES.join(",")} maxMB={MAX_MB} hint="JPG · PNG · PDF"
          onAdd={(files) => setLicense((old) => { old.forEach((x) => URL.revokeObjectURL(x.url)); return toPhotos(files); })}
          onRemove={() => setLicense((old) => { old.forEach((x) => URL.revokeObjectURL(x.url)); return []; })} />
        {msg("license")}
      </div>
      <fieldset className="mj-fieldset" id="terms" aria-describedby={errors.terms ? "terms-err" : undefined}>
        <legend className="mj-label" style={{ marginBottom: 8 }}>약관 동의</legend>
        <label className="mj-choice"><input type="checkbox" name="terms" /><span className="mj-choice-main"><span className="mj-choice-title">이용약관 동의 (필수)</span></span></label>
        <label className="mj-choice"><input type="checkbox" name="privacy" /><span className="mj-choice-main"><span className="mj-choice-title">개인정보 수집 · 이용 동의 (필수)</span><span className="mj-choice-desc">이름 · 이메일 · 사업자등록증을 가입 심사에만 써요</span></span></label>
        {msg("terms")}
      </fieldset>
      <button type="submit" className="mj-btn mj-btn-pri" disabled={busy}>{busy ? "신청하는 중…" : "가입 신청하기"}</button>
    </form>
  );
}
