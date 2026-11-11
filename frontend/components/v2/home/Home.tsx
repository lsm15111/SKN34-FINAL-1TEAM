"use client";
// 첫 화면 (자리만 잡아 둠: 첫 화면 작업에서 채운다)
import { goChat } from "../V2App";

export function Home() {
  return (
    <div className="wrap home">
      <section className="hero">
        <div>
          <h1>우리 집 인테리어, 대화로 정해요</h1>
          <p className="lead">스타일부터 자재까지 하나씩 골라 드려요.</p>
          <div className="cta">
            <a className="btn btn-pri" href="#chat" onClick={() => goChat(null)}>표준견적서 받기</a>
          </div>
        </div>
      </section>
    </div>
  );
}
