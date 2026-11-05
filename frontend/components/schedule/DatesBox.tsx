"use client";
// 공사 날짜 칸 아래 버튼 자리 (시안 WSchedule): 수락하기(확인 창) · 다른 날짜 요청하기(후보 1~3개 + 이유) · 업체 다시 고르기(수락 전).
// 수락한 뒤에는 날짜 바꾸기(ChangeBox)를 같은 자리에 둔다.
// 날짜 · 끝나는 날 · 남은 요청 수는 API 값 그대로 보이고 보낸다. 수락은 화면이 본 날짜(proposal id)로만 한다.
// 그사이 업체가 다시 냈으면(409 dates_changed) 화면을 새로 읽어 새 날짜를 보인다. 확정 하나에 이 칸 하나라(key) 새로 읽어도 안내가 남는다.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FieldError } from "@/components/auth/parts";
import { Reselect } from "@/components/confirm/Reselect";
import { day } from "@/components/confirm/text";
import { Check, Close, Warn } from "@/components/vendors/icons";
import { iGa } from "@/components/vendors/text";
import { ApiError, call, errorText } from "@/lib/backend/client";
import { eulReul } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { ChangeBox } from "./ChangeBox";
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
  /** 수락했거나 그 뒤 공사 상태 */
  accepted: boolean;
  /** 업체가 공사를 끝냈다고 올린 뒤(내 확인 기다림 · 남은 일 · 끝남): 날짜 바꾸기 요청을 막는다 */
  finished?: boolean;
  /** 수락 기다리는 날짜 (없으면 아직 안 냄) */
  proposal: Proposal | null;
  /** 열린 다른 날짜 요청이 있음 */
  requested: boolean;
  /** 열린 요청 (수락한 뒤 날짜 바꾸기에 쓴다) */
  request: DateReq | null;
  /** 이 집 공정이 둘 이상 */
  multi: boolean;
  requestsLeft: number;
  /** 다른 공정과 겹쳐 수락할 수 없음 (API fit.conflicts) */
  conflict: boolean;
  options: StartOption[];
  weekendWork: boolean;
  /** 기한 지남: 날짜를 아직 안 냈음 */
  overdue: boolean;
  /** 전화 걸기 번호 (숫자만, 연락처가 보일 때) */
  tel: string | null;
  /** 화면이 본 확정 공정표 버전 (API final_version, 수락할 때 그대로 보낸다. 바뀌었으면 409 plan_changed → 새로 읽는다) */
  seenVersion: number;
  /** 업체 다시 고르기 확인 창 (수락 전만) */
  reselect: { title: string; body: string; note?: string } | null;
  /** 확정 공정표 */
  finalHref: string;
  /** 수락한 뒤 다음 할 일 (다른 공정 날짜 확인 · 확정 공정표). 없으면 보조 버튼만 */
  next?: { href: string; label: string } | null;
};

type Err = { text: string; code?: string; from?: string; retry?: "accept" | "request" };

const Spin = () => (
  <svg className={s.spin} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M8 2a6 6 0 1 1-6 6" strokeLinecap="round" /></svg>
);

export function DatesBox(p: Props) {
  const router = useRouter();
  const dlg = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const doneRef = useRef<HTMLParagraphElement>(null);
  const sentRef = useRef<HTMLParagraphElement>(null);
  const firstOpt = useRef<HTMLInputElement>(null);
  const tName = tradeLabel(p.trade);
  const x = p.proposal;
  const canRequest = !!x && !p.requested && p.requestsLeft > 0 && !p.accepted;

  const [busy, setBusy] = useState<"" | "accept" | "request">("");
  const [err, setErr] = useState<Err | null>(null);
  const [done, setDone] = useState(false);
  const [sent, setSent] = useState(false);
  // 겹치면 요청 칸을 처음부터 펼치고 겹치지 않는 첫날을 골라 둔다
  const [open, setOpen] = useState(p.conflict);
  const [picked, setPicked] = useState<string[]>(() => (p.conflict && p.options[0] ? [p.options[0].start] : []));
  const [reason, setReason] = useState("");
  const [pickErr, setPickErr] = useState("");
  const acceptId = useRef<string | null>(null);

  useEffect(() => { if (done) doneRef.current?.focus(); }, [done]);
  useEffect(() => { if (sent) sentRef.current?.focus(); }, [sent]);

  function refreshOn(e: unknown, retry: Err["retry"], netText: string, from?: string) {
    if (e instanceof ApiError && e.status === 0) {
      setErr({ text: netText, retry });
      return;
    }
    setErr({ text: errorText(e), code: e instanceof ApiError ? e.code : undefined, from });
    router.refresh();
  }

  async function accept() {
    const id = acceptId.current;
    if (busy || !id) return;
    setBusy("accept");
    setErr(null);
    try {
      await call<Schedule>("POST", `/projects/${p.projectId}/deals/${p.dealId}/dates/${id}/accept`, { seen_version: p.seenVersion });
      setDone(true);
      router.refresh();
    } catch (e) {
      refreshOn(e, "accept", "연결이 끊겨 수락하지 못했어요. 다시 눌러 주세요.", id);
    }
    setBusy("");
  }

  function ask() {
    if (busy || !x) return;
    acceptId.current = x.id;
    setErr(null);
    dlg.current?.showModal();
  }

  async function request() {
    if (busy) return;
    // 후보 순서(이른 날 먼저)대로 보낸다. 새로 읽어 후보가 바뀌었으면 남은 것만
    const wish = p.options.map((o) => o.start).filter((v) => picked.includes(v));
    if (!wish.length) {
      setPickErr("시작해도 되는 날을 하나 이상 골라 주세요.");
      firstOpt.current?.focus();
      return;
    }
    setBusy("request");
    setErr(null);
    try {
      const why = reason.trim();
      await call<Schedule>("POST", `/projects/${p.projectId}/deals/${p.dealId}/date-requests`, { wish_dates: wish, reason: why || null });
      setSent(true);
      setOpen(false);
      setPicked([]);
      setReason("");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) setPickErr(e.message);
      else refreshOn(e, "request", "연결이 끊겨 요청을 보내지 못했어요. 다시 눌러 주세요.");
    }
    setBusy("");
  }

  function toggle(v: string, on: boolean) {
    setPickErr("");
    if (!on) return setPicked((a) => a.filter((t) => t !== v));
    if (picked.length >= WISH_MAX) return setPickErr(`${WISH_MAX}개까지 고를 수 있어요. 하나를 빼고 골라 주세요.`);
    setPicked((a) => [...a, v]);
  }

  // 수락한 뒤: 날짜 바꾸기 (새로 읽기 전에는 확정 공정표 링크만)
  if (p.accepted || done) {
    return (
      <div className={s.box}>
        {/* 수락했다는 말은 화면 제목이 한다. 이 줄은 화면 읽기 프로그램에만 알린다 */}
        {done ? <p ref={doneRef} tabIndex={-1} role="status" className="mj-sr">수락했어요. 확정 공정표에 넣었어요.</p> : null}
        {p.accepted ? (
          <ChangeBox
            projectId={p.projectId}
            dealId={p.dealId}
            trade={p.trade}
            vendorName={p.vendorName}
            proposal={x}
            request={p.request}
            requestsLeft={p.requestsLeft}
            finished={!!p.finished}
            conflict={p.conflict}
            options={p.options}
            weekendWork={p.weekendWork}
            multi={p.multi}
            tel={p.tel}
            seenVersion={p.seenVersion}
            planHref={p.finalHref}
            next={p.next}
          />
        ) : (
          <div className={s.btns}><Link className={`mj-btn ${p.next ? "mj-btn-pri" : "mj-btn-sec"}`} href={p.next?.href ?? p.finalHref}>{p.next?.label ?? "확정 공정표 보기"}</Link></div>
        )}
      </div>
    );
  }

  const changedNote = err?.code === "dates_changed" ? (
    <div className={`mj-notice mj-notice-warn mj-num ${s.note}`} role="alert">
      <span className={s.noteWarn}><Warn /></span>
      <p><b>날짜가 바뀌었어요.</b> {x && x.id !== err.from ? `${iGa(p.vendorName)} ${span(x.start, x.end)}로 다시 냈어요. ` : ""}새 날짜를 확인해 주세요.</p>
    </div>
  ) : null;

  const errLine = err && err.code !== "dates_changed" ? (
    <div className={s.err}>
      <FieldError id="sd-e" alert>{err.text}</FieldError>
      {err.retry ? <button type="button" className={`mj-btn mj-btn-sec ${s.self}`} onClick={() => void (err.retry === "accept" ? accept() : request())}>다시 시도</button> : null}
    </div>
  ) : null;

  // 아직 날짜를 안 냄
  if (!x) {
    return (
      <div className={s.box}>
        {errLine}
        <div className={s.btns}>
          {p.reselect ? <Reselect projectId={p.projectId} trade={p.trade} dealId={p.dealId} {...p.reselect} /> : null}
        </div>
        {p.reselect ? <p className="mj-small">업체를 다시 고르면 실측부터 다시 해요. 공사 날짜를 수락하기 전까지만 다시 고를 수 있어요.</p> : null}
      </div>
    );
  }

  const callMade = x.method === "call";
  return (
    <div className={s.box}>
      {changedNote}
      {sent ? <p ref={sentRef} tabIndex={-1} role="status" className={`mj-st mj-st-ok ${s.stLine} ${s.stBig} ${s.focusT}`}><Check size={16} />다른 날짜를 요청했어요. {iGa(p.vendorName)} 새 날짜를 내면 알려 드려요.</p> : null}
      <div className={s.btns}>
        {p.conflict ? null : (
          <button ref={opener} type="button" className={`mj-btn mj-btn-pri ${busy === "accept" ? s.busy : ""}`} aria-disabled={busy ? true : undefined} aria-haspopup="dialog" aria-describedby="sd-acc" onClick={ask}>
            {busy === "accept" ? <><Spin />수락하는 중이에요…</> : callMade ? "통화로 정한 날짜로 수락하기" : "이 날짜로 수락하기"}
          </button>
        )}
        {canRequest && !p.conflict ? (
          <button type="button" className="mj-btn mj-btn-sec" aria-expanded={open} aria-controls="sd-req" onClick={() => { setOpen((o) => !o); setPickErr(""); }}>
            다른 날짜 요청하기
            <svg className={open ? s.up : undefined} width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3.5 5.5L7 9l3.5-3.5" /></svg>
          </button>
        ) : null}
      </div>
      <p className="mj-sr" role="status">{busy === "accept" ? "수락하는 중이에요" : busy === "request" ? "요청을 보내는 중이에요" : ""}</p>
      {errLine}

      {canRequest && open ? (
        <form id="sd-req" aria-labelledby="sd-req-h" noValidate className={s.req} onSubmit={(e) => { e.preventDefault(); void request(); }}>
          <h3 id="sd-req-h" className="mj-h3">다른 날짜 요청</h3>
          <p className="mj-small">{p.vendorName}에 보내면 업체가 새 날짜를 다시 내요. 그동안 지금 날짜는 그대로 남아 있어요. <span className="mj-num">남은 요청 {p.requestsLeft}번</span>이에요.</p>
          {p.options.length ? (
            <fieldset className="mj-fieldset" aria-describedby={`sd-hint${pickErr ? " sd-pick-e" : ""}`}>
              <legend className={`mj-label ${s.legend}`}>{eulReul(tName)} 시작해도 되는 날 <span className={s.opt}>(필수 · {WISH_MAX}개까지)</span></legend>
              {p.options.map((o, i) => (
                <label key={o.start} className={s.pick}>
                  <input
                    ref={i === 0 ? firstOpt : undefined}
                    type="checkbox"
                    value={o.start}
                    checked={picked.includes(o.start)}
                    aria-invalid={pickErr ? true : undefined}
                    onChange={(e) => toggle(o.start, e.target.checked)}
                  />
                  <span className={`mj-num ${s.pickT}`}><b>{day(o.start)} 시작</b><span className="mj-small">끝나는 날 {day(o.end)}</span></span>
                </label>
              ))}
              <p id="sd-hint" className="mj-hint mj-num">끝나는 날은 믿집 계산이에요 · 일하는 날 {x.workdays}일 · {offText(p.weekendWork)}</p>
              {pickErr ? <FieldError id="sd-pick-e" alert>{pickErr}</FieldError> : null}
            </fieldset>
          ) : (
            <p className="mj-small">지금 고를 수 있는 날이 없어요. {p.vendorName}에 전화해 날짜를 다시 정해 주세요.</p>
          )}
          <div className="mj-field">
            <label htmlFor="sd-why" className="mj-label">이유 <span className={s.opt}>(선택)</span></label>
            <textarea id="sd-why" className="mj-textarea" rows={3} maxLength={REASON_MAX} value={reason} aria-describedby="sd-why-n" onChange={(e) => setReason(e.target.value)} />
            <p id="sd-why-n" className="mj-hint mj-num">{reason.length} / {REASON_MAX}자</p>
          </div>
          {p.options.length ? (
            <div>
              <button type="submit" className={`mj-btn ${p.conflict ? "mj-btn-pri" : "mj-btn-sec"} ${busy === "request" ? s.busy : ""}`} aria-disabled={busy ? true : undefined}>
                {busy === "request" ? <><Spin />보내는 중이에요…</> : "요청 보내기"}
              </button>
            </div>
          ) : null}
        </form>
      ) : null}

      {!canRequest && !p.requested ? (
        <p className="mj-small">다른 날짜 요청을 다 썼어요. 날짜를 바꾸려면 {p.vendorName}에 전화해 주세요.</p>
      ) : null}
      {p.conflict ? null : <p id="sd-acc" className="mj-hint">수락하면 공사 날짜가 확정되고 {p.vendorName}에 알려요.</p>}
      {p.reselect ? <div className={s.btns}><Reselect projectId={p.projectId} trade={p.trade} dealId={p.dealId} {...p.reselect} /></div> : null}

      <dialog ref={dlg} className={d.dlg} aria-labelledby="sd-q" onClose={() => opener.current?.focus()}>
        <button type="button" className={d.x} aria-label="닫기" onClick={() => dlg.current?.close()}><Close /></button>
        <h2 id="sd-q" className="mj-h3 mj-num">{tName} 공사를 {span(x.start, x.end)}에 할까요?</h2>
        <p>수락하면 업체를 다시 고를 수 없어요.</p>
        <div className={d.btns}>
          <button type="button" className="mj-btn mj-btn-pri" onClick={() => { dlg.current?.close(); void accept(); }}>네, 수락할게요</button>
          <button type="button" className="mj-btn mj-btn-sec" autoFocus onClick={() => dlg.current?.close()}>아니요</button>
        </div>
      </dialog>
    </div>
  );
}
