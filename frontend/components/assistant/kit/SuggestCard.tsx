"use client";
// 제안 카드: ✦ 제안 · 한 줄 제안 · 근거 한 줄(코드 사실) · [해 볼게요] [괜찮아요]. 한 말에 하나예요(턴 끝 제안이 여럿이면 둘째부터는 칩, Message).
// [해 볼게요]는 채팅으로 이어지고(턴), 실행이 필요한 일은 다음 승인 카드가 맡아요.
// 먼저 말 건 제안(nudge_id 있음)이면 [해 볼게요]는 열기(open), [괜찮아요]는 닫기(dismiss, 같은 일 3일 쉬기)를 서버에 알려요.
import { useState } from "react";
import type { SuggestOut } from "@/lib/api/assistant";
import { I } from "./icons";
import k from "./kit.module.css";

export function SuggestCard({ suggest, disabled, onAccept, onDismiss }: { suggest: SuggestOut; disabled?: boolean; onAccept: (say: string) => void; onDismiss?: () => void }) {
  const [state, setState] = useState<"open" | "yes" | "no">("open");
  if (state === "no") return null;
  return (
    <section className={k.suggest} aria-label="비서 제안">
      <I n="sparkle" />
      <div>
        <b>{suggest.text}</b>
        <p>{suggest.why}</p>
      </div>
      {state === "open" ? (
        <div className={k.acts}>
          <button type="button" className={`${k.btn} ${k.sm} ${k.pri}`} disabled={disabled} onClick={() => { setState("yes"); onAccept(suggest.say); }}>해 볼게요</button>
          <button type="button" className={`${k.text} ${k.gray}`} onClick={() => { setState("no"); onDismiss?.(); }}>괜찮아요</button>
        </div>
      ) : null}
    </section>
  );
}
