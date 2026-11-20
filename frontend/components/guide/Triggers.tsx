"use client";
// 백과 화면의 '찾기 칸'과 'AI 채팅에 묻기' 단추. 누르면 백과 레이아웃에 하나씩 있는 창(GuideFind · GuideAsk)을 열어요.
import { ASK_EVENT, FIND_EVENT } from "@/lib/guide/shared";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import s from "./guide.module.css";

export const openFind = () => window.dispatchEvent(new Event(FIND_EVENT));
export const openAsk = (text = "") => window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text } }));

export function FindButton({ label = "용어나 궁금한 것을 찾아보세요" }: { label?: string }) {
  return (
    <button type="button" className={s.searchBtn} onClick={openFind} aria-haspopup="dialog">
      <Icon name="search" size={20} />
      <span>{label}</span>
      <kbd aria-hidden="true">Ctrl K</kbd>
    </button>
  );
}

export function AskButton({ block }: { block?: boolean }) {
  return <Button variant="weak" size="sm" icon="chat" block={block} onClick={() => openAsk()}>AI 채팅에 묻기</Button>;
}
