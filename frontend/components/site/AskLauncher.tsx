"use client";
// 오른쪽 아래 '공사 상담' 버튼과 떠 있는 창 (시안 WProjectBChat · B안). 상담 API가 없어서 예시 데이터(lib/mock/ask.ts)로 답한다.
// 질문 칩이나 입력한 말로 장면을 고른다. 공사 화면이면 창 맨 위에 표준견적서 합계를 보이고, 견적 설명의 숫자는 지금 공사의 저장된 표준견적서(GET /projects/{id}/standard)를
// 읽어 그대로 보이기만 하고 화면에서 계산하지 않는다.
// 창은 380 × 560, 폰(600px 아래)에서는 아래에서 올라오는 창. 닫기(X) · Esc로 닫고 '공사 상담' 버튼으로 돌아간다.
// 업체 자세히 오른쪽 창이 열려 있으면 버튼이 창 왼쪽으로 비킨다(AskLauncher.module.css).
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { call, type Schemas } from "@/lib/backend/client";
import { decText, won, wonFull } from "@/lib/format";
import {
  ASK_CHIPS, BOTH, BOTH_QS, BOTH_SUM, CARD_TITLE, DOBAE, GUIDE, INTRO, NO_ROOM, NONE_TEXT, OUT_TEXT, PRICE, WALL, WHO,
  pickReply, roomOf, type BothKey, type Reply, type Wall,
} from "@/lib/mock/ask";
import s from "./AskLauncher.module.css";

type Std = Schemas["StandardOut"];
type Turn = { id: number; q: string; reply: Reply };
/** 새로 붙은 말이 보이게 창 안을 내린다. el을 안 주면 그 질문 말풍선이 기준 */
type Grow = (el?: HTMLElement | null) => void;
type Row = { k: string; v: string; later?: boolean };

const PROJECT = /^\/projects\/([0-9a-f-]{36})(?:\/|$)/i;
const LEN = /^(?!0+(?:\.0+)?$)\d{1,3}(?:\.\d{1,2})?$/;

const Bubble = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true"><path d="M5 3.5h10A1.5 1.5 0 0 1 16.5 5v6.5A1.5 1.5 0 0 1 15 13H9.5L6 16v-3H5a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 5 3.5z" /></svg>
);
const X = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" /></svg>
);

export function AskLauncher() {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [std, setStd] = useState<{ pid: string; data: Std | null } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);
  const pid = PROJECT.exec(usePathname() ?? "")?.[1] ?? null;
  // 공사 화면이 아니면 null, 읽는 중이면 undefined
  const cur = !pid ? null : std?.pid === pid ? std.data : undefined;

  useEffect(() => {
    if (!open) return;
    title.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector("dialog[open]")) return;
      setOpen(false);
      btn.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open || !pid || std?.pid === pid) return;
    let live = true;
    call<Std>("GET", `/projects/${pid}/standard`).catch(() => null).then((data) => { if (live) setStd({ pid, data }); });
    return () => { live = false; };
  }, [open, pid, std?.pid]);

  const grow = useCallback<Grow>((el) => {
    requestAnimationFrame(() => {
      const box = log.current;
      if (!box) return;
      const end = box.scrollHeight - box.clientHeight;
      const top = el ? el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 12 : end;
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      box.scrollTo({ top: Math.max(0, Math.min(end, top)), behavior: smooth ? "smooth" : "auto" });
    });
  }, []);

  function close() { setOpen(false); btn.current?.focus(); }
  function ask(q: string) {
    const t = q.trim();
    if (!t) return;
    const id = nextId.current++;
    setTurns((xs) => [...xs, { id, q: t, reply: pickReply(t) }]);
  }
  function submit() { ask(text); setText(""); }

  return (
    <>
      {open ? (
        <section id="ask-win" className={s.win} aria-labelledby="ask-t">
          <div className={s.hd}>
            <h2 id="ask-t" ref={title} tabIndex={-1} className={s.t}>공사 상담</h2>
            <button type="button" className={s.x} aria-label="공사 상담 창 닫기" onClick={close}><X /></button>
          </div>
          <div ref={log} className={s.log} role="log" aria-live="polite" aria-label="공사 상담 대화">
            {pid && cur ? (
              <div className={s.std}>
                <span className={s.box}>표준견적서</span>
                <span className="mj-num">합계 <strong>{won(cur.total)}</strong> · 부가세 포함</span>
                <Link className="mj-lnk" href={`/projects/${pid}/standard`} aria-label="표준견적서 보기">보기</Link>
              </div>
            ) : null}
            {/* 안내 문장 · 예시 질문은 첫 질문 전에만 보인다 */}
            {turns.length ? null : (
              <>
                <p className={s.intro}>{INTRO}</p>
                <div className={s.chips} role="group" aria-label="질문 예시">
                  {ASK_CHIPS.map((c) => <button key={c.q} type="button" className={s.chip} onClick={() => ask(c.q)}>{c.q}</button>)}
                </div>
              </>
            )}
            {turns.map((t) => <TurnView key={t.id} t={t} pid={pid} std={cur} grow={grow} />)}
          </div>
          <form className={s.fm} onSubmit={(e) => { e.preventDefault(); submit(); }} aria-label="질문 보내기">
            <label className="mj-sr" htmlFor="ask-q">질문</label>
            <textarea
              id="ask-q" className={`mj-textarea ${s.q}`} rows={1} maxLength={200} placeholder="물어보세요" value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
            />
            <button type="submit" className="mj-btn mj-btn-pri mj-btn-sm">보내기</button>
          </form>
        </section>
      ) : null}
      <button ref={btn} type="button" className={s.launch} aria-expanded={open} aria-controls="ask-win" data-ask-launch="" onClick={() => (open ? close() : setOpen(true))}>
        <Bubble /><span className={s.lbl}>공사 상담</span>
      </button>
    </>
  );
}

function TurnView({ t, pid, std, grow }: { t: Turn; pid: string | null; std: Std | null | undefined; grow: Grow }) {
  const me = useRef<HTMLParagraphElement>(null);
  const g = useCallback<Grow>((el) => grow(el ?? me.current), [grow]);
  useEffect(() => { g(); }, [g]);
  return (
    <div className={s.turn}>
      <p ref={me} className={s.me}>{t.q}</p>
      {t.reply === "guide" ? <GuideA pid={pid} />
        : t.reply === "dobae" ? <DobaeA q={t.q} grow={g} />
        : t.reply === "both" ? <BothA q={t.q} grow={g} />
        : t.reply === "price" ? <PriceA pid={pid} std={std} />
        : t.reply === "out" ? <Bot who={WHO.out}>{OUT_TEXT.map((x) => <p key={x}>{x}</p>)}</Bot>
        : <Bot who={WHO.none}><p>{NONE_TEXT}</p><Link className="mj-lnk" href="/faq">자주 묻는 질문 보기</Link></Bot>}
    </div>
  );
}

function Bot({ who, busy, children }: { who: string; busy?: string; children: ReactNode }) {
  return (
    <div className={s.bot}>
      <p className={s.who}>{who}{busy ? <span className={s.busy}> · {busy}</span> : null}</p>
      {children}
    </div>
  );
}

function Choices<V extends string>({ label, items, value, locked, onPick }: { label: string; items: { v: V; label: string }[]; value: string | null; locked: boolean; onPick: (v: V) => void }) {
  return (
    <div className={s.choices} role="group" aria-label={label}>
      {items.map((c) => (
        <button key={c.v} type="button" className={s.choice} aria-pressed={value === c.v} aria-disabled={locked || undefined} onClick={() => { if (!locked) onPick(c.v); }}>
          {c.label}
        </button>
      ))}
    </div>
  );
}

function Card({ groups }: { groups: { head?: string; rows: Row[] }[] }) {
  return (
    <div className={s.card}>
      <p className={s.cardT}>{CARD_TITLE}</p>
      {groups.map((gr, i) => (
        <div key={gr.head ?? i}>
          {gr.head ? <p className={s.cardH}>{gr.head}</p> : null}
          <dl className={s.sum}>
            {gr.rows.map((r) => <div key={r.k}><dt>{r.k}</dt><dd className={r.later ? s.later : undefined}>{r.v}</dd></div>)}
          </dl>
        </div>
      ))}
    </div>
  );
}

function GuideA({ pid }: { pid: string | null }) {
  const acts = pid ? GUIDE.acts.map((a) => ({ href: `/projects/${pid}/${a.sub}`, label: a.label })) : GUIDE.actsNoProject;
  return (
    <Bot who={WHO.guide}>
      <p>{GUIDE.lead}</p>
      <ol className={s.steps} role="list">{GUIDE.steps.map((x) => <li key={x}>{x}</li>)}</ol>
      <div className={s.acts}>{acts.map((a) => <Link key={a.href} className="mj-btn mj-btn-sec mj-btn-sm" href={a.href}>{a.label}</Link>)}</div>
    </Bot>
  );
}

function DobaeA({ q, grow }: { q: string; grow: Grow }) {
  const [pick, setPick] = useState<Wall | null>(null);
  const mine = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (pick) grow(mine.current); }, [pick, grow]);
  const w = WALL.find((x) => x.v === pick);
  return (
    <>
      <Bot who={WHO.dobae}>
        <p>{DOBAE.ask}</p>
        <Choices label={DOBAE.ask} items={WALL} value={pick} locked={pick !== null} onPick={setPick} />
      </Bot>
      {w ? (
        <>
          <p ref={mine} className={s.me}>{w.label}</p>
          <Bot who={WHO.dobae}>
            <p>{w.say}</p>
            <Card groups={[{ rows: [
              { k: "공정", v: "도배" },
              { k: "범위", v: roomOf(q) ?? NO_ROOM },
              { k: "기존 벽지", v: w.sum, later: w.v === "unknown" },
              { k: "도배 유형", v: DOBAE.grade },
            ] }]} />
          </Bot>
        </>
      ) : null}
    </>
  );
}

function BothA({ q, grow }: { q: string; grow: Grow }) {
  const [ready, setReady] = useState(false);
  const [ans, setAns] = useState<Partial<Record<BothKey, string>>>({});
  const [len, setLen] = useState("");
  const [err, setErr] = useState("");
  const [sent, setSent] = useState(false);
  const mine = useRef<HTMLParagraphElement>(null);
  const lenIn = useRef<HTMLInputElement>(null);
  const uid = useId();
  const typing = ans.molding === "input";

  useEffect(() => { const t = setTimeout(() => setReady(true), BOTH.waitMs); return () => clearTimeout(t); }, []);
  useEffect(() => { if (ready) grow(); }, [ready, grow]);
  useEffect(() => { if (sent) grow(mine.current); }, [sent, grow]);
  useEffect(() => { if (typing) lenIn.current?.focus(); }, [typing]);

  if (!ready) {
    return (
      <Bot who={WHO.both} busy={BOTH.workingTag}>
        <p className={s.working}>{BOTH.working}</p>
        <ul className={s.prog}>
          {BOTH.progress.map((p) => <li key={p.label}><span className={p.done ? s.dotOn : s.dot} aria-hidden="true" />{p.label}</li>)}
        </ul>
      </Bot>
    );
  }

  const items = BOTH_QS.flatMap((gr) => gr.items);
  const choiceOf = (k: BothKey) => items.find((x) => x.k === k)?.choices.find((c) => c.v === ans[k]);
  const sumOf = (k: BothKey) => (k === "molding" && typing ? `${len.trim()}m` : choiceOf(k)?.sum ?? "");
  function send() {
    const miss = items.filter((x) => !ans[x.k]).map((x) => x.label);
    if (miss.length) { setErr(`${BOTH.missing}: ${miss.join(", ")}`); return; }
    if (typing && !LEN.test(len.trim())) { setErr(BOTH.badLen); lenIn.current?.focus(); return; }
    setErr("");
    setSent(true);
  }
  const row = (k: BothKey): Row => ({ k: BOTH_SUM[k], v: sumOf(k), later: ans[k] === "unknown" });

  return (
    <>
      <Bot who={WHO.both}>
        <p><strong>{BOTH.leadStrong}</strong> {BOTH.lead}</p>
        <div className={s.qcard}>
          {BOTH_QS.map((gr) => (
            <div key={gr.trade} className={s.qgroup}>
              <p className={s.cardT}>{gr.trade}</p>
              {gr.items.map((x) => (
                <div key={x.k} className={s.qrow}>
                  <p className={s.qlab}>{x.label}</p>
                  <Choices label={x.label} items={x.choices} value={ans[x.k] ?? null} locked={sent} onPick={(v) => { setAns((a) => ({ ...a, [x.k]: v })); setErr(""); }} />
                  {x.k === "molding" && typing ? (
                    <div className={s.len}>
                      <label className="mj-sr" htmlFor={`${uid}-len`}>{BOTH.lenLabel}</label>
                      <input
                        id={`${uid}-len`} ref={lenIn} className={`mj-input ${s.lenIn}`} inputMode="decimal" maxLength={6} placeholder="예: 12.5"
                        value={len} readOnly={sent} aria-invalid={err === BOTH.badLen || undefined}
                        onChange={(e) => { setLen(e.target.value); setErr(""); }}
                      />
                      <span aria-hidden="true">m</span>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ))}
        </div>
        {err ? <p className="mj-error" role="alert">{err}</p> : null}
        <div>
          <button type="button" className="mj-btn mj-btn-pri mj-btn-sm" aria-disabled={sent || undefined} onClick={() => { if (!sent) send(); }}>
            {sent ? BOTH.sent : BOTH.send}
          </button>
        </div>
      </Bot>
      {sent ? (
        <>
          <p ref={mine} className={s.me}>
            {items.map((x) => `${x.short} ${x.k === "molding" && typing ? `${len.trim()}m` : choiceOf(x.k)?.label ?? ""}`).join(" · ")}
          </p>
          <Bot who={WHO.both}>
            <p>{BOTH.done}{items.some((x) => ans[x.k] === "unknown") ? ` ${BOTH.doneLater}` : ""}</p>
            <Card groups={[
              { rows: [{ k: "순서", v: BOTH.order }, { k: "범위", v: roomOf(q) ?? NO_ROOM }] },
              { head: "목공", rows: [row("molding"), row("base")] },
              { head: "도배", rows: [row("wall"), row("grade")] },
            ]} />
          </Bot>
        </>
      ) : null}
    </>
  );
}

function PriceA({ pid, std }: { pid: string | null; std: Std | null | undefined }) {
  if (std === undefined) return <Bot who={WHO.price}><p className="mj-small">{PRICE.loading}</p></Bot>;
  const line = std?.trades.flatMap((t) => t.lines).find((l) => l.key === PRICE.lineKey);
  if (!std || !line || line.qty == null || line.unit_price == null || line.amount == null) {
    const note = !std ? (pid ? null : PRICE.noProject) : !line ? PRICE.noLine : null;
    return (
      <Bot who={WHO.price}>
        <p>{PRICE.say}</p>
        {note ? <p className="mj-small">{note}</p> : null}
        <div className={s.acts}>
          <Link className="mj-btn mj-btn-sec mj-btn-sm" href={pid ? `/projects/${pid}/standard` : "/my"}>{pid ? "표준견적서 보기" : "내 공사에서 표준견적서 보기"}</Link>
        </div>
      </Bot>
    );
  }
  const qty = `${decText(line.qty)}${line.unit}`;
  return (
    <Bot who={WHO.price}>
      <p>{PRICE.say}</p>
      <ul className={s.calc} role="list">
        <li><span className={s.box}>{PRICE.calcTag}</span><span className="mj-num">{decText(std.pyeong)}{PRICE.estimated} {qty}</span></li>
        <li><span className={s.box}>{PRICE.calcTag}</span><span className="mj-num">{qty} × {wonFull(line.unit_price)} = <strong>{wonFull(line.amount)}</strong></span></li>
      </ul>
      <div className={s.basis}>
        <p className="mj-small">{PRICE.basis} {line.source}</p>
        <Link className="mj-lnk" href={PRICE.basisLink}>원문 보기</Link>
      </div>
    </Bot>
  );
}
