"use client";
// 첫 폼: 견적 받기에서 받지 않은 칸만 묻는다. 질문 종류(kind)로 그리고, 공정별로 묶어 API가 준 공정 이름을 붙인다.
import { useState } from "react";
import type { Schemas } from "@/lib/backend/client";
import s from "./QuestionForm.module.css";

type Question = Schemas["Question"];
type FormValue = string | string[];
export type AnswerIn = { field: string; value: FormValue };

const UNKNOWN = "unknown";
const UNKNOWN_DESC = "기본값으로 계산하고 실측 때 확인해요";

/** 폼 답이 다 찼는지 (여러 개 고르기는 최소 개수 이상) */
function filled(q: Question, v: FormValue | undefined): boolean {
  if (Array.isArray(v)) return v.includes(UNKNOWN) || v.length >= (q.min ?? 1);
  return !!v && v.trim() !== "";
}

/** 보낼 값. 여러 개 고르기에서 '모르겠어요'를 골랐으면 그 값 하나만 */
function answerValue(v: FormValue): FormValue {
  if (Array.isArray(v)) return v.includes(UNKNOWN) ? UNKNOWN : v;
  return v.trim();
}

/** 질문을 API 순서 그대로 공정별로 묶는다 (공통 칸은 '집 정보') */
function groupOf(questions: Question[], labels: Record<string, string>) {
  const groups: { key: string; label: string; qs: Question[] }[] = [];
  for (const q of questions) {
    const key = q.trade ?? "home";
    let g = groups.find((x) => x.key === key);
    if (!g) groups.push((g = { key, label: q.trade ? labels[q.trade] ?? "공정" : "집 정보", qs: [] }));
    g.qs.push(q);
  }
  return groups;
}

type Props = {
  questions: Question[];
  labels: Record<string, string>;
  busy: boolean;
  error: string | null;
  onSubmit: (answers: AnswerIn[]) => void;
};

export function QuestionForm({ questions, labels, busy, error, onSubmit }: Props) {
  const [form, setForm] = useState<Record<string, FormValue>>({});
  const left = questions.filter((q) => !filled(q, form[q.field])).length;

  function pick(field: string, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function toggle(field: string, value: string) {
    setForm((f) => {
      const cur = Array.isArray(f[field]) ? (f[field] as string[]) : [];
      if (value === UNKNOWN) return { ...f, [field]: cur.includes(UNKNOWN) ? [] : [UNKNOWN] };
      const rest = cur.filter((x) => x !== UNKNOWN);
      return { ...f, [field]: rest.includes(value) ? rest.filter((x) => x !== value) : [...rest, value] };
    });
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (left || busy) return;
    onSubmit(questions.map((q) => ({ field: q.field, value: answerValue(form[q.field]) })));
  }

  return (
    <form className={`mj-panel ${s.form}`} onSubmit={submit} aria-labelledby="form-h">
      <div className={s.head}>
        <h2 id="form-h" className="mj-h2">먼저 몇 가지만 정해요</h2>
        <p className="mj-sub">견적 받기에서 받지 않은 것만 물어요. 모르면 &lsquo;모르겠어요&rsquo;를 고르면 기본값으로 계산하고 실측 때 확인해요.</p>
      </div>
      {groupOf(questions, labels).map((g) => (
        <section key={g.key} className={s.group} aria-labelledby={`fg-${g.key}`}>
          <h3 id={`fg-${g.key}`} className="mj-h3">{g.label}</h3>
          {g.qs.map((q) => (
            <Field key={q.field} q={q} value={form[q.field]} busy={busy} onPick={(v) => pick(q.field, v)} onToggle={(v) => toggle(q.field, v)} />
          ))}
        </section>
      ))}
      {error ? <p className="mj-error" role="alert">{error}</p> : null}
      <div className={s.foot}>
        <button type="submit" className={`mj-btn mj-btn-pri ${s.submit}`} disabled={busy || left > 0}>{busy ? "계산하고 있어요…" : "표준견적서 보기"}</button>
        {left && !busy ? <p className="mj-small mj-num">{left}개 더 고르면 볼 수 있어요</p> : null}
      </div>
    </form>
  );
}

type FieldProps = { q: Question; value?: FormValue; busy: boolean; onPick: (v: string) => void; onToggle: (v: string) => void };

function Field({ q, value, busy, onPick, onToggle }: FieldProps) {
  const id = `q-${q.field.replace(/\W/g, "-")}`;
  const one = typeof value === "string" ? value : "";
  const chip = `mj-btn mj-btn-sec mj-btn-sm ${s.chip}`;

  // 평수: 적거나 빠른 선택 칩으로
  if (q.kind === "text") {
    const area = q.field === "area";
    return (
      <div className="mj-field">
        <label htmlFor={id} className="mj-label">{q.text}</label>
        <input id={id} className="mj-input" inputMode={area ? "decimal" : undefined} maxLength={20} placeholder={area ? "예: 34평, 84㎡" : undefined}
          value={one} disabled={busy} onChange={(e) => onPick(e.target.value)} />
        {q.choices.length ? (
          <div className={s.quick} role="group" aria-label="빠른 선택">
            {q.choices.map((c) => (
              <button key={c.value} type="button" className={chip} disabled={busy} aria-pressed={one === c.value} onClick={() => onPick(c.value)}>{c.label}</button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  // 개수: − 숫자 + (min~max)와 '모르겠어요'
  if (q.kind === "count") {
    const lo = q.min ?? 1;
    const hi = q.max ?? lo;
    const n = /^\d+$/.test(one) ? Number(one) : null;
    const unknown = q.choices.find((c) => c.value === UNKNOWN);
    return (
      <fieldset className="mj-fieldset">
        <legend className="mj-label">{q.text}</legend>
        <div className={s.count}>
          <div className={s.stepper}>
            <button type="button" className={s.step} aria-label="하나 줄이기" disabled={busy || n === null || n <= lo} onClick={() => n !== null && onPick(String(n - 1))}>
              <span aria-hidden="true">−</span>
            </button>
            <output className={`mj-num ${s.val}`} aria-live="polite">
              {n ?? <><span aria-hidden="true" className={s.empty}>?</span><span className="mj-sr">{one === UNKNOWN ? "모르겠어요" : "아직 안 골랐어요"}</span></>}
            </output>
            <button type="button" className={s.step} aria-label="하나 늘리기" disabled={busy || (n !== null && n >= hi)} onClick={() => onPick(String(n === null ? lo : n + 1))}>
              <span aria-hidden="true">+</span>
            </button>
          </div>
          {unknown ? (
            <button type="button" className={chip} disabled={busy} aria-pressed={one === UNKNOWN} onClick={() => onPick(UNKNOWN)}>{unknown.label}</button>
          ) : null}
        </div>
        <p className="mj-hint mj-num">{lo}부터 {hi}까지 고를 수 있어요</p>
      </fieldset>
    );
  }

  // 하나 고르기 · 여러 개 고르기: 종류 카드
  const multi = q.kind === "multi";
  const many = Array.isArray(value) ? value : [];
  return (
    <fieldset className="mj-fieldset">
      <legend className="mj-label">{q.text}</legend>
      {multi && (q.min ?? 1) > 1 ? <p className="mj-hint mj-num">{q.min}개 이상 골라 주세요</p> : null}
      <div className={`mj-choices ${s.cards}`}>
        {q.choices.map((c) => {
          const unknown = c.value === UNKNOWN;
          const desc = c.desc || (unknown ? UNKNOWN_DESC : "");
          return (
            <label key={c.value} className={`mj-choice ${unknown ? s.unknown : ""}`}>
              <input type={multi ? "checkbox" : "radio"} name={id} value={c.value} checked={multi ? many.includes(c.value) : one === c.value} disabled={busy}
                onChange={() => (multi ? onToggle(c.value) : onPick(c.value))} />
              <span className="mj-choice-main">
                <span className="mj-choice-title">{c.label}</span>
                {desc ? <span className="mj-choice-desc">{desc}</span> : null}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
