"""사람 확인 표본: 판정 결과에서 N건(기본 20)을 고르게 뽑아 사람이 채울 CSV를 만들어요. LLM 0회.

    cd backend && uv run python ../evaluation/v4/human_sample.py --judgments ../evaluation/v4/runs/j1/judgments.jsonl

- 고르게: (출처, 판정기 종합 결과)로 묶어 돌아가며 하나씩(씨앗 고정). 같은 글로 자동 무승부인 쌍은 빼요
- 사람 쪽도 라벨을 숨겨요: 답 1 · 답 2 순서를 판정기와 따로 섞고, 어느 시스템인지는 열쇠 파일에만 둬요
- 만드는 것(판정 결과 옆): human_<n>.csv(사람이 채움, 엑셀용 UTF-8 BOM) · human_<n>_key.csv(열쇠, 채우는 사람은 열지 않아요)
- 채우는 값: 종합 · 차원 칸에 1 · 2 · 같음 · 둘다나쁨(종합만) · 모름. 빈칸은 세지 않아요. 기준은 rubric.md
"""

import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from kit import jsonl, stable_int, utf8_stdout

DIMS_KO = ("정확", "근거", "유용", "간결", "안전", "숫자")
DIM_KEY = dict(
    zip(
        DIMS_KO,
        ("accuracy", "grounding", "usefulness", "concision", "safety", "numbers"),
        strict=True,
    )
)
COLS = (
    "표본",
    "질문",
    "집",
    "기대",
    "답 1",
    "답 1 계산 값",
    "답 2",
    "답 2 계산 값",
    "종합",
    *DIMS_KO,
    "메모",
)
KEY_COLS = ("표본", "item_id", "답1")
CHOICES = "1 · 2 · 같음 · 둘다나쁨(종합만) · 모름"


def pick(rows: list[dict], n: int, seed: int) -> list[dict]:
    """(출처, 판정기 종합 결과) 묶음을 돌아가며 하나씩 뽑아요."""
    rnd = random.Random(seed)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("auto") is None:
            groups[(r["source"], r["dims"]["overall"]["final"])].append(r)
    for g in groups.values():
        rnd.shuffle(g)
    keys = sorted(groups)
    out: list[dict] = []
    while len(out) < n and any(groups.values()):
        for k in keys:
            if groups[k] and len(out) < n:
                out.append(groups[k].pop())
    return out


def expect_text(item: dict, sets: dict) -> str:
    q = sets.get(item["id"], {})
    parts = [f"해야: {e}" for e in q.get("expect", [])] + [f"피할: {e}" for e in q.get("avoid", [])]
    return "\n".join(parts)


def main(argv=None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="사람 확인 표본 CSV")
    ap.add_argument("--judgments", type=Path, required=True)
    ap.add_argument("--set", type=Path, default=HERE / "sets" / "compare.jsonl")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20261121)
    a = ap.parse_args(argv)
    rows = jsonl(a.judgments)
    if not rows:
        sys.exit("판정 결과가 없어요")
    sets = {r["id"]: r for r in jsonl(a.set)}
    chosen = pick(rows, a.n, a.seed)
    out_dir = a.judgments.parent
    data, keys = out_dir / f"human_{a.n}.csv", out_dir / f"human_{a.n}_key.csv"
    with (
        data.open("w", encoding="utf-8-sig", newline="") as f,
        keys.open("w", encoding="utf-8-sig", newline="") as k,
    ):
        w, wk = csv.writer(f), csv.writer(k)
        w.writerow(COLS)
        wk.writerow(KEY_COLS)
        for i, r in enumerate(chosen, 1):
            sid = f"h{i:02d}"
            first = "A" if stable_int("human", a.seed, r["id"]) % 2 == 0 else "B"
            second = "B" if first == "A" else "A"
            facts = r.get("facts") or {}
            w.writerow([sid, r["question"], r.get("home_text", ""), expect_text(r, sets),
                        r["texts"][first], facts.get(first, ""), r["texts"][second], facts.get(second, ""),
                        "", *[""] * len(DIMS_KO), ""])  # fmt: skip
            wk.writerow([sid, r["id"], first])
    by = defaultdict(int)
    for r in chosen:
        by[r["source"]] += 1
    print(f"표본 {len(chosen)}건 · 출처 {dict(by)}")
    print(f"사람이 채울 파일: {data}")
    print(f"열쇠(채우는 사람은 열지 않아요): {keys}")
    print(f"칸에 넣을 값: {CHOICES}. 기준은 evaluation/v4/rubric.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
