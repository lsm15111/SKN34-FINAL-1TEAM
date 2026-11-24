"use client";
// 업체 확정 확인(C34 · W11): 질문 한 문장 + 무엇이 고정되는지 + [닫기 | ○○으로 확정](CF-26).
// POST /projects/{id}/quotes/{visit_id}/confirm {seen_ver} → 다른 업체 견적서 닫힘 · 대화 읽기만(서버) → 공사 날짜 화면으로.
// 고객이 누른 요청으로만 확정해요. 유효기간이 지났으면 서버가 409 expired로 막고 그 말을 그 자리에 보여요.
// 409(업체가 견적서를 다시 올림 quote_changed · 지남 · 이미 확정)면 말을 남긴 채 화면을 다시 읽어 새 금액 · 판(seen_ver)으로 바꿔요.
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { ApiError, errorText } from "@/lib/backend/client";
import { euro } from "@/lib/format";
import { send } from "@/lib/mock/v3b/client";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { Btns } from "@/components/project/Kit";
import s from "./card.module.css";

export function ConfirmCard({ projectId, visitId, vendorName, seenVer, backHref, children }: {
  projectId: string;
  visitId: string;
  vendorName: string;
  seenVer: number;
  backHref: string;
  /** 확정 금액 · 견적서 · 공사 기간 줄과 안내 글 */
  children: ReactNode;
}) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const label = `${euro(vendorName)} 확정`;

  async function confirm() {
    setBusy(true);
    setErr(null);
    try {
      await send("POST", `/projects/${encodeURIComponent(projectId)}/quotes/${encodeURIComponent(visitId)}/confirm`, { seen_ver: seenVer }, { step: "confirmed" });
      toast.show(`${euro(vendorName)} 확정했어요`);
      router.push(`/projects/${encodeURIComponent(projectId)}/schedule`);
      router.refresh();
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
      if (e instanceof ApiError && e.status === 409) router.refresh();
    }
  }

  return (
    <section className={s.card} aria-labelledby="cf-t">
      <h2 id="cf-t" className={s.title}>{euro(vendorName)} 확정할까요?</h2>
      {children}
      {err ? <p className={s.err} role="alert"><Icon name="error" size={16} />{err}</p> : null}
      <Btns>
        <Button variant="secondary" size="lg" href={backHref} disabled={busy}>닫기</Button>
        <Button size="lg" onClick={confirm} busy={busy}>{busy ? "보내는 중" : label}</Button>
      </Btns>
    </section>
  );
}
