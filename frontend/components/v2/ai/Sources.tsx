"use client";
// AI 답 아래 '근거 n개' (v10 ragSourcesEl + v7 덧씌움: 인용 검증 · 출처 종류 표시)
import { rag, RAG7, ragDoc, ragRefs, verifyCites } from "./rag";

export function ragSources(text: string) {
  if (!rag.index) return null;
  const v = verifyCites(text);
  const refs = ragRefs(v.text).map((k) => ragDoc(k)).filter((x) => !!x);
  if (!refs.length) return v.dropped ? <p className="muted src-drop">{`근거와 맞지 않는 표시 ${v.dropped}개를 뺐어요`}</p> : null;
  return (
    <details className="srcs">
      <summary>
        {`근거 ${refs.length}개`}
        {v.dropped ? ` · 맞지 않는 표시 ${v.dropped}개 뺌` : null}
      </summary>
      <ol>
        {refs.map((x) => (
          <li key={x.c.k}>
            <span className={"src-type t-" + ((RAG7.tier[x.d.kind || ""] ?? 0.5) >= 0.8 ? "hi" : "lo")}>{RAG7.type_ko[x.d.kind || ""] || "기타"}</span>
            <b>{x.c.k}</b>{" "}
            {x.d.url ? (
              <a href={x.d.url} target="_blank" rel="noopener">
                {x.d.title || x.d.pub || "출처"}
              </a>
            ) : (
              x.d.title || ""
            )}
            {x.d.pub ? <span className="muted">{` · ${x.d.pub}${x.d.date ? " · " + x.d.date : ""}`}</span> : null}
            {x.c.sec ? <span className="muted">{` · ${x.c.sec}`}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}
