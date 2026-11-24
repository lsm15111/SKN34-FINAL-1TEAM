"use client";
// 도배 전 점검(갈래 P2, 서버 prework_brief): 앞 공사(목공 · 전기 · 필름 · 바닥)가 끝났는지 · 도배 전에 끝낼 직접 할 일 · 벽지 직접
// 구매면 살 롤 수(자투리 포함 · 여분 따로)와 풀 · 초배지 · 부직포가 표준견적서에 들어 있는지. 숫자는 모두 서버(계산 엔진) 값이에요.
// - 앞 공사 단추(끝났어요 · 아직이에요 · 안 해요)는 이 화면에서 골라 두고 [고른 답 보내기]로 한 턴에 보내요(choice
//   'prework.<공정>:<값>' 여럿, preworkSend). 서버가 승인 카드를 만들고, 고객이 그 카드를 눌러야 저장돼요(고정 선 1).
// - 저장된 답은 카드 때 값 위에 실행된 앞 공사 승인 카드 값을 덮은 것이에요(다시 열어도 저장한 단추가 골라져 보이게, preworkSaved).
//   바꾼 것만 보내요. 믿집은 그 공정 업체를 잇거나 견적을 내지 않아요.
// - 할 일이 끝난 줄의 카드(old)는 단추를 두지 않아요.
import Link from "next/link";
import { useState } from "react";
import { PREWORK_STATES, preworkSaved, preworkSend, type PreworkKey, type PreworkState } from "@/lib/api/assistant";
import { lineStateLabel } from "@/lib/labels";
import { SourceTag, StatusTag, type Tone } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import type { CardProps } from "./types";
import s from "./PreworkCheckCard.module.css";

const TONE: Record<PreworkState, Tone> = { done: "ok", todo: "waiting", none: "cancelled" };
const word = (x: PreworkState) => PREWORK_STATES.find((p) => p.key === x)?.label ?? x;

export function PreworkCheckCard({ card, ctx, old }: CardProps<"prework_check">) {
  const d = card.data;
  const rows = preworkSaved(d.rows, (label) => ctx.lastAction("prework", (a) => a.status === "executed" && !!a.summary.rows?.some((x) => x.label === label)));
  const [picked, setPicked] = useState<Partial<Record<PreworkKey, PreworkState>>>({});
  const [sent, setSent] = useState(false);
  const out = preworkSend(rows, picked);
  const pick = (key: PreworkKey, x: PreworkState) => {
    setPicked((v) => ({ ...v, [key]: x }));
    setSent(false);
  };
  const p = d.paper;

  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>도배 전 점검</h3>
        <SourceTag src="guide" />
      </div>

      <div className={s.sec}>
        <p className={s.head}>앞 공사</p>
        <ul className={s.rows}>
          {rows.map((r) => {
            const now = picked[r.key] ?? r.state;
            return (
              <li key={r.key} className={s.row}>
                <div className={s.rowHead}>
                  <b>{r.label}</b>
                  {r.state ? <StatusTag tone={TONE[r.state]}>{word(r.state)}</StatusTag> : null}
                </div>
                <p className={s.why}>{r.why}</p>
                {r.note ? <p className={s.note}>{r.note}</p> : null}
                {old ? null : (
                  <div className={s.chips} role="group" aria-label={`${r.label} 끝났는지`}>
                    {PREWORK_STATES.map((x) => (
                      <button key={x.key} type="button" className={`${k.chip} ${k.chipSm}`} aria-pressed={now === x.key} disabled={ctx.busy}
                        onClick={() => pick(r.key, x.key)}>
                        {x.label}
                      </button>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        {old ? null : (
          <div className={k.row}>
            <button type="button" className={`${k.btn} ${k.sm} ${k.pri}`} disabled={!out || sent || ctx.busy}
              onClick={() => { if (!out) return; ctx.send(out.text, { card_id: card.card_id, choice: out.choice }); setSent(true); }}>
              고른 답 보내기
            </button>
          </div>
        )}
      </div>

      {d.tasks.length ? (
        <div className={s.sec}>
          <p className={s.head}>도배 전에 직접 할 일</p>
          <ul className={s.tasks}>
            {d.tasks.map((t) => <li key={t.label}><b>{t.label}</b><span>{t.when}</span></li>)}
          </ul>
        </div>
      ) : null}

      {p ? (
        <div className={s.sec}>
          <div className={k.top}>
            <p className={s.head}>벽지 직접 구매</p>
            <SourceTag src="calc" />
          </div>
          <div className={k.kpi}>
            <span>{p.name}({p.size}) · 실측 전 어림</span>
            <b className={k.num}>{p.count}롤</b>
            <small>면적 {p.base}롤 + 자투리 {p.loss}롤 · 여분 {p.spare_min}~{p.spare_max}롤은 따로</small>
          </div>
          <p className={s.why}>{p.basis}</p>
          <ul className={s.mats} aria-label="부자재가 표준견적서에 들어 있는지">
            {p.materials.map((m) => (
              <li key={m.name}>
                <div className={s.rowHead}>
                  <b>{m.name}</b>
                  {m.state ? <StatusTag tone={m.state === "excluded" ? "cancelled" : "ok"}>{lineStateLabel(m.state)}</StatusTag> : <StatusTag tone="need">업체 확인</StatusTag>}
                </div>
                {m.line || m.amount ? <p className={s.why}>{[m.line, m.amount].filter(Boolean).join(" · ")}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={s.next}>
        <p><I n="bulb" />{d.next}</p>
        <div className={k.row}>
          {!old && d.next_say && d.next_label ? (
            <button type="button" className={`${k.btn} ${k.sm}`} disabled={ctx.busy} onClick={() => ctx.send(d.next_say as string)}>{d.next_label}</button>
          ) : null}
          <Link className={k.text} href={d.href} scroll={false}>공정표 보기<I n="chev" /></Link>
        </div>
      </div>
    </section>
  );
}
