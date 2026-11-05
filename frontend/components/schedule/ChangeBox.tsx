"use client";
// 수락한 뒤 공사 날짜 바꾸기 (시안 WPlanDone '확정한 날짜 바꾸기' · WSchedule '수락한 뒤'):
// 업체가 새 날짜를 올렸으면 '새 날짜 수락하기'(확인 창, 화면이 본 확정 공정표 버전으로) · 아니면 '공사 날짜 바꾸기 요청하기'(후보 1~3개 + 이유 필수).
// 후보 · 끝나는 날 · 남은 요청 수는 API 값 그대로다. 수락하기 전까지는 지금 날짜가 그대로다.
// 업체가 공사를 끝냈다고 올린 뒤(finished)에는 날짜 바꾸기 요청을 두지 않는다(서버도 409).
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FieldError } from "@/components/auth/parts";
import { spanRo as ro } from "@/components/plan/text";
import { day } from "@/components/confirm/text";
import { Check, Close, Warn } from "@/components/vendors/icons";
import { iGa } from "@/components/vendors/text";
import { ApiError, call, errorText } from "@/lib/backend/client";
import { tradeLabel } from "@/lib/labels";
import { offText, span, type DateReq, type Proposal, type Schedule, type StartOption } from "./text";
import d from "@/components/vendors/dialog.module.css";
import s from "./schedule.module.css";

const WISH_MAX = 3;
const REASON_MAX = 300;

type Props = {
  projectId: string;
  dealId: string;
  trade: string;
  vendorName: string;
  /** 수락 기다리는 새 날짜 (업체가 올림) */
  proposal: Proposal | null;
  /** 열린 날짜 바꾸기 요청 */
  request: DateReq | null;
  requestsLeft: number;
  /** 업체가 공사를 끝냈다고 올린 뒤: 날짜를 바꾸지 않는다 */
  finished: boolean;
  /** 새 날짜가 다른 공정과 겹쳐 수락할 수 없음 (API fit.conflicts) */
  conflict: boolean;
  /** 요청 후보: 지금과 같은 일하는 날 수, 다른 공정과 겹치지 않는 날부터 */
  options: StartOption[];
  weekendWork: boolean;
  /** 이 집 공정이 둘 이상 */
  multi: boolean;
  tel: string | null;
  /** 화면이 본 확정 공정표 버전 (API final_version) */
  seenVersion: number;
  planHref: string;
  /** 다음 할 일 (다른 공정 날짜 확인 · 확정 공정표): 새 날짜가 없을 때 맨 앞 주 버튼 */
  next?: { href: string; label: string } | null;
};

type Err = { text: string; code?: string; retry?: "accept" | "request" };

const Spin = () => (
  <svg className={s.spin} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M8 2a6 6 0 1 1-6 6" strokeLinecap="round" /></svg>
);

export function ChangeBox(p: Props) {
  const router = useRouter();
  const dlg = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const noRef = useRef<HTMLButtonElement>(null);
  const doneRef = useRef<HTMLParagraphElement>(null);
  const sentRef = useRef<HTMLParagraphElement>(null);
  const firstOpt = useRef<HTMLInputElement>(null);
  const whyRef = useRef<HTMLTextAreaElement>(null);
  const tName = tradeLabel(p.trade);
  const x = p.proposal;
  const canRequest = !p.finished && !p.request && p.requestsLeft > 0;

  const [busy, setBusy] = useState<"" | "accept" | "request">("");
  const [err, setErr] = useState<Err | null>(null);
  const [done, setDone] = useState("");
  const [sent, setSent] = useState(false);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [pickErr, setPickErr] = useState("");
  const [whyErr, setWhyErr] = useState("");
  const acceptId = useRef<{ id: string; dates: string } | null>(null);

  useEffect(() => { if (done) doneRef.current?.focus(); }, [done]);
  useEffect(() => { if (sent) sentRef.current?.focus(); }, [sent]);

  function fail(e: unknown, retry: Err["retry"], netText: string) {
    if (e instanceof ApiError && e.status === 0) return setErr({ text: netText, retry });
    setErr({ text: errorText(e), code: e instanceof ApiError ? e.code : undefined });
    router.refresh();
  }

  function ask() {
    if (busy || !x) return;
    acceptId.current = { id: x.id, dates: span(x.start, x.end) };
    setErr(null);
    dlg.current?.showModal();
    noRef.current?.focus();
  }

  async function accept() {
    const a = acceptId.current;
    if (busy || !a) return;
    setBusy("accept");
    setErr(null);
    try {
      await call<Schedule>("POST", `/projects/${p.projectId}/deals/${p.dealId}/dates/${a.id}/accept`, { seen_version: p.seenVersion });
      setDone(a.dates);
      setOpen(false);
      router.refresh();
    } catch (e) {
      fail(e, "accept", "연결이 끊겨 수락하지 못했어요. 다시 눌러 주세요.");
    }
    setBusy("");
  }

  async function request() {
    if (busy) return;
    const wish = p.options.map((o) => o.start).filter((v) => picked.includes(v));
    const why = reason.trim();
    let bad = false;
    if (!wish.length) { setPickErr("시작하고 싶은 날을 하나 이상 골라 주세요."); bad = true; }
    if (!why) { setWhyErr("날짜를 바꾸고 싶은 이유를 적어 주세요."); bad = true; }
    if (bad) {
      (wish.length ? whyRef.current : firstOpt.current)?.focus();
      return;
    }
    setBusy("request");
    setErr(null);
    try {
      await call<Schedule>("POST", `/projects/${p.projectId}/deals/${p.dealId}/date-requests`, { wish_dates: wish, reason: why });
      setSent(true);
      setOpen(false);
      setPicked([]);
      setReason("");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.code === "reason") { setWhyErr(e.message); whyRef.current?.focus(); }
      else if (e instanceof ApiError && e.status === 422) { setPickErr(e.message); firstOpt.current?.focus(); }
      else fail(e, "request", "연결이 끊겨 요청을 보내지 못했어요. 다시 눌러 주세요.");
    }
    setBusy("");
  }

  function toggle(v: string, on: boolean) {
    setPickErr("");
    if (!on) return setPicked((a) => a.filter((t) => t !== v));
    if (picked.length >= WISH_MAX) return setPickErr(`${WISH_MAX}개까지 고를 수 있어요. 하나를 빼고 골라 주세요.`);
    setPicked((a) => [...a, v]);
  }

  const errLine = err ? (
    err.code === "dates_changed" ? (
      <div className={`mj-notice mj-notice-warn ${s.note}`} role="alert">
        <span className={s.noteWarn}><Warn /></span>
        <p><b>날짜가 바뀌었어요.</b> {iGa(p.vendorName)} 새 날짜를 다시 올렸어요. 새 날짜를 확인해 주세요.</p>
      </div>
    ) : (
      <div className={s.err}>
        <FieldError id="cb-e" alert>{err.text}</FieldError>
        {err.retry ? <button type="button" className={`mj-btn mj-btn-sec ${s.self}`} onClick={() => void (err.retry === "accept" ? accept() : request())}>다시 시도</button> : null}
      </div>
    )
  ) : null;

  return (
    <div className={s.box}>
      {done ? (
        <p ref={doneRef} tabIndex={-1} role="status" className={`mj-st mj-st-ok mj-num ${s.stLine} ${s.stBig} ${s.focusT}`}><Check size={16} />{tName} 날짜를 {ro(done)} 바꿨어요. 확정 공정표에 넣었어요.</p>
      ) : null}
      {sent ? (
        <p ref={sentRef} tabIndex={-1} role="status" className={`mj-st mj-st-ok ${s.stLine} ${s.stBig} ${s.focusT}`}><Check size={16} />날짜 바꾸기를 요청했어요. {iGa(p.vendorName)} 새 날짜를 올리면 알려 드려요.</p>
      ) : null}
      {errLine}

      <div className={s.btns}>
        {!x && p.next ? <Link className="mj-btn mj-btn-pri" href={p.next.href}>{p.next.label}</Link> : null}
        {x && !p.conflict ? (
          <button ref={opener} type="button" className={`mj-btn mj-btn-pri ${busy === "accept" ? s.busy : ""}`} aria-disabled={busy ? true : undefined} aria-haspopup="dialog" onClick={ask}>
            {busy === "accept" ? <><Spin />수락하는 중이에요…</> : "새 날짜 수락하기"}
          </button>
        ) : null}
        {canRequest ? (
          <button type="button" className="mj-btn mj-btn-sec" aria-expanded={open} aria-controls="cb-req" onClick={() => { setOpen((o) => !o); setPickErr(""); setWhyErr(""); }}>
            {x ? "다른 날짜 요청하기" : "공사 날짜 바꾸기 요청하기"}
            <svg className={open ? s.up : undefined} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3.5 5.5L7 9l3.5-3.5" /></svg>
          </button>
        ) : null}
        {!x && p.next?.href === p.planHref ? null : <Link className="mj-btn mj-btn-sec" href={p.planHref}>확정 공정표 보기</Link>}
      </div>
      <p className="mj-sr" role="status">{busy === "accept" ? "수락하는 중이에요" : busy === "request" ? "요청을 보내는 중이에요" : ""}</p>

      {canRequest && open ? (
        <form id="cb-req" aria-labelledby="cb-req-h" noValidate className={s.req} onSubmit={(e) => { e.preventDefault(); void request(); }}>
          <h3 id="cb-req-h" className="mj-h3">{tName} 날짜 바꾸기 요청</h3>
          <p className="mj-small">{p.vendorName}에 보내면 업체가 새 날짜를 올려요. <span className="mj-num">남은 요청 {p.requestsLeft}번</span>이에요.</p>
          {p.options.length ? (
            <fieldset className="mj-fieldset" aria-describedby={`cb-hint${pickErr ? " cb-pick-e" : ""}`}>
              <legend className={`mj-label ${s.legend}`}>시작하고 싶은 날 <span className={s.opt}>(필수 · {WISH_MAX}개까지)</span></legend>
              {p.options.map((o, i) => (
                <label key={o.start} className={s.pick}>
                  <input ref={i === 0 ? firstOpt : undefined} type="checkbox" value={o.start} checked={picked.includes(o.start)} aria-invalid={pickErr ? true : undefined} onChange={(e) => toggle(o.start, e.target.checked)} />
                  <span className={`mj-num ${s.pickT}`}><b>{day(o.start)} 시작</b><span className="mj-small">끝나는 날 {day(o.end)}</span></span>
                </label>
              ))}
              <p id="cb-hint" className="mj-hint">끝나는 날은 믿집 계산이에요 · 지금과 같은 일하는 날 수 · {offText(p.weekendWork)}</p>
              {pickErr ? <FieldError id="cb-pick-e" alert>{pickErr}</FieldError> : null}
            </fieldset>
          ) : (
            <p className="mj-small">지금 고를 수 있는 날이 없어요. {p.vendorName}에 전화해 날짜를 다시 정해 주세요.</p>
          )}
          <div className="mj-field">
            <label htmlFor="cb-why" className="mj-label">이유 <span className={s.opt}>(필수)</span></label>
            <textarea
              ref={whyRef}
              id="cb-why"
              className="mj-textarea"
              rows={3}
              maxLength={REASON_MAX}
              value={reason}
              required
              aria-invalid={whyErr ? true : undefined}
              aria-describedby={`cb-why-h cb-why-n${whyErr ? " cb-why-e" : ""}`}
              onChange={(e) => { setReason(e.target.value); setWhyErr(""); }}
            />
            <p id="cb-why-h" className="mj-hint">{iGa(p.vendorName)} 요청 다음 날 18:00까지 새 날짜를 올려요. 그전까지 지금 날짜가 그대로예요.</p>
            <p id="cb-why-n" className="mj-hint mj-num">{reason.length} / {REASON_MAX}자</p>
            {whyErr ? <FieldError id="cb-why-e" alert>{whyErr}</FieldError> : null}
          </div>
          {p.options.length ? (
            <div>
              <button type="submit" className={`mj-btn mj-btn-sec ${busy === "request" ? s.busy : ""}`} aria-disabled={busy ? true : undefined}>
                {busy === "request" ? <><Spin />보내는 중이에요…</> : "요청 보내기"}
              </button>
            </div>
          ) : null}
          {p.multi ? <p className="mj-small">공정마다 따로 보내요. 목공을 미루면 도배는 목공이 끝난 다음 날부터만 고를 수 있어요.</p> : null}
        </form>
      ) : null}

      {p.finished ? <p className="mj-small">업체가 공사를 끝냈다고 올린 뒤에는 날짜를 바꿀 수 없어요.</p> : null}
      {!p.finished && !p.request && p.requestsLeft <= 0 ? (
        <p className="mj-small">다른 날짜 요청을 다 썼어요. 날짜를 바꾸려면 {p.vendorName}에 전화해 주세요.</p>
      ) : null}

      <dialog ref={dlg} className={d.dlg} aria-labelledby="cb-q" onClose={() => opener.current?.focus()}>
        <button type="button" className={d.x} aria-label="닫기" onClick={() => dlg.current?.close()}><Close /></button>
        <h2 id="cb-q" className="mj-h3 mj-num">{x ? `${tName} 날짜를 ${ro(span(x.start, x.end))} 바꿀까요?` : "새 날짜 수락"}</h2>
        <p>바꾸면 확정 공정표가 바뀌고 {p.vendorName}에 알려요.</p>
        <div className={d.btns}>
          <button type="button" className="mj-btn mj-btn-pri" onClick={() => { dlg.current?.close(); void accept(); }}>네, 바꿀게요</button>
          <button ref={noRef} type="button" className="mj-btn mj-btn-sec" onClick={() => dlg.current?.close()}>아니요</button>
        </div>
      </dialog>
    </div>
  );
}
