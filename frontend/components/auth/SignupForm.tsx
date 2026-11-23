"use client";
// 이메일 가입 · 약관 동의(C05). 가입하면 바로 로그인돼요(API가 세션 쿠키를 심어요).
// - 검사는 '가입하고 업체 보기'를 누를 때 한 번(I6 B), 오류는 칸 아래, 첫 틀린 칸으로 초점을 옮겨요.
// - 가입이 끝나면 기기에 둔 답과 표준견적서를 내 공사로 옮기고(POST /projects + Idempotency-Key) 업체 보기로 가요(N1 A · dev-03).
// - 휴대폰은 선택이에요(9판). 업체에는 가지 않아요.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { ApiError, call, errorText } from "@/lib/backend/client";
import { afterAuth, hasGuestAnswers } from "./after";
import { PHONE_MSG, phoneOk } from "./parts";
import s from "./card.module.css";

type Key = "email" | "password" | "name" | "phone" | "terms";
type Errors = Partial<Record<Key | "form", string>>;
const ORDER: Key[] = ["email", "password", "name", "phone", "terms"];
const ID: Record<Key, string> = { email: "su-email", password: "su-pw", name: "su-name", phone: "su-phone", terms: "su-tos" };
// 약관 '보기'는 새 창으로 열어요: 같은 창으로 가면 돌아왔을 때 넣은 칸이 모두 사라져요(QA r6 M14)
const TERMS = [
  { key: "tos", label: "[필수] 이용약관", see: "/legal?tab=terms", seeLabel: "이용약관 보기" },
  { key: "privacy", label: "[필수] 개인정보 수집 · 이용", see: "/legal?tab=privacy", seeLabel: "개인정보 수집 · 이용 보기" },
  { key: "age", label: "[필수] 만 14세 이상이에요" },
] as const;
type TermKey = (typeof TERMS)[number]["key"];

export function SignupForm({ next, mock }: { next?: string; mock: boolean }) {
  const router = useRouter();
  const [v, setV] = useState({ email: "", password: "", name: "", phone: "" });
  const [agree, setAgree] = useState<Record<TermKey, boolean>>({ tos: false, privacy: false, age: false });
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [carry, setCarry] = useState(false);
  /** 이미 가입한 이메일: 칸 아래 로그인 길을 줘요(QA r6 L6) */
  const [taken, setTaken] = useState(false);
  const allRef = useRef<HTMLInputElement>(null);
  const all = TERMS.every((t) => agree[t.key]);
  const some = TERMS.some((t) => agree[t.key]);

  useEffect(() => { setCarry(hasGuestAnswers()); }, []);
  useEffect(() => { if (allRef.current) allRef.current.indeterminate = some && !all; }, [some, all]);

  const focus = (k: Key | "form") => setTimeout(() => document.getElementById(k === "form" ? "su-form-e" : k === "terms" ? (TERMS.find((t) => !agree[t.key]) ? `su-${TERMS.find((t) => !agree[t.key])!.key}` : "su-all") : ID[k])?.focus(), 0);

  function check(): Errors {
    const e: Errors = {};
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email.trim())) e.email = "이메일 형식을 확인해 주세요. 예: name@example.com";
    if (v.password.length < 8) e.password = "비밀번호를 8자 이상으로 넣어 주세요.";
    if (!v.name.trim()) e.name = "이름을 넣어 주세요.";
    if (v.phone.trim() && !phoneOk(v.phone)) e.phone = PHONE_MSG;
    if (!all) e.terms = "필수 동의 세 가지에 모두 체크해 주세요.";
    return e;
  }

  async function onSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    if (busy) return;
    const e = check();
    setErrors(e);
    const first = ORDER.find((k) => e[k]);
    if (first) { focus(first); return; }
    setBusy(true);
    try {
      await call("POST", "/auth/signup", { email: v.email.trim(), password: v.password, name: v.name.trim(), phone: v.phone.trim() });
    } catch (er) {
      const got: Errors = {};
      if (er instanceof ApiError && er.code === "email_taken") { got.email = er.message; setTaken(true); }
      else if (er instanceof ApiError && er.fields?.length) {
        for (const fe of er.fields) {
          const k = (["name", "phone", "email", "password"] as Key[]).find((x) => x === fe.loc[fe.loc.length - 1] || x === fe.loc[0]);
          if (k && !got[k]) got[k] = k === "phone" ? PHONE_MSG : fe.msg;
        }
      }
      if (!Object.keys(got).length) got.form = errorText(er);
      setErrors(got);
      setBusy(false);
      focus(ORDER.find((k) => got[k]) ?? "form");
      return;
    }
    const a = await afterAuth("customer", next, mock, { fresh: true });
    if (a.kind === "go") { router.push(a.href); router.refresh(); return; }
    // 가입은 됐지만 답을 옮기지 못했어요: 기기 답은 그대로 두고 알려요
    setErrors({ form: `가입했어요. 넣은 답을 내 공사로 옮기지 못했어요: ${a.kind === "error" ? a.message : ""}` });
    setBusy(false);
    focus("form");
  }

  const fieldErr = (k: Key) => errors[k] ?? null;
  // 칸을 고치면 그 칸의 오류 글은 바로 지워요(고친 뒤에도 빨간 글이 남지 않게, QA r6 L4). 다시 검사는 보낼 때 한 번이에요
  const edit = (k: Exclude<Key, "terms">, val: string) => {
    setV((x) => ({ ...x, [k]: val }));
    setErrors((x) => (x[k] ? { ...x, [k]: undefined } : x));
    if (k === "email") setTaken(false);
  };
  const agreeTo = (value: Record<TermKey, boolean>) => { setAgree(value); setErrors((x) => (x.terms ? { ...x, terms: undefined } : x)); };
  const label = carry ? "가입하고 업체 보기" : "가입하기";

  return (
    <form className={s.card} onSubmit={onSubmit} noValidate aria-label="이메일로 가입">
      <section className={s.group}>
        <Field id={ID.email} label="이메일" type="email" autoComplete="email" maxLength={254} value={v.email} error={fieldErr("email")} onChange={(e) => edit("email", e.target.value)} />
        {taken ? <p className={s.note}>이미 회원이에요 · <Button variant="text" href={next ? `/login?next=${encodeURIComponent(next)}` : "/login"}>로그인</Button></p> : null}
        <Field id={ID.password} label="비밀번호" type="password" autoComplete="new-password" maxLength={128} value={v.password} error={fieldErr("password")} hint="8자 이상" onChange={(e) => edit("password", e.target.value)} />
        <Field id={ID.name} label="이름" autoComplete="name" maxLength={50} value={v.name} error={fieldErr("name")} onChange={(e) => edit("name", e.target.value)} />
        <Field id={ID.phone} label="휴대폰" optional type="tel" inputMode="tel" autoComplete="tel" maxLength={20} placeholder="010-0000-0000" value={v.phone} error={fieldErr("phone")} hint="업체에는 가지 않아요." onChange={(e) => edit("phone", e.target.value)} />
      </section>
      <section className={s.group}>
        <fieldset className={s.terms} aria-describedby={errors.terms ? "su-terms-e" : undefined}>
          <legend className="mj-sr">약관 동의</legend>
          <div className={`${s.term} ${s.all}`}>
            <label><input ref={allRef} id="su-all" type="checkbox" className={s.ck} checked={all} onChange={(e) => agreeTo({ tos: e.target.checked, privacy: e.target.checked, age: e.target.checked })} />모두 동의해요</label>
          </div>
          {TERMS.map((t) => (
            <div key={t.key} className={s.term}>
              <label><input id={`su-${t.key}`} type="checkbox" className={s.ck} checked={agree[t.key]} onChange={(e) => agreeTo({ ...agree, [t.key]: e.target.checked })} />{t.label}</label>
              {"see" in t ? <Button variant="text" gray href={t.see} external aria-label={`${t.seeLabel} · 새 창`}>보기</Button> : null}
            </div>
          ))}
        </fieldset>
        {errors.terms ? <p id="su-terms-e" className={s.err}><Icon name="error" size={16} />{errors.terms}</p> : null}
      </section>
      {errors.form ? <p id="su-form-e" tabIndex={-1} className={s.err} role="alert"><Icon name="error" size={16} />{errors.form}</p> : null}
      <Button type="submit" size="lg" block busy={busy}>{busy ? "가입하는 중" : label}</Button>
    </form>
  );
}
