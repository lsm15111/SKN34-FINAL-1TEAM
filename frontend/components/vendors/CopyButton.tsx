"use client";
// 글 복사 버튼. 클립보드를 못 쓰면(권한 · http 주소) 대상 글을 선택해 두고 직접 복사하도록 알린다.
import { useEffect, useState } from "react";

/** 대상 글을 선택해 둔다: 입력 칸이면 칸 안 글, 아니면 요소 안 글 전체 */
function selectText(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
    el.focus();
    el.select();
    return;
  }
  window.getSelection()?.selectAllChildren(el);
}

type Props = {
  text: string;
  label: string;
  /** 복사하지 못했을 때 선택해 둘 글의 id */
  targetId: string;
  /** 접힌 글을 펼치는 등, 선택하기 전에 할 일 */
  onFail?: () => void;
  className?: string;
};

export function CopyButton({ text, label, targetId, onFail, className = "mj-btn mj-btn-sec" }: Props) {
  const [msg, setMsg] = useState("");
  const [failed, setFailed] = useState(0);
  // 접힌 글은 펼친 화면이 그려진 뒤에야 선택할 수 있어서 effect에서 고른다
  useEffect(() => { if (failed) selectText(targetId); }, [failed, targetId]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setMsg("복사했어요.");
    } catch {
      onFail?.();
      setFailed((n) => n + 1);
      setMsg("복사하지 못했어요. 글을 선택해 두었으니 직접 복사해 주세요.");
    }
  }
  return (
    <>
      <button type="button" className={className} onClick={copy}>{label}</button>
      <span className="mj-small" role="status">{msg}</span>
    </>
  );
}
