"use client";
// 07 이웃 안내문 초안: 코드 틀(LLM 없음)이고 공사 날짜는 공정표 값이에요. 동 · 호수 · 이름 · 연락처는 빈칸(○○)이고 믿집은 보내지 않아요.
// 이웃에게 붙이는 글이라 본문만 '-합니다'체예요(data.style_exempt). 화면 말은 '-해요'체예요.
// [복사하기]는 누른 그 자리에서 navigator.clipboard.writeText를 불러요. 막히면 글을 골라 두고 직접 복사하게 알려요.
import { useRef, useState } from "react";
import { SourceTag } from "../kit/StatusTag";
import { I } from "../kit/icons";
import k from "../kit/kit.module.css";
import s from "./NoticeCard.module.css";
import type { CardProps } from "./types";

type Copy = "idle" | "done" | "picked";

export function NoticeCard({ card }: CardProps<"notice">) {
  const d = card.data;
  const box = useRef<HTMLTextAreaElement>(null);
  const [copy, setCopy] = useState<Copy>("idle");
  const pick = () => {
    box.current?.focus();
    box.current?.select();
    setCopy("picked");
  };
  const onCopy = () => {
    const clip = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (!clip?.writeText) {
      pick();
      return;
    }
    clip.writeText(d.text).then(() => setCopy("done"), pick);
  };
  const lines = d.text.split("\n").length;
  return (
    <section className={k.card} aria-labelledby={`${card.card_id}-t`}>
      <div className={k.top}>
        <h3 id={`${card.card_id}-t`}>{d.title}</h3>
        <SourceTag src="guide" />
      </div>
      <textarea ref={box} className={s.text} readOnly value={d.text} rows={Math.min(Math.max(lines, 6), 14)} aria-label="이웃 안내문 초안" />
      {d.blanks.length ? (
        <p className={s.blanks}>
          <span>직접 채울 칸</span>
          {d.blanks.join(" · ")}
        </p>
      ) : null}
      <p className={k.muted}>{d.note}</p>
      <div className={s.foot}>
        <button type="button" className={`${k.btn} ${k.sm}`} onClick={onCopy}>
          <I n="doc" />
          복사하기
        </button>
        <span className={s.said} role="status" aria-live="polite">
          {copy === "done" ? "복사했어요" : copy === "picked" ? "글을 골라 뒀어요. 길게 누르거나 복사 키로 복사해 주세요." : ""}
        </span>
      </div>
    </section>
  );
}
