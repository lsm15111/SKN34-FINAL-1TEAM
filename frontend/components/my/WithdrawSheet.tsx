"use client";
// 회원 탈퇴(C53): 아래 시트(웹은 가운데 창 모양)로 지워지는 것 · 남는 것을 보이고 비밀번호를 다시 받아 POST /me/withdraw.
// 진행 중인 공사가 있어도 막지 않아요(개인정보 보호법 제38조④: 가입보다 어렵게 하지 않음). 탈퇴하면 첫 화면으로 가요.
import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";
import { errorText } from "@/lib/backend/client";
import { send } from "@/lib/mock/v3b/client";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Sheet } from "@/components/ui/Sheet";
import { writeDraft } from "@/components/start/draft";
import { Btns, Row, Rows } from "@/components/project/Kit";
import s from "./account2.module.css";

/** ongoing: 진행 중인 공사 줄(서버가 만든 이름 · 지금 할 일) */
export function WithdrawSheet({ vendor, ongoing = [] }: { vendor: boolean; ongoing?: string[] }) {
  const router = useRouter();
  const formId = useId();
  const pw = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  function close() { if (!busy) { setOpen(false); setErr(""); } }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const password = pw.current?.value ?? "";
    if (!password) { setErr("비밀번호를 적어 주세요."); pw.current?.focus(); return; }
    setErr("");
    setBusy(true);
    try {
      await send("POST", "/me/withdraw", { password });
      writeDraft(null); // 이 브라우저에 남은 쓰던 기본 정보도 지워요
      router.push("/?bye=1"); // 홈 맨 위에 '탈퇴했어요'를 보여요(QA r6 L8)
      router.refresh();
    } catch (x) {
      setErr(errorText(x));
      setBusy(false);
      pw.current?.focus();
    }
  }

  return (
    <>
      <Button variant="text" gray onClick={() => setOpen(true)} aria-haspopup="dialog">탈퇴</Button>
      <Sheet
        open={open}
        onClose={close}
        title="탈퇴할까요?"
        dismissible={!busy}
        hideClose
        actions={
          <Btns>
            <Button variant="secondary" size="lg" onClick={close} disabled={busy}>닫기</Button>
            <Button variant="danger" size="lg" type="submit" form={formId} busy={busy}>{busy ? "지우는 중" : "탈퇴"}</Button>
          </Btns>
        }
      >
        <Rows>
          {vendor ? (
            <>
              <Row label="업체 정보" sub="사업자등록증 · 업체 정보 · 로그인 기록을 지워요" />
              <Row label="진행 중인 공사" sub="고객과 주고받은 채팅 · 견적서는 그 고객 쪽에 남아요" />
            </>
          ) : (
            <>
              {ongoing.map((line) => <Row key={line} label="진행 중인 공사" sub={line} />)}
              <Row label="채팅 · 알림 · 견적서" sub="탈퇴하면 더 볼 수 없어요" />
              <Row label="채팅으로 알려 준 동 · 호수 · 연락처" sub="이미 보낸 메시지는 그 업체 채팅에 남아요" />
            </>
          )}
        </Rows>
        <p className={s.warn}>탈퇴하면 되돌릴 수 없어요.</p>
        <form id={formId} noValidate onSubmit={submit} aria-label="탈퇴 확인">
          <Field ref={pw} label="비밀번호" type="password" autoComplete="current-password" error={err || undefined} />
        </form>
      </Sheet>
    </>
  );
}
