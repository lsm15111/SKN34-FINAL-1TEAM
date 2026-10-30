"use client";
// 실측 업체 선택 · 실측 요청. 공정마다 한 번에 1곳만.
import { useRef, useState } from "react";
import Link from "next/link";

type Opt = { id: string; name: string; total: string };

export function MeasurePick({ projectId, trade, tradeLabel, options, current }: { projectId: string; trade: string; tradeLabel: string; options: Opt[]; current: { name: string; when: string; done: boolean } | null }) {
  const [open, setOpen] = useState(!current);
  const [pick, setPick] = useState<string>("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [dong, setDong] = useState("");
  const [ho, setHo] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const errRef = useRef<HTMLParagraphElement>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const err = !pick ? "실측 받을 업체를 1곳 골라 주세요." : !date ? "희망 날짜를 골라 주세요." : !time ? "시간대를 골라 주세요." : !dong || !ho ? "동과 호수를 적어 주세요." : !agree ? "동 · 호수 제공에 동의해 주세요." : null;
    setError(err);
    if (err) { setTimeout(() => errRef.current?.focus(), 0); return; }
    setSent(options.find((o) => o.id === pick)?.name ?? "");
  }

  return (
    <section className="mj-panel" aria-labelledby="mp-h" style={{ borderColor: "var(--accent)", borderWidth: 2 }}>
      <h2 id="mp-h" className="mj-h2">{tradeLabel} 실측 요청</h2>
      {current ? (
        <p className="mj-notice" role="status"><span><b>{current.name}</b>에 실측을 요청했어요 · {current.when} {current.done ? "· 실측이 끝났어요" : ""} · <Link href={`/projects/${projectId}/measure?trade=${trade}`}>실측 견적 보기</Link></span></p>
      ) : null}
      {sent ? (
        <p className="mj-notice" role="status"><span><b>{sent}</b>에 실측을 요청했어요. 업체가 시간을 확정하면 알려 드려요.</span></p>
      ) : !open ? (
        <button type="button" className="mj-btn mj-btn-sec" style={{ alignSelf: "flex-start" }} onClick={() => setOpen(true)} aria-expanded={open} aria-controls="mp-form">다른 업체에 다시 요청하기</button>
      ) : (
        <form id="mp-form" onSubmit={submit} noValidate style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {error ? <p ref={errRef} tabIndex={-1} className="mj-error" role="alert">{error}</p> : null}
          <fieldset className="mj-fieldset">
            <legend className="mj-label">실측 받을 업체 (1곳)</legend>
            <div className="mj-choices">
              {options.map((o) => (
                <label key={o.id} className="mj-choice"><input type="radio" name={`mp-${trade}`} checked={pick === o.id} onChange={() => setPick(o.id)} /><span className="mj-choice-main"><span className="mj-choice-title">{o.name}</span><span className="mj-choice-desc mj-num">가견적 {o.total}</span></span></label>
              ))}
            </div>
          </fieldset>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
            <div className="mj-field" style={{ flex: "1 1 200px" }}>
              <label className="mj-label" htmlFor={`md-${trade}`}>희망 날짜</label>
              <input id={`md-${trade}`} type="date" min="2026-10-30" className="mj-input" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <fieldset className="mj-fieldset" style={{ flex: "2 1 300px" }}>
              <legend className="mj-label">시간대</legend>
              <div className="mj-choices" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(110px, 100%), 1fr))" }}>
                {["오전", "오후", "상관없어요"].map((t) => <label key={t} className="mj-choice" style={{ minHeight: 52 }}><input type="radio" name={`mt-${trade}`} checked={time === t} onChange={() => setTime(t)} /><span className="mj-choice-title">{t}</span></label>)}
              </div>
            </fieldset>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
            <div className="mj-field" style={{ width: 140 }}><label className="mj-label" htmlFor={`dong-${trade}`}>동</label><input id={`dong-${trade}`} inputMode="numeric" className="mj-input mj-num" value={dong} onChange={(e) => setDong(e.target.value.replace(/\D/g, ""))} /></div>
            <div className="mj-field" style={{ width: 140 }}><label className="mj-label" htmlFor={`ho-${trade}`}>호</label><input id={`ho-${trade}`} inputMode="numeric" className="mj-input mj-num" value={ho} onChange={(e) => setHo(e.target.value.replace(/\D/g, ""))} /></div>
          </div>
          <label className="mj-choice"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /><span className="mj-choice-main"><span className="mj-choice-title">고른 업체에 동 · 호수를 보여 주는 데 동의해요 (필수)</span><span className="mj-choice-desc">실측 시간이 확정된 그 업체에만 보여요</span></span></label>
          <div className="mj-btn-row">
            <button type="submit" className="mj-btn mj-btn-pri">실측 요청 보내기</button>
            {current ? <button type="button" className="mj-btn mj-btn-sec" onClick={() => setOpen(false)}>닫기</button> : null}
          </div>
        </form>
      )}
    </section>
  );
}
