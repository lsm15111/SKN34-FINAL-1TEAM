"use client";
// 외부 업체 수신거부: 링크를 연 사람이 버튼을 눌러야 거부한다 (링크 미리 보기만으로 바뀌지 않게).
import { useRef, useState } from "react";
import { call, errorText, type Schemas } from "@/lib/backend/client";

export function OptOutForm({ token }: { token: string }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [err, setErr] = useState("");
  const doneRef = useRef<HTMLHeadingElement>(null);

  async function go() {
    setBusy(true);
    setErr("");
    try {
      const r = await call<Schemas["OptOutOut"]>("POST", "/directory/opt-out", { token });
      setDone(r.message);
      setTimeout(() => doneRef.current?.focus(), 0);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <section className="mj-panel" aria-labelledby="oo-done-h">
        <h2 id="oo-done-h" ref={doneRef} tabIndex={-1} className="mj-h2">연락을 받지 않게 했어요</h2>
        <p>{done}</p>
      </section>
    );
  }
  return (
    <section className="mj-panel" aria-labelledby="oo-h">
      <h2 id="oo-h" className="mj-h3">이 업체에 더 연락하지 않을까요?</h2>
      <p className="mj-sub">버튼을 누르면 믿집은 이 업체에 가견적 요청을 더 전하지 않고, 고객이 보는 업체 목록에서도 빼요. 동의해 주신 연락처도 지워요.</p>
      <div className="mj-btn-row">
        <button type="button" className="mj-btn mj-btn-pri" disabled={busy} onClick={go}>{busy ? "처리하는 중…" : "연락 받지 않기"}</button>
      </div>
      {err ? <p className="mj-error" role="alert">{err}</p> : null}
    </section>
  );
}
