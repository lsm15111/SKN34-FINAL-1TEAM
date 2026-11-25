"use client";
// 가입 · 로그인 카드(C59 · D13, W9 A)의 v5 사본: dev components/auth/JoinDialog와 같고, 가입 · 로그인 주소에 돌아올 곳(next=)을 붙여요.
// next가 /v5로 시작하면 가입 · 로그인 뒤 넣은 답이 옮겨진 공사도 v5 화면(/v5/projects/{id}/vendors)으로 가요(components/auth/after.ts).
import { withNext } from "@/components/auth/next";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import s from "@/components/auth/join.module.css";

export function JoinDialog({ open, onClose, next = "/v5/start" }: { open: boolean; onClose: () => void; next?: string }) {
  return (
    <Dialog open={open} onClose={onClose} title="가입하고 이어서 봐요">
      <p className={s.sub}>업체 가견적 · 예상 공정표는 가입하면 열려요. 넣은 답과 표준견적서가 그대로 이어져요</p>
      <div className={s.btns}>
        <Button size="lg" block href={withNext("/signup?step=email", next)}>이메일로 가입</Button>
        <Button size="lg" block variant="kakao">카카오로 가입 <Badge tone="mute">준비 중</Badge></Button>
      </div>
      <p className={s.note}>이미 회원이에요 · <Button variant="text" href={withNext("/login", next)}>로그인</Button></p>
      <Button variant="text" gray className={s.later} onClick={onClose}>나중에 할게요</Button>
    </Dialog>
  );
}
