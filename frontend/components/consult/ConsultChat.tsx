"use client";
// 도배 · 목공 상담. 무엇을 물을지와 숫자는 API(코드 · 계산 엔진)가 정하고, 이 화면은 폼 · 대화 · 결과를 보여 주기만 한다.
// 필수 칸은 프로젝트 정보로 채우고 빈 칸만 첫 폼으로 받는다. 대화와 카드는 화면이 들고 매 턴 보낸다 (아직 DB에 남기지 않음).
import { useEffect, useRef, useState } from "react";
import { call, errorText, type Schemas } from "@/lib/backend/client";
import { won, wonFull } from "@/lib/format";
import { mokLabel } from "@/lib/labels";
import s from "./ConsultChat.module.css";

type Card = Schemas["ConsultCard-Output"];
type Out = Schemas["ConsultOut"];
type Result = Schemas["TradeOut"];
type Plan = NonNullable<Result["plan"]>;
type TradeKey = Result["trade"];
type Turn = { role: "user" | "assistant"; text: string };

const TRADE: Record<TradeKey, string> = { dobae: "도배", mokgong: "목공" };
const STATE: Record<string, { label: string; cls: string }> = {
  included: { label: "포함", cls: "mj-b-in" },
  bundled: { label: "묶음 포함", cls: "mj-b-bundle" },
  separate: { label: "따로 계산", cls: "mj-b-sep" },
  optional: { label: "선택", cls: "mj-b-opt" },
  after_visit: { label: "실측 후", cls: "mj-b-cond" },
  excluded: { label: "안 함", cls: "mj-b-no" },
};
const CHECK_LABEL: Record<string, string> = { area_basis: "면적 기준", grade: "등급", include_ceiling: "천장 포함", doors: "방문 개수", door_frame: "문틀 교체" };
const GROUPS: { trade: TradeKey | null; label: string }[] = [{ trade: null, label: "집 정보" }, { trade: "dobae", label: "도배" }, { trade: "mokgong", label: "목공" }];
const yesNo = (v: boolean | null | undefined, yes: string, no: string) => (v == null ? "—" : v ? yes : no);

export function ConsultChat({ projectId }: { projectId: string }) {
  const [card, setCard] = useState<Card | null>(null);
  const [out, setOut] = useState<Out | null>(null);
  const [plans, setPlans] = useState<Partial<Record<TradeKey, Plan>>>({});
  const [form, setForm] = useState<Record<string, string>>({});
  const [log, setLog] = useState<Turn[]>([{ role: "assistant", text: "안녕하세요. 견적 받기에서 알려 주신 정보로 상담을 시작할게요." }]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const end = useRef<HTMLDivElement>(null);

  async function send(input: { message?: string; answers?: { field: string; value: string }[]; say?: string; first?: boolean }) {
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
        const next: Partial<Record<TradeKey, Plan>> = {};
        for (const r of res.results) {
          if (r.plan_status === "new" && r.plan) next[r.trade] = r.plan;
          else if (r.plan_status === "same" && prev[r.trade]) next[r.trade] = prev[r.trade];
        }
        return next;
      });
      const said = [res.reply, ready ? "아래에 표준견적서와 공정별 의견을 보여 드려요. 궁금한 것이나 바꿀 것은 여기에 적어 주세요." : null].filter(Boolean).join(" ");
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
  const formReady = questions.length > 0 && questions.every((q) => (form[q.field] ?? "").trim());

  function submitForm(e: React.FormEvent) {
    e.preventDefault();
    if (!formReady || busy) return;
    void send({ answers: questions.map((q) => ({ field: q.field, value: form[q.field].trim() })) });
  }

  function submitChat(e: React.FormEvent) {
    e.preventDefault();
    const m = text.trim();
    if (!m || busy) return;
    setText("");
    void send({ message: m, say: m });
  }

  const has = (t: TradeKey) => card?.trades?.includes(t) ?? false;
  const items = card?.mok_items ?? [];
  const spaces = card?.mok_spaces ?? [];

  return (
    <div className={s.wrap}>
      {questions.length ? (
        <form className={`mj-panel ${s.form}`} onSubmit={submitForm} aria-labelledby="form-h">
          <div className={s.head}>
            <h2 id="form-h" className="mj-h2">먼저 몇 가지만 정해요</h2>
            <p className="mj-sub">견적 받기에서 받지 않은 것만 물어요. 모르면 &lsquo;모르겠어요&rsquo;를 고르면 기본값으로 계산하고 실측 때 확인해요.</p>
          </div>
          {GROUPS.map((g) => {
            const qs = questions.filter((q) => (q.trade ?? null) === g.trade);
            if (!qs.length) return null;
            return (
              <div key={g.label} className={s.group}>
                <span className="mj-eyebrow">{g.label}</span>
                {qs.map((q) =>
                  q.field === "area" ? (
                    <div key={q.field} className="mj-field">
                      <label htmlFor="q-area" className="mj-label">{q.text}</label>
                      <input id="q-area" className="mj-input" inputMode="decimal" maxLength={20} placeholder="예: 34평, 84㎡" value={form.area ?? ""} disabled={busy}
                        onChange={(e) => setForm((f) => ({ ...f, area: e.target.value }))} />
                      <div className="mj-chips">
                        {q.choices.map((c) => (
                          <button key={c.value} type="button" className={`mj-btn mj-btn-sec mj-btn-sm ${s.chip}`} disabled={busy} aria-pressed={form.area === c.value}
                            onClick={() => setForm((f) => ({ ...f, area: c.value }))}>{c.label}</button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <fieldset key={q.field} className="mj-fieldset">
                      <legend className="mj-label">{q.text}</legend>
                      <div className={`mj-choices ${s.options}`}>
                        {q.choices.map((c) => (
                          <label key={c.value} className="mj-choice">
                            <input type="radio" name={`q-${q.field}`} value={c.value} checked={form[q.field] === c.value} disabled={busy}
                              onChange={() => setForm((f) => ({ ...f, [q.field]: c.value }))} />
                            <span className="mj-choice-main"><span className="mj-choice-title">{c.label}</span></span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ),
                )}
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
            <dt>공정</dt><dd>{card?.trades?.map((t) => TRADE[t]).join(" · ") ?? "—"}</dd>
            <dt>면적</dt><dd className="mj-num">{card?.area_m2 ? `${card.area_basis === "exclusive" ? "전용" : card.area_basis === "supply" ? "공급" : ""} ${card.area_m2}㎡` : "—"}</dd>
            <dt>집 상태</dt><dd>{yesNo(card?.occupied, "살면서 공사", "빈집")}</dd>
            {has("dobae") ? (
              <>
                <dt>도배 등급</dt><dd>{card?.grade ? (card.grade === "basic" ? "기본형 · 실크" : "저가형 · 합지") : "—"}</dd>
                <dt>천장 도배</dt><dd>{yesNo(card?.include_ceiling, "천장도 해요", "벽만 해요")}</dd>
              </>
            ) : null}
            {has("mokgong") ? (
              <>
                <dt>목공 항목</dt><dd>{items.map(mokLabel).join(" · ")}</dd>
                {spaces.length ? <><dt>목공 공간</dt><dd>{spaces.join(" · ")}</dd></> : null}
                {items.includes("door") ? <><dt>방문</dt><dd className="mj-num">{card?.doors ? `${card.doors}개 · ${card.door_frame === false ? "문짝만" : "문틀까지"}` : "—"}</dd></> : null}
              </>
            ) : null}
          </dl>
          {card?.to_check?.length ? (
            <p className="mj-small">모른다고 하신 칸은 기본값으로 두고 실측 때 확인해요: {card.to_check.map((f) => CHECK_LABEL[f] ?? f).join(", ")}</p>
          ) : null}
          <p className="mj-tiny">바꾸고 싶으면 대화창에 적어 주세요. 예: 천장은 빼 주세요, 방문은 2개예요</p>
        </aside>
      </div>

      {out?.results.length ? (
        <>
          <section className={`mj-panel ${s.result}`} aria-labelledby="sched-h">
            <div className={s.head}>
              <h2 id="sched-h" className="mj-h2">예상 공정표</h2>
              <p className="mj-sub">계산 엔진이 반나절 단위로 잡은 작업 순서예요. 모두 <b className="mj-num">{out.days}일</b> 정도 걸려요. 실측 뒤 업체가 날짜를 정해요.</p>
            </div>
            <ol className={s.list}>
              {out.schedule.map((st) => (
                <li key={`${st.trade}-${st.key}`}>
                  <span className="mj-badge mj-b-in">{TRADE[st.trade]}</span> <b>{st.name}</b> <span className="mj-small mj-num">반나절 {st.half_days}번</span>
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

function TradeResult({ r, plan }: { r: Result; plan?: Plan }) {
  const q = r.quote;
  const name = TRADE[r.trade];
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
