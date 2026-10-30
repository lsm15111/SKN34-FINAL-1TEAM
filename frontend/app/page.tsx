// 첫 화면 (초기 설정). 웹 → API → DB · Redis가 이어지는지만 보여 준다. 기능 화면은 이슈 단위로 더한다.
import { isReady } from "@/lib/api/health";

export default async function Home() {
  const ready = await isReady();
  return (
    <main id="main" className="mj-wrap mj-main">
      <h1 className="mj-h1">믿집</h1>
      <p className="mj-sub">아파트 도배 · 목공 견적 비교. 지금은 초기 설정만 있어요.</p>
      <section className="mj-panel" aria-labelledby="conn-h" style={{ maxWidth: 520 }}>
        <h2 id="conn-h" className="mj-h3">연결 확인</h2>
        <p>{ready ? "웹 · API · DB · Redis가 모두 이어졌어요." : "API · DB · Redis 중 연결되지 않은 곳이 있어요. docker compose ps로 확인해 주세요."}</p>
      </section>
    </main>
  );
}
