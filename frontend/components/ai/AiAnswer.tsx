// AI 답 한 개를 그린다: 묶음별 출처 표시 · 굵은 첫 줄(결론) · 묶음 문장 · 출처 번호 · 주의 · 팁 · 출처 목록 · 믿집 계산 상자 · 화면 조각.
// 출처 표시: 계산 엔진 묶음은 '믿집 계산', LLM이 쓴 묶음은 'AI 답변', 정해 둔 글 · 카드 · 자료 발췌는 '믿집 안내',
// 믿집 자료가 없어 LLM이 일반 상식으로 쓴 묶음은 '일반 설명(믿집 자료 밖)'.
// pending(LLM 모드에서 먼저 온 고정 몫): 그 묶음 아래에 진행 줄을 두고, 마지막 답이 오면 같은 자리 아래로 이어 붙어요.
// 출처 번호는 서버가 문서마다 처음 나온 순서로 매긴 것(refs · cites)이고, 화면은 그대로 그리기만 해요.
// 숫자는 계산 엔진 값(calc)만 상자로 보이고, 이 조각은 계산하지 않아요. 링크는 믿집 화면 주소만 만들어요.
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { CalcBox, type CalcLine } from "@/components/ui/CalcBox";
import { md } from "@/lib/format";
import type { AiAnswer as Answer, AiButton, AiCalc, AiCard, AiChoice, AiSource, AiTable } from "@/lib/api/chat";
import s from "./ai.module.css";

const ACTION_PATH: Record<string, (id?: string) => string> = {
  start: () => "/start",
  login: () => "/login",
  standard: (id) => (id ? `/projects/${id}/standard` : "/start/standard"),
  plan: (id) => (id ? `/projects/${id}/plan` : "/start"),
  vendors: (id) => (id ? `/projects/${id}/vendors` : "/start"),
  visits_new: (id) => (id ? `/projects/${id}/visits/new` : "/start"),
  visits: (id) => (id ? `/projects/${id}/visits` : "/start"),
  calendar: (id) => (id ? `/projects/${id}/visits` : "/start"),
  quotes: (id) => (id ? `/projects/${id}/quotes` : "/start"),
};

function calcLine(c: AiCalc): CalcLine | null {
  if (c.amount != null && c.qty != null && c.unit_price != null) {
    return {
      terms: [{ n: c.qty, unit: (c.unit as "㎡") || "" }, "×", { n: c.unit_price, unit: "원" }],
      result: { n: c.amount, unit: "원", paren: !c.in_total },
      note: c.in_total ? c.label : `${c.label} · 합계 밖`,
    };
  }
  if (c.amount != null) return { terms: [], result: { n: c.amount, unit: "원", label: c.label }, note: c.note || undefined };
  return null;
}

const STEP = /^(\d)\.\s(.+)$/; // 서버가 쓴 단계 문장('1. …')은 번호 동그라미로 그려요

/** 묶음 제목은 서로 다른 제목이 둘 이상일 때만 보여요(한 공정 답의 '[도배]'는 빼요) */
function titled(list: { title: string }[]): boolean {
  return new Set(list.map((x) => x.title).filter(Boolean)).size > 1;
}

/** '업체에 물을 말' 표의 첫 칸을 번호를 붙여 복사해요(업체 채팅에 붙여 넣기). 복사가 막히면 글을 펼쳐 골라 둬요 */
function CopyRows({ rows }: { rows: string[] }) {
  const [done, setDone] = useState(false);
  const [manual, setManual] = useState(false);
  const text = rows.map((r, i) => `${i + 1}. ${r}`).join("\n");
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
    } catch {
      setManual(true);
    }
  }
  return (
    <div className={s.copyRow}>
      <Button variant="secondary" size="sm" onClick={() => void copy()}>{done ? "복사했어요" : "물을 말 복사"}</Button>
      <span className="mj-sr" role="status">{done ? "업체에 물을 말을 복사했어요" : ""}</span>
      {manual ? (
        <textarea
          className={s.copyText} readOnly value={text} rows={rows.length} aria-label="업체에 물을 말"
          ref={(el) => { el?.focus(); el?.select(); }}
        />
      ) : null}
    </div>
  );
}

/** 묶음 출처 표시. 같은 표시가 이어지면 맨 앞에 한 번만 보여요 */
export function byLabel(source?: string): string {
  if (source === "calc") return "믿집 계산";
  if (source === "llm") return "AI 답변";
  if (source === "general") return "일반 설명(믿집 자료 밖)";
  return "믿집 안내";
}

function Line({ text, nums, refs, lead }: { text: string; nums?: number[]; refs: AiSource[]; lead?: boolean }) {
  const ok = (nums ?? []).filter((n) => refs[n - 1]);
  const step = STEP.exec(text);
  return (
    <p className={step ? s.step : lead ? s.lead : undefined}>
      {step ? <span className={s.stepNum} aria-hidden="true">{step[1]}</span> : null}
      {step ? <span className="mj-sr">{step[1]}단계 </span> : null}
      {step ? step[2] : text}
      {ok.map((n) => (
        <sup key={n} className={s.cite} title={refs[n - 1].title} aria-label={`출처 ${n}`}>{n}</sup>
      ))}
    </p>
  );
}

function RefList({ refs, fallback }: { refs: AiSource[]; fallback: string[] }) {
  if (refs.length) {
    return (
      <ol className={s.refs} aria-label="출처">
        {refs.slice(0, 3).map((r, i) => (
          <li key={r.ref}><span className={s.refNum}>{i + 1}</span>{r.title}</li>
        ))}
      </ol>
    );
  }
  return fallback.length ? <p className={s.sources}>출처 · {fallback.join(" · ")}</p> : null;
}

function Choices({ choices, projectId, onPick }: { choices: AiChoice[]; projectId?: string; onPick?: (text: string, b?: AiButton) => void }) {
  return (
    <div className={s.choices}>
      {choices.map((c, i) => {
        if (c.action && ACTION_PATH[c.action]) {
          return <Button key={i} variant="secondary" size="sm" href={ACTION_PATH[c.action](projectId)}>{c.text}</Button>;
        }
        return (
          <Button key={i} variant="weak" size="sm" onClick={() => onPick?.(c.text, c.route ? { route: c.route, trade: c.trade, slot: c.slot, value: c.value } : undefined)}>
            {c.text}
          </Button>
        );
      })}
    </div>
  );
}

// 코드가 고른 추천 업체(조건 필터 + 점수). 금액은 계산 엔진 가견적, 사유는 서버 틀 그대로예요
function VendorReco({ card, projectId, onPick }: { card: AiCard; projectId?: string; onPick?: (text: string, b?: AiButton) => void }) {
  const list = card.vendors ?? [];
  return (
    <div className={s.reco}>
      <p className={s.draftTitle}>{card.title || "추천 업체"}</p>
      <ol className={s.recoList}>
        {list.map((v, i) => (
          <li key={v.vendor_id} className={s.recoItem}>
            <span className={s.stepNum} aria-hidden="true">{i + 1}</span>
            <div className={s.recoBody}>
              {projectId ? (
                <a className={s.recoName} href={`/projects/${projectId}/vendors/${encodeURIComponent(v.vendor_id)}?trade=dobae`}>{v.name}</a>
              ) : (
                <span className={s.recoName}>{v.name}</span>
              )}
              {v.estimate_total != null ? <span className={`${s.mute} mj-num`}>가견적 {v.estimate_total.toLocaleString("ko-KR")}원(부가세 포함)</span> : null}
              {v.reasons.length ? <span className={s.recoWhy}>{v.reasons.join(" · ")}</span> : null}
            </div>
          </li>
        ))}
      </ol>
      {card.text ? <p className={s.sources}>{card.text}</p> : null}
      <Choices choices={card.choices} projectId={projectId} onPick={onPick} />
    </div>
  );
}

// 비교표: 폰 너비에서 가로로 넘치지 않게 줄마다 '칸 이름 · 값'으로 쌓아요. 글은 검증된 카드 그대로예요.
function Compare({ title, table }: { title: string; table: AiTable }) {
  const [head, ...rest] = table.cols;
  return (
    <section className={s.compare} aria-label={title || head}>
      {title ? <p className={s.draftTitle}>{title}</p> : null}
      {table.rows.map((r, i) => (
        <div key={i} className={s.compareRow}>
          <p className={s.compareName}>{r.cells[0]}</p>
          <dl>
            {rest.map((c, j) => (
              <div key={c} className={s.compareItem}>
                <dt>{c}</dt>
                <dd>{r.cells[j + 1]}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
      {table.sources.length ? <p className={s.sources}>출처 · {table.sources.slice(0, 3).join(" · ")}</p> : null}
    </section>
  );
}

function UiCard({ card, projectId, onPick }: { card: AiCard; projectId?: string; onPick?: (text: string, b?: AiButton) => void }) {
  if (card.kind === "vendor_reco") return <VendorReco card={card} projectId={projectId} onPick={onPick} />;
  if (card.kind === "compare" && card.table) return <Compare title={card.title} table={card.table} />;
  if (card.kind === "visit_draft" && card.draft) {
    const d = card.draft;
    return (
      <div className={s.draft}>
        <p className={s.draftTitle}>{card.title || "실측 일정 요청 · 초안"}</p>
        {d.wish_start && d.wish_end ? (
          <p><span className={s.mute}>희망 기간</span> {md(d.wish_start)} ~ {md(d.wish_end)}</p>
        ) : null}
        {d.vendors.length ? <p><span className={s.mute}>업체</span> {d.vendors.join(" · ")}</p> : null}
        <p className={s.mute}>AI는 초안만 만들어요. 보내기는 직접 눌러요.</p>
        <Choices choices={card.choices} projectId={projectId} onPick={onPick} />
      </div>
    );
  }
  return <Choices choices={card.choices} projectId={projectId} onPick={onPick} />;
}

export function AiAnswer({ answer, projectId, onPick, pending = false }: {
  answer: Answer;
  projectId?: string;
  onPick?: (text: string, b?: AiButton) => void;
  /** 먼저 온 고정 몫만 있는 답(LLM이 아래 글을 쓰는 중) */
  pending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  // 먼저 보낸 고정 묶음(fixed개)은 그 묶음끼리만 보고 제목을 정해서, 아래에 AI 글이 붙어도 모양이 바뀌지 않아요
  const fixed = Math.min(answer.fixed ?? 0, answer.sections.length);
  const titleHead = titled(answer.sections.slice(0, fixed));
  const titleRest = titled(answer.sections);
  const lines = answer.calc.map(calcLine).filter((x): x is CalcLine => x !== null);
  const notes = answer.calc.filter((c) => calcLine(c) === null && (c.note || c.qty != null));
  // 짧은 답(brief): 자세히에 남는 문장이 있을 때만 접어서 보여요. 문장은 서버가 sections에서 고른 그대로예요
  const brief = answer.brief && answer.brief.lines.length && answer.brief.more > 0 ? answer.brief : null;
  const briefSources = Array.from(new Set(answer.sections.flatMap((x) => x.sources.map((y) => y.title)))).slice(0, 2);
  const refs = answer.refs ?? [];
  let first = true; // 처음 그리는 문장 하나만 굵게(결론 자리)
  const isLead = () => { const v = first; first = false; return v; };
  return (
    <div className={s.answer}>
      {brief && !open ? (
        <div className={s.section}>
          <p className={s.by}>{byLabel(answer.sections[0]?.source)}</p>
          {brief.lines.map((t, j) => <Line key={j} text={t} nums={brief.cites?.[j]} refs={refs} lead={isLead()} />)}
          <RefList refs={refs} fallback={briefSources} />
        </div>
      ) : (
        answer.sections.map((sec, i) => (
          <div key={i} className={s.section}>
            {i === 0 || byLabel(answer.sections[i - 1].source) !== byLabel(sec.source) ? (
              <p className={s.by}>{byLabel(sec.source)}</p>
            ) : null}
            {sec.title && (i < fixed ? titleHead : titleRest) ? <p className={s.secTitle}>{sec.title}</p> : null}
            {sec.steps ? (
              <ol className={s.steps}>
                {sec.sentences.map((t, j) => (
                  <li key={j} className={s.step}>
                    <span className={s.stepNum} aria-hidden="true">{j + 1}</span>
                    <Line text={t} nums={sec.cites?.[j]} refs={refs} />
                  </li>
                ))}
              </ol>
            ) : (
              // 표가 있으면 첫 문장(결론) → 표 → 나머지 문장 순서로 그려요
              sec.sentences.slice(0, sec.table?.length ? 1 : undefined).map((t, j) => <Line key={j} text={t} nums={sec.cites?.[j]} refs={refs} lead={isLead()} />)
            )}
            {sec.table?.length ? (
              <div className={s.tableWrap}>
                <table className={s.table}>
                  <tbody>
                    {sec.table.map((r, j) => (
                      <tr key={j}><th scope="row">{r[0]}</th><td>{r[1]}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {sec.copyable && sec.table?.length ? <CopyRows rows={sec.table.map((r) => r[0])} /> : null}
            {!sec.steps && sec.table?.length
              ? sec.sentences.slice(1).map((t, j) => <Line key={j + 1} text={t} nums={sec.cites?.[j + 1]} refs={refs} lead={isLead()} />)
              : null}
            {sec.caution ? <p className={s.caution}>주의: {sec.caution}</p> : null}
            {sec.tip ? <p className={s.tip}>팁: {sec.tip}</p> : null}
            {!refs.length && sec.sources.length ? (
              <p className={s.sources}>출처 · {Array.from(new Set(sec.sources.map((x) => x.title))).slice(0, 3).join(" · ")}</p>
            ) : null}
          </div>
        ))
      )}
      {pending ? (
        <p className={s.working} role="status">
          AI가 믿집 자료로 답을 쓰고 있어요<span className={s.dots} aria-hidden="true"><i /><i /><i /></span>
        </p>
      ) : null}
      {!answer.sections.length && !pending && !brief ? <p className={s.by}>{byLabel()}</p> : null}
      {!(brief && !open) && !pending && refs.length ? <RefList refs={refs} fallback={[]} /> : null}
      {brief ? (
        <Button variant="text" size="sm" className={s.more} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "짧게 보기" : `자세히 보기 · ${brief.more}문장 더`}
        </Button>
      ) : null}
      {answer.unknown.map((t, i) => <p key={`u${i}`} className={s.unknown}>{t}</p>)}
      {lines.length ? <CalcBox lines={lines} /> : null}
      {notes.map((c, i) => (
        <p key={`n${i}`} className={`${s.calcNote} mj-num`}>믿집 계산 · {c.label} {c.qty != null ? `${c.qty}${c.unit} · ` : ""}{c.note}</p>
      ))}
      {answer.ask ? (
        <div className={s.ask}>
          <p>{answer.ask.question}</p>
          <div className={s.choices}>
            {answer.ask.options.map((o) => (
              <Button key={o} variant="weak" size="sm" onClick={() => onPick?.(o, { route: "trade", trade: answer.ask!.trade, slot: answer.ask!.slot, value: o })}>{o}</Button>
            ))}
          </div>
        </div>
      ) : null}
      {answer.cards.map((c, i) => <UiCard key={`c${i}`} card={c} projectId={projectId} onPick={onPick} />)}
      {answer.suggest.length ? (
        <div className={s.choices} aria-label="이어 물을 질문">
          {answer.suggest.map((q) => <Button key={q} variant="text" size="sm" onClick={() => onPick?.(q)}>{q}</Button>)}
        </div>
      ) : null}
    </div>
  );
}
