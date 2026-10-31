"use client";
// 지금까지 정한 것: API가 화면 말로 준 facts를 공정별로 묶어 보인다. 넓은 화면은 왼쪽에 늘 펼치고, 폰에서는 위에 접어 둔다.
import { useState } from "react";
import type { Schemas } from "@/lib/backend/client";
import { FoldIcon } from "./FoldIcon";
import s from "./Facts.module.css";

type Fact = Schemas["Fact"];

/** facts를 API 순서 그대로 공정별로 묶는다 (공통 칸은 '집 정보') */
function groupOf(facts: Fact[], labels: Record<string, string>) {
  const groups: { key: string; label: string; facts: Fact[] }[] = [];
  for (const f of facts) {
    const key = f.trade ?? "home";
    let g = groups.find((x) => x.key === key);
    if (!g) groups.push((g = { key, label: f.trade ? labels[f.trade] ?? "공정" : "집 정보", facts: [] }));
    g.facts.push(f);
  }
  return groups;
}

export function Facts({ facts, labels }: { facts: Fact[]; labels: Record<string, string> }) {
  const [open, setOpen] = useState(false);
  const checks = facts.filter((f) => f.check).length;
  const trades = Object.values(labels).join(" · ");
  return (
    <aside className={`mj-aside mj-panel ${s.facts}`} aria-labelledby="facts-h">
      <div className={s.head}>
        <h2 id="facts-h" className="mj-h3">지금까지 정한 것</h2>
        <button type="button" className={`mj-btn mj-btn-ghost mj-btn-sm ${s.toggle}`} aria-expanded={open} aria-controls="facts-body" onClick={() => setOpen((o) => !o)}>
          {open ? "접기" : "펼쳐 보기"}<FoldIcon />
        </button>
      </div>
      <p className={s.gist}>
        <span>{trades || "불러오고 있어요…"}</span>
        {checks ? <> <span className="mj-badge mj-b-check mj-num">실측 때 확인 {checks}개</span></> : null}
      </p>
      <div id="facts-body" className={`${s.body} ${open ? s.open : ""}`}>
        {groupOf(facts, labels).map((g) => (
          <section key={g.key} className={s.group} aria-labelledby={`fact-${g.key}`}>
            <h3 id={`fact-${g.key}`} className={s.groupH}>{g.label}</h3>
            <dl className={s.list}>
              {g.facts.map((f) => (
                <div key={f.label} className={s.row}>
                  <dt>{f.label}</dt>
                  <dd>
                    <span>{f.text}</span>
                    {f.check ? <> <span className="mj-badge mj-b-check">실측 때 확인</span></> : null}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        {checks ? <p className="mj-small">&lsquo;실측 때 확인&rsquo; 칸은 모른다고 하셔서 기본값으로 계산했어요.</p> : null}
        <p className="mj-tiny">바꾸고 싶으면 대화창에 적어 주세요. 예: 천장은 빼 주세요, 방문은 2개예요</p>
      </div>
    </aside>
  );
}
