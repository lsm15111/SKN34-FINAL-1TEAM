"use client";
// V1 새 요청 브리핑(작업함 옆 자세히 · /vendor/requests/{vid} 맨 위).
// 요청 요약 · 우리 업체와 맞음/확인 필요(코드가 정함) · 확인한 단가로 만든 가견적(계산 엔진) · 빈 반나절 · 추천 응답(기간 초안).
// [수락하고 시간 제안]은 비서가 만든 '이 기간으로 답하기' 제안의 승인이에요. [거절]은 v3 '못 받아요'(이유 고르기)로 가요.
// 개인정보: 고객 이름 · 연락처 · 동 · 호는 없어요. 고객 메모는 인용 상자로만 보여요(비서 지시에 넣지 않아요). 비서는 금액을 제안하지 않아요.
// 승인이 실행되면 요청 화면(서버)을 다시 읽어요. 409(만료 · 판 바뀜)면 브리핑을 다시 읽어 새 제안으로 그려요.
// 요청 화면의 v3 단추(기간 답하기 · 못 받아요)를 누른 뒤에도 브리핑을 다시 읽어요(이미 답했으면 제안이 사라져요).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { approveVendorAction, getVendorBrief, newClientKey, vendorKindsForWrite, type ActionOut, type BriefSeed, type VendorBriefData } from "@/lib/api/assistant";
import { API_WRITE_EVENT, ApiError, errorText, type ApiWrite } from "@/lib/backend/client";
import { dayParts, dueText, rangeText, won } from "@/lib/format";
import { I } from "@/components/assistant/kit/icons";
import { SourceTag, StatusTag } from "@/components/assistant/kit/StatusTag";
import k from "@/components/assistant/kit/kit.module.css";
import p from "./pro.module.css";

export function BriefCard({ visitId, seed, data, now, compact = false }: {
  visitId: string;
  seed?: BriefSeed;
  /** 대화 카드(registry)에서 값을 이미 받았으면 */
  data?: VendorBriefData;
  now: string;
  /** 작업함 옆 자세히: 반나절 칸 · 메모를 빼요 */
  compact?: boolean;
}) {
  const router = useRouter();
  const [d, setD] = useState<VendorBriefData | null>(data ?? null);
  const [fail, setFail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<ActionOut | null>(null);
  const [key] = useState(newClientKey);
  const seedKey = JSON.stringify(seed ?? null);

  const reload = useCallback(async () => {
    try { setD(await getVendorBrief(visitId, seed)); setFail(false); } catch { setFail(true); }
    // seed는 값이 같으면 다시 읽지 않아요
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visitId, seedKey]);

  useEffect(() => {
    if (data) return;
    let alive = true;
    getVendorBrief(visitId, seed).then((x) => { if (alive) setD(x); }).catch(() => { if (alive) setFail(true); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visitId, seedKey, data]);

  // 요청 화면의 v3 단추로 이 요청에 답했으면 브리핑(제안)을 다시 읽어요
  useEffect(() => {
    const on = (e: Event) => {
      const { method, path } = (e as CustomEvent<ApiWrite>).detail ?? { method: "", path: "" };
      if (vendorKindsForWrite(method, path).length && path.includes(`/${visitId}/`)) void reload();
    };
    window.addEventListener(API_WRITE_EVENT, on);
    return () => window.removeEventListener(API_WRITE_EVENT, on);
  }, [visitId, reload]);

  if (fail) return <p className={k.muted} role="status">브리핑을 만들지 못했어요. 아래 요청 내용을 봐 주세요.</p>;
  if (!d) return <section className={`${k.card} ${p.skel}`} aria-busy="true" aria-label="요청 브리핑을 만들고 있어요"><i /><i /><i /></section>;

  async function accept() {
    if (!d?.suggest || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const out = await approveVendorAction(d.suggest.action_id, key);
      setDone(out);
      if (out.status === "executed") router.refresh();
    } catch (e) {
      setErr(errorText(e));
      if (e instanceof ApiError && e.status === 409) await reload();
    } finally {
      setBusy(false);
    }
  }
  const sug = d.suggest;
  const days = d.halves.days;

  return (
    <section className={`${k.card} ${p.brief}`} aria-label="새 요청 브리핑">
      <div className={k.askHead}>
        <StatusTag tone="need">새 요청</StatusTag>
        {d.due_at ? <StatusTag tone="waiting">답 기한 {dueText(d.due_at, { now, relative: true })}</StatusTag> : null}
      </div>
      <h3>{d.title}</h3>
      <ul className={k.facts}>{d.facts.map((f) => <li key={f}>{f}</li>)}</ul>
      {d.sentence ? <p className={p.say}><I n="sparkle" />{d.sentence}</p> : null}
      <ul className={p.fit} aria-label="우리 업체와 맞는지">
        {d.fit.map((f) => (
          <li key={f.key} data-ok={f.ok}>
            <I n={f.ok ? "check" : "alert"} />
            <b>{f.label}</b>
            <span>{f.ok ? "" : "확인 필요 · "}{f.text}</span>
          </li>
        ))}
      </ul>
      {d.estimate ? (
        <div className={p.est}>
          <div><span>가견적 · 부가세 포함</span><b className={k.num}>{won(d.estimate.total_won)}</b><span>{d.estimate.basis}</span></div>
          <SourceTag src="calc" />
        </div>
      ) : null}
      {!compact ? (
        <>
          <p className={p.secT}>내 빈 반나절</p>
          {/* 2주까지 와요: 7일씩 끊어 주마다 날짜 머리 · 오전 · 오후 줄을 따로 그려요(칸이 머리와 같은 열에 서요) */}
          <div className={p.weeks} role="img" aria-label={`${rangeText(days[0].day, days[days.length - 1].day)} 내 반나절: 빈 칸 ${d.halves.open_count}개`}>
            {weeksOf(days).map((wk) => (
              <div key={wk[0].day} className={p.slots}>
                <span className={p.lab} />
                {wk.map((x) => { const w = dayParts(x.day); return <span key={x.day} className={x.off ? `${p.h} ${p.off}` : p.h}><b className={k.num}>{w.d}</b>{w.w}</span>; })}
                {(["am", "pm"] as const).map((h) => (
                  <Half key={h} h={h} days={wk} taken={d.halves.taken} />
                ))}
              </div>
            ))}
          </div>
          <p className={p.legend}><span><i />고객이 고를 칸</span><span><i className={p.t} />잡힌 일</span></p>
          {d.memo ? <blockquote className={p.memo}><b>고객 메모</b>{d.memo}</blockquote> : null}
        </>
      ) : null}

      {done?.status === "executed" ? (
        <div className={k.fold}>
          <span className={k.result}><StatusTag tone="ok">완료</StatusTag><b>{done.result?.text}</b></span>
          {done.result?.href ? <Link className={k.text} href={done.result.href}>{done.result.label ?? "보기"}<I n="chev" /></Link> : null}
        </div>
      ) : sug ? (
        <div className={`${k.card} ${k.ask}`} aria-label="승인 카드 · 이 기간으로 답하기">
          <div className={k.askHead}><StatusTag tone={busy ? "running" : "need"}>{busy ? "작업 중" : "승인이 필요해요"}</StatusTag><span className={k.due}>비서 제안</span></div>
          <dl className={k.rows}>
            <div><dt>기간</dt><dd className={k.num}>{rangeText(sug.start, sug.end, { weekday: true })}<small>{sug.excluded.length ? `${sug.excluded.length}일 빼고 · ` : ""}고객이 고를 칸 {sug.open_count}</small></dd></div>
            <div><dt>바로 확정</dt><dd>{sug.instant ? "고객이 고르면 바로 잡혀요" : "고객이 고르면 한 번 더 수락해요"}</dd></div>
          </dl>
          {err ? <p className={k.err} role="alert">{err}</p> : null}
          <div className={k.acts}>
            <button type="button" className={`${k.btn} ${k.pri}`} onClick={accept} disabled={busy} aria-busy={busy || undefined}>수락하고 시간 제안</button>
            <Link className={`${k.btn} ${k.sm}`} href={`/vendor/requests/${encodeURIComponent(visitId)}?decline=1`}>거절</Link>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/** 반나절 칸 날짜를 7일씩(한 주 한 덩어리) */
function weeksOf<T>(days: T[]): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < days.length; i += 7) out.push(days.slice(i, i + 7));
  return out;
}

function Half({ h, days, taken }: { h: "am" | "pm"; days: VendorBriefData["halves"]["days"]; taken: Record<string, string> }) {
  return (
    <>
      <span className={p.lab}>{h === "am" ? "오전" : "오후"}</span>
      {days.map((x) => {
        if (x.off) return <span key={x.day + h} className={`${p.cell} ${p.cellOff}`} />;
        const t = taken[`${x.day}:${h}`];
        return t ? <span key={x.day + h} className={`${p.cell} ${p.taken}`} title={t}>{t}</span> : <span key={x.day + h} className={p.cell} />;
      })}
    </>
  );
}
