"""답 품질 평가 2단계: 판정(judge.md 기준) + 실행 기록으로 지표를 낸다. 무료.

    python evaluation/answer/score.py [--final]   # --final이면 held-out까지

입력: .cache/answers.jsonl (run.py), .cache/judged_*.json (판정 {질문 id: {claims, cites, behavior, ...}})
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
C = HERE / ".cache"


def ratio(a: int, b: int) -> str:
    return f"{a / b:.3f} ({a}/{b})" if b else "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args()
    rows = [json.loads(x) for x in (C / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    judged: dict = {}
    for p in sorted(C.glob("judged_*.json")):
        judged.update(json.loads(p.read_text(encoding="utf-8")))
    splits = ["dev", "heldout"] if a.final else ["dev"]
    for split in splits:
        rs = [r for r in rows if r["split"] == split and r["id"] in judged]
        claims = [c["label"] for r in rs for c in judged[r["id"]]["claims"]]
        cites = [c["ok"] for r in rs for c in judged[r["id"]]["cites"]]
        print(
            f"## {split} · {len(rs)}문항 (판정 없는 문항 {sum(1 for r in rows if r['split'] == split and r['id'] not in judged)})"
        )
        print("- 근거성:", ratio(claims.count("supported"), len(claims)),
              f"· 일부 {claims.count('partial')} · 근거 없음 {claims.count('unsupported')}")  # fmt: skip
        print("- 인용 정밀도:", ratio(sum(cites), len(cites)))
        for kind in ("answer", "weak", "no_source", "engine"):
            b = [judged[r["id"]]["behavior"] for r in rs if r["kind"] == kind]
            if b:
                print(
                    f"- 행동 {kind}:", ratio(b.count("yes"), len(b)), f"· 일부 {b.count('partial')}"
                )
        print("- 지어낸 숫자:", sum(judged[r["id"]]["made_up_numbers"] for r in rs))
        sug = [x for r in rs for x in judged[r["id"]].get("suggest_ok", [])]
        print("- 추천 질문 자연스러움:", ratio(sum(sug), len(sug)),
              f"· 추천 0개 문항 {sum(1 for r in rs if not r['suggest'])}")  # fmt: skip
        print("- 해요체:", ratio(sum(judged[r["id"]]["tone_ok"] for r in rs), len(rs)))
        print("- 숫자 검사로 뺀 문장:", sum(len(r["dropped"]) for r in rs),
              "· 뗀 인용:", sum(r["cites_dropped"] for r in rs),
              "· 실패:", sum(r["failed"] for r in rs))  # fmt: skip
    all_rs = rows
    print(f"## 비용 · 시간 (실행 {len(all_rs)}문항)")
    print(
        f"- 합계 ${sum(r['cost'] for r in all_rs):.4f} · 문항당 평균 ${sum(r['cost'] for r in all_rs) / len(all_rs):.4f}"
    )
    print(f"- LLM 호출 평균 {sum(len(r['calls']) for r in all_rs) / len(all_rs):.1f}번 · "
          f"평균 {sum(r['seconds'] for r in all_rs) / len(all_rs):.1f}초")  # fmt: skip
    u = {k: sum(r["usage"][k] for r in all_rs) for k in ("input", "cached", "output")}
    print(f"- 토큰: 입력 {u['input']:,} (캐시 {u['cached']:,}) · 출력 {u['output']:,}")


if __name__ == "__main__":
    main()
