// 작업 카드: 머리(상태 + 제목 + 시각) · 줄(업체별 상태와 한 줄 사실) · 꼬리(자세히 ›).
// 비서가 시작한 일(요청 보내기 · 단지 찾기)과 그 뒤 기능 상태(업체 답 · 견적서)를 한 카드에서 보여요.
// 같은 task_id가 다시 오면 이 카드가 바뀌어요(대화 어디에 있든). 실패는 숨기지 않아요.
import Link from "next/link";
import type { TaskOut } from "@/lib/api/assistant";
import { listStamp, timeSeoul, dateSeoul } from "@/lib/format";
import { I } from "./icons";
import { StatusTag, TASK_WORD } from "./StatusTag";
import k from "./kit.module.css";

export function TaskCard({ task, now }: { task: TaskOut; now: string }) {
  const sameDay = dateSeoul(task.at) === dateSeoul(now);
  return (
    <section className={`${k.card} ${k.task}`} aria-label={`${task.title} · ${TASK_WORD[task.state]}`}>
      <div className={k.taskHead}>
        <StatusTag tone={task.state}>{TASK_WORD[task.state]}</StatusTag>
        <b>{task.title}</b>
        <time className={k.num} dateTime={task.at}>{sameDay ? timeSeoul(task.at) : listStamp(task.at)}</time>
      </div>
      {task.rows?.length ? (
        <ul className={k.taskRows}>
          {task.rows.map((r) => (
            <li key={r.label}>
              <b>{r.label}</b>
              <StatusTag tone={r.state}>{r.text}</StatusTag>
              <span className={k.num}>{r.note ?? ""}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {task.sources?.length ? <div className={k.srcs}>{task.sources.map((x) => <span key={x} className={k.basis}>{x}</span>)}</div> : null}
      {task.error ? <p className={k.err} role="alert">{task.error}</p> : null}
      {task.link ? (
        <div className={k.taskFoot}>
          <Link className={k.text} href={task.link.href} scroll={false}>{task.link.label}<I n="chev" /></Link>
        </div>
      ) : null}
    </section>
  );
}
