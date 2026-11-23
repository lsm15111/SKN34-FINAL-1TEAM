// 글 속 [[용어]]를 용어 칸(TermTip)으로 바꿔 그려요. 용어집에 없는 이름은 그냥 글로 둬요.
import { pieces, termHref, TRADE_LABEL } from "@/lib/guide";
import { TermTip } from "./TermTip";

export function Rich({ text }: { text: string }) {
  return (
    <>
      {pieces(text).map((p, i) =>
        typeof p === "string" ? (
          p
        ) : (
          <TermTip key={i} label={p.label} name={p.term.term} trade={TRADE_LABEL[p.term.trade]} easy={p.term.easy} href={termHref(p.term)} />
        ),
      )}
    </>
  );
}
