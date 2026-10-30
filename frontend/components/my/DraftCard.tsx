"use client";
// '쓰던 요청서가 있어요' 카드. 홈과 내 프로젝트에서 보인다. 질문 흐름이 답을 저장하면 바로 따라 바뀐다.
import { useEffect, useState } from "react";
import { QuoteButton } from "@/components/start/QuoteDialog";
import { DRAFT_EVENT, clearPhotoMemo, draftLine, readDraft, writeDraft } from "@/components/start/draft";

export function DraftCard() {
  const [d, setD] = useState<ReturnType<typeof readDraft>>(null);
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    const up = () => setD(readDraft());
    up();
    window.addEventListener(DRAFT_EVENT, up);
    window.addEventListener("storage", up);
    return () => { window.removeEventListener(DRAFT_EVENT, up); window.removeEventListener("storage", up); };
  }, []);
  if (!d) return null;
  const rows = draftLine(d.a);
  return (
    <section className="mj-panel mj-draft" aria-labelledby="draft-h">
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <h2 id="draft-h" className="mj-h3">쓰던 요청서가 있어요</h2>
        <p className="mj-small">멈춘 질문부터 이어서 쓸 수 있어요.</p>
      </div>
      {rows.length ? (
        <dl className="mj-draft-kv">
          {rows.map((r) => <div key={r.label}><dt>{r.label}</dt><dd>{r.value}</dd></div>)}
        </dl>
      ) : null}
      {asking ? (
        <div className="mj-btn-row" role="group" aria-label="쓰던 요청서 지우기 확인">
          <span className="mj-small" style={{ alignSelf: "center" }}>고른 답을 모두 지울까요?</span>
          <button type="button" className="mj-btn mj-btn-danger mj-btn-sm" onClick={() => { clearPhotoMemo(); writeDraft(null); }}>지울게요</button>
          <button type="button" className="mj-btn mj-btn-sec mj-btn-sm" onClick={() => setAsking(false)}>그대로 둘게요</button>
        </div>
      ) : (
        <div className="mj-btn-row">
          <QuoteButton label="이어서 쓰기" className="mj-btn mj-btn-pri mj-btn-sm" />
          <button type="button" className="mj-btn mj-btn-ghost mj-btn-sm" onClick={() => setAsking(true)}>지우기</button>
        </div>
      )}
    </section>
  );
}
