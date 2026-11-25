"use client";
// 홈 '인테리어 받기'(2026-11-23 사용자, 앞은 CF-09 '표준견적서 받기'). 진행 중인 공사가 있는 고객은 먼저 이어 하기 / 새 집을 물어요(C41, B2b components/my/ResumeDialog).
// 로그인 뒤 기기에 둔 답이 있고 진행 중 공사도 있으면 /?resume=1로 와서 창이 바로 열려요(dev-03). 새 집이면 기본 정보에 그 답이 그대로 들어가요.
import { useState } from "react";
import { ResumeDialog } from "@/components/v5/my/ResumeDialog";
import { Button } from "@/components/ui/Button";
import type { Ongoing } from "@/lib/v5/guest/api";

/** '상계동 아파트 도배' → '상계동 도배'(단추 '상계동 도배 이어 하기') */
const shortName = (name: string) => name.replace(" 아파트 ", " ");

export function StartCta({ ongoing, autoOpen = false, className }: { ongoing: Ongoing | null; autoOpen?: boolean; className?: string }) {
  const [open, setOpen] = useState(autoOpen && !!ongoing);
  if (!ongoing) return <Button size="lg" href="/v5/start" className={className}>인테리어 받기</Button>;
  return (
    <>
      <Button size="lg" className={className} onClick={() => setOpen(true)} aria-haspopup="dialog">인테리어 받기</Button>
      <ResumeDialog
        open={open}
        onClose={() => setOpen(false)}
        newHref="/v5/start"
        project={{ name: ongoing.name, short: shortName(ongoing.name), stepLabel: ongoing.step, href: ongoing.href ?? `/v5/projects/${encodeURIComponent(ongoing.id)}` }}
      />
    </>
  );
}
