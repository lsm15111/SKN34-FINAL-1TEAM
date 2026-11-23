"""요청 점검 부탁 뽑기(app.assistant.asks.extract) 채점. 무료(LLM 없음).

사용: cd backend && uv run python ../evaluation/v4/request_check/score_asks.py [--split dev|held_out|all] [--show-misses]
- 정답은 asks_set.jsonl(v4 대화 고객 말 118 + QA 보고서 2). show가 null인 줄(어느 카드인지 모름)은 카드 채점에서 빼요.
- 카드는 두 가지로 재요: 점검하는 여섯 종류(asks.SHOW_NOUN: 집 정보 · 표준견적서 · 공정표 · 견적서 비교 · 업체 추천 ·
  오늘 할 일) 안에서, 그리고 모든 카드 부탁(실측 시간 등 show_card로 못 보이는 카드 포함).
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "backend"))

from app.assistant import asks

SCOPE = set(asks.SHOW_NOUN)


def prf(tp: int, fp: int, fn: int) -> str:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return f"정밀도 {p:.2f}({tp}/{tp + fp}) · 재현율 {r:.2f}({tp}/{tp + fn})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["dev", "held_out", "all"])
    ap.add_argument("--show-misses", action="store_true")
    a = ap.parse_args()
    rows = [
        json.loads(x) for x in (HERE / "asks_set.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows = [r for r in rows if a.split == "all" or r["split"] == a.split]
    c = {k: [0, 0, 0] for k in ("count", "price", "show_scope", "show_all")}
    misses: list[str] = []
    for r in rows:
        got = asks.extract(r["text"])
        # 수: 수까지 맞아야 맞음
        want_n = r["count"]
        if want_n and got.count == want_n:
            c["count"][0] += 1
        else:
            if got.count:
                c["count"][1] += 1
            if want_n:
                c["count"][2] += 1
            if got.count != want_n:
                misses.append(f"{r['id']} 수 {want_n} → {got.count}: {r['text']}")
        # 값
        if r["price"] and got.price:
            c["price"][0] += 1
        elif got.price and not r["price"]:
            c["price"][1] += 1
            misses.append(f"{r['id']} 값 잘못 잡음: {r['text']}")
        elif r["price"] and not got.price:
            c["price"][2] += 1
            misses.append(f"{r['id']} 값 놓침: {r['text']}")
        # 카드
        if r["show"] is None:
            continue
        want, have = set(r["show"]), set(got.show)
        for key, ws in (("show_scope", want & SCOPE), ("show_all", want)):
            c[key][0] += len(ws & have)
            c[key][1] += len(have - ws)
            c[key][2] += len(ws - have)
        if want != have:
            misses.append(f"{r['id']} 카드 {sorted(want)} → {sorted(have)}: {r['text']}")
    print(f"세트 {a.split} {len(rows)}줄")
    print(f"- 수: {prf(*c['count'])}")
    print(f"- 값: {prf(*c['price'])}")
    print(f"- 카드(점검하는 종류 안): {prf(*c['show_scope'])}")
    print(f"- 카드(모든 카드 부탁): {prf(*c['show_all'])}")
    if a.show_misses:
        print("\n".join(["", "틀린 줄", *misses]))


if __name__ == "__main__":
    main()
