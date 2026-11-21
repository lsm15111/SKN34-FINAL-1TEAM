"use client";
// 카드 kind → 컴포넌트(계약서 3장: 서버 · 화면이 같은 이름). 같은 card_id면 카드를 바꿔 끼워요(lib/api/assistant applyTurnEvent).
// 모르는 kind는 그리지 않아요(서버가 새 kind를 먼저 더해도 화면이 깨지지 않게).
import type { ComponentType } from "react";
import type { CardKind, CardOut } from "@/lib/api/assistant";
import { BriefCard } from "@/components/pro/assistant/BriefCard";
import { QuoteChecklist } from "@/components/pro/assistant/QuoteChecklist";
import { TodayCard } from "../kit/TodayCard";
import { ExtraCard } from "./ExtraCard";
import { HomeInfoCard } from "./HomeInfoCard";
import { NoticeCard } from "./NoticeCard";
import { QuoteCompareCard } from "./QuoteCompareCard";
import { ScheduleCard } from "./ScheduleCard";
import { AnswerCard, FloorplanLinksCard, KnowledgeCard } from "./SmallCards";
import { StandardQuoteCard } from "./StandardQuoteCard";
import type { CardCtx, CardProps } from "./types";
import { VendorPicksCard } from "./VendorPicksCard";
import { VisitSlotsCard } from "./VisitSlotsCard";

type Registry = { [K in CardKind]: ComponentType<CardProps<K>> };

export const CARDS: Registry = {
  home_info: HomeInfoCard,
  standard_quote: StandardQuoteCard,
  vendor_picks: VendorPicksCard,
  visit_slots: VisitSlotsCard,
  quote_compare: QuoteCompareCard,
  schedule: ScheduleCard,
  knowledge: KnowledgeCard,
  answer: AnswerCard,
  floorplan_links: FloorplanLinksCard,
  today: TodayCard,
  vendor_brief: ({ card, ctx }) => <BriefCard visitId={card.data.visit_id} data={card.data} now={ctx.now} />,
  quote_checklist: ({ card }) => <QuoteChecklist visitId={card.data.visit_id} data={card.data} />,
  extra: ExtraCard,
  notice: NoticeCard,
};

/** old: 할 일이 끝난 먼저 말 건 줄의 카드(보낸 때 모습). 서버는 그 카드 id에 '@줄 id'를 붙여 보내요(뒤 카드와 합쳐지지 않게).
 *  그런 카드는 줄 표시와 상관없이 끝난 카드로 그려요(단추를 두지 않아요: 눌러도 지난 카드라 받지 않아요) */
export function Card({ card, ctx, old }: { card: CardOut; ctx: CardCtx; old: boolean }) {
  const C = CARDS[card.kind] as ComponentType<CardProps<CardKind>> | undefined;
  return C ? <C card={card} ctx={ctx} old={old || card.card_id.includes("@")} /> : null;
}
