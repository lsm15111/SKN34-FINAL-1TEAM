"use client";
// 업체 가입 신청(V01 v_signup): 첫 칸은 9판 그대로(상호 · 대표자 · 사업자등록번호 · 이메일 · 사업자등록증 · 하는 공사 · 다니는 지역).
// '가입 신청'을 누르면 다음 칸에서 휴대폰 · 비밀번호 · 약관 동의를 넣고 보내요.
// 다니는 지역은 지역 두 칸 목록(RegionPicker, 여러 개 · 지역 전체)이에요. 기본 정보 지역 고르기와 같은 모양이에요.
//   새로 신청: 신청서 + 사업자등록증을 multipart로 POST /auth/vendor-signup → 로그인된 채 업체 홈(심사 기다림).
// 다시 신청(again, V22 '신청 정보 고치기'): 로그인한 거절된 업체. 지난 값을 채우고 이메일 · 비밀번호 · 약관 칸은 없어요.
//   새 등록증은 고르면 바로 올리고(POST /files kind=license) → POST /vendor/application/reapply(멱등 키). 등록번호도 고칠 수 있어요(VS02, 남의 번호면 409 biz_no_taken).
// CF-11: '하는 공정' → '하는 공사'. 오류는 칸 아래에 보이고 첫 틀린 칸으로 옮겨 가요.
import { useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { Check } from "@/components/ui/Check";
import { ChoiceChips } from "@/components/ui/ChoiceChip";
import { Field } from "@/components/ui/Field";
import { FileDrop } from "@/components/ui/FileDrop";
import { FileRow } from "@/components/ui/FileRow";
import { Icon } from "@/components/ui/Icon";
import { RegionPicker } from "@/components/ui/RegionPicker";
import { useToast } from "@/components/ui/Toast";
import type { Region } from "@/lib/api/vendor";
import { ApiError, errorText, type Schemas } from "@/lib/backend/client";
import { phoneText, tradeLabel } from "@/lib/labels";
import { MOCK } from "@/lib/mock/v3c/mode";
import { newKey, send, upload } from "@/components/pro/send";
import { Eyebrow, Group, Small } from "@/components/pro/ui/parts";
import { PHONE_MSG, phoneOk } from "./parts";
import { fileErrorText, isImage, LICENSE_ACCEPT, licenseError } from "./VendorSignupForm.license";
import s from "./VendorSignupForm.module.css";

type Area = { sido: string; sgg: string };
type Lic = { filename: string; size: number; content_type: string };
export type Again = { email: string; prev: { biz_name: string; owner_name: string; phone: string; biz_no: string; trades: string[]; areas: Area[]; license: Lic | null } };
type Key = "bizName" | "owner" | "bizNo" | "email" | "file" | "trades" | "areas" | "phone" | "pw" | "pw2" | "terms" | "form";
type Errs = Partial<Record<Key, string>>;
const STEP1: Key[] = ["bizName", "owner", "bizNo", "email", "file", "trades", "areas"];
const STEP2: Key[] = ["phone", "pw", "pw2", "terms"];
const TRADES = ["dobae", "mokgong"] as const;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// 약관 '보기'는 새 창으로 열어요: 같은 창으로 가면 돌아왔을 때 넣은 칸이 모두 사라져요(QA r6 M14)
const TERMS = [
  { key: "tos", label: "[필수] 이용약관", see: "/legal?tab=terms", seeLabel: "이용약관 보기" },
  { key: "privacy", label: "[필수] 개인정보 수집 · 이용", see: "/legal?tab=privacy", seeLabel: "개인정보 수집 · 이용 보기" },
] as const;
type TermKey = (typeof TERMS)[number]["key"];
const API_KEY: Record<string, Key> = {
  email: "email", password: "pw", biz_name: "bizName", owner_name: "owner", biz_no: "bizNo", phone: "phone",
  trades: "trades", areas: "areas", license_file: "file", license_file_id: "file",
};

const digits = (v: string) => v.replace(/\D/g, "");
/** 사업자등록번호 칸: 숫자만 받고 '-'는 저절로 붙여요(123-45-67890) */
function bizInput(v: string) {
  const d = digits(v).slice(0, 10);
  return d.length > 5 ? `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}` : d.length > 3 ? `${d.slice(0, 3)}-${d.slice(3)}` : d;
}
const areaKey = (a: Area) => `${a.sido}/${a.sgg}`;

export function VendorSignupForm({ regions, again }: { regions: Region[]; again?: Again }) {
  const router = useRouter();
  const toast = useToast();
  const p = again?.prev;
  const [step, setStep] = useState<1 | 2>(1);
  const [bizName, setBizName] = useState(p?.biz_name ?? "");
  const [owner, setOwner] = useState(p?.owner_name ?? "");
  const [bizNo, setBizNo] = useState(p?.biz_no ? bizInput(p.biz_no) : "");
  const [email, setEmail] = useState("");
  const [file, setFile] = useState<File | null>(null);
  /** 다시 신청: 새로 올린 등록증(서버가 사진 위치 정보를 지운 뒤) */
  const [up, setUp] = useState<(Lic & { id: string }) | null>(null);
  const [uploading, setUploading] = useState(false);
  const [trades, setTrades] = useState<string[]>(p?.trades ?? []);
  const [areas, setAreas] = useState<string[]>(p?.areas.map(areaKey) ?? []);
  const [sido, setSido] = useState(p?.areas[0]?.sido ?? regions[0]?.id ?? "seoul");
  const [phone, setPhone] = useState(phoneText(p?.phone));
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [agree, setAgree] = useState<Record<TermKey, boolean>>({ tos: false, privacy: false });
  const [errs, setErrs] = useState<Errs>({});
  const [busy, setBusy] = useState(false);
  const [idem] = useState(newKey);
  const refs = {
    bizName: useRef<HTMLInputElement>(null), owner: useRef<HTMLInputElement>(null), bizNo: useRef<HTMLInputElement>(null), email: useRef<HTMLInputElement>(null),
    phone: useRef<HTMLInputElement>(null), pw: useRef<HTMLInputElement>(null), pw2: useRef<HTMLInputElement>(null),
  };
  const allOn = TERMS.every((t) => agree[t.key]);

  function clear(k: Key) { if (errs[k] || errs.form) setErrs((e) => ({ ...e, [k]: undefined, form: undefined })); }
  function focusFirst(e: Errs) {
    const k = [...STEP1, ...STEP2, "form" as Key].find((x) => e[x]);
    if (!k) return;
    setTimeout(() => {
      const el =
        k === "file" ? document.querySelector<HTMLElement>("#v-doc input[type=file]")
          : k === "trades" ? document.querySelector<HTMLElement>("#v-trades input")
          : k === "areas" ? document.querySelector<HTMLElement>("#v-areas input")
          : k === "terms" ? document.querySelector<HTMLElement>("#v-terms input")
          : k === "form" ? document.getElementById("v-form-e")
          : refs[k as keyof typeof refs]?.current;
      el?.focus();
    }, 0);
  }

  function check1(): Errs {
    const e: Errs = {};
    if (!bizName.trim()) e.bizName = "상호를 등록증과 같게 적어 주세요.";
    if (!owner.trim()) e.owner = "대표자 이름을 등록증과 같게 적어 주세요.";
    if (digits(bizNo).length !== 10) e.bizNo = "사업자등록번호 10자리를 넣어 주세요.";
    if (!again) {
      if (!EMAIL.test(email.trim())) e.email = "이메일 형식을 확인해 주세요. 예: name@example.com";
      if (!file) e.file = "사업자등록증 파일을 올려 주세요.";
      else if (licenseError(file)) e.file = licenseError(file) ?? undefined;
    }
    if (!trades.length) e.trades = "하는 공사를 하나 이상 골라 주세요.";
    if (!areas.length) e.areas = "다니는 지역을 하나 이상 골라 주세요.";
    return e;
  }
  function check2(): Errs {
    const e: Errs = {};
    if (!phoneOk(phone)) e.phone = PHONE_MSG;
    if (!again) {
      if (pw.length < 8) e.pw = "비밀번호를 8자 이상으로 넣어 주세요.";
      else if (pw2 !== pw) e.pw2 = "비밀번호가 달라요.";
      if (!allOn) e.terms = "필수 동의 두 가지에 모두 체크해 주세요.";
    }
    return e;
  }

  /** 서버 오류를 칸으로 나눠요. 첫 칸 오류면 첫 칸으로 돌아가요 */
  function fail(er: unknown) {
    const got: Errs = {};
    const fileMsg = fileErrorText(er);
    if (fileMsg) got.file = fileMsg;
    else if (er instanceof ApiError && er.code === "email_taken") got.email = er.message;
    else if (er instanceof ApiError && er.code === "biz_no_taken") got.bizNo = er.message;
    else if (er instanceof ApiError && er.code === "region") got.areas = er.message;
    else if (er instanceof ApiError && er.fields?.length) {
      for (const f of er.fields) {
        const k = API_KEY[String(f.loc[f.loc.length - 1] ?? "")] ?? API_KEY[String(f.loc[0] ?? "")] ?? "form";
        if (!got[k]) got[k] = k === "phone" ? PHONE_MSG : f.msg;
      }
    }
    if (!Object.keys(got).length) got.form = errorText(er);
    setErrs(got);
    if (STEP1.some((k) => got[k])) setStep(1);
    focusFirst(got);
  }

  async function pickFile(files: File[]) {
    const f = files[0];
    if (!f) return;
    const bad = licenseError(f);
    if (bad) { setErrs((e) => ({ ...e, file: bad })); return; }
    clear("file");
    if (!again) { setFile(f); return; }
    // 다시 신청은 로그인한 업체라 바로 올려요(서버가 형식 · 크기를 다시 보고 사진 위치 정보를 지워요)
    setUploading(true);
    try {
      const out = await upload("license", f);
      setUp({ id: out.id, filename: out.filename, size: out.size, content_type: out.content_type });
    } catch (e) {
      setErrs((x) => ({ ...x, file: fileErrorText(e) ?? errorText(e) }));
    } finally {
      setUploading(false);
    }
  }

  function next(ev: FormEvent) {
    ev.preventDefault();
    const e = check1();
    setErrs(e);
    if (Object.keys(e).length) { focusFirst(e); return; }
    if (again) { void submit(); return; }
    setStep(2);
    setTimeout(() => { window.scrollTo({ top: 0 }); refs.phone.current?.focus(); }, 0);
  }

  async function submit(ev?: FormEvent) {
    ev?.preventDefault();
    if (busy || uploading) return;
    const e = { ...check1(), ...check2() };
    setErrs(e);
    if (Object.keys(e).length) { if (STEP1.some((k) => e[k])) setStep(1); focusFirst(e); return; }
    setBusy(true);
    const areaIn = areas.map((a) => { const [sd, sg] = a.split("/"); return { sido: sd, sgg: sg }; });
    const tradeIn = TRADES.filter((t) => trades.includes(t));
    try {
      if (again) {
        const body: Schemas["ReapplyIn"] = { biz_name: bizName.trim(), owner_name: owner.trim(), biz_no: digits(bizNo), phone: digits(phone), trades: tradeIn, areas: areaIn, ...(up ? { license_file_id: up.id } : {}) };
        await send("POST", "/vendor/application/reapply", body, { idem });
        toast.show("다시 신청했어요. 관리자가 확인하면 알림으로 알려 드려요.");
      } else {
        const fd = new FormData();
        fd.append("email", email.trim());
        fd.append("password", pw);
        fd.append("biz_name", bizName.trim());
        fd.append("owner_name", owner.trim());
        fd.append("biz_no", digits(bizNo));
        fd.append("phone", digits(phone));
        tradeIn.forEach((t) => fd.append("trades", t));
        areas.forEach((a) => fd.append("areas", a));
        fd.append("license_file", file as File, (file as File).name);
        await send("POST", "/auth/vendor-signup", fd, { idem });
      }
      // 예시 모드는 세션이 없어서 '심사 기다림' 예시 화면으로 가요
      router.push(MOCK ? "/vendor?mock=pending" : "/vendor");
      router.refresh();
    } catch (er) {
      setBusy(false);
      fail(er);
    }
  }

  const oldLic = !up && p?.license ? p.license : null;

  if (step === 2) {
    return (
      <>
        <Main narrow>
          <PageHead title="업체 가입 신청" />
          <form id="v-signup-2" noValidate onSubmit={submit} className={s.form} aria-label="업체 가입 신청 · 비밀번호와 약관">
            <Group>
              <Field ref={refs.phone} label="휴대폰" type="tel" inputMode="tel" autoComplete="tel" maxLength={20} value={phone} error={errs.phone} onChange={(e) => { setPhone(e.target.value); clear("phone"); }} />
              <Field ref={refs.pw} label="비밀번호" type="password" autoComplete="new-password" maxLength={128} value={pw} error={errs.pw} hint="8자 이상" onChange={(e) => { setPw(e.target.value); clear("pw"); clear("pw2"); }} />
              <Field ref={refs.pw2} label="비밀번호 확인" type="password" autoComplete="new-password" maxLength={128} value={pw2} error={errs.pw2} onChange={(e) => { setPw2(e.target.value); clear("pw2"); }} />
            </Group>
            <Group>
              <fieldset id="v-terms" className={s.terms} aria-describedby={errs.terms ? "v-terms-e" : undefined}>
                <legend className="mj-sr">약관 동의</legend>
                <Check row label={<b>모두 동의해요</b>} checked={allOn} onChange={(on) => { setAgree({ tos: on, privacy: on }); clear("terms"); }} />
                {TERMS.map((t) => (
                  <div key={t.key} className={s.term}>
                    <Check label={t.label} checked={agree[t.key]} onChange={(on) => { setAgree((a) => ({ ...a, [t.key]: on })); clear("terms"); }} />
                    <Button variant="text" gray href={t.see} external aria-label={`${t.seeLabel} · 새 창`}>보기</Button>
                  </div>
                ))}
              </fieldset>
              {errs.terms ? <p id="v-terms-e" className={s.err}><Icon name="error" size={16} />{errs.terms}</p> : null}
            </Group>
            {errs.form ? <p id="v-form-e" tabIndex={-1} className={s.err} role="alert"><Icon name="error" size={16} />{errs.form}</p> : null}
          </form>
        </Main>
        <BottomBar>
          <Button size="lg" variant="secondary" onClick={() => { setStep(1); setErrs({}); }} disabled={busy}>이전</Button>
          <Button size="lg" type="submit" form="v-signup-2" busy={busy}>{busy ? "보내는 중" : "가입 신청"}</Button>
        </BottomBar>
      </>
    );
  }

  return (
    <>
      <Main narrow>
        <PageHead title="업체 가입 신청" />
        {again ? <Small>지난 신청 값을 채워 뒀어요. 고칠 칸만 고쳐 다시 신청해요.</Small> : null}
        <form id="v-signup-1" noValidate onSubmit={next} className={s.form} aria-label={again ? "업체 다시 신청" : "업체 가입 신청"}>
          <Group>
            <Field ref={refs.bizName} label="상호" autoComplete="organization" maxLength={100} value={bizName} error={errs.bizName} onChange={(e) => { setBizName(e.target.value); clear("bizName"); }} />
            <Field ref={refs.owner} label="대표자" autoComplete="name" maxLength={50} value={owner} error={errs.owner} onChange={(e) => { setOwner(e.target.value); clear("owner"); }} />
            <Field
              ref={refs.bizNo} label="사업자등록번호" num inputMode="numeric" autoComplete="off" maxLength={12} value={bizNo} error={errs.bizNo}
              onChange={(e) => { setBizNo(bizInput(e.target.value)); clear("bizNo"); }}
              onBlur={() => { if (bizNo && digits(bizNo).length !== 10) setErrs((x) => ({ ...x, bizNo: "사업자등록번호 10자리를 넣어 주세요." })); }}
            />
            {again ? (
              <>
                <Field label="이메일" value={again.email} readOnly />
                <Field ref={refs.phone} label="휴대폰" type="tel" inputMode="tel" autoComplete="tel" maxLength={20} value={phone} error={errs.phone} onChange={(e) => { setPhone(e.target.value); clear("phone"); }} />
              </>
            ) : (
              <Field ref={refs.email} label="이메일" type="email" autoComplete="email" maxLength={254} value={email} error={errs.email} onChange={(e) => { setEmail(e.target.value); clear("email"); }} />
            )}
          </Group>

          <Group>
            <div id="v-doc" className={s.doc}>
              <Eyebrow>사업자등록증</Eyebrow>
              {file ? (
                <FileRow name={file.name} size={file.size} action={<Button variant="text" gray onClick={() => setFile(null)} aria-label={`${file.name} 빼기`}>빼기</Button>} />
              ) : up ? (
                <FileRow name={up.filename} size={up.size} note={isImage(up.content_type, up.filename) ? "위치 정보 지움" : undefined} action={<Button variant="text" gray onClick={() => setUp(null)} aria-label={`${up.filename} 빼기`}>빼기</Button>} />
              ) : oldLic ? (
                <FileRow name={oldLic.filename} size={oldLic.size} note="지난 신청 파일" />
              ) : null}
              <FileDrop kind="doc" label="사업자등록증 파일 올리기" accept={LICENSE_ACCEPT} multiple={false} types="PDF · 사진" busy={uploading} error={errs.file} onFiles={pickFile} />
              <Small>{again && oldLic ? "새로 올리지 않으면 지난 파일로 다시 봐요. " : ""}관리자가 확인하고, 승인되면 알림으로 알려 드려요.</Small>
            </div>
          </Group>

          <Group>
            <div id="v-trades">
              <ChoiceChips multiple legend="하는 공사" options={TRADES.map((t) => ({ value: t, label: tradeLabel(t) }))} value={trades} onChange={(v) => { setTrades(v); clear("trades"); }} error={errs.trades} />
            </div>
            <div id="v-areas" className={s.areas}>
              <p className={s.legend} id="v-areas-l">다니는 지역{areas.length ? <span className="mj-num"> · {areas.length}곳</span> : null}</p>
              <RegionPicker mode="many" label="다니는 지역" regions={regions} sido={sido} onSido={setSido}
                value={areas} onChange={(v) => { setAreas(v); clear("areas"); }} className={s.picker} />
              {errs.areas ? <p className={s.err} role="alert"><Icon name="error" size={16} />{errs.areas}</p> : null}
            </div>
          </Group>
          {errs.form ? <p id="v-form-e" tabIndex={-1} className={s.err} role="alert"><Icon name="error" size={16} />{errs.form}</p> : null}
        </form>
      </Main>
      <BottomBar>
        <Button size="lg" block type="submit" form="v-signup-1" busy={busy || uploading}>{busy ? "보내는 중" : again ? "다시 신청" : "가입 신청"}</Button>
      </BottomBar>
    </>
  );
}
