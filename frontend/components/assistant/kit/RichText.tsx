// AI 답 글 그리기: 굵게 · 줄바꿈 · '- ' 목록만 화면 꼴로(lib/richText). HTML을 넣지 않고 글 조각을 React 요소로만 그려요.
import { Fragment } from "react";
import { blocks, type Line } from "@/lib/richText";
import r from "./RichText.module.css";

function Spans({ line }: { line: Line }) {
  return <>{line.map((x, i) => (x.bold ? <strong key={i}>{x.text}</strong> : <Fragment key={i}>{x.text}</Fragment>))}</>;
}

export function RichText({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className ? `${r.rich} ${className}` : r.rich}>
      {blocks(text).map((b, i) => (b.t === "list" ? (
        <ul key={i}>{b.items.map((it, j) => <li key={j}><Spans line={it} /></li>)}</ul>
      ) : (
        <p key={i}>{b.lines.map((l, j) => <Fragment key={j}>{j ? <br /> : null}<Spans line={l} /></Fragment>)}</p>
      )))}
    </div>
  );
}
