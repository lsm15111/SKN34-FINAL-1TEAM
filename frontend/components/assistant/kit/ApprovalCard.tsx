"use client";
// 승인 카드: 무엇을(제목) · 얼마에(부가세 포함) · 어느 판 · 기한. 금액이 바뀌었으면 차액 줄을 맨 먼저.
// 상태: 승인 기다림 → 작업 중 → 완료(결과 링크) / 거절 / 만료(새 카드로 바뀜 · 기한 지남) / 실패. 판이 바뀌면(409) 새 판 카드가 이 자리에 와요.
// 되돌릴 수 없는 일은 이 카드의 단추로만 실행돼요. 누르면 바로 단추를 끄고(aria-busy) 결과를 카드 안에서 보여요(따로 확인 창 없음).
import Link from "next/link";
import type { ActionOut } from "@/lib/api/assistant";
import { dueText, timeSeoul, listStamp, dateSeoul, won, wonDelta } from "@/lib/format";
import { I } from "./icons";
import { StatusTag } from "./StatusTag";
import k from "./kit.module.css";

export function ApprovalCard({ action: a, now, busy = false, error = null, onApprove, onReject, onRemake }: {
  action: ActionOut;
  now: string;
  busy?: boolean;
  error?: string | null;
  onApprove: () => void;
  onReject: () => void;
  /** 거절 · 만료 뒤 비서에게 다시 만들어 달라고 해요 */
  onRemake?: () => void;
}) {
  const s = a.summary;
  const stamp = (t?: string | null) => (t ? (dateSeoul(t) === dateSeoul(now) ? timeSeoul(t) : listStamp(t)) : "");

  if (a.status === "executed") {
    return (
      <section className={k.fold} aria-label={`${s.title} · 완료`}>
        <span className={k.result}>
          <StatusTag tone="ok">완료</StatusTag>
          <b>{a.result?.text ?? s.title}</b>
          <span className={k.num}>{stamp(a.executed_at)}</span>
        </span>
        {a.result?.href ? <Link className={k.text} href={a.result.href} scroll={false}>{a.result.label ?? "보기"}<I n="chev" /></Link> : null}
      </section>
    );
  }
  if (a.status === "rejected" || a.status === "expired" || a.status === "failed") {
    const word =
      a.status === "rejected" ? "거절했어요"
        : a.error_code === "replaced" ? "새 카드로 바뀌었어요"
          : a.status === "expired" ? "기한이 지났어요"
            : a.error_code === "quote_changed" ? "견적서가 새 판으로 바뀌었어요"
              : "실행하지 못했어요";
    const tone = a.status === "failed" ? "failed" : a.status === "rejected" ? "cancelled" : "cancelled";
    return (
      <section className={k.fold} aria-label={`${s.title} · ${word}`}>
        <span className={k.result}>
          <StatusTag tone={tone}>{word}</StatusTag>
          <b>{s.title}</b>
        </span>
        {onRemake && a.error_code !== "replaced" ? <button type="button" className={k.text} onClick={onRemake}>다시 만들기</button> : null}
      </section>
    );
  }

  const up = (s.diff?.diff_won ?? 0) >= 0;
  return (
    <section className={`${k.card} ${k.ask}`} aria-label={`승인 카드 · ${s.title}`} aria-busy={busy || undefined}>
      <div className={k.askHead}>
        {busy ? <StatusTag tone="running">작업 중</StatusTag> : <StatusTag tone="need">승인이 필요해요</StatusTag>}
        <span className={`${k.due} ${k.num}`}>{dueText(a.expires_at, { now, relative: true })}</span>
      </div>
      <h3>{s.title}</h3>
      {a.supersedes ? (
        <p className={k.changed} role="status"><I n="info" />바뀐 판이에요. 값을 보고 다시 눌러 주세요.</p>
      ) : null}
      {s.diff ? (
        <div className={k.diff}>
          <b className={k.num}><I n={up ? "arrowUp" : "arrowDown"} />{s.diff.label} {wonDelta(s.diff.diff_won)}</b>
          <span className={k.num}>{won(s.diff.from_won)} → {won(s.diff.to_won)}</span>
        </div>
      ) : null}
      {s.amount_won != null ? (
        <div className={k.amt}><b className={k.num}>{won(s.amount_won)}</b><span>부가세 포함</span></div>
      ) : null}
      <dl className={k.rows}>
        {s.amounts?.length ? (
          <div>
            <dt>업체 · 가견적</dt>
            <dd>
              <ul className={k.amtList}>{s.amounts.map((x) => <li key={x.label}><span>{x.label}</span><b className={k.num}>{won(x.won)}</b></li>)}</ul>
              <small>부가세 포함</small>
            </dd>
          </div>
        ) : null}
        {s.version ? (
          <div>
            <dt>기준</dt>
            <dd>{s.version}{s.file ? <> · <Link className={k.text} href={s.file.href} scroll={false}><I n="file" />{s.file.label}</Link></> : null}</dd>
          </div>
        ) : null}
        {s.rows?.map((r) => (
          <div key={r.label}><dt>{r.label}</dt><dd className={k.num}>{r.value}{r.sub ? <small>{r.sub}</small> : null}</dd></div>
        ))}
        {s.photos?.length ? (
          <div>
            <dt>사진</dt>
            <dd><span className={k.thumbs}>{s.photos.slice(0, 4).map((p) => <img key={p} src={p} alt="" loading="lazy" width={40} height={30} />)}<span className={k.muted}>{s.photos.length}장</span></span></dd>
          </div>
        ) : null}
      </dl>
      {s.note ? <p className={k.note}><I n="info" />{s.note}</p> : null}
      {error ? <p className={k.err} role="alert">{error}</p> : null}
      <div className={k.acts}>
        <button type="button" className={`${k.btn} ${k.pri}`} onClick={onApprove} disabled={busy} aria-busy={busy || undefined}>{s.approve_label}</button>
        <button type="button" className={`${k.text} ${k.gray}`} onClick={onReject} disabled={busy}>거절</button>
      </div>
    </section>
  );
}
