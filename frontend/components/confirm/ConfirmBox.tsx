"use client";
// 확정하기 칸 (시안 WConfirm 폼 · '누른 뒤 모습'). 견적서 파일 확인 체크 → '○○으로 확정하기' → 확인 창 → POST confirm.
// 체크는 화면 확인이라 서버에 보내지 않는다. 본 버전(seen_ver)은 비교 응답 값 그대로 보낸다.
// 업체가 그사이 다시 올렸으면(409 quote_changed) 화면을 새로 읽어 새 버전을 보이고 다시 체크하게 한다.
// 확정한 뒤에는 같은 자리에 '확정한 뒤' 모습을 둔다(새로 읽은 뒤에도 이 칸이 그대로 남아 초점을 잃지 않는다).
// 공사 날짜를 수락하기 전이면 '○○ 업체 다시 고르기'(확인 창 → 업체 고르기)를 함께 둔다.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FieldError } from "@/components/auth/parts";
import { Close, Warn } from "@/components/vendors/icons";
import { gwaWa } from "@/components/vendors/text";
import { ApiError, call, errorText } from "@/lib/backend/client";
import { euro } from "@/lib/format";
import { tradeLabel } from "@/lib/labels";
import { DealStatus } from "./DealStatus";
import { Reselect } from "./Reselect";
import { canReselect, day, dealReselectText, type ConfirmOut, type Deal } from "./text";
import d from "@/components/vendors/dialog.module.css";
import s from "./confirm.module.css";

type Props = {
  projectId: string;
  visitId: string;
  trade: string;
  vendorName: string;
  /** 이 화면을 연 때의 본 버전 (비교 응답 seen_ver) */
  seenVer: number;
  /** 확정하면 닫히는 같은 공정의 다른 업체 */
  others: string[];
  /** 유효기간이 지났는지 (API expired) */
  expired: boolean;
  validUntil: string | null;
  /** 이 요청으로 이미 확정했으면 그 확정 (서버가 읽음) */
  deal: Deal | null;
  compareHref: string;
  /** 다른 공정과 그 확정 (다시 고르기 창의 '그대로예요') */
  other: { trade: string; deal: Deal | null } | null;
};

type Err = { text: string; retry?: boolean };

const Spin = () => (
  <svg className={s.spin} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M8 2a6 6 0 1 1-6 6" strokeLinecap="round" /></svg>
);

export function ConfirmBox({ projectId, visitId, trade, vendorName, seenVer, others, expired, validUntil, deal, compareHref, other }: Props) {
  const router = useRouter();
  const dlg = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const chk = useRef<HTMLInputElement>(null);
  const doneRef = useRef<HTMLDivElement>(null);
  const [checked, setChecked] = useState(false);
  const [chkErr, setChkErr] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<Err | null>(null);
  const [done, setDone] = useState<ConfirmOut | null>(null);
  const tName = tradeLabel(trade);
  const names = others.join(" · ");

  useEffect(() => { if (done) doneRef.current?.focus(); }, [done]);

  const shown = done?.deal ?? deal;
  if (shown) {
    const late = done ? done.quote_expired : expired;
    return (
      <div ref={doneRef} tabIndex={-1} className={s.done} role="status" aria-label={`${tName} 업체 확정`}>
        <DealStatus d={shown} titled />
        {late ? (
          <p className={`mj-notice mj-notice-warn ${s.notice}`}><Warn /><span>유효기간이 지난 견적서로 확정했어요. 금액이 그대로인지 {vendorName}에 확인해 주세요.</span></p>
        ) : null}
        <div className={s.btns}>
          <Link className="mj-btn mj-btn-pri" href={`/projects/${projectId}`}>내 공사로 가기</Link>
          {/* 다른 공정을 아직 확정하지 않았으면 그 비교가 다음 할 일 */}
          {other && !other.deal ? <Link className="mj-btn mj-btn-sec" href={`/projects/${projectId}/quotes?trade=${other.trade}`}>{tradeLabel(other.trade)} 견적서 비교하기</Link> : null}
          {canReselect(shown) ? <Reselect projectId={projectId} trade={trade} dealId={shown.id} {...dealReselectText(shown, other)} /> : null}
        </div>
      </div>
    );
  }

  async function go() {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      const out = await call<ConfirmOut>("POST", `/projects/${projectId}/quotes/${visitId}/confirm`, { seen_ver: seenVer });
      setDone(out);
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        setErr({ text: "연결이 끊겨 확정하지 못했어요. 다시 눌러 주세요.", retry: true });
      } else if (e instanceof ApiError && e.code === "quote_changed") {
        // 새 버전을 보고 다시 확인하게 체크를 푼다
        setChecked(false);
        setErr({ text: e.message });
        router.refresh();
      } else {
        setErr({ text: errorText(e) });
        router.refresh();
      }
    }
    setBusy(false);
  }

  function ask() {
    if (busy) return;
    if (!checked) {
      setChkErr(true);
      chk.current?.focus();
      return;
    }
    setErr(null);
    dlg.current?.showModal();
  }

  return (
    <>
      <form aria-labelledby="go-h" noValidate className={s.go} onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <h2 id="go-h" className="mj-sr">확정하기</h2>
        {expired ? (
          <p className={`mj-notice mj-notice-warn ${s.notice}`}>
            <Warn />
            <span><b>유효기간이 지난 견적서예요</b>{validUntil ? <span className="mj-num"> · {day(validUntil)}까지였어요</span> : null}. 확정은 할 수 있어요. 금액이 그대로인지 {vendorName}에 먼저 확인해 주세요.</span>
          </p>
        ) : null}
        <label className={s.chk}>
          <input
            ref={chk}
            type="checkbox"
            required
            checked={checked}
            aria-invalid={chkErr || undefined}
            aria-describedby={chkErr ? "cf-chk-e" : undefined}
            onChange={(e) => { setChecked(e.target.checked); if (e.target.checked) setChkErr(false); }}
          />
          <span><b>견적서 파일 내용을 확인했어요</b> <span className="mj-sub">(필수)</span></span>
        </label>
        {chkErr ? <FieldError id="cf-chk-e">견적서 파일을 열어 내용을 확인해 주세요.</FieldError> : null}
        <p id="cf-deal" className="mj-small">
          {others.length ? `확정하면 ${names}의 실측 요청은 닫히고 서로 보이던 연락처가 가려져요. ` : ""}
          계약과 대금은 {gwaWa(vendorName)} 직접 해요. 믿집은 계약 당사자가 아니에요.
        </p>
        <div className={s.btns}>
          <button
            ref={opener}
            type="submit"
            className={`mj-btn mj-btn-pri ${busy ? s.busy : ""}`}
            aria-disabled={!checked || busy || undefined}
            aria-describedby="c-amt cf-deal"
            aria-haspopup="dialog"
          >
            {busy ? <><Spin />확정하는 중이에요…</> : `${euro(vendorName)} 확정하기`}
          </button>
          <Link className="mj-btn mj-btn-sec" href={compareHref}>더 비교해 볼게요</Link>
        </div>
        <p className="mj-sr" role="status">{busy ? "확정하는 중이에요" : ""}</p>
        {err ? (
          <div className={s.err}>
            <FieldError id="cf-e" alert>{err.text}</FieldError>
            {err.retry ? <button type="button" className={`mj-btn mj-btn-sec ${s.self}`} onClick={go}>다시 시도</button> : null}
          </div>
        ) : null}
      </form>

      <dialog ref={dlg} className={d.dlg} aria-labelledby="cf-q" onClose={() => opener.current?.focus()}>
        <button type="button" className={d.x} aria-label="닫기" onClick={() => dlg.current?.close()}><Close /></button>
        <h2 id="cf-q" className="mj-h3">마지막으로 확인해요</h2>
        <p>확정한 견적서는 바꿀 수 없어요.</p>
        <p className="mj-small">공사 날짜를 수락하기 전까지는 &lsquo;다시 고르기&rsquo;로 업체를 새로 고를 수 있어요. 다만 실측부터 새로 요청해요.</p>
        <div className={d.btns}>
          <button type="button" className="mj-btn mj-btn-pri" onClick={() => { dlg.current?.close(); void go(); }}>확정하기</button>
          <button type="button" className="mj-btn mj-btn-sec" autoFocus onClick={() => dlg.current?.close()}>돌아가기</button>
        </div>
      </dialog>
    </>
  );
}
