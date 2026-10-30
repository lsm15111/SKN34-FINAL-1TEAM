import Link from "next/link";
import type { Trade } from "@/lib/types";
import { TRADE_LABEL } from "@/lib/types";

// 공정 전환 (주소가 바뀌는 링크 탭: 뒤로 가기 · 공유가 그대로 된다)
export function TradeTabs({ base, trades, current, counts }: { base: string; trades: Trade[]; current: Trade; counts?: Partial<Record<Trade, string>> }) {
  return (
    <nav aria-label="공정" className="mj-tabs">
      {trades.map((t) => (
        <Link key={t} href={`${base}?trade=${t}`} aria-current={t === current ? "page" : undefined}>
          {TRADE_LABEL[t]}{counts?.[t] ? <span className="mj-badge mj-b-in mj-num">{counts[t]}</span> : null}
        </Link>
      ))}
    </nav>
  );
}
