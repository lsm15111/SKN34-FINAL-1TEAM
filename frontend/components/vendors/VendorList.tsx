"use client";
// 업체 보기 + 담기(C10 · C12 · D06): 가견적 낮은 순 카드, 3곳까지 담기(공사마다 서버에 저장 · 폰 · PC 어디서든 이어져요).
// - 담기 POST /projects/{id}/shortlist · 빼기 DELETE …/shortlist/{vendor_id}. 같은 업체를 빠르게 두 번 눌러도 한 번만 보내요(D29).
// - 409는 서버 글을 그대로 알려요(already · slots_full · no_estimate · paper_unsupported · blocked_retry · locked).
// - 이 구에 업체가 없으면 가까운 구 업체를 보여요(C12). 막다른 화면을 만들지 않아요.
// - 폰: 담기 띠가 아래에 붙어요. 웹: 목록 아래 카드 + 담은 업체 칩(빼기).
// - 업체가 많아져도 처음엔 5곳만 보이고 아래 '더보기'로 5곳씩 더 펼쳐요. 가견적 설명은 제목 옆 '!' 도움말에 있어요(11-19).
import { useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Main, PageHead, WithAside, type Crumb } from "@/components/site/Frame";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { HelpTip } from "@/components/ui/HelpTip";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { VendorCard, type ShortlistState } from "@/components/ui/VendorCard";
import { ApiError, call, errorText, type Schemas } from "@/lib/backend/client";
import { eulReul, won } from "@/lib/format";
import { feeText } from "./v3text";
import s from "./vendors3.module.css";

type List = Schemas["VendorListOut"];
type Card = Schemas["VendorCardOut"];
type Short = Schemas["ShortlistOut"];
const MAX = 3;
const PAGE = 5; // 처음 보이는 업체 수 · 더보기로 더 여는 수

export function VendorList({ projectId, list, shortlist, mock, head, aside }: {
  projectId: string;
  list: List;
  shortlist: Short | null;
  mock: boolean;
  head: { title: string; crumbs: Crumb[]; desc: ReactNode };
  aside: ReactNode;
}) {
  const router = useRouter();
  const toast = useToast();
  const base = `/projects/${projectId}`;
  const all = useMemo(() => [...list.local, ...list.nearby], [list]);
  const nameOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of all) m.set(c.vendor_id, c.name);
    for (const it of shortlist?.items ?? []) m.set(it.vendor_id, it.name);
    return m;
  }, [all, shortlist]);
  const [picked, setPicked] = useState<string[]>(() => {
    const ids = new Set<string>(shortlist?.items.map((it) => it.vendor_id) ?? []);
    for (const c of all) if (c.shortlisted) ids.add(c.vendor_id);
    return [...ids];
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE);
  // 같은 틱에 두 번 눌려도 한 번만 보내요(상태는 다음 그리기에야 바뀌어서 ref로 막아요, D29)
  const lock = useRef(false);
  const count = picked.length;
  const left = Math.max(0, MAX - count);

  async function toggle(c: Card | { vendor_id: string }) {
    const vid = c.vendor_id;
    if (busy || lock.current) return;
    lock.current = true;
    const on = picked.includes(vid);
    setBusy(vid);
    try {
      if (!mock) {
        if (on) await call("DELETE", `/projects/${encodeURIComponent(projectId)}/shortlist/${encodeURIComponent(vid)}?trade=dobae`);
        else await call<Short>("POST", `/projects/${encodeURIComponent(projectId)}/shortlist`, { trade: "dobae", vendor_id: vid });
      }
      setPicked((p) => (on ? p.filter((x) => x !== vid) : p.includes(vid) ? p : [...p, vid]));
      toast.show(`${eulReul(nameOf.get(vid) ?? "업체")} ${on ? "뺐어요" : "담았어요"}`);
      if (!mock) router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.code === "already" && !on) setPicked((p) => (p.includes(vid) ? p : [...p, vid]));
      toast.show(errorText(e), { tone: "error" });
    } finally {
      lock.current = false;
      setBusy(null);
    }
  }

  const stateOf = (c: Card): ShortlistState => {
    if (c.state === "no_estimate") return "preparing";
    if (c.state === "paper_unsupported") return "excluded";
    if (c.state === "blocked_retry") return "full";
    if (picked.includes(c.vendor_id)) return "added";
    return left === 0 ? "full" : "add";
  };
  const cardOf = (c: Card, nearby: boolean) => (
    <VendorCard
      key={c.vendor_id}
      name={c.name}
      href={`${base}/vendors/${c.vendor_id}`}
      amount={c.estimate_total}
      place={nearby ? c.sgg : undefined}
      badge={c.instant_badge ? <Badge tone="ok">바로 확정</Badge> : undefined}
      rating={c.rating != null && c.review_count > 0 ? { avg: Number(c.rating), count: c.review_count } : undefined}
      extra={nearby ? undefined : feeText(c.visit_fee)}
      state={stateOf(c)}
      busy={busy === c.vendor_id}
      onToggle={() => void toggle(c)}
    />
  );

  const ready = list.local.filter((c) => c.state !== "no_estimate");
  const preparing = list.local.filter((c) => c.state === "no_estimate");
  const zero = list.local.length === 0;
  const trayText = count === 0 ? `${MAX}곳까지 담을 수 있어요` : left > 0 ? "" : `${MAX}곳을 다 담았어요`;
  // 5곳씩: 가견적 있는 업체 → 준비 중 업체 순서로 채워요(이 구에 업체가 없으면 가까운 구 업체를 같은 식으로)
  const readyShown = ready.slice(0, shown);
  const prepShown = preparing.slice(0, Math.max(0, shown - ready.length));
  const nearShown = list.nearby.slice(0, shown);
  const hiddenCount = zero ? list.nearby.length - nearShown.length : ready.length + preparing.length - readyShown.length - prepShown.length;
  const tip = !zero ? `가견적은 업체가 확인한 단가 × 믿집 수량이에요. 부가세 포함이고, 표준견적서는 ${won(list.standard_total)}이에요.` : null;
  const go = <Button size="sm" href={`${base}/visits/new`} disabled={count === 0}>실측 일정 잡기</Button>;

  return (
    <>
      <Main>
        <PageHead title={head.title} crumbs={head.crumbs}
          desc={tip ? <>{head.desc}<HelpTip only="phone" label="가견적 안내">{tip}</HelpTip></> : head.desc}
          badge={tip ? <HelpTip only="web" label="가견적 안내">{tip}</HelpTip> : undefined} />
        <WithAside aside={aside}>
          {zero ? (
            <section className={s.group} aria-labelledby="zero-t">
              <h2 id="zero-t" className={s.hs}>{list.area_name}에서 도배하는<br />믿집 업체가 아직 없어요</h2>
              <p className={s.sub}>가까운 구 업체를 보여 드려요. 출장 갈 수 있는지는 업체가 답해요.</p>
              <div><Button variant="text" arrow href={`${base}/standard`}>표준견적서 보기</Button></div>
            </section>
          ) : null}

          {/* 벽지 직접 구매: 가견적은 벽지 값이 든 값이라 안내 한 줄(API paper_note, 틀) */}
          {list.paper_note ? <p className={s.meta}>{list.paper_note}</p> : null}

          {zero && list.nearby.length ? <p className={s.metaB}>가까운 구 · {list.nearby_sgg.join(" · ")} {list.nearby.length}곳</p> : null}
          {zero && list.nearby.length ? <div className={s.list}>{nearShown.map((c) => cardOf(c, true))}</div> : null}
          {zero && !list.nearby.length ? (
            <p className={s.sub}>가까운 구에도 아직 업체가 없어요.</p>
          ) : null}

          {readyShown.length ? <div className={s.list}>{readyShown.map((c) => cardOf(c, false))}</div> : null}
          {prepShown.length ? (
            <>
              <p className={s.metaB}>가견적 준비 중인 업체 {preparing.length}곳 · 업체가 단가를 확인하면 담을 수 있어요</p>
              <div className={s.list}>{prepShown.map((c) => cardOf(c, false))}</div>
            </>
          ) : null}
          {hiddenCount > 0 ? (
            <Button variant="secondary" block className={s.more} onClick={() => setShown((n) => n + PAGE)}>
              더보기 <span className="mj-num">{hiddenCount}곳</span>
            </Button>
          ) : null}

          {/* 웹: 목록 아래 담기 카드 */}
          <div className={s.webTray} aria-live="polite">
            <div className={s.trayText}>
              {/* CF-31: 0곳일 때는 '3곳까지 담을 수 있어요'만 보여요 */}
              {count > 0 ? (
                <p className={s.trayHead}>
                  <b>담은 업체 {count}곳</b>
                  {picked.map((vid) => (
                    <span key={vid} className={s.pchip}>
                      {nameOf.get(vid) ?? "업체"}
                      <button type="button" className={s.pchipX} aria-label={`${nameOf.get(vid) ?? "업체"} 빼기`} disabled={busy === vid} onClick={() => void toggle({ vendor_id: vid })}><Icon name="close" size={16} /></button>
                    </span>
                  ))}
                </p>
              ) : null}
              {trayText ? <span>{trayText}</span> : null}
            </div>
            {go}
          </div>
        </WithAside>
      </Main>
      {/* 폰: 아래에 붙는 담기 띠 */}
      <div className={s.phoneTray} aria-live="polite">
        <div className={s.trayText}>{count > 0 ? <b>담은 업체 {count}곳</b> : null}{trayText ? <span>{trayText}</span> : null}</div>
        {go}
      </div>
    </>
  );
}
