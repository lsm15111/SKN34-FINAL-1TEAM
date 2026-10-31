"use client";
// 도배 상담. 무엇을 물을지와 숫자는 API(코드 · 계산 엔진)가 정하고, 이 화면은 대화와 결과를 보여 주기만 한다.
// 대화와 카드는 화면이 들고 매 턴 보낸다 (아직 DB에 남기지 않음).
import { useEffect, useRef, useState } from "react";
import { call, errorText, type Schemas } from "@/lib/backend/client";
import { won, wonFull } from "@/lib/format";
import s from "./ConsultChat.module.css";

type Card = Schemas["DobaeCard-Output"];
type Out = Schemas["ConsultOut"];
type Turn = { role: "user" | "assistant"; text: string };

const STATE: Record<string, { label: string; cls: string }> = {
  included: { label: "포함", cls: "mj-b-in" },
  bundled: { label: "묶음 포함", cls: "mj-b-bundle" },
  separate: { label: "따로 계산", cls: "mj-b-sep" },
  optional: { label: "선택", cls: "mj-b-opt" },
  after_visit: { label: "실측 후", cls: "mj-b-cond" },
  excluded: { label: "안 함", cls: "mj-b-no" },
};
const CHECK_LABEL: Record<string, string> = { area_basis: "면적 기준", grade: "등급", include_ceiling: "천장 포함" };
const yesNo = (v: boolean | null | undefined, yes: string, no: string) => (v == null ? "—" : v ? yes : no);

export function ConsultChat({ projectId }: { projectId: string | null }) {
  const [card, setCard] = useState<Card | null>(null);
  const [log, setLog] = useState<Turn[]>([{ role: "assistant", text: "안녕하세요. 도배 상담을 도와드릴게요." }]);
  const [out, setOut] = useState<Out | null>(null);
  const [plan, setPlan] = useState<Out["plan"]>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const end = useRef<HTMLDivElement>(null);

  async function send(input: { message?: string; answer?: { field: string; value: string }; say?: string; first?: boolean }) {
    setBusy(true);
    setError(null);
    const history = log.slice(1).slice(-40);
    if (input.say) setLog((l) => [...l, { role: "user", text: input.say! }]);
    try {
      const res = await call<Out>("POST", "/consult/dobae", {
        card: input.first || !card ? {} : card,
        history,
        message: input.message ?? null,
        answer: input.answer ?? null,
        project_id: input.first ? projectId : null,
      });
      setCard(res.card);
      setOut(res);
      if (!res.quote || res.plan_status === "failed") setPlan(null);
      else if (res.plan_status === "new") setPlan(res.plan);
      const said = [res.reply, res.question?.text].filter(Boolean).join(" ");
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
    void send({ first: true }); // 처음 한 번만 불러 첫 질문을 받는다
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [log]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const m = text.trim();
    if (!m || busy) return;
    setText("");
    void send({ message: m, say: m });
  }

  const q = out?.question ?? null;
  const quote = out?.quote ?? null;

  return (
    <div className={s.wrap}>
      <div className="mj-split">
        <section className={`mj-col mj-panel ${s.chat}`} aria-label="상담 대화">
          <div className={s.log} aria-live="polite">
            {log.map((t, i) => (
              <p key={i} className={`${s.bubble} ${t.role === "user" ? s.me : s.bot}`}>{t.text}</p>
            ))}
            {busy ? <p className={`${s.bubble} ${s.bot} ${s.wait}`}>답을 만들고 있어요…</p> : null}
            <div ref={end} />
          </div>
          {q ? (
            <div className={s.choices} role="group" aria-label="빠른 답">
              {q.choices.map((c) => (
                <button key={c.value} type="button" className="mj-btn mj-btn-sec mj-btn-sm" disabled={busy}
                  onClick={() => void send({ answer: { field: q.field, value: c.value }, say: c.label })}>
                  {c.label}
                </button>
              ))}
            </div>
          ) : null}
          {error ? <p className="mj-error" role="alert">{error}</p> : null}
          <form className={s.composer} onSubmit={submit}>
            <label htmlFor="consult-msg" className="mj-sr">상담 메시지</label>
            <input id="consult-msg" className="mj-input" value={text} maxLength={500} disabled={busy}
              placeholder={q?.field === "area" ? "예: 34평" : "궁금한 것을 적어 주세요"} onChange={(e) => setText(e.target.value)} />
            <button type="submit" className="mj-btn mj-btn-pri" disabled={busy || !text.trim()}>보내기</button>
          </form>
        </section>

        <aside className="mj-aside mj-panel" aria-labelledby="card-h">
          <h2 id="card-h" className="mj-h3">지금까지 정한 것</h2>
          <dl className="mj-kv">
            <dt>면적</dt><dd className="mj-num">{card?.area_m2 ? `${card?.area_basis === "exclusive" ? "전용" : card?.area_basis === "supply" ? "공급" : ""} ${card.area_m2}㎡` : "—"}</dd>
            <dt>등급</dt><dd>{card?.grade ? (card.grade === "basic" ? "기본형 · 실크" : "저가형 · 합지") : "—"}</dd>
            <dt>천장</dt><dd>{yesNo(card?.include_ceiling, "천장도 해요", "벽만 해요")}</dd>
            <dt>집 상태</dt><dd>{yesNo(card?.occupied, "살면서 공사", "빈집")}</dd>
            <dt>발코니</dt><dd>{card?.balcony_ext ? "확장" : "확장 안 함"}</dd>
          </dl>
          {card?.to_check?.length ? (
            <p className="mj-small">모른다고 하신 칸은 기본값으로 두고 실측 때 확인해요: {card.to_check.map((f) => CHECK_LABEL[f] ?? f).join(", ")}</p>
          ) : null}
          <p className="mj-tiny">바꾸고 싶으면 대화창에 적어 주세요. 예: 천장은 빼 주세요</p>
        </aside>
      </div>

      {quote ? (
        <section className={s.result} aria-labelledby="std-h">
          <div className={s.head}>
            <h2 id="std-h" className="mj-h2">도배 표준견적서</h2>
            <p className="mj-sub">공공 기준 단가({quote.version})로 믿집이 계산한 비교 기준이에요. 업체 견적이 아니에요.</p>
          </div>
          <div className={`mj-panel ${s.totals}`}>
            <div><span className="mj-small">기준 금액 · VAT 별도</span><b className="mj-num">{won(quote.subtotal)}</b></div>
            <div><span className="mj-small">VAT</span><b className="mj-num">{won(quote.vat)}</b></div>
            <div><span className="mj-small">합계 · VAT 포함</span><b className={`mj-num ${s.accent}`}>{won(quote.total)}</b></div>
            <div><span className="mj-small">예상 기간</span><b className="mj-num">{quote.days}일</b></div>
          </div>
          <div className="mj-table-box">
            <table className="mj-table">
              <caption>도배 면적 {quote.paper_m2}㎡ (벽 {quote.wall_m2} · 천장 {quote.ceiling_m2})</caption>
              <thead><tr><th scope="col">항목</th><th scope="col" className="r">수량</th><th scope="col" className="r">공공 단가</th><th scope="col" className="r">금액</th><th scope="col">상태</th><th scope="col">출처</th></tr></thead>
              <tbody>
                {quote.lines.map((l) => (
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
          <p className="mj-small">합계에는 '포함'과 '따로 계산'만 들어가요. '실측 후' 금액은 참고용이고, 실측 뒤 업체 견적에서 정해져요.</p>
          <ul className={`mj-small ${s.list}`}>{quote.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>

          {out?.notice ? <p className="mj-notice mj-notice-warn"><span>{out.notice}</span></p> : null}
          {plan ? (
            <section className="mj-panel" aria-labelledby="plan-h">
              <div className={s.planHead}>
                <h3 id="plan-h" className="mj-h3">도배 전문가 의견</h3>
                <span className="mj-badge mj-b-wait">AI가 만든 설명</span>
              </div>
              <p>{plan.summary}</p>
              <ol className={s.list}>
                {quote.steps.map((st) => {
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
      ) : null}
    </div>
  );
}
