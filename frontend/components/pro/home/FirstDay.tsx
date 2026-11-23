// 승인 · 처음 할 일(V02 v_first) = 업체 정보 탭의 첫 화면. 9판: 업체 정보 탭 · 업체 정보 · 링크 · 리뷰 화면의 ‹ 가 이 화면으로 와요.
// /vendor(받은 요청이 아직 없을 때, home)와 /vendor/profile(탭 '업체 정보')이 같이 써요.
// 마친 일(✓)은 부르는 쪽이 지금 있는 읽기로 정해 넘겨요: 단가 = v3 확인 묶음 있음 · 업체 정보 = 한 번이라도 저장 · 링크 = 1개 이상.
// 목공만 하는 업체: 목공 고객 연결은 준비 중이라 도배 단가 할 일을 빼고, 지금 할 수 있는 일(업체 정보 · 사례 · 링크)로 이끌어요(QA r6 M3).
// 다 마친 뒤 /vendor에서는 다음에 올 일(고객 요청이 작업함에 와요)을 알려요.
import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Icon } from "@/components/ui/Icon";
import { Group, Hero } from "../ui/parts";
import s from "./home.module.css";

/** trades: 업체 공정(없으면 도배로 봐요) */
export type FirstDone = { prices: boolean; profile: boolean; links: boolean; trades?: string[] };

export function FirstDay({ done, waiting, home = false }: {
  done: FirstDone;
  /** 답글 기다리는 리뷰 수 */
  waiting?: number;
  /** 업체 홈(/vendor, 받은 요청이 아직 없을 때) */
  home?: boolean;
}) {
  const dobae = !done.trades?.length || done.trades.includes("dobae");
  const items = [
    ...(dobae ? [{ k: "prices", on: done.prices, t: "도배 단가 넣기", d: "견적서 줄마다 단가 · 다른 줄에 포함 · 빼기", href: "/vendor/prices/dobae" }] : []),
    { k: "profile", on: done.profile, t: "업체 정보 · 시공 사례", d: "다니는 지역 · 연락 방법 · 출장비 · 사진", href: "/vendor/profile?tab=basic" },
    { k: "links", on: done.links, t: "외부 리뷰 · 시공 사례 링크", d: "외부 리뷰 링크는 3개까지 · 관리자가 확인해요", href: "/vendor/profile?tab=links" },
  ];
  const left = items.some((x) => !x.on);
  const approved = left ? <Badge tone="ok">승인됐어요</Badge> : undefined;
  return (
    <>
      {!dobae ? (
        <Hero badge={approved} title={<>목공 고객 연결은<br />준비 중이에요</>} sub={left ? "그동안 업체 정보 · 시공 사례를 채워 둬요." : "업체 정보 · 링크는 아래에서 고쳐요."} />
      ) : left ? (
        <Hero badge={approved} title={<>고객에게 보일<br />준비를 해요</>} sub="단가를 넣고 확인하면 고객에게 가견적이 보여요." />
      ) : home ? (
        <Hero title="준비를 마쳤어요" sub="고객이 실측을 요청하면 작업함에 와요." />
      ) : (
        <Hero title="업체 정보" sub="고객에게 보이는 단가 · 정보 · 링크를 여기서 고쳐요." />
      )}
      <Group flush>
        <ul className={s.todo} aria-label="처음 할 일">
          {items.map((x) => (
            <li key={x.k}>
              <Link className={s.ti} href={x.href}>
                <span className={`${s.ck} ${x.on ? s.ckOn : ""}`} aria-hidden="true">{x.on ? <Icon name="check" size={14} strokeWidth={3} /> : null}</span>
                <span className={s.tt}>
                  <b><span className="mj-sr">{x.on ? "마쳤어요, " : "아직 안 했어요, "}</span>{x.t}</b>
                  <span>{x.d}</span>
                </span>
                <Icon name="chevron-right" size={18} className={s.chev} />
              </Link>
            </li>
          ))}
          <li>
            <Link className={s.ti} href="/vendor/reviews">
              <span className={s.tt}>
                <b>리뷰 · 답글</b>
                <span>{waiting ? `답글 기다림 ${waiting}` : "고객이 리뷰를 쓰면 여기서 답글을 달아요"}</span>
              </span>
              <Icon name="chevron-right" size={18} className={s.chev} />
            </Link>
          </li>
        </ul>
      </Group>
    </>
  );
}
