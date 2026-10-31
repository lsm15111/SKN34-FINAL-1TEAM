"use client";
// 공정 상담. 무엇을 물을지와 숫자는 API(코드 · 계산 엔진)가 정하고, 이 화면은 폼 · 대화 · 결과를 보여 주기만 한다.
// 결과는 한눈에 보기 → 예상 공정표 → 공정별 자세히(접힘) 순서이고, 지금까지 정한 것은 왼쪽(폰에서는 위)에 둔다.
// 필수 칸은 프로젝트 정보로 채우고 빈 칸만 첫 폼으로 받는다. 대화와 카드는 화면이 들고 매 턴 보낸다 (아직 DB에 남기지 않음).
// 상담 상태는 이 탭에만 남겨서(saved.ts) 다른 화면에 다녀와도 이어서 보이고, '처음부터 다시'로 지운다.
import { useEffect, useRef, useState } from "react";
import { call, errorText, type Schemas } from "@/lib/backend/client";
import { Facts } from "./Facts";
import { QuestionForm, type AnswerIn } from "./QuestionForm";
import { Schedule } from "./Schedule";
import { Summary } from "./Summary";
import { TradeDetail } from "./TradeDetail";
import { clearSaved, readSaved, writeSaved, type Turn } from "./saved";
import s from "./ConsultChat.module.css";

type Card = Schemas["ConsultCard-Output"];
type Out = Schemas["ConsultOut"];
type Plan = Schemas["PlanOut"];

const HELLO: Turn = { role: "assistant", text: "안녕하세요. 견적 받기에서 알려 주신 정보로 상담을 시작할게요." };

export function ConsultChat({ projectId, userId }: { projectId: string; userId: string }) {
  const [card, setCard] = useState<Card | null>(null);
  const [out, setOut] = useState<Out | null>(null);
  const [plans, setPlans] = useState<Record<string, Plan>>({});
  const [log, setLog] = useState<Turn[]>([HELLO]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumed, setResumed] = useState(false);
  const started = useRef(false);
  const jump = useRef(false);
  const chatBox = useRef<HTMLElement>(null);
  const logBox = useRef<HTMLDivElement>(null);
  const sumHead = useRef<HTMLHeadingElement>(null);

  async function send(input: { message?: string; answers?: AnswerIn[]; say?: string; first?: boolean }) {
    setBusy(true);
    setError(null);
    const history = input.first ? [] : log.slice(1).slice(-40);
    if (input.say) setLog((l) => [...l, { role: "user", text: input.say! }]);
    try {
      const res = await call<Out>("POST", "/consult", {
        card: input.first ? null : card,
        history,
        message: input.message ?? null,
        answers: input.answers ?? [],
        project_id: input.first ? projectId : null,
      });
      const before = input.first ? null : out; // 처음부터 다시 할 때는 지난 결과를 보지 않는다
      const ready = !before?.results.length && res.results.length > 0;
      jump.current = ready && !input.first; // 폼을 내고 처음 결과가 나오면 한눈에 보기로 옮긴다
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
      const made = res.results.some((r) => r.plan) ? "표준견적서와 공정별 의견을" : "표준견적서를";
      const said = [res.reply, ready ? `${made} 만들었어요. 궁금한 것이나 바꿀 것은 여기에 적어 주세요.` : null].filter(Boolean).join("\n");
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
    const saved = readSaved(userId, projectId); // 이 탭에서 하던 상담이 있으면 다시 묻지 않고 이어서 보인다
    if (saved) {
      setCard(saved.out.card);
      setOut(saved.out);
      setPlans(saved.plans);
      setLog(saved.log);
      setResumed(true);
      return;
    }
    void send({ first: true }); // 처음 한 번만 불러 프로젝트 정보로 칸을 채운다
  }, []);
  useEffect(() => {
    if (out && !busy) writeSaved(userId, projectId, { out, plans, log }); // 답을 기다리는 동안은 남기지 않는다
  }, [userId, projectId, out, plans, log, busy]);
  useEffect(() => {
    const box = logBox.current; // 대화 칸 안에서만 내린다 (화면 전체는 움직이지 않는다)
    if (box) box.scrollTop = box.scrollHeight;
  }, [log, busy]);
  useEffect(() => {
    if (!jump.current) return;
    jump.current = false;
    const h = sumHead.current;
    h?.closest("section")?.scrollIntoView({ block: "start" });
    h?.focus({ preventScroll: true });
  }, [out]);

  function submitChat(e: React.FormEvent) {
    e.preventDefault();
    const m = text.trim();
    if (!m || busy) return;
    setText("");
    void send({ message: m, say: m });
  }

  function restart() {
    clearSaved(userId, projectId);
    setCard(null);
    setOut(null);
    setPlans({});
    setLog([HELLO]);
    setText("");
    setResumed(false);
    chatBox.current?.focus(); // 누른 버튼이 사라져도 초점은 대화 칸에 둔다
    void send({ first: true });
  }

  const questions = out?.questions ?? [];
  const labels = out?.trade_labels ?? {};
  const results = out?.results ?? [];
  const summary = out?.summary;

  return (
    <div className="mj-split">
      <Facts facts={out?.facts ?? []} labels={labels} />

      <div className="mj-col">
        {questions.length ? (
          <QuestionForm questions={questions} labels={labels} busy={busy} error={error} onSubmit={(answers) => void send({ answers })} />
        ) : null}

        <section ref={chatBox} tabIndex={-1} className={`mj-panel ${s.chat}`} aria-label="상담 대화">
          {out ? (
            <div className={s.bar}>
              <p className="mj-small">{resumed ? "이 탭에서 하던 상담을 이어서 보여 드려요." : "이 탭을 닫기 전까지 상담이 남아 있어요."}</p>
              <button type="button" className="mj-btn mj-btn-ghost mj-btn-sm" disabled={busy} onClick={restart}>처음부터 다시</button>
            </div>
          ) : null}
          <div ref={logBox} className={s.log} aria-live="polite">
            {log.map((t, i) => (
              <p key={i} className={`${s.bubble} ${t.role === "user" ? s.me : s.bot}`}>{t.text}</p>
            ))}
            {busy ? <p className={`${s.bubble} ${s.bot} ${s.wait}`}>답을 만들고 있어요…</p> : null}
          </div>
          {error && !questions.length ? <p className="mj-error" role="alert">{error}</p> : null}
          <form className={s.composer} onSubmit={submitChat}>
            <label htmlFor="consult-msg" className="mj-sr">상담 메시지</label>
            <input id="consult-msg" className="mj-input" value={text} maxLength={500} disabled={busy}
              placeholder="예: 천장은 빼 주세요, 걸레받이는 뭘로 해요?" onChange={(e) => setText(e.target.value)} />
            <button type="submit" className="mj-btn mj-btn-pri" disabled={busy || !text.trim()}>보내기</button>
          </form>
        </section>

        {out && summary && results.length ? (
          <div className={s.results} aria-busy={busy}>
            <Summary out={out} summary={summary} plans={plans} projectId={projectId} headingRef={sumHead} />
            <Schedule steps={out.schedule} labels={labels} total={summary.days} />
            <section className={s.details} aria-labelledby="detail-h">
              <div className={s.head}>
                <h2 id="detail-h" className="mj-h2">공정별 자세히</h2>
                <p className="mj-small">공정을 누르면 견적 줄 · 계산에 넣은 가정 · 전문가 의견을 펼쳐 볼 수 있어요.</p>
              </div>
              {results.map((r) => <TradeDetail key={r.trade} r={r} plan={plans[r.trade]} />)}
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}
