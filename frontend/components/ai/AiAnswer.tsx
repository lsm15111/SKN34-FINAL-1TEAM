// AI 답 한 개를 그린다: '자동 답변' · 묶음 문장 · 주의 · 팁 · 출처 · 믿집 계산 상자 · 화면 조각(버튼 · 초안 카드).
// 숫자는 계산 엔진 값(calc)만 상자로 보이고, 이 조각은 계산하지 않아요. 링크는 믿집 화면 주소만 만들어요.
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { CalcBox, type CalcLine } from "@/components/ui/CalcBox";
import { md } from "@/lib/format";
import type { AiAnswer as Answer, AiButton, AiCalc, AiCard, AiChoice } from "@/lib/api/chat";
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

function UiCard({ card, projectId, onPick }: { card: AiCard; projectId?: string; onPick?: (text: string, b?: AiButton) => void }) {
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

export function AiAnswer({ answer, projectId, onPick }: { answer: Answer; projectId?: string; onPick?: (text: string, b?: AiButton) => void }) {
  const [open, setOpen] = useState(false);
  const many = answer.sections.length > 1;
  const lines = answer.calc.map(calcLine).filter((x): x is CalcLine => x !== null);
  const notes = answer.calc.filter((c) => calcLine(c) === null && (c.note || c.qty != null));
  // 짧은 답(brief): 자세히에 남는 문장이 있을 때만 접어서 보여요. 문장은 서버가 sections에서 고른 그대로예요
  const brief = answer.brief && answer.brief.lines.length && answer.brief.more > 0 ? answer.brief : null;
  const briefSources = Array.from(new Set(answer.sections.flatMap((x) => x.sources.map((y) => y.title)))).slice(0, 2);
  return (
    <div className={s.answer}>
      <p className={s.notice}>{answer.notice}</p>
      {brief && !open ? (
        <div className={s.section}>
          {brief.lines.map((t, j) => <p key={j}>{t}</p>)}
          {briefSources.length ? <p className={s.sources}>출처 · {briefSources.join(" · ")}</p> : null}
        </div>
      ) : (
        answer.sections.map((sec, i) => (
          <div key={i} className={s.section}>
            {many && sec.title ? <p className={s.secTitle}>{sec.title}</p> : null}
            {sec.sentences.map((t, j) => <p key={j}>{t}</p>)}
            {sec.caution ? <p className={s.caution}>주의: {sec.caution}</p> : null}
            {sec.tip ? <p className={s.tip}>팁: {sec.tip}</p> : null}
            {sec.sources.length ? (
              <p className={s.sources}>출처 · {Array.from(new Set(sec.sources.map((x) => x.title))).slice(0, 3).join(" · ")}</p>
            ) : null}
          </div>
        ))
      )}
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
