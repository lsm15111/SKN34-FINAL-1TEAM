"use client";
// 공정 상담. 무엇을 물을지와 숫자는 API(코드 · 계산 엔진)가 정하고, 이 화면은 폼 · 대화 · 결과를 보여 주기만 한다.
// 폼은 질문 종류(kind)로 그리고, 지금까지 정한 것은 API가 화면 말로 준 facts를 그대로 보인다 (공정 이름을 화면에 박지 않는다).
// 필수 칸은 프로젝트 정보로 채우고 빈 칸만 첫 폼으로 받는다. 대화와 카드는 화면이 들고 매 턴 보낸다 (아직 DB에 남기지 않음).
import { Fragment, useEffect, useRef, useState } from "react";
import { call, errorText, type Schemas } from "@/lib/backend/client";
import { won, wonFull } from "@/lib/format";
import s from "./ConsultChat.module.css";

type Card = Schemas["ConsultCard-Output"];
type Out = Schemas["ConsultOut"];
type Result = Schemas["TradeOut"];
type Plan = NonNullable<Result["plan"]>;
type Question = Schemas["Question"];
type Turn = { role: "user" | "assistant"; text: string };
type FormValue = string | string[];
type AnswerIn = { field: string; value: FormValue };

const UNKNOWN = "unknown";
const STATE: Record<string, { label: string; cls: string }> = {
  included: { label: "포함", cls: "mj-b-in" },
  bundled: { label: "묶음 포함", cls: "mj-b-bundle" },
  separate: { label: "따로 계산", cls: "mj-b-sep" },
  optional: { label: "선택", cls: "mj-b-opt" },
  after_visit: { label: "실측 후", cls: "mj-b-cond" },
  excluded: { label: "안 함", cls: "mj-b-no" },
};

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

function counts(q: Question): number[] {
  const lo = q.min ?? 1;
  const hi = q.max ?? lo;
  return Array.from({ length: Math.max(hi - lo + 1, 0) }, (_, i) => lo + i);
}

export function ConsultChat({ projectId }: { projectId: string }) {
  const [card, setCard] = useState<Card | null>(null);
  const [out, setOut] = useState<Out | null>(null);
  const [plans, setPlans] = useState<Record<string, Plan>>({});
  const [form, setForm] = useState<Record<string, FormValue>>({});
  const [log, setLog] = useState<Turn[]>([{ role: "assistant", text: "안녕하세요. 견적 받기에서 알려 주신 정보로 상담을 시작할게요." }]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const end = useRef<HTMLDivElement>(null);

  async function send(input: { message?: string; answers?: AnswerIn[]; say?: string; first?: boolean }) {
    setBusy(true);
    setError(null);
    const history = log.slice(1).slice(-40);
    if (input.say) setLog((l) => [...l, { role: "user", text: input.say! }]);
    try {
      const res = await call<Out>("POST", "/consult", {
        card: input.first ? null : card,
        history,
        message: input.message ?? null,
        answers: input.answers ?? [],
        project_id: input.first ? projectId : null,
      });
      const ready = !out?.results.length && res.results.length > 0;
      setCard(res.card);
      setOut(res);
      setPlans((prev) => {
        const next: Record<string, Plan> = {};
        for (const r of res.results) {
          if (r.plan_status === "new" && r.plan) next[r.trade] = r.plan;
          else if (r.plan_status === "same" && prev[r.trade]) next[r.trade] = prev[r.trade];
        }
        return next;
      });
      const said = [res.reply, ready ? "아래에 표준견적서와 공정별 의견을 보여 드려요. 궁금한 것이나 바꿀 것은 여기에 적어 주세요." : null].filter(Boolean).join("\n");
      if (said) setLog((l) => [...l, { role: "assistant", text: said }]);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void send({ first: true }); // 처음 한 번만 불러 프로젝트 정보로 칸을 채운다
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [log]);

  const questions = out?.questions ?? [];
  const labels = out?.trade_labels ?? {};
  const formReady = questions.length > 0 && questions.every((q) => filled(q, form[q.field]));
  const groups: { trade: string | null; label: string }[] = [{ trade: null, label: "집 정보" }, ...Object.entries(labels).map(([trade, label]) => ({ trade, label }))];

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

  function submitForm(e: React.FormEvent) {
    e.preventDefault();
    if (!formReady || busy) return;
    void send({ answers: questions.map((q) => ({ field: q.field, value: answerValue(form[q.field]) })) });
  }

  function submitChat(e: React.FormEvent) {
    e.preventDefault();
    const m = text.trim();
    if (!m || busy) return;
    setText("");
    void send({ message: m, say: m });
  }

  const facts = out?.facts ?? [];
  const summary = out?.summary;

  return (
    <div className={s.wrap}>
      {questions.length ? (
        <form className={`mj-panel ${s.form}`} onSubmit={submitForm} aria-labelledby="form-h">
          <div className={s.head}>
            <h2 id="form-h" className="mj-h2">먼저 몇 가지만 정해요</h2>
            <p className="mj-sub">견적 받기에서 받지 않은 것만 물어요. 모르면 &lsquo;모르겠어요&rsquo;를 고르면 기본값으로 계산하고 실측 때 확인해요.</p>
          </div>
          {groups.map((g) => {
            const qs = questions.filter((q) => (q.trade ?? null) === g.trade);
            if (!qs.length) return null;
            return (
              <div key={g.label} className={s.group}>
                <span className="mj-eyebrow">{g.label}</span>
                {qs.map((q) => (
                  <QuestionField key={q.field} q={q} value={form[q.field]} busy={busy} onPick={(v) => pick(q.field, v)} onToggle={(v) => toggle(q.field, v)} />
                ))}
              </div>
            );
          })}
          {error ? <p className="mj-error" role="alert">{error}</p> : null}
          <div className="mj-btn-row">
            <button type="submit" className="mj-btn mj-btn-pri" disabled={busy || !formReady}>{busy ? "계산하고 있어요…" : "표준견적서 보기"}</button>
          </div>
        </form>
      ) : null}

      <div className="mj-split">
        <section className={`mj-col mj-panel ${s.chat}`} aria-label="상담 대화">
          <div className={s.log} aria-live="polite">
            {log.map((t, i) => (
              <p key={i} className={`${s.bubble} ${t.role === "user" ? s.me : s.bot}`}>{t.text}</p>
            ))}
            {busy ? <p className={`${s.bubble} ${s.bot} ${s.wait}`}>답을 만들고 있어요…</p> : null}
            <div ref={end} />
          </div>
          {error && !questions.length ? <p className="mj-error" role="alert">{error}</p> : null}
          <form className={s.composer} onSubmit={submitChat}>
            <label htmlFor="consult-msg" className="mj-sr">상담 메시지</label>
            <input id="consult-msg" className="mj-input" value={text} maxLength={500} disabled={busy}
              placeholder="예: 천장은 빼 주세요, 걸레받이는 뭘로 해요?" onChange={(e) => setText(e.target.value)} />
            <button type="submit" className="mj-btn mj-btn-pri" disabled={busy || !text.trim()}>보내기</button>
          </form>
        </section>

        <aside className="mj-aside mj-panel" aria-labelledby="card-h">
          <h2 id="card-h" className="mj-h3">지금까지 정한 것</h2>
          <dl className="mj-kv">
            {facts.length ? facts.map((f) => (
              <Fragment key={`${f.trade ?? "home"}-${f.label}`}>
                <dt>{f.label}</dt>
                <dd>{f.text}{f.check ? <> <span className="mj-badge mj-b-cond">실측 때 확인</span></> : null}</dd>
              </Fragment>
            )) : (
              <><dt>공정</dt><dd>—</dd></>
            )}
          </dl>
          {facts.some((f) => f.check) ? (
            <p className="mj-small">&lsquo;실측 때 확인&rsquo; 칸은 모른다고 하셔서 기본값으로 계산했어요.</p>
          ) : null}
          <p className="mj-tiny">바꾸고 싶으면 대화창에 적어 주세요. 예: 천장은 빼 주세요, 방문은 2개예요</p>
        </aside>
      </div>

      {out?.results.length ? (
        <>
          {summary ? (
            <section className={`mj-panel ${s.result}`} aria-labelledby="sum-h">
              <h2 id="sum-h" className="mj-h2">한눈에 보기</h2>
              <p className="mj-sub">
                {out.results.map((r) => r.label).join(" · ")} 합계 <b className="mj-num">{won(summary.total)}</b>(VAT 포함), 모두 <b className="mj-num">{summary.days}일</b> 정도 걸려요.
              </p>
            </section>
          ) : null}
          <section className={`mj-panel ${s.result}`} aria-labelledby="sched-h">
            <div className={s.head}>
              <h2 id="sched-h" className="mj-h2">예상 공정표</h2>
              <p className="mj-sub">계산 엔진이 반나절 단위로 잡은 작업 순서예요. 실측 뒤 업체가 날짜를 정해요.</p>
            </div>
            <ol className={s.list}>
              {out.schedule.map((st) => (
                <li key={`${st.trade}-${st.key}`}>
                  <span className="mj-badge mj-b-in">{labels[st.trade] ?? st.trade}</span> <b>{st.name}</b> <span className="mj-small mj-num">반나절 {st.half_days}번</span>
                </li>
              ))}
            </ol>
          </section>
          {out.notice ? <p className="mj-notice mj-notice-warn"><span>{out.notice}</span></p> : null}
          {out.results.map((r) => <TradeResult key={r.trade} r={r} plan={plans[r.trade]} />)}
        </>
      ) : null}
    </div>
  );
}

function QuestionField({ q, value, busy, onPick, onToggle }: { q: Question; value?: FormValue; busy: boolean; onPick: (v: string) => void; onToggle: (v: string) => void }) {
  const id = `q-${q.field.replace(/\W/g, "-")}`;
  const one = typeof value === "string" ? value : "";
  const chip = `mj-btn mj-btn-sec mj-btn-sm ${s.chip}`;
  if (q.kind === "text") {
    const area = q.field === "area";
    return (
      <div className="mj-field">
        <label htmlFor={id} className="mj-label">{q.text}</label>
        <input id={id} className="mj-input" inputMode={area ? "decimal" : undefined} maxLength={20} placeholder={area ? "예: 34평, 84㎡" : undefined} value={one} disabled={busy}
          onChange={(e) => onPick(e.target.value)} />
        <div className="mj-chips">
          {q.choices.map((c) => (
            <button key={c.value} type="button" className={chip} disabled={busy} aria-pressed={one === c.value} onClick={() => onPick(c.value)}>{c.label}</button>
          ))}
        </div>
      </div>
    );
  }
  if (q.kind === "count") {
    return (
      <fieldset className="mj-fieldset">
        <legend className="mj-label">{q.text}</legend>
        <div className="mj-chips">
          {counts(q).map((n) => (
            <button key={n} type="button" className={`${chip} mj-num`} disabled={busy} aria-pressed={one === String(n)} onClick={() => onPick(String(n))}>{n}</button>
          ))}
          {q.choices.map((c) => (
            <button key={c.value} type="button" className={chip} disabled={busy} aria-pressed={one === c.value} onClick={() => onPick(c.value)}>{c.label}</button>
          ))}
        </div>
      </fieldset>
    );
  }
  const multi = q.kind === "multi";
  const many = Array.isArray(value) ? value : [];
  return (
    <fieldset className="mj-fieldset">
      <legend className="mj-label">{q.text}</legend>
      <div className={`mj-choices ${s.options}`}>
        {q.choices.map((c) => (
          <label key={c.value} className="mj-choice">
            <input type={multi ? "checkbox" : "radio"} name={id} value={c.value} checked={multi ? many.includes(c.value) : one === c.value} disabled={busy}
              onChange={() => (multi ? onToggle(c.value) : onPick(c.value))} />
            <span className="mj-choice-main">
              <span className="mj-choice-title">{c.label}</span>
              {c.desc ? <span className="mj-choice-desc">{c.desc}</span> : null}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function TradeResult({ r, plan }: { r: Result; plan?: Plan }) {
  const q = r.quote;
  const name = r.label;
  return (
    <section className={s.result} aria-labelledby={`${r.trade}-h`}>
      <div className={s.head}>
        <h2 id={`${r.trade}-h`} className="mj-h2">{name} 표준견적서</h2>
        <p className="mj-sub">공공 기준 단가({q.version})로 믿집이 계산한 비교 기준이에요. 업체 견적이 아니에요.</p>
      </div>
      <div className={`mj-panel ${s.totals}`}>
        <div><span className="mj-small">기준 금액 · VAT 별도</span><b className="mj-num">{won(q.subtotal)}</b></div>
        <div><span className="mj-small">VAT</span><b className="mj-num">{won(q.vat)}</b></div>
        <div><span className="mj-small">합계 · VAT 포함</span><b className={`mj-num ${s.accent}`}>{won(q.total)}</b></div>
        <div><span className="mj-small">{name}만 했을 때 기간</span><b className="mj-num">{q.days}일</b></div>
      </div>
      <div className="mj-table-box">
        <table className="mj-table">
          <caption className="mj-sr">{name} 표준견적서 줄</caption>
          <thead><tr><th scope="col">항목</th><th scope="col" className="r">수량</th><th scope="col" className="r">공공 단가</th><th scope="col" className="r">금액</th><th scope="col">상태</th><th scope="col">출처</th></tr></thead>
          <tbody>
            {q.lines.map((l) => (
              <tr key={l.key}>
                <th scope="row">{l.name}</th>
                <td className="r mj-num">{l.qty != null ? `${l.qty}${l.unit}` : "—"}</td>
                <td className="r mj-num">{l.unit_price != null ? `${l.unit_price.toLocaleString("ko-KR")}원/${l.unit}` : "—"}</td>
                <td className={`r mj-num ${l.state === "after_visit" ? s.muted : ""}`}>{l.amount != null ? wonFull(l.amount) : "—"}</td>
                <td><span className={`mj-badge ${STATE[l.state].cls}`}>{STATE[l.state].label}</span></td>
                <td className="mj-small">{l.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mj-small">합계에는 &lsquo;포함&rsquo;과 &lsquo;따로 계산&rsquo;만 들어가요. &lsquo;실측 후&rsquo; 줄은 실측 뒤 업체 견적에서 정해져요.</p>
      <ul className={`mj-small ${s.list}`}>{q.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>

      {plan ? (
        <section className="mj-panel" aria-labelledby={`${r.trade}-plan-h`}>
          <div className={s.planHead}>
            <h3 id={`${r.trade}-plan-h`} className="mj-h3">{name} 전문가 의견</h3>
            <span className="mj-badge mj-b-wait">AI가 만든 설명</span>
          </div>
          <p>{plan.summary}</p>
          <ol className={s.list}>
            {q.steps.map((st) => {
              const note = plan.steps.find((p) => p.key === st.key)?.note;
              return <li key={st.key}><b>{st.name}</b> <span className="mj-small mj-num">반나절 {st.half_days}번</span>{note ? <> · {note}</> : null}</li>;
            })}
          </ol>
          <h4 className="mj-h3">실측 때 업체에게 물어볼 것</h4>
          <ul className={s.list}>{plan.visit_checks.map((c) => <li key={c}>{c}</li>)}</ul>
          <h4 className="mj-h3">알아 두면 좋은 것</h4>
          <ul className={s.list}>{plan.cautions.map((c) => <li key={c.text}>{c.text} <span className="mj-tiny">· {c.source}</span></li>)}</ul>
        </section>
      ) : null}
    </section>
  );
}
