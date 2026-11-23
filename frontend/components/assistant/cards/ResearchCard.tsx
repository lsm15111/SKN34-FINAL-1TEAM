"use client";
// 09 조사 담당 카드(진행 과정은 Claude의 웹 검색 · 생각 과정 접기처럼).
// 진행(phase progress): 제목 · 상태 · 종류, 접힌 머리 줄(도는 동안 반짝이는 '지금 하는 일' · 시계, 끝나면 'n초 동안
// 조사했어요' · 검색 n번 · 페이지 n곳), 펼치면 왼쪽 세로선 타임라인(조사 담당의 말은 본문 글씨, 검색 · 읽기는 아이콘 줄,
// 검색 줄은 찾은 페이지 목록을 펼침) · [멈추기]. 도는 동안 몇 초마다 다시 읽고, 끝난 것을 보면 대화를 새로 읽어 결과 줄이
// 보이게 해요.
// 결과(phase result): 요약 · 항목(이름 · 특징 · 주의할 점 · 판매가 · 제조사 그림, 링크 없음) · 맨 밑 링크(항목 페이지 먼저,
// 새 탭) · 출처 도메인 · 글 날짜 · 믿집 밖 표시. 링크 · 그림은 서버가 뽑은 주소만 와요. 순위 · 연락처는 없어요.
import { useEffect, useId, useRef, useState } from "react";
import { getResearch, stopResearch, type ResearchData, type ResearchStatus } from "@/lib/api/assistant";
import { errorText } from "@/lib/backend/client";
import { dateShort } from "@/lib/format";
import { SourceTag, StatusTag, type Tone } from "../kit/StatusTag";
import { I, type IconName } from "../kit/icons";
import k from "../kit/kit.module.css";
import s from "./ResearchCard.module.css";
import type { CardProps } from "./types";

type Trail = ResearchData["trail"][number];
type Item = ResearchData["items"][number];
type Clock = { text: string; spoken: string };

const POLL_MS = 4000;
const KIND_WORD: Record<ResearchData["kind"], string> = { outside_vendors: "믿집 밖 업체", materials: "도배 자재", general: "도배 자료" };
const STEP_WORD = { search: "찾는 중", read: "자료 읽는 중", write: "정리하는 중" } as const;
const END: Record<Exclude<ResearchStatus, "queued" | "running">, { tone: Tone; word: string; icon: IconName }> = {
  done: { tone: "done", word: "마쳤어요", icon: "check" },
  stopped: { tone: "cancelled", word: "멈췄어요", icon: "x" },
  failed: { tone: "failed", word: "못 끝냈어요", icon: "alert" },
};
/** 타임라인에 보이는 줄(시작 · 동적 거르기 · 정리 · 끝은 머리 줄이 대신 말해요) */
const SHOWN: ReadonlySet<Trail["kind"]> = new Set(["say", "search", "read", "steer"]);
const isLive = (st: ResearchStatus) => st === "queued" || st === "running";
const isWeb = (href: string) => /^https?:\/\//i.test(href);
/** 끝난 것을 보고 대화를 다시 읽은 조사(다시 그려도 또 읽지 않게, 이 탭에서만) */
const reloaded = new Set<string>();

function clock(ms: number): Clock {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(sec / 60);
  const r = sec % 60;
  return { text: `${m}:${String(r).padStart(2, "0")}`, spoken: m ? (r ? `${m}분 ${r}초` : `${m}분`) : `${r}초` };
}

/** 도는 동안 머리 줄: 가장 최근 기록으로 지금 하는 일 */
function nowLine(t: Trail | undefined, queued: boolean): string {
  if (queued) return "곧 시작해요";
  switch (t?.kind) {
    case "say": return t.text ?? "조사하는 중";
    case "search": return t.text ? `‘${t.text}’ 찾는 중` : "찾는 중";
    case "read": return `${t.title ?? t.text ?? "자료"} 읽는 중`;
    case "filter": return "자료를 살펴보는 중";
    case "write": return "찾은 것을 정리하는 중";
    case "steer": return "바꾼 조건으로 이어서 찾는 중";
    default: return "조사를 시작했어요";
  }
}

/** 끝난 뒤 머리 줄(Claude의 'n초 동안 생각함'처럼) */
function doneLine(status: ResearchStatus, took: Clock): string {
  if (status === "done") return `${took.spoken} 동안 조사했어요`;
  if (status === "stopped") return `${took.spoken} 만에 멈췄어요`;
  return "끝까지 하지 못했어요";
}

/** 머리 줄 오른쪽 셈: 검색 n번 · 페이지 n곳(연 곳만) */
function tally(trail: Trail[]): string {
  const n = trail.filter((t) => t.kind === "search").length;
  const m = trail.filter((t) => t.kind === "read" && t.ok !== false).length;
  return [n ? `검색 ${n}번` : null, m ? `페이지 ${m}곳` : null].filter(Boolean).join(" · ");
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
  const trail = d.trail ?? [];
  const head = live
    ? (asked ? "멈추는 중이에요. 그때까지 찾은 것으로 정리해요" : nowLine(trail[trail.length - 1], d.status === "queued"))
    : doneLine(d.status, took);
  const found = (d.items?.length ?? 0) + d.links.length;
  return (
    <section className={`${k.card} ${s.card}`} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{d.title}</h3>
        {tag}
      </div>
      <p className={s.prog}>{KIND_WORD[d.kind]} 조사</p>
      <Steps trail={trail} head={head} live={live} took={took} icon={end?.icon ?? "check"} />
      {!live && d.status !== "failed" && found ? <p className={k.muted}>결과는 아래에 올렸어요.</p> : null}
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

/** 진행 과정: 접힌 머리 줄(지금 하는 일 · 시계, 끝나면 걸린 시간 · 셈) + 펼치면 왼쪽 세로선 타임라인 */
function Steps({ trail, head, live, took, icon }: { trail: Trail[]; head: string; live: boolean; took: Clock; icon: IconName }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const rows = trail.filter((t) => SHOWN.has(t.kind));
  const sum = tally(trail);
  const inner = (
    <>
      <I n={live ? "spin" : icon} className={live ? s.spin : undefined} />
      <span className={live ? s.shine : s.headText}>{head}</span>
      {live ? <time className={s.side} aria-label={took.spoken}>{took.text}</time> : sum ? <span className={s.side}>{sum}</span> : null}
    </>
  );
  return (
    <div className={s.steps}>
      {rows.length ? (
        <button type="button" className={s.head} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
          {inner}
          <I n={open ? "up" : "down"} className={s.chev} />
        </button>
      ) : (
        <p className={s.head}>{inner}</p>
      )}
      {open && rows.length ? (
        <ol id={id} className={s.rail} aria-label="진행 과정">
          {rows.map((t, i) => <Step key={`${t.at}-${i}`} t={t} />)}
        </ol>
      ) : null}
    </div>
  );
}

/** 타임라인 한 줄: 조사 담당의 말은 본문 글씨, 검색 · 읽기는 아이콘 줄(검색은 찾은 페이지 목록을 펼쳐요) */
function Step({ t }: { t: Trail }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (t.kind === "say") return <li className={s.say}>{t.text}</li>;
  if (t.kind === "steer") {
    return (
      <li className={s.tool}>
        <I n="info" />
        <span className={s.toolText}>바꾼 조건으로 이어서 찾았어요</span>
      </li>
    );
  }
  if (t.kind === "search") {
    const hits = (t.hits ?? []).filter((h) => isWeb(h.href));
    return (
      <li className={s.tool}>
        <I n="search" />
        <span className={s.toolText}>‘{t.text}’</span>
        {hits.length ? (
          <button type="button" className={s.res} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
            {t.n}개 결과
            <I n={open ? "up" : "down"} />
          </button>
        ) : t.n != null ? (
          <span className={s.dim}>{t.n ? `${t.n}개 결과` : "결과 없음"}</span>
        ) : null}
        {open && hits.length ? (
          <ul id={id} className={s.hits}>
            {hits.map((h) => (
              <li key={h.href}>
                <a href={h.href} target="_blank" rel="noopener noreferrer nofollow">
                  <span>{h.title}</span>
                  <span className="mj-sr">(새 창)</span>
                </a>
                <span className={s.dim}>{h.source}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </li>
    );
  }
  const label = t.ok === false ? t.text ?? "" : t.title ?? t.text ?? "";
  const side = t.ok === false ? "열지 못했어요" : t.title ? t.text : t.ok == null ? "읽는 중" : null;
  return (
    <li className={s.tool}>
      <I n="doc" />
      {t.href && isWeb(t.href) && t.ok !== false ? (
        <a className={s.toolText} href={t.href} target="_blank" rel="noopener noreferrer nofollow">
          {label}
          <span className="mj-sr">(새 창)</span>
        </a>
      ) : (
        <span className={s.toolText}>{label}</span>
      )}
      {side ? <span className={s.dim}>{side}</span> : null}
    </li>
  );
}

/** 결과 항목 그림: 제조사 페이지 대표 그림(그 사이트에서 바로 불러옴). 못 불러오면 그림 칸을 빼요. 링크는 맨 밑에만 둬요 */
function Pic({ item }: { item: Item }) {
  const [gone, setGone] = useState(false);
  if (!item.image || gone || !isWeb(item.image)) return null;
  return (
    <span className={s.pic} aria-hidden="true">
      <img src={item.image} alt="" width={88} height={88} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setGone(true)} />
    </span>
  );
}

type Page = { href: string; title: string; source: string; day?: string | null; memo?: string | null };

/** 맨 밑 링크 목록: 항목 페이지(이름 그대로) 먼저, 그다음 다른 자료. 같은 주소는 한 번만
 *  (2026-11-23 사용자: 이름에 링크를 걸지 말고 링크는 맨 밑에) */
function pagesOf(items: Item[], links: ResearchData["links"]): Page[] {
  const seen = new Set<string>();
  const out: Page[] = [];
  for (const p of [...items.map((x) => ({ href: x.href, title: x.name, source: x.source })), ...links]) {
    if (!isWeb(p.href) || seen.has(p.href)) continue;
    seen.add(p.href);
    out.push(p);
  }
  return out;
}

function ResearchResult({ card, ctx }: CardProps<"research">) {
  const d = card.data;
  const today = ctx.now ? ctx.now.slice(0, 10) : undefined;
  const items = (d.items ?? []).filter((x) => isWeb(x.href));
  const pages = pagesOf(items, d.links);
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
      {items.length ? (
        <ul className={s.items} aria-label="찾은 것">
          {items.map((it) => (
            <li key={it.href} className={s.item}>
              <Pic item={it} />
              <div className={s.body}>
                <p className={s.name}>{it.name}</p>
                {it.feature ? <p className={s.feat}>{it.feature}</p> : null}
                {it.caution ? (
                  <p className={s.caution}>
                    <span>주의</span>
                    {it.caution}
                  </p>
                ) : null}
                {/* 판매가 · 규격: 서버가 판매처 페이지에서 같은 값을 찾은 것만 와요(판매처 표시 값, 믿집 계산 아님) */}
                {it.price?.checked ? (
                  <p className={s.price}>
                    <span>판매가</span>
                    <b className={k.num}>{it.price.text}</b>
                    <span className={s.dim}>판매처 표시 값 · {dateShort(it.price.checked, today)} 확인</span>
                  </p>
                ) : null}
                {it.size?.checked ? <p className={s.price}><span>규격</span>{it.size.text}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {items.length && pages.length ? <p className={s.sub}>링크</p> : null}
      {pages.length ? (
        <ul className={s.links} aria-label={items.length ? "링크" : "찾은 링크"}>
          {pages.map((l) => (
            <li key={l.href}>
              <a className={s.lnk} href={l.href} target="_blank" rel="noopener noreferrer nofollow">
                <span>{l.title}</span>
                <I n="external" />
                <span className="mj-sr">(새 창)</span>
              </a>
              {/* 믿집 밖 업체 안내는 카드 위 한 줄만(2026-11-23 사용자: 링크마다 같은 말은 빼도 됨) */}
              <span className={s.meta}>
                <span>{l.source}</span>
                {l.day ? <span>{dateShort(l.day, today)}</span> : null}
              </span>
              {l.memo ? <p className={s.memo}>{l.memo}</p> : null}
            </li>
          ))}
        </ul>
      ) : items.length ? null : (
        <p className={k.muted}>찾은 링크가 없어요.</p>
      )}
    </section>
  );
}
