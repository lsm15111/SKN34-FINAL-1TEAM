"use client";
// 공사 끝 확인(C38 · D24 A): [고칠 곳 있어요] [공사 끝 확인]. POST /projects/{id}/deals/{did}/check {result}.
// 끝 확인이면 리뷰 쓰기가 열리고, 고칠 곳이면 채팅으로 이어져 업체가 다시 '공사 끝냈어요'를 보내요.
import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorText } from "@/lib/backend/client";
import { send } from "@/lib/mock/v3b/client";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import s from "@/components/schedule/v3.module.css";

export function DoneActions({ projectId, dealId, threadId }: { projectId: string; dealId: string; threadId: string | null }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<"done" | "fixing" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pid = encodeURIComponent(projectId);

  async function check(result: "done" | "fixing") {
    setBusy(result);
    setErr(null);
    try {
      await send("POST", `/projects/${pid}/deals/${encodeURIComponent(dealId)}/check`, { result }, result === "done" ? { step: "review" } : undefined);
      if (result === "done") {
        toast.show("공사가 끝났어요");
        router.push(`/v5/projects/${pid}/review`);
      } else {
        router.push(threadId ? `/chat/${encodeURIComponent(threadId)}` : "/chat");
      }
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
      setBusy(null);
    }
  }

  return (
    <BottomBar note={err ? <span className={s.err} role="alert">{err}</span> : undefined}>
      <Button variant="secondary" size="lg" onClick={() => check("fixing")} busy={busy === "fixing"} disabled={busy === "done"}>{busy === "fixing" ? "보내는 중" : "고칠 곳 있어요"}</Button>
      <Button size="lg" onClick={() => check("done")} busy={busy === "done"} disabled={busy === "fixing"}>{busy === "done" ? "보내는 중" : "공사 끝 확인"}</Button>
    </BottomBar>
  );
}
