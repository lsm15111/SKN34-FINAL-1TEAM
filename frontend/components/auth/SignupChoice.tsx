"use client";
// 가입 고르기(C04): 이메일로 가입 · 카카오 준비 중(눌러도 아무 일 없음) · 이미 회원이면 로그인.
// 기기에 둔 답이 있으면 '넣은 답이 그대로 이어져요'와 그 요약을 보여요(N1 A).
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { summaryLine } from "@/lib/guest/info";
import { draftOf, readGuest } from "@/lib/guest/store";
import { withNext } from "./next";
import s from "./card.module.css";

export function SignupChoice({ next }: { next?: string }) {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    const g = readGuest();
    setLine(g ? summaryLine(draftOf(g)) : null);
  }, []);
  return (
    <div className={s.card}>
      <section className={s.group} aria-labelledby="su-h">
        <h1 id="su-h" className={s.h}>가입하면 업체 가견적을<br />비교할 수 있어요</h1>
        <ul className={s.ticks}>
          {["견적서 저장", "가견적 비교", "일정 알림", "AI 채팅"].map((t) => <li key={t}><Icon name="check" size={16} strokeWidth={2.6} />{t}</li>)}
        </ul>
      </section>
      {line ? <p className={s.carry}><b>넣은 답이 그대로 이어져요</b><span>{line}</span></p> : null}
      <div className={s.btns}>
        <Button size="lg" block href={withNext("/signup?step=email", next)}>이메일로 가입</Button>
        <Button size="lg" block variant="kakao">카카오로 가입 <Badge tone="mute">준비 중</Badge></Button>
      </div>
      <p className={s.note}>이미 회원이에요 · <Button variant="text" href={withNext("/login", next)}>로그인</Button></p>
    </div>
  );
}
