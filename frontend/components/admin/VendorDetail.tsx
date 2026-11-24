"use client";
// 업체 심사 오른쪽 자세히(A01 a_review) + 거절 · 이유(A04 a_reject, D26 A) + 보완 요청 창.
// 등록증 · 신청 칸을 눈으로 견주는 체크 3개, 업체가 넣은 외부 리뷰 링크 확인(POST /admin/vendors/{id}/links/{sort}), 처리 메모,
// 거절 · 보완 요청 · 승인(POST /admin/vendors/{id}/review, 멱등 키). 등록증은 새 창에서 열고, 열 때마다 서버가 열람 기록을 남겨요(B7).
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Check } from "@/components/ui/Check";
import { Dialog } from "@/components/ui/Dialog";
import { Field, TextArea } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { OptionRow } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import type { VendorApplicationDetail } from "@/lib/api/admin";
import { errorText } from "@/lib/backend/client";
import { listStamp } from "@/lib/format";
import { bizNoText, NEEDS_INFO_REASONS, REVIEW_ACTION_LABEL, reasonLabel, tradeLabel } from "@/lib/labels";
import { isImage } from "@/components/auth/VendorSignupForm.license";
import { enc, newKey, send } from "@/components/pro/send";
import { REJECT_V3, rejectLabel } from "@/components/pro/text";
import { FileRow } from "@/components/ui/FileRow";
import { Eyebrow, Row, Rows, Small } from "@/components/pro/ui/parts";
import { areasText, vendorBadge } from "./text";
import s from "./admin.module.css";

const MATCH: Record<string, string> = { biz_name: "상호", biz_no: "등록번호", owner_name: "대표자" };

export function VendorDetail({ v }: { v: VendorApplicationDetail }) {
  const router = useRouter();
  const toast = useToast();
  const [checks, setChecks] = useState({ name: false, no: false, owner: false });
  const [links, setLinks] = useState(v.review_links);
  const [note, setNote] = useState("");
  const [dlg, setDlg] = useState<"reject" | "needs" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [idem] = useState(newKey);
  const open = v.status === "pending";
  const badge = vendorBadge(v.status);
  const lic = v.license;
  const lastWhy = v.review_code ? (v.status === "rejected" ? rejectLabel(v.review_code) : reasonLabel("needs_info", v.review_code)) : null;

  async function toggleLink(sort: number, on: boolean) {
    setBusy(`link-${sort}`);
    try {
      await send("POST", `/admin/vendors/${enc(v.user_id)}/links/${sort}`, { status: on ? "shown" : "hidden" });
      setLinks((xs) => xs.map((l) => (l.sort === sort ? { ...l, status: on ? "shown" : "hidden" } : l)));
      toast.show(on ? "링크를 확인했어요. 고객 화면에 보여요." : "링크를 숨겼어요.");
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  async function decide(action: "approve" | "needs_info" | "reject", code?: string | null, memo?: string) {
    setBusy(action);
    setErr(null);
    try {
      // 승인에는 사유 · 보낼 말을 넣지 않아요(서버 ReviewIn: 넣으면 422). 처리 메모는 거절 · 보완 창으로만 가요
      const body = action === "approve" ? { action, code: null, note: null } : { action, code: code ?? null, note: (memo ?? note).trim() || null };
      await send("POST", `/admin/vendors/${enc(v.user_id)}/review`, body, { idem: `${idem}-${action}` });
      toast.show(action === "approve" ? `${v.biz_name ?? "업체"} 가입을 승인했어요. 업체에게 알림이 가요.` : action === "reject" ? "거절했어요. 업체 화면에 이유가 보여요." : "보완을 요청했어요. 업체에게 알림이 가요.");
      setDlg(null);
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <aside className={s.aside} aria-label="고른 신청 자세히">
      <div className={s.ah}><h2 className={s.at}>{v.biz_name ?? v.name}</h2><Badge tone={badge.tone}>{badge.label}</Badge></div>
      <Rows label="신청 내용">
        <Row label="대표자" value={v.owner_name ?? "—"} />
        <Row label="사업자등록번호" value={bizNoText(v.biz_no) || "—"} />
        {/* CF-11: '공정' 대신 '공사' */}
        <Row label="공사 · 지역" value={`${v.trades.map(tradeLabel).join(" · ")} · ${areasText(v.areas, 1)}`} />
        {v.suspended_at ? <Row label="업체 기능" value={v.suspend_scope === "all" ? "멈춤 · 진행 중인 건도" : "멈춤 · 새 요청만"} /> : null}
      </Rows>
      {lic ? <FileRow name={lic.filename} size={lic.size} note={isImage(lic.content_type, lic.filename) ? "위치 정보 지움" : undefined} href={`/api/files/${enc(v.license_file_id)}`} openLabel="크게" /> : <Small>사업자등록증 파일이 없어요.</Small>}
      {open ? (
        <div className={s.checks} role="group" aria-label="등록증과 신청 칸 견주기">
          <Check label="상호가 같아요" checked={checks.name} onChange={(x) => setChecks((c) => ({ ...c, name: x }))} />
          <Check label="등록번호가 같아요" checked={checks.no} onChange={(x) => setChecks((c) => ({ ...c, no: x }))} />
          <Check label="대표자가 같아요" checked={checks.owner} onChange={(x) => setChecks((c) => ({ ...c, owner: x }))} />
        </div>
      ) : null}
      {v.same_name.length ? (
        <div className={s.warnBox}>
          <b>같은 칸으로 낸 다른 신청이 있어요</b>
          <ul>{v.same_name.map((x) => <li key={x.user_id}>{x.biz_name ?? "이름 없음"} · {vendorBadge(x.status).label} · {x.match.map((m) => MATCH[m] ?? m).join(" · ")} 같음</li>)}</ul>
        </div>
      ) : null}
      <Eyebrow>업체가 넣은 외부 리뷰 링크 {links.length}</Eyebrow>
      {links.length ? (
        <ul className={s.linkList}>
          {links.map((l) => (
            <li key={l.sort}>
              <span className={s.ll}>
                <b>{l.label ?? "링크"}</b>
                <a href={l.url} target="_blank" rel="noopener noreferrer">열어 보고 확인해요<Icon name="external" size={14} /><span className="mj-sr"> ({l.label ?? "링크"}, 새 창)</span></a>
              </span>
              <Check className={s.linkCheck} label={<span className="mj-sr">{l.label ?? "링크"} 확인</span>} checked={l.status === "shown"} disabled={busy === `link-${l.sort}`} onChange={(x) => toggleLink(l.sort, x)} />
            </li>
          ))}
        </ul>
      ) : <Small>넣은 링크가 없어요.</Small>}
      {open ? (
        <>
          <Field label="처리 메모" optional maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className={s.acts}>
            <Button variant="secondary" size="sm" onClick={() => setDlg("reject")} disabled={!!busy}>거절</Button>
            <Button variant="secondary" size="sm" onClick={() => setDlg("needs")} disabled={!!busy}>보완 요청</Button>
            <Button size="sm" onClick={() => decide("approve")} busy={busy === "approve"}>{busy === "approve" ? "보내는 중" : "승인"}</Button>
          </div>
        </>
      ) : (
        <Small>{v.status === "needs_info" ? `보완을 요청했어요${lastWhy ? ` · ${lastWhy}` : ""}. 업체가 다시 보내면 심사 기다림으로 와요.` : v.status === "rejected" ? `거절했어요${lastWhy ? ` · ${lastWhy}` : ""}.` : "승인한 업체예요."}</Small>
      )}
      {err ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
      {v.reviews.length ? (
        <>
          <Eyebrow>처리 기록</Eyebrow>
          <Rows label="처리 기록">{v.reviews.map((r) => <Row key={r.id} label={REVIEW_ACTION_LABEL[r.action] ?? "기록"} sub={r.note ?? undefined} value={listStamp(r.at)} />)}</Rows>
        </>
      ) : null}

      <ReasonDialog
        open={dlg === "reject"}
        onClose={() => setDlg(null)}
        title={`${v.biz_name ?? "이 업체"} 가입을 거절할까요?`}
        sub="이유를 하나 골라요 · 업체 화면에 그대로 보여요"
        reasons={REJECT_V3.map((r) => ({ key: r.key, label: r.label }))}
        memoLabel="메모"
        foot="거절된 업체는 이유를 보고 고쳐서 다시 신청할 수 있어요. 보완으로 될 일이면 '보완 요청'을 써요."
        confirm="거절"
        danger
        busy={busy === "reject"}
        initialMemo={note}
        onConfirm={(code, memo) => decide("reject", code, memo)}
      />
      <ReasonDialog
        open={dlg === "needs"}
        onClose={() => setDlg(null)}
        title={`${v.biz_name ?? "이 업체"}에 보완을 요청할까요?`}
        sub="이유를 하나 골라요 · 업체 화면에 그대로 보여요"
        reasons={NEEDS_INFO_REASONS}
        memoLabel="업체에 남길 말"
        foot="업체는 이유에 맞는 칸만 고쳐서 다시 보내요."
        confirm="보완 요청"
        busy={busy === "needs_info"}
        initialMemo={note}
        onConfirm={(code, memo) => decide("needs_info", code, memo)}
      />
    </aside>
  );
}

/** 이유 고르기 창(A04 · 보완 요청): 이유 하나 + 메모. '그 밖'이면 메모가 꼭 있어야 해요 */
function ReasonDialog({ open, onClose, title, sub, reasons, memoLabel, foot, confirm, danger, busy, initialMemo, onConfirm }: {
  open: boolean; onClose: () => void; title: string; sub: string; reasons: { key: string; label: string }[]; memoLabel: string; foot: string;
  confirm: string; danger?: boolean; busy: boolean; initialMemo: string; onConfirm: (code: string, memo: string) => void;
}) {
  const [code, setCode] = useState<string | null>(null);
  const [memo, setMemo] = useState(initialMemo);
  const [err, setErr] = useState<string | null>(null);
  // 창은 닫혀 있어도 늘 그려져요: 열릴 때마다 옆 '처리 메모'를 다시 받아요(처음 그릴 때 빈 값에 고정되지 않게)
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) { setMemo(initialMemo); setErr(null); }
  }
  function go() {
    if (!code) { setErr("이유를 하나 골라 주세요."); return; }
    if (code === "other" && !memo.trim()) { setErr("그 밖이면 메모로 이유를 적어 주세요."); return; }
    onConfirm(code, memo);
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      dismissible={!busy}
      actions={<><Button variant="secondary" size="lg" onClick={onClose} disabled={busy}>닫기</Button><Button variant={danger ? "danger" : "primary"} size="lg" onClick={go} busy={busy}>{busy ? "보내는 중" : confirm}</Button></>}
    >
      <p className={s.dsub}>{sub}</p>
      <div role="radiogroup" aria-label="이유" className={s.opts}>
        {reasons.map((r) => <OptionRow key={r.key} selected={code === r.key} onClick={() => { setCode(r.key); setErr(null); }}>{r.label}</OptionRow>)}
      </div>
      {code === "other" ? <TextArea label={memoLabel} rows={3} maxLength={300} value={memo} onChange={(e) => setMemo(e.target.value)} /> : <Field label={memoLabel} optional maxLength={300} value={memo} onChange={(e) => setMemo(e.target.value)} />}
      <Small>{foot}</Small>
      {err ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
    </Dialog>
  );
}
