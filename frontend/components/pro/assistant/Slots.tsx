// 업체 v3 화면(본문 틀 Main을 화면이 그려요) 위에 비서 카드를 얹는 자리. 본문과 같은 너비 · 옆 여백으로 맞춰요.
import type { VendorVisitV3 } from "@/lib/api/vendor";
import { BriefCard } from "./BriefCard";
import { QuoteChecklist } from "./QuoteChecklist";
import { seedFromVisit } from "./seed";
import p from "./pro.module.css";

export function BriefSlot({ v, now }: { v: VendorVisitV3; now: string }) {
  return <div className={p.slot}><BriefCard visitId={v.id} seed={seedFromVisit(v)} now={now} /></div>;
}

export function ChecklistSlot({ visitId }: { visitId: string }) {
  return <div className={p.slot}><QuoteChecklist visitId={visitId} /></div>;
}
