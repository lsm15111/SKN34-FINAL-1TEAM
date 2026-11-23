"use client";
// '확인할 것'을 한 번에 복사해 업체 채팅에 붙여요. 클립보드가 막히면 글을 골라 둬요.
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import s from "./guide.module.css";

export function CopyChecks({ lines, target }: { lines: string[]; target: string }) {
  const [msg, setMsg] = useState("");
  async function copy() {
    const text = lines.map((l) => `- ${l}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setMsg("복사했어요");
    } catch {
      const el = document.getElementById(target);
      if (el) {
        const r = document.createRange();
        r.selectNodeContents(el);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(r);
      }
      setMsg("글을 골라 뒀어요. 복사해 주세요");
    }
  }
  return (
    <div className={s.copyRow}>
      <Button variant="secondary" size="sm" onClick={copy}>업체에 물을 말 복사</Button>
      <span className={s.mute} role="status">{msg}</span>
    </div>
  );
}
