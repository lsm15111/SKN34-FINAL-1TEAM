"use client";
// 로그인 전 표준견적서(C57 · D12 · N1 A). 이 기기에 둔 답(mj_guest_v3)을 읽어 서버 계산 엔진에 물어요(POST /guest/standard, 저장 안 함).
// - 줄은 모두 가입 없이 봐요. '업체 보기' · '예상 공정표' · AI 칸 '가입 · 로그인'을 누르면 그 자리에 가입 카드가 떠요(C59 · D13).
// - 웹 ≥1024: 옆 칸은 로그인 전 AI 칸(자주 묻는 질문 칩만, D12). 폰: 머리 'AI에게 묻기' → 아래 시트(C58).
// - 금액은 서버가 다시 센 값이에요. 화면이 보낸 숫자를 믿지 않고, 화면도 더하지 않아요.
// - v5: 기능 확인(caps.v4)이 꺼져 있으면 방 개수 · 철거 범위 · 직접 할 일을 몸통에 넣지 않아요(dev 백엔드).
// - 전체 도배는 dev와 같이 시장 단가 표준견적서(업체 견적서 중앙값, POST /v2/market-quote)로 보여요.
//   부분 공사는 고른 공간만 어림하는 계산이라 기존 표준견적서 계산 그대로예요(dev components/start/GuestStandard와 같은 몫).
import { useCallback, useEffect, useState } from "react";
import { GuestAsk } from "@/components/ai/GuestAsk";
import { JoinDialog } from "@/components/v5/auth/JoinDialog";
import { Main, PageHead, WithAside } from "@/components/site/Frame";
import { BottomBar } from "@/components/ui/BottomBar";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { MarketSheet, MarketTotal, MarketTrust } from "@/components/v2/market/MarketQuote";
import { call, errorText } from "@/lib/backend/client";
import { toMarketIn, type MqOut } from "@/lib/guest/market";
import { calcGuest } from "@/lib/v5/guest/api";
import { checkDraft, conditionText, toHomeInfo } from "@/lib/v5/guest/info";
import { budgetText, toQuoteLines, type StdView } from "@/lib/v5/guest/standard";
import { draftOf, readGuest } from "@/lib/v5/guest/store";
import { GUEST_ASK_EVENT, GuestAskSheet } from "@/components/start/GuestAside";
import { StandardSheet, StandardSkeleton } from "./StandardSheet";
import type { Caps } from "@/lib/v5/caps";
import s from "./standard.module.css";

type State = { kind: "loading" } | { kind: "none" } | { kind: "error"; msg: string } | { kind: "ok"; view: StdView } | { kind: "market"; q: MqOut };

export function GuestStandard({ mock, caps }: { mock: boolean; caps: Caps }) {
  const [st, setSt] = useState<State>({ kind: "loading" });
  const [join, setJoin] = useState(false);
  const [ask, setAsk] = useState(false);

  const load = useCallback(async () => {
    const g = readGuest();
    const d = g ? draftOf(g) : null;
    if (!d || Object.keys(checkDraft(d)).length) { setSt({ kind: "none" }); return; }
    setSt({ kind: "loading" });
    const info = toHomeInfo(d, caps);
    try {
      if (info.scope === "full" && !mock) {
        setSt({ kind: "market", q: await call<MqOut>("POST", "/v2/market-quote", toMarketIn(info)) });
        return;
      }
      const r = await calcGuest(info, mock);
      // 직접 할 일 '벽지 직접 구매'면 도배지 줄은 '고객 구매'(합계 밖, 계산 엔진)이고 롤 수를 보여요(가입 뒤 표준견적서와 같은 모양)
      const own = r.own_paper ? { rolls: r.rolls_text ?? null } : undefined;
      setSt({
        kind: "ok",
        view: {
          scope: r.scope, lines: toQuoteLines(r.lines, r.scope, own), supply: r.supply, vat: r.vat, total: r.total, days: r.days,
          budget: budgetText(r.budget_fit, info.budget_won),
          condition: conditionText({ ...info, area_m2: r.area_m2, area_basis: r.area_basis, rooms: r.rooms }),
        },
      });
    } catch (e) {
      setSt({ kind: "error", msg: errorText(e) });
    }
  }, [mock, caps]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const on = () => setAsk(true);
    window.addEventListener(GUEST_ASK_EVENT, on);
    return () => window.removeEventListener(GUEST_ASK_EVENT, on);
  }, []);

  // 시트 위에 창을 겹치지 않아요: 시트를 닫고 가입 카드를 열어요
  const openJoin = () => { setAsk(false); setJoin(true); };
  const ok = st.kind === "ok" ? st.view : null;
  const shown = ok != null || st.kind === "market";

  return (
    <>
      <Main>
        <PageHead title="표준견적서" crumbs={[{ label: "인테리어 받기", href: "/v5/start" }, { label: "표준견적서" }]} />
        <WithAside aside={<GuestAsk onJoin={openJoin} />}>
          {st.kind === "loading" ? <StandardSkeleton /> : null}
          {st.kind === "none" ? (
            <EmptyState icon="doc" title="넣은 답이 없어요" action={<Button href="/v5/start">기본 정보 넣기</Button>}>
              기본 정보를 넣으면 가입 없이 표준견적서가 나와요. 답은 이 기기에 저장돼요.
            </EmptyState>
          ) : null}
          {st.kind === "error" ? (
            <div className={s.alert} role="alert">
              <p>표준견적서를 계산하지 못했어요</p>
              <p>{st.msg}</p>
              <div className={s.alertBtns}>
                <Button onClick={() => void load()}>다시 계산하기</Button>
                <Button variant="secondary" href="/v5/start">기본 정보 보기</Button>
              </div>
            </div>
          ) : null}
          {ok ? <StandardSheet view={ok} changeHref="/v5/start" /> : null}
          {st.kind === "market" ? (
            <>
              <MarketTotal q={st.q} changeHref="/v5/start" />
              <MarketSheet q={st.q} />
              <MarketTrust q={st.q} />
            </>
          ) : null}
        </WithAside>
      </Main>
      {shown ? (
        <BottomBar>
          {ok?.scope === "partial" ? null : <Button variant="secondary" size="lg" onClick={() => setJoin(true)}>예상 공정표</Button>}
          <Button size="lg" onClick={() => setJoin(true)}>업체 보기</Button>
        </BottomBar>
      ) : null}
      <GuestAskSheet open={ask} onClose={() => setAsk(false)} onJoin={openJoin} />
      <JoinDialog open={join} onClose={() => setJoin(false)} />
    </>
  );
}
