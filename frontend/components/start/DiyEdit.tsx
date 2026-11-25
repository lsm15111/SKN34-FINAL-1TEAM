"use client";
// 잠긴 기본 정보(C50)에서도 직접 할 일은 고쳐요(PUT /projects/{id}/diy: 실측 요청 뒤에도 바꿀 수 있어요, 나머지 칸은 읽기만).
// 확정 전 실측 요청 · 공사 시작 전 확정 업체에는 서버가 바뀐 직접 할 일을 알려요(told). 알린 업체가 있으면 그 이름을 짧게 알려요.
// '우리 집 정보' 화면(/projects/{id}/home)이면 저장 뒤 after로 가요(고치기 폼과 같아요). 칩은 첫 대화 · 서버 project/diy.py와 같아요.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { ChoiceChips } from "@/components/ui/ChoiceChip";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { call, errorText, type Schemas } from "@/lib/backend/client";
import { DIY_CHIPS, DIY_FIELD_ID, diyFromPicks, diyPicks, type DiyKey } from "@/lib/guest/info";
import s from "./info.module.css";
import q from "./standard.module.css";

export function DiyEdit({ projectId, initial, after, focus, mock }: {
  projectId: string;
  /** 저장된 직접 할 일(null 아직 안 물음 · [] 없어요) */
  initial: DiyKey[] | null;
  /** 저장 뒤 갈 곳(대화 안 창이면 대화) */
  after?: string;
  /** 보드 '직접 할 일' 줄로 열었으면 처음 초점 */
  focus?: boolean;
  mock?: boolean;
}) {
  const router = useRouter();
  const toast = useToast();
  const [diy, setDiy] = useState<DiyKey[] | null>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const picks = diyPicks(diy);
  const same = diy === initial || (diy != null && initial != null && diy.join() === initial.join());

  useEffect(() => {
    if (!focus) return;
    const t = window.setTimeout(() => {
      const box = document.getElementById(DIY_FIELD_ID);
      box?.querySelector<HTMLElement>("input:not([disabled])")?.focus();
      box?.scrollIntoView({ block: "center" });
    }, 60);
    return () => window.clearTimeout(t);
  }, [focus]);

  async function save() {
    if (busy || diy == null || same) return;
    setBusy(true);
    setErr(null);
    try {
      const out = mock ? { told: [] as string[] } : await call<Schemas["DiyOut"]>("PUT", `/projects/${encodeURIComponent(projectId)}/diy`, { diy });
      if (out.told?.length) toast.show(`${out.told.join(" · ")}에 바뀐 직접 할 일을 알렸어요`);
      else if (!after) toast.show("저장했어요");
      if (after) router.replace(after, { scroll: false });
      router.refresh();
      if (!after) setBusy(false);
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  }

  return (
    <section className={q.group} aria-labelledby="diy-t">
      <h2 id="diy-t" className={s.grp}>직접 할 일</h2>
      <div id={DIY_FIELD_ID}>
        <ChoiceChips multiple legend="직접 할 일" hideLegend value={picks} onChange={(v) => setDiy(diyFromPicks(v, picks))} options={DIY_CHIPS} />
      </div>
      {err ? <p className={s.formErr} role="alert"><Icon name="error" size={18} />{err}</p> : null}
      <div className={s.diySave}>
        <Button onClick={() => { void save(); }} busy={busy} disabled={diy == null || same}>{busy ? "저장하는 중" : "저장"}</Button>
      </div>
    </section>
  );
}
