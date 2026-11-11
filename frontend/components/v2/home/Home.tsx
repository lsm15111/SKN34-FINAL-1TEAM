"use client";
// 첫 화면 (v10 showHome 최종: 큰 사진 + 사진 줄 + 자주 묻는 질문).
// v10 덧씌움에서 '우리 집에 칠해 보기'(ToneRoom)와 '견적서에 나오는 말'(PartsGuide)은 빠져 있어 여기서도 그리지 않는다.
import { STYLES } from "../data";
import { loadSaved } from "../store";
import { goChat } from "../V2App";
import { FaqSection } from "./Faq";
import { HomeStage } from "./HomeStage";
import { LookStrip } from "./LookStrip";

function ResumeCard() {
  const v = loadSaved();
  if (!v) return null;
  const n = Object.keys(v.picks || {}).length;
  const st = STYLES.find((s) => s.id === v.style);
  return (
    <div className="resume">
      <div>
        <b>지난번 상담이 있어요</b>
        <p className="muted">{[st?.ko, v.info?.pyeong ? `${v.info.pyeong}평` : null, n ? `자재 ${n}개 고름` : null].filter(Boolean).join(" · ") || "진행 중"}</p>
      </div>
      <a className="btn btn-pri btn-sm" href="#chat" onClick={() => goChat("resume")}>이어서 하기</a>
    </div>
  );
}

export function Home() {
  return (
    <div className="wrap home">
      <section className="hero">
        <div className="hero-t">
          <h1>
            사진으로 고르는
            <br />
            우리 집 인테리어
          </h1>
          <div className="cta">
            <a className="btn btn-pri" href="#chat">시작하기</a>
            <a className="btn" href="#chat" onClick={() => goChat("quick")}>자재부터 볼게요</a>
          </div>
          <ol className="flow-mini" aria-label="진행 순서">
            {["스타일", "집 정보", "자재", "견적서 · 공정표"].map((t, k) => (
              <li key={t}>
                <span>{k + 1}</span>
                {t}
              </li>
            ))}
          </ol>
          <ResumeCard />
        </div>
        <HomeStage />
      </section>
      <LookStrip />
      <FaqSection />
    </div>
  );
}
