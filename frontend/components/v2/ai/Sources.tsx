"use client";
// AI 답 아래 '근거 n개'. 근거는 서버가 인용 검사(이번 턴에 보여 준 자료 · 문장과 맞는 것)를 마치고 보낸다
import type { AskOut } from "./llm";

export function ragSources(out: AskOut | null) {
  const refs = out?.sources || [];
  const dropped = out?.cites_dropped || 0;
  if (!refs.length) return dropped ? <p className="muted src-drop">{`근거와 맞지 않는 표시 ${dropped}개를 뺐어요`}</p> : null;
  return (
    <details className="srcs">
      <summary>
        {`근거 ${refs.length}개`}
        {dropped ? ` · 맞지 않는 표시 ${dropped}개 뺌` : null}
      </summary>
      <ol>
        {refs.map((x) => (
          <li key={x.ref}>
            <span className={"src-type t-" + (x.official ? "hi" : "lo")}>{x.source_type || "기타"}</span>
            <b>{x.ref}</b>{" "}
            {x.url ? (
              <a href={x.url} target="_blank" rel="noopener">
                {x.title || x.publisher || "출처"}
              </a>
            ) : (
              x.title || ""
            )}
            {x.publisher ? <span className="muted">{` · ${x.publisher}${x.date ? " · " + x.date : ""}`}</span> : null}
            {x.section ? <span className="muted">{` · ${x.section}`}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}
