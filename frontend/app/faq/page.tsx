// 자주 묻는 질문. 비용 · 기간 표는 시장 참고 값(2025~2026년 수도권, 반셀프 기준)을 옮겨 적은 것이고
// 믿집 계산 엔진이 만든 값이 아니다. 우리 집 금액은 프로젝트의 표준견적서에서 본다.
import { SiteHeader } from "@/components/site/SiteHeader";

export const metadata = { title: "자주 묻는 질문" };

const COST = [
  { size: "10평대 (원룸 · 투룸)", total: "800~1,500만 원", per: "80~100만 원", period: "2~3주" },
  { size: "20평대 (24~29평)", total: "1,500~3,000만 원", per: "60~120만 원", period: "4~6주" },
  { size: "30평대 (30~35평)", total: "2,500~5,000만 원", per: "70~150만 원", period: "5~7주" },
  { size: "40평대 (40~50평)", total: "4,000~8,000만 원", per: "80~160만 원", period: "6~9주" },
];
const BASIS = "2025~2026년 수도권, 반셀프(공정별 개별 계약) 기준이에요. 턴키 업체에 일괄 시공을 맡기면 30~50% 더 들어요.";

export default function FaqPage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="mj-wrap mj-main" style={{ maxWidth: 880 }}>
        <h1 className="mj-h1">자주 묻는 질문</h1>

        <details className="mj-fold mj-panel" open>
          <summary>평수별 인테리어 비용은 얼마인가요?</summary>
          <div className="mj-table-box">
            <table className="mj-table">
              <caption>평수별 인테리어 비용 (올수리 기준)</caption>
              <thead><tr><th scope="col">평수</th><th scope="col">총비용</th><th scope="col">평당 가격</th><th scope="col">예상 기간</th></tr></thead>
              <tbody>
                {COST.map((r) => (
                  <tr key={r.size}><th scope="row">{r.size}</th><td className="mj-num"><b>{r.total}</b></td><td className="mj-num">{r.per}</td><td className="mj-num">{r.period}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mj-small">{BASIS}</p>
        </details>

        <details className="mj-fold mj-panel">
          <summary>반셀프와 턴키는 무엇이 다른가요?</summary>
          <p>반셀프는 공정마다 업체를 골라 따로 계약하는 방식이에요. 턴키는 한 업체가 전체 공사를 일괄로 맡는 방식이에요.</p>
          <p className="mj-small">위 비용 표는 반셀프 기준이고, 턴키로 맡기면 30~50% 더 들어요. 믿집은 도배 · 바닥재 · 욕실 · 주방 같은 10개 공정마다 업체를 비교해 고르는 반셀프 방식이에요.</p>
        </details>
      </main>
    </>
  );
}
