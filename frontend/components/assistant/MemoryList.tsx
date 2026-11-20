"use client";
// 내 정보 '비서가 기억한 것'(고객): 비서가 내 말에서만 뽑은 것(되는 시간 · 자재 등)과 근거로 남긴 내 말 인용 · 지우기.
// GET /assistant/memory · DELETE /assistant/memory/{id}(다른 담당이 같은 때 만들어요). API가 아직 없으면(404) 이 칸을 그리지 않아요.
// 건강 · 연락처 · 금액은 서버가 기억하지 않아요. 지우면 비서가 다음 대화부터 그 말을 쓰지 않아요.
import { useEffect, useState } from "react";
import { forgetMemory, getMemory, MEMORY_LABEL, type MemoryKey, type MemoryOut } from "@/lib/api/assistant";
import { errorText } from "@/lib/backend/client";
import m from "./memory.module.css";

export function MemoryList() {
  const [list, setList] = useState<MemoryOut[] | null | undefined>(undefined);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getMemory().then((x) => { if (alive) setList(x); }).catch(() => { if (alive) setList(null); });
    return () => { alive = false; };
  }, []);

  async function forget(id: string) {
    setBusy(id);
    setErr(null);
    try {
      await forgetMemory(id);
      setList((cur) => (cur ? cur.filter((x) => x.id !== id) : cur));
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (!list) return null;
  return (
    <section className={m.box} aria-labelledby="memory-t">
      <h2 id="memory-t" className={m.title}>비서가 기억한 것</h2>
      {list.length ? (
        <ul className={m.list}>
          {list.map((x) => (
            <li key={x.id}>
              <div className={m.body}>
                <span className={m.key}>{MEMORY_LABEL[x.key as MemoryKey] ?? "기억"}</span>
                <b>{x.value}</b>
                {x.evidence_quote ? <blockquote className={m.quote}><span>내가 한 말</span>{x.evidence_quote}</blockquote> : null}
              </div>
              <button type="button" className={m.del} disabled={busy === x.id} aria-busy={busy === x.id || undefined} aria-label={`'${x.value}' 지우기`} onClick={() => { void forget(x.id); }}>
                지우기
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={m.empty}>아직 기억한 것이 없어요. 내가 말한 것만 기억해요</p>
      )}
      {err ? <p className={m.err} role="alert">{err}</p> : null}
    </section>
  );
}
