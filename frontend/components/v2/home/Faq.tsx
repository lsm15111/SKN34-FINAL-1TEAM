"use client";
// 자주 묻는 질문 (v10 FAQ7 · faqSection): 누르면 그 질문으로 상담을 시작해요. 아래에 셀프 도구 두 개.
import { startWithAsk, startWithTool } from "./start";

const FAQ7: [string, string[]][] = [
  ["준비", ["공사 순서는 어떻게 돼요?", "관리사무소 신고는 어떻게 해요?"]],
  ["업체 · 계약", ["견적은 몇 군데에서 받아야 해요?", "계약서에 꼭 적어야 할 건 뭐예요?"]],
  ["자재", ["합지랑 실크 벽지는 뭐가 달라요?", "기존 벽지 위에 덧방해도 돼요?"]],
  ["공사 · 하자", ["겨울에 도배해도 괜찮아요?", "하자가 생기면 어떻게 해요?"]],
];

export function FaqSection() {
  return (
    <section className="home-sec faq7">
      <div className="sec-t">
        <h2>자주 묻는 질문</h2>
      </div>
      <div className="faq7-grid">
        {FAQ7.map(([g, qs]) => (
          <div key={g}>
            <b>{g}</b>
            {qs.map((q) => (
              <button key={q} type="button" className="faq7-q" onClick={() => startWithAsk(q)}>
                {q}
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="row">
        <button type="button" className="btn btn-sm" onClick={() => startWithTool("calc")}>셀프 계산기</button>
        <button type="button" className="btn btn-sm" onClick={() => startWithTool("check")}>체크리스트</button>
      </div>
    </section>
  );
}
