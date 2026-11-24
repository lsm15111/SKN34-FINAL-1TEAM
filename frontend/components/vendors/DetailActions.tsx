"use client";
// 업체 자세히 아래 단추(C11 · D07): [담음 ✓ | 담기] [실측 일정 잡기]. 담기는 업체 보기와 같은 POST · DELETE …/shortlist예요.
// 담음은 눌린 단추(aria-pressed)로 읽혀요(CF-76). 가견적이 없거나 고른 벽지를 안 하거나 3곳을 다 담았으면 '담을 수 없어요'.
// 담을 때 지금 보는 벽지(grade)를 같이 보내요: 그 벽지의 가견적으로 요청해요(C11 · ShortlistIn.grade).
// 벽지를 바꾸는 중(GradeToggle이 새 가견적을 받기 전)에는 [담기]가 기다려요: grade가 아직 옛 벽지예요.
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { ApiError, call, errorText } from "@/lib/backend/client";
import { eulReul } from "@/lib/format";
import { useGradeSwitching } from "./GradeToggle";

const MAX = 3;

export function DetailActions({ projectId, vendorId, name, grade, canPick, shortlisted, count, mock }: {
  projectId: string;
  vendorId: string;
  name: string;
  /** 지금 보는 벽지 */
  grade: "basic" | "economy";
  /** 가견적이 있고 고른 벽지를 하는 업체(state ok) */
  canPick: boolean;
  shortlisted: boolean;
  /** 이 공사에 담은 업체 수 */
  count: number;
  mock: boolean;
}) {
  const router = useRouter();
  const toast = useToast();
  const [on, setOn] = useState(shortlisted);
  const [n, setN] = useState(count);
  const [busy, setBusy] = useState(false);
  const switching = useGradeSwitching();
  const pid = encodeURIComponent(projectId);

  async function toggle() {
    if (busy || (!on && switching)) return;
    setBusy(true);
    try {
      if (!mock) {
        if (on) await call("DELETE", `/projects/${pid}/shortlist/${encodeURIComponent(vendorId)}?trade=dobae`);
        else await call("POST", `/projects/${pid}/shortlist`, { trade: "dobae", vendor_id: vendorId, grade });
      }
      setOn(!on);
      setN((x) => Math.max(0, x + (on ? -1 : 1)));
      toast.show(`${eulReul(name)} ${on ? "뺐어요" : "담았어요"}`);
      if (!mock) router.refresh();
    } catch (e) {
      // 다른 기기에서 먼저 담았어요: 담음 · 담은 수를 같이 맞추고 서버 값으로 다시 읽어요(실측 일정 잡기가 켜지게)
      if (e instanceof ApiError && e.code === "already" && !on) {
        setOn(true);
        setN((x) => x + 1);
        if (!mock) router.refresh();
      }
      toast.show(errorText(e), { tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  const blocked = !on && (!canPick || n >= MAX);
  return (
    <>
      {blocked ? (
        <Button variant="weak" size="lg" disabled>담을 수 없어요</Button>
      ) : (
        <Button variant="weak" size="lg" aria-pressed={on} busy={busy || (!on && switching)} onClick={() => void toggle()}>
          {on ? <>담음 <Icon name="check" size={18} strokeWidth={2.6} /></> : "담기"}
        </Button>
      )}
      <Button size="lg" href={`/projects/${pid}/visits/new`} disabled={n === 0}>실측 일정 잡기</Button>
    </>
  );
}
