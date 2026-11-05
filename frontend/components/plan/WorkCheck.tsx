"use client";
// 공사가 끝났을 때 (시안 WPlanDone '공사가 끝났을 때'). 확정 공정표 · 공사 날짜 화면이 같이 쓴다.
// 업체가 '공사 끝냈어요' · '남은 일 다 했어요'를 올리면(checking) '확인했어요'(확인 창) · '아직 남은 일이 있어요'(남은 일 필수 300자)로
// POST /projects/{id}/deals/{deal}/check에 답한다. 남은 일(fixing)이면 업체를 기다리고, 끝남(done)이면 연락처 기한을 보인다.
// 끝낸 날 · 연락처 기한은 API 값 그대로다(화면에서 1년을 세지 않는다). 이미 답했으면(409) 서버 문장을 보이고 새로 읽는다.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FieldError } from "@/components/auth/parts";
import { Clock } from "@/components/confirm/DealStatus";
import { day } from "@/components/confirm/text";
import { isFinished, untilDay } from "@/components/schedule/text";
import { Check, Close } from "@/components/vendors/icons";
import { iGa } from "@/components/vendors/text";
import { ApiError, call, errorText, type Schemas } from "@/lib/backend/client";
import { tradeLabel } from "@/lib/labels";
import d from "@/components/vendors/dialog.module.css";
import s from "./plan.module.css";

type Deal = Schemas["DealOut"];
type Result = Schemas["CheckIn"]["result"];

const NOTE_MAX = 300;
const ORDER = ["checking", "fixing", "done"];
/** 끝난 뒤 문제가 생기면 (공정마다) */
const AFTER: Record<string, string> = { dobae: "벽지가 들뜨거나 이음매가 벌어지면", mokgong: "몰딩 · 걸레받이가 들뜨거나 틈이 생기면" };

type Props = {
  projectId: string;
  deals: Deal[];
  /** 확정 id → 전화 걸기 번호 (숫자만, 연락처가 보일 때) */
  tels: Record<string, string | null>;
};

export function WorkCheck({ projectId, deals }: Props) {
  const router = useRouter();
  const dlg = useRef<HTMLDialogElement>(null);
  const noRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const msgRef = useRef<HTMLParagraphElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const [seen, setSeen] = useState(deals);
  const [local, setLocal] = useState<Record<string, Deal>>({}); // 답한 뒤 응답 값 (화면을 새로 읽을 때까지)
  const [asking, setAsking] = useState<Deal | null>(null);
  const [open, setOpen] = useState<string | null>(null); // 남은 일 적기를 펼친 확정 id
  const [note, setNote] = useState("");
  const [noteErr, setNoteErr] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<{ deal: string; text: string; warn: boolean } | null>(null);

  // 화면을 새로 그리면(router.refresh) 새 값으로 바꾼다
  if (seen !== deals) {
    setSeen(deals);
    setLocal({});
  }

  useEffect(() => { if (msg) msgRef.current?.focus(); }, [msg]);

  // 확인 창은 내용이 그려진 뒤 연다('아니요'에 초점)
  useEffect(() => {
    if (!asking) return;
    dlg.current?.showModal();
    noRef.current?.focus();
  }, [asking]);

  const shown = deals.map((x) => local[x.id] ?? x).filter((x) => isFinished(x.status)).sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  if (!shown.length && !msg) return null;
  const done = shown.filter((x) => x.status === "done");

  function toggle(x: Deal) {
    setNoteErr("");
    setErr(null);
    if (open === x.id) return setOpen(null);
    setOpen(x.id);
    setNote("");
    setTimeout(() => noteRef.current?.focus(), 0);
  }

  async function check(x: Deal, result: Result) {
    if (busy) return;
    const text = note.trim();
    if (result === "fixing" && !text) {
      setNoteErr("남은 일을 적어 주세요.");
      noteRef.current?.focus();
      return;
    }
    setBusy(`${x.id}|${result}`);
    setErr(null);
    setMsg(null);
    const tName = tradeLabel(x.trade);
    try {
      const out = await call<Deal>("POST", `/projects/${projectId}/deals/${x.id}/check`, result === "done" ? { result } : { result, note: text });
      setLocal((m) => ({ ...m, [x.id]: out }));
      setOpen(null);
      setNote("");
      setMsg(result === "done"
        ? `${tName} 공사가 끝났어요.${out.contact_until ? ` ${x.vendor_name} 연락처는 ${untilDay(out.contact_until)}까지 보여요.` : ""}`
        : `남은 일을 ${x.vendor_name}에 알렸어요. ${iGa(x.vendor_name)} 다 하고 다시 올리면 알려 드려요.`);
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setNoteErr(e.code === "note" ? e.message : `남은 일은 ${NOTE_MAX}자까지 적어 주세요.`);
        noteRef.current?.focus();
      } else {
        // 이미 답함 · 업체가 상태를 바꿈(409) · 다시 고른 공사(404): 서버 문장을 보이고 새로 읽는다
        setErr({ deal: x.id, text: errorText(e), warn: e instanceof ApiError && e.status === 409 });
        if (!(e instanceof ApiError) || e.status !== 0) router.refresh();
      }
    }
    setBusy("");
  }

  return (
    <section aria-labelledby="wc-t" className={s.work}>
      <h2 id="wc-t" className="mj-sr">공사 끝남 확인</h2>
      {msg ? <p ref={msgRef} tabIndex={-1} role="status" className={`mj-st mj-st-ok mj-num ${s.stBig} ${s.focusT}`}><Check size={16} />{msg}</p> : null}

      {shown.filter((x) => x.status !== "done").map((x) => {
        const tName = tradeLabel(x.trade);
        const v = x.vendor_name;
        const e = err?.deal === x.id ? err : null;
        const errLine = e ? (e.warn ? <p role="alert" className="mj-notice mj-notice-warn"><span><b>{e.text}</b> 다시 읽은 상태를 확인해 주세요.</span></p> : <FieldError id={`wc-e-${x.id}`} alert>{e.text}</FieldError>) : null;
        if (x.status === "fixing") {
          return (
            <div key={x.id} className={s.reqLines}>
              <p className={`mj-st mj-st-wait ${s.stBig}`}><Clock />{tName} 남은 일 기다림</p>
              {x.fixing_note ? <p className={s.exText}>&ldquo;{x.fixing_note}&rdquo;</p> : null}
              <p className="mj-small">{v}에 알렸어요. {iGa(v)} 남은 일을 마치고 &lsquo;남은 일 다 했어요&rsquo;를 올리면 다시 확인해요.</p>
              {errLine}
            </div>
          );
        }
        const hid = `wc-${x.id}`;
        const formId = `wc-f-${x.id}`;
        const mid = `wc-m-${x.id}`;
        return (
          <div key={x.id} className={s.box} role="group" aria-labelledby={hid}>
            <p id={hid} className={`mj-num ${s.boxH}`}>{iGa(v)} {tName} 공사를 끝냈다고 알렸어요{x.work_done_on ? <span className={s.exWhen}> · {day(x.work_done_on)}</span> : null}</p>
            <p className="mj-small">집을 둘러보고 알려 주세요.</p>
            {errLine}
            <div className={s.acts}>
              <button type="button" className={`mj-btn mj-btn-pri ${busy === `${x.id}|done` ? s.busy : ""}`} aria-disabled={busy ? true : undefined} aria-haspopup="dialog"
                aria-label={`${tName} 공사 끝났어요, 확인했어요`} onClick={(ev) => { if (busy) return; opener.current = ev.currentTarget; setErr(null); setAsking(x); }}>
                {busy === `${x.id}|done` ? "보내는 중이에요…" : "확인했어요"}
              </button>
              <button type="button" className="mj-btn mj-btn-sec" aria-expanded={open === x.id} aria-controls={formId} onClick={() => toggle(x)}>
                아직 남은 일이 있어요
              </button>
            </div>
            {open === x.id ? (
              <form id={formId} aria-label={`${v}에 남은 일 알리기`} noValidate className={s.fixForm} onSubmit={(ev) => { ev.preventDefault(); void check(x, "fixing"); }}>
                <div className="mj-field">
                  <label htmlFor={mid} className="mj-label">업체에 남은 일을 알려요 <span className="mj-opt">(필수)</span></label>
                  <textarea ref={noteRef} id={mid} className="mj-textarea" rows={3} maxLength={NOTE_MAX} value={note} required
                    aria-invalid={noteErr ? true : undefined} aria-describedby={`${mid}-h ${mid}-n${noteErr ? ` ${mid}-e` : ""}`}
                    onChange={(ev) => { setNote(ev.target.value); setNoteErr(""); }} />
                  <p id={`${mid}-h`} className="mj-hint">{v}에 알림이 가요. {iGa(v)} 남은 일을 마치고 &lsquo;남은 일 다 했어요&rsquo;를 다시 올려요.</p>
                  <p id={`${mid}-n`} className="mj-hint mj-num">{note.length} / {NOTE_MAX}자</p>
                  {noteErr ? <FieldError id={`${mid}-e`} alert>{noteErr}</FieldError> : null}
                </div>
                <div>
                  <button type="submit" className={`mj-btn mj-btn-sec ${busy === `${x.id}|fixing` ? s.busy : ""}`} aria-disabled={busy ? true : undefined}>
                    {busy === `${x.id}|fixing` ? "보내는 중이에요…" : "보내기"}
                  </button>
                </div>
              </form>
            ) : null}
          </div>
        );
      })}

      {done.length ? (
        <div className={s.doneBox}>
          <ul className={`mj-num ${s.doneList}`}>
            {done.map((x) => {
              const v = x.vendor_name;
              return (
                <li key={x.id}>
                  <p className={`mj-st mj-st-ok ${s.stBig}`}><Check size={16} />{tradeLabel(x.trade)} 공사 끝남{x.work_done_on ? ` · ${day(x.work_done_on)} 끝남` : ""}</p>
                  <div className={s.doneRow}>
                    <p className="mj-small">{AFTER[x.trade] ?? "문제가 생기면"} {v}에 전화해요.</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      <p className="mj-sr" role="status">{busy ? "보내는 중이에요" : ""}</p>

      <dialog ref={dlg} className={d.dlg} aria-labelledby="wc-q" onClose={() => { setAsking(null); opener.current?.focus(); }}>
        <button type="button" className={d.x} aria-label="닫기" onClick={() => dlg.current?.close()}><Close /></button>
        {asking ? (
          <>
            <h2 id="wc-q" className="mj-h3">{tradeLabel(asking.trade)} 공사가 끝났다고 확인할까요?</h2>
            <p className="mj-num">
              확인하면 {tradeLabel(asking.trade)} 공사가 끝나요.{asking.contact_until ? ` ${asking.vendor_name} 연락처는 ${untilDay(asking.contact_until)}까지 보여요.` : ""} 확인한 뒤에는 되돌릴 수 없어요.
            </p>
            <p className="mj-small">남은 일이 있으면 &lsquo;아직 남은 일이 있어요&rsquo;로 알려 주세요.</p>
            <div className={d.btns}>
              <button type="button" className="mj-btn mj-btn-pri" onClick={() => { const a = asking; dlg.current?.close(); void check(a, "done"); }}>네, 끝났어요</button>
              <button ref={noRef} type="button" className="mj-btn mj-btn-sec" onClick={() => dlg.current?.close()}>아니요</button>
            </div>
          </>
        ) : <h2 id="wc-q" className="mj-sr">공사 끝남 확인</h2>}
      </dialog>
    </section>
  );
}
