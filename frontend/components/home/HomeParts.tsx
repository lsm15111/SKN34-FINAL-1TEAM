// 홈 조각(C01 · C40 · D10): 진행 중 공사 띠 · 이렇게 진행돼요(웹) · 바닥 링크 · 폰 자주 묻는 질문 줄.
import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import s from "./home.module.css";

/** 진행 중 공사 띠(C40 · D10 덧그림, S5 A): 누르면 그 일로 가요 */
export function ResumeStrip({ name, status, href }: { name: string; status: string; href: string }) {
  return (
    <div className={s.stripWrap}>
      <Link className={s.strip} href={href}>
        <Badge tone="now">진행 중</Badge>
        <span className={s.stripText}><b>{name}</b><span>{status}</span></span>
        <Icon name="chevron-right" size={20} />
      </Link>
    </div>
  );
}

const FLOW = [
  { t: "기본 정보", d: "공사 · 우리 집 · 희망 · 1분" },
  { t: "표준견적서", d: "시장 데이터 기준 참고 금액" },
  { t: "업체 담기", d: "가견적을 견줘 3곳까지" },
  { t: "실측 일정", d: "믿집이 날짜를 맞춰요" },
  { t: "실측", d: "업체가 집을 보고 견적서" },
  { t: "실측 뒤", d: "확정 · 공사 날짜 · 리뷰" },
];

/** 이렇게 진행돼요(D10). 이름은 내 공사 단계 띠와 같아요(S20 A) */
export function HowItWorks() {
  return (
    <section className={`${s.group} ${s.flow}`} aria-labelledby="flow-t">
      <h2 id="flow-t" className={s.eb}>이렇게 진행돼요</h2>
      <ol className={s.flowList}>
        {FLOW.map((f, i) => (
          <li key={f.t}><span className={`${s.flowNo} mj-num`} aria-hidden="true">{i + 1}</span><b>{f.t}</b><span>{f.d}</span></li>
        ))}
      </ol>
    </section>
  );
}

/** 폰: 믿집 백과 · 자주 묻는 질문 줄 + 업체 가입(C01) · 웹: 바닥 링크(D10) */
/** 홈 아래 링크. '업체로 가입'은 로그인 전에만 보여요(로그인한 고객 홈 C40에는 없어요) */
export function HomeLinks({ guest }: { guest: boolean }) {
  return (
    <>
      <Link className={`${s.faqRow} ${s.phoneOnly}`} href="/guide">
        <span className={s.stripText}><b>믿집 백과</b><span>처음 순서 · 용어 사전</span></span>
        <Icon name="chevron-right" size={20} />
      </Link>
      <Link className={`${s.faqRow} ${s.phoneOnly}`} href="/faq">
        <span className={s.stripText}><b>자주 묻는 질문</b><span>가견적 · 실측 · 업체 확인</span></span>
        <Icon name="chevron-right" size={20} />
      </Link>
      {guest ? <p className={`${s.meta} ${s.phoneOnly}`}>업체이신가요? <Button variant="inline" href="/signup/vendor">업체로 가입</Button></p> : null}
      <footer className={s.foot}>
        <Link href="/guide">믿집 백과</Link>
        <Link href="/faq">자주 묻는 질문</Link>
        <Link href="/legal">약관 · 개인정보 처리방침</Link>
        {guest ? (
          <>
            <span className={s.sp} />
            <span>업체이신가요?</span>
            <Button variant="text" arrow href="/signup/vendor">업체로 가입</Button>
          </>
        ) : null}
      </footer>
    </>
  );
}
