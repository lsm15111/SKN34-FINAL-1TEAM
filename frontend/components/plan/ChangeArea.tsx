"use client";
// 수락한 날짜를 바꾸자는 새 날짜 (시안 WPlanDone '확정한 날짜 바꾸기'): 지금 → 새 날짜 · 이유 · 밀린 공정표 미리 보기 · 겹침.
// '새 날짜 수락하기'는 확인 창 뒤 화면이 본 공정표 버전(seen_version)으로 수락하고, '다른 날짜 요청하기'는 공사 날짜 화면으로 보낸다.
// 날짜 · 일하는 날 · 미리 보기는 API 값 그대로다. 수락하면 화면을 새로 읽고, 이 칸은 늘 같은 자리에 있어 안내가 남는다.
import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FieldError } from "@/components/auth/parts";
import { day } from "@/components/confirm/text";
import { span } from "@/components/schedule/text";
import { Check, Close, Warn } from "@/components/vendors/icons";
import { eunNeun, iGa } from "@/components/vendors/text";
import { ApiError, call, errorText } from "@/lib/backend/client";
import { md } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { spanRo, workEnd, type PlanChange } from "./text";
import d from "@/components/vendors/dialog.module.css";
import s from "./plan.module.css";

export type ChangeItem = {
  change: PlanChange;
  /** 밀린 공정표 막대 · 범례 (서버가 그린다) */
  preview: ReactNode;
  /** 다른 날짜 요청 남은 수 · 열린 요청이 있는지 (GET schedule) */
  requestsLeft: number;
  requestOpen: boolean;
  /** 전화 걸기 번호 (숫자만, 연락처가 보일 때) */
  tel: string | null;
};

/** lead: 열린 날짜 바꾸기 요청 줄 (서버가 그린다) */
type Props = { projectId: string; version: number; items: ChangeItem[]; lead?: ReactNode };
type Done = { trade: string; vendorName: string; dates: string };
type Err = { text: string; code?: string; trade: string; retry?: string };

const Spin = () => (
  <svg className={s.spin} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M8 2a6 6 0 1 1-6 6" strokeLinecap="round" /></svg>
);

function FitLine({ c }: { c: PlanChange }) {
  const tName = tradeLabel(c.trade);
  const f = c.fit;
  if (f.conflicts.length) {
    const can = f.start_from && f.end_by
      ? `${eunNeun(tName)} ${day(f.start_from)}부터 ${day(f.end_by)} 사이에 할 수 있어요.`
      : f.start_from ? `${eunNeun(tName)} ${day(f.start_from)}부터 시작할 수 있어요.`
      : f.end_by ? `${eunNeun(tName)} ${day(f.end_by)}까지 끝나야 해요.` : "";
    return (
      <div className={`mj-notice mj-notice-bad mj-num ${s.note}`}>
        <span className={s.noteBad}><Warn /></span>
        <p>
          <b>겹치는 날이 있어 수락할 수 없어요.</b>{" "}
          새 날짜가 {f.conflicts.map((o) => `${tradeLabel(o.trade)} ${span(o.start, o.end)}`).join(" · ")}와 겹쳐요. {can} 다른 날짜를 요청하거나 {c.vendor_name}에 전화해 주세요.
        </p>
      </div>
    );
  }
  return (
    <p className="mj-small mj-num">
      겹치는 날이 없어요. 바꾸면 공사 기간이 {md(c.start)} ~ {md(workEnd(c))} · 일하는 날 {c.work_days}일이 되고, 자연 건조 · 입주 청소도 그 뒤로 옮겨요 · 믿집 계산
    </p>
  );
}

export function ChangeArea({ projectId, version, items, lead }: Props) {
  const router = useRouter();
  const dlg = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const doneRef = useRef<HTMLParagraphElement>(null);
  const noRef = useRef<HTMLButtonElement>(null);
  const [asking, setAsking] = useState<PlanChange | null>(null);
  const [busy, setBusy] = useState("");
  const [done, setDone] = useState<Done | null>(null);
  const [err, setErr] = useState<Err | null>(null);

  useEffect(() => { if (done) doneRef.current?.focus(); }, [done]);

  // 확인 창은 내용이 그려진 뒤 연다(고른 새 날짜로 묻고 '아니요'에 초점)
  useEffect(() => {
    if (!asking) return;
    dlg.current?.showModal();
    noRef.current?.focus();
  }, [asking]);

  function ask(c: PlanChange, btn: HTMLButtonElement) {
    if (busy) return;
    opener.current = btn;
    setErr(null);
    setAsking(c);
  }

  async function accept(c: PlanChange) {
    if (busy) return;
    setBusy(c.deal_id);
    setErr(null);
    try {
      await call("POST", `/projects/${projectId}/deals/${c.deal_id}/dates/${c.proposal.id}/accept`, { seen_version: version });
      setDone({ trade: c.trade, vendorName: c.vendor_name, dates: span(c.proposal.start, c.proposal.end) });
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) setErr({ text: "연결이 끊겨 수락하지 못했어요. 다시 눌러 주세요.", trade: c.trade, retry: c.deal_id });
      else {
        setErr({ text: errorText(e), code: e instanceof ApiError ? e.code : undefined, trade: c.trade });
        router.refresh();
      }
    }
    setBusy("");
  }

  const retryItem = err?.retry ? items.find((i) => i.change.deal_id === err.retry) : undefined;

  // 보일 것이 없어도 같은 자리에 둔다(새로 읽은 뒤에도 수락 안내가 남게)
  const shown = !!done || !!err || !!lead || items.length > 0;
  return (
    <div className={shown ? s.changes : undefined}>
      {lead}
      {done ? (
        <div className={s.doneBox}>
          <p ref={doneRef} tabIndex={-1} role="status" className={`mj-st mj-st-ok mj-num ${s.stBig} ${s.focusT}`}><Check size={16} />{tradeLabel(done.trade)} 날짜를 {spanRo(done.dates)} 바꿨어요</p>
          <p className="mj-small">확정 공정표를 바꾸고 {done.vendorName}에 알렸어요.</p>
        </div>
      ) : null}
      {err ? (
        err.code === "dates_changed" ? (
          <div className={`mj-notice mj-notice-warn ${s.note}`} role="alert">
            <span className={s.noteWarn}><Warn /></span>
            <p><b>날짜가 바뀌었어요.</b> 업체가 {tradeLabel(err.trade)} 날짜를 다시 올렸어요. 새 날짜를 확인해 주세요.</p>
          </div>
        ) : (
          <div className={s.err}>
            <FieldError id="pc-err" alert>{err.text}</FieldError>
            {retryItem ? <button type="button" className="mj-btn mj-btn-sec" onClick={() => void accept(retryItem.change)}>다시 시도</button> : null}
          </div>
        )
      ) : null}

      {items.map(({ change: c, preview, requestsLeft, requestOpen }) => {
        const tName = tradeLabel(c.trade);
        const x = c.proposal;
        const hid = `pc-${c.trade}`;
        const canRequest = requestsLeft > 0 && !requestOpen;
        const conflict = c.fit.conflicts.length > 0;
        return (
          <section key={c.deal_id} className={s.box} aria-labelledby={hid}>
            <h2 id={hid} className={`mj-num ${s.boxH}`}>{x.request_id ? `${iGa(c.vendor_name)} 새 ${tName} 날짜를 올렸어요` : `${iGa(c.vendor_name)} ${tName} 날짜를 바꾸자고 했어요`}</h2>
            <p className="mj-num"><span className="mj-sub">지금</span> {span(c.current_start, c.current_end)} <span aria-hidden="true">→</span><span className="mj-sr">에서</span> <span className="mj-sub">새 날짜</span> <b>{span(x.start, x.end)}</b></p>
            {x.reason ? <p className="mj-small">{iGa(c.vendor_name)} 적은 이유 · {x.reason}</p> : null}
            {preview}
            <FitLine c={c} />
            <div className={s.acts}>
              {conflict ? null : (
                <button
                  type="button"
                  className={`mj-btn mj-btn-pri ${busy === c.deal_id ? s.busy : ""}`}
                  aria-disabled={busy ? true : undefined}
                  aria-haspopup="dialog"
                  onClick={(e) => ask(c, e.currentTarget)}
                >
                  {busy === c.deal_id ? <><Spin />수락하는 중이에요…</> : "새 날짜 수락하기"}
                </button>
              )}
              {canRequest ? <Link className="mj-btn mj-btn-sec" href={`/projects/${projectId}/schedule?trade=${c.trade}`}>다른 날짜 요청하기</Link> : null}
            </div>
            <p className="mj-small">수락하기 전까지는 지금 날짜가 그대로예요.{canRequest || requestOpen ? "" : ` 다른 날짜 요청은 2번까지라 더 요청할 수 없어요. 날짜를 바꿔야 하면 ${c.vendor_name}에 전화해 주세요.`}</p>
          </section>
        );
      })}
      <p className="mj-sr" role="status">{busy ? "수락하는 중이에요" : ""}</p>

      <dialog ref={dlg} className={d.dlg} aria-labelledby="pc-q" onClose={() => { setAsking(null); opener.current?.focus(); }}>
        <button type="button" className={d.x} aria-label="닫기" onClick={() => dlg.current?.close()}><Close /></button>
        {asking ? (
          <>
            <h2 id="pc-q" className="mj-h3 mj-num">{tradeLabel(asking.trade)} 날짜를 {spanRo(span(asking.proposal.start, asking.proposal.end))} 바꿀까요?</h2>
            <p>바꾸면 확정 공정표가 바뀌고 {asking.vendor_name}에 알려요.</p>
            <div className={d.btns}>
              <button type="button" className="mj-btn mj-btn-pri" onClick={() => { const c = asking; dlg.current?.close(); void accept(c); }}>네, 바꿀게요</button>
              <button ref={noRef} type="button" className="mj-btn mj-btn-sec" onClick={() => dlg.current?.close()}>아니요</button>
            </div>
          </>
        ) : <h2 id="pc-q" className="mj-sr">새 날짜 수락</h2>}
      </dialog>
    </div>
  );
}
