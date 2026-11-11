"use client";
// 체크리스트 카드 (v10 CHECKS · ckGet · ckSet · checkCard). 고른 칸은 이 브라우저에만 기억한다.
import { useState } from "react";
import { store } from "../store";

type Which = "before" | "contract" | "after";
const CHECKS: Record<Which, { ko: string; items: string[] }> = {
  before: { ko: "공사 전", items: ["관리사무소에 공사 신고하고 공사 가능 시간 확인하기", "공사 안내문을 2~3일 전에 붙이기(날짜 · 동호수 · 공사 내용 · 연락처)", "승강기 보호재 설치를 관리사무소와 정하기",
    "벽 철거 · 발코니 확장이 있으면 구청 허가 · 신고 대상인지 확인하기", "단지 관리규약에 이웃 동의가 필요한지 확인하기", "자재 고르는 날짜를 공정 전으로 정해 두기"] },
  contract: { ko: "계약 전", items: ["공사 범위와 자재 품명 · 규격이 견적서에 줄마다 적혀 있는지", "부가세 포함인지 별도인지", "공사 기간과 늦어질 때 책임(지체상금)", "대금을 공정에 맞춰 나눠 내고 잔금은 확인 뒤에 내는지",
    "하자 보수 기간과 연락 방법", "사업자등록 · 건설업 등록 여부(큰 공사)", "공정위 실내건축 표준계약서를 쓰는지", "추가 비용이 생길 때 미리 알리는 조건"] },
  after: { ko: "공사 뒤 검수", items: ["벽지 들뜸 · 기포 · 이음매 벌어짐이 없는지", "모서리 · 콘센트 주변 벽지 마감", "몰딩 · 걸레받이 이음과 벽 사이 틈", "문이 걸리지 않고 끝까지 닫히는지 · 손잡이 흔들림",
    "천장 평탄화 부분의 굴곡", "남은 자재 · 폐기물을 치웠는지", "고칠 곳은 사진을 찍어 날짜와 함께 업체에 보내기"] },
};
const CK_KEY = "mj-v7-checks";
const ckGet = (): Record<string, boolean> => {
  try {
    return JSON.parse(store.get(CK_KEY) || "{}");
  } catch {
    return {};
  }
};
const ckSet = (o: Record<string, boolean>) => store.set(CK_KEY, JSON.stringify(o));

export function CheckCard({ which: first = "before" }: { which?: Which }) {
  const [which, setWhich] = useState<Which>(first in CHECKS ? first : "before");
  const [st, setSt] = useState(ckGet);
  const c = CHECKS[which], done = c.items.filter((_, i) => st[`${which}.${i}`]).length;
  return (
    <div className="card c7">
      <h3>체크리스트</h3>
      <div className="seg" role="group" aria-label="체크리스트">
        {(Object.keys(CHECKS) as Which[]).map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={k === which}
            onClick={() => {
              setWhich(k);
              setSt(ckGet());
            }}
          >
            {CHECKS[k].ko}
          </button>
        ))}
      </div>
      <div>
        <p className="muted num">{`${done} / ${c.items.length} 확인`}</p>
        <ul className="c7-list">
          {c.items.map((t, i) => (
            <li key={`${which}.${i}`}>
              <label className="chk">
                <input
                  type="checkbox"
                  checked={!!st[`${which}.${i}`]}
                  onChange={(e) => {
                    const s = ckGet();
                    s[`${which}.${i}`] = e.target.checked;
                    ckSet(s);
                    setSt(s);
                  }}
                />
                {t}
              </label>
            </li>
          ))}
        </ul>
      </div>
      <p className="muted">고른 칸은 이 브라우저에만 남아요.</p>
    </div>
  );
}
