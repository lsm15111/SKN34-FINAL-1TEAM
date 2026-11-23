"use client";
// 이어 하기 확인 창(C41): 진행 중인 공사가 있는데 '인테리어 받기'를 누르면 묻는 가운데 창이에요(조각만).
// 여는 곳(홈 · 시작 화면)이 open · 공사 이름 · 지금 단계 이름 · 이어 갈 화면을 넘겨요. 단계 이름은 API 값을 B4 단계 이름으로 바꿔서 넘겨요.
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import s from "./resume.module.css";

export type ResumeProject = {
  /** '상계동 아파트 도배' */
  name: string;
  /** 단추에 넣는 짧은 이름 '상계동' */
  short: string;
  /** 지금 단계 이름 '실측 일정' */
  stepLabel: string;
  /** 이어 갈 화면(보통 한 공사 화면 · 지금 할 일 화면) */
  href: string;
};

export function ResumeDialog({ open, onClose, project, newHref }: { open: boolean; onClose: () => void; project: ResumeProject; newHref: string }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="진행 중인 공사가 있어요"
      actions={
        <>
          <Button variant="secondary" href={newHref} onClick={onClose}>다른 집 새로 받기</Button>
          <Button href={project.href} onClick={onClose}>{project.short} 이어 하기</Button>
        </>
      }
    >
      <p className={s.line}>{project.name} · {project.stepLabel} 단계</p>
      <p className={s.sub}>다른 집이면 새로 받아요. 같은 집은 이어서 해요.</p>
    </Dialog>
  );
}
