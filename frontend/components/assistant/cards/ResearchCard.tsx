"use client";
// 09 조사 담당 카드. 진행(phase progress): 제목 · 지금 단계(찾는 중 · 자료 읽는 중 · 정리하는 중) · 경과 시간(started_at으로 셈) ·
// [멈추기]. 도는 동안 몇 초마다 다시 읽고, 끝난 것을 보면 대화를 새로 읽어 결과 줄이 보이게 해요.
// 결과(phase result): 요약 · 링크(새 탭) · 출처 도메인 · 글 날짜 · 믿집 밖 표시 · 직접 확인하는 곳.
// 링크는 서버가 서버 도구 결과에서 뽑은 주소만 와요. 순위 · 금액 · 연락처는 없어요.
import { useEffect, useRef, useState } from "react";
import { getResearch, stopResearch, type ResearchData, type ResearchStatus } from "@/lib/api/assistant";
import { errorText } from "@/lib/backend/client";
import { dateShort } from "@/lib/format";
import { SourceTag, StatusTag, type Tone } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import s from "./ResearchCard.module.css";
import type { CardProps } from "./types";

const POLL_MS = 4000;
const KIND_WORD: Record<ResearchData["kind"], string> = { outside_vendors: "믿집 밖 업체", materials: "도배 자재", general: "도배 자료" };
const STEP_WORD = { search: "찾는 중", read: "자료 읽는 중", write: "정리하는 중" } as const;
const END: Record<Exclude<ResearchStatus, "queued" | "running">, { tone: Tone; word: string }> = {
  done: { tone: "done", word: "마쳤어요" },
  stopped: { tone: "cancelled", word: "멈췄어요" },
  failed: { tone: "failed", word: "못 끝냈어요" },
};
const isLive = (st: ResearchStatus) => st === "queued" || st === "running";
const isWeb = (href: string) => /^https?:\/\//i.test(href);
/** 끝난 것을 보고 대화를 다시 읽은 조사(다시 그려도 또 읽지 않게, 이 탭에서만) */
const reloaded = new Set<string>();

function clock(ms: number): { text: string; spoken: string } {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(sec / 60);
  const r = sec % 60;
  return { text: `${m}:${String(r).padStart(2, "0")}`, spoken: m ? `${m}분 ${r}초` : `${r}초` };
}

export function ResearchCard({ card, ctx, old }: CardProps<"research">) {
  return card.data.phase === "result" ? <ResearchResult card={card} ctx={ctx} old={old} /> : <ResearchProgress card={card} ctx={ctx} old={old} />;
}

function ResearchProgress({ card, ctx, old }: CardProps<"research">) {
  const [d, setD] = useState<ResearchData>(card.data);
  const [asked, setAsked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const { reload } = ctx;
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  const live = isLive(d.status);
  const id = d.research_id;

  useEffect(() => { setD(card.data); }, [card.data]);

  // 도는 동안: 처음 한 번 · 몇 초마다 다시 읽어요. 끝난 것을 보면 대화를 다시 읽어요(한 번)
  useEffect(() => {
    if (old || !live) return;
    let alive = true;
    const pull = async () => {
      try {
        const got = await getResearch(id);
        if (!alive || !got) return;
        setD(got);
        if (!isLive(got.status) && !reloaded.has(id)) {
          reloaded.add(id);
          reloadRef.current?.();
        }
      } catch { /* 다음 차례에 다시 읽어요 */ }
    };
    void pull();
    const t = setInterval(() => { void pull(); }, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [old, live, id]);

  // 경과 시간은 화면이 started_at(대기면 만든 때)으로 세요
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, [live]);

  const stop = async () => {
    setBusy(true);
    setErr(null);
    try {
      const got = await stopResearch(id);
      if (got) setD(got);
      setAsked(true);
      if (got && !isLive(got.status) && !reloaded.has(id)) { reloaded.add(id); reload?.(); }
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const since = Date.parse(d.started_at ?? d.created_at);
  const took = clock((live ? nowMs : Date.parse(d.ended_at ?? d.created_at)) - since);
  const end = live ? null : END[d.status as keyof typeof END];
  const tag = live
    ? <StatusTag tone={d.status === "queued" ? "waiting" : "running"}>{d.status === "queued" ? "곧 시작해요" : STEP_WORD[d.step ?? "search"]}</StatusTag>
    : <StatusTag tone={end?.tone ?? "done"}>{end?.word ?? "마쳤어요"}</StatusTag>;
  return (
    <section className={`${k.card} ${s.card}`} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{d.title}</h3>
        {tag}
      </div>
      <p className={s.prog}>
        <span>{KIND_WORD[d.kind]} 조사</span>
        <span aria-hidden="true">·</span>
        <span>
          {live ? "지난 시간 " : "걸린 시간 "}
          <time aria-label={took.spoken}>{took.text}</time>
        </span>
      </p>
      {live ? <p className={k.muted}>{asked ? "멈추는 중이에요. 그때까지 찾은 것으로 정리해요." : "그동안 다른 얘기 하셔도 돼요."}</p> : null}
      {!live && d.status !== "failed" && d.links.length ? <p className={k.muted}>결과는 아래에 올렸어요.</p> : null}
      {live && !old ? (
        <div className={s.foot}>
          <button type="button" className={`${k.btn} ${k.sm} ${s.stop}`} onClick={() => { void stop(); }} disabled={busy || asked} aria-busy={busy}>
            <I n="x" />
            멈추기
          </button>
        </div>
      ) : null}
      {err ? <p className={k.err} role="alert">{err}</p> : null}
    </section>
  );
}

function ResearchResult({ card, ctx }: CardProps<"research">) {
  const d = card.data;
  const today = ctx.now ? ctx.now.slice(0, 10) : undefined;
  const links = d.links.filter((l) => isWeb(l.href));
  return (
    <section className={`${k.card} ${s.card}`} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{d.title}</h3>
        <SourceTag src="ai" />
      </div>
      {d.note ? (
        <p className={s.warn}>
          <I n="info" />
          <span>{d.note}</span>
        </p>
      ) : null}
      <p className={s.summary}>{d.summary ?? "요약을 만들지 못했어요."}</p>
      {d.partial ? <p className={k.muted}>그때까지 찾은 것만 정리했어요.</p> : null}
      {links.length ? (
        <ul className={s.links} aria-label="찾은 링크">
          {links.map((l) => (
            <li key={l.href}>
              <a className={s.lnk} href={l.href} target="_blank" rel="noopener noreferrer nofollow">
                <span>{l.title}</span>
                <I n="external" />
                <span className="mj-sr">(새 창)</span>
              </a>
              <span className={s.meta}>
                <span>{l.source}</span>
                {l.day ? <span>{dateShort(l.day, today)}</span> : null}
                {d.outside ? <span className={s.badge}>믿집이 확인하지 않은 곳이에요</span> : null}
              </span>
              {l.memo ? <p className={s.memo}>{l.memo}</p> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className={k.muted}>찾은 링크가 없어요.</p>
      )}
      {d.checks.length ? (
        <div className={s.checks}>
          <span>직접 확인하는 곳</span>
          {d.checks.filter((c) => isWeb(c.href)).map((c) => (
            <a key={c.href} className={s.lnk} href={c.href} target="_blank" rel="noopener noreferrer">
              <span>{c.label}</span>
              <I n="external" />
              <span className="mj-sr">(새 창)</span>
            </a>
          ))}
        </div>
      ) : null}
    </section>
  );
}
