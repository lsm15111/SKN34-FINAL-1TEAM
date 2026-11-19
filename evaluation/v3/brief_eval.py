"""짧은 답(brief) 평가: 초보 질문 227 + 질문 은행 493에서 짧은 답 길이 · 예산 · 질문 꼴 · 결론 먼저를 재요. LLM · DB 없음(무료).

    cd backend && uv run --no-sync python ../evaluation/v3/brief_eval.py

- 비교안(같은 예산)
  - full: 지금 답 전체(sections + unknown)
  - head: 앞에서부터 자르기(정책 글 우선 없이 첫 문장부터 예산까지). 가장 단순한 짧은 답이에요
  - brief: brief.make(질문 꼴 · 정책 글 먼저 · 질문 낱말 덮기로 고르기)
- 코드 지표: 글자 수(중앙값 · 90%), 예산 넘김, 예/아니요 꼴에서 첫 문장이 결론 말투인가(brief.YESNO_S, 대리 지표)
- 판정 묶음: judge_packs/brief_pairs.jsonl(+ _key). head와 brief가 다른 것만, A/B 순서는 섞어요.
  판정자는 '질문에 더 바로 답하는 짧은 답'과 '전체 답의 핵심을 잃었나'를 매겨요(rubric은 docs/v3/agent-next.md 6장).
"""

import asyncio
import json
import random
import statistics
import uuid
from collections import Counter, defaultdict

from common import RESULTS, ROOT, jsonl, utf8_stdout
from judge_pack import OUT
from kb3 import TODAY, bank, kb

from app.agent.v3 import brief
from app.agent.v3.schemas import TurnContext
from app.agent.v3.turn import run_turn

BEGINNER = ROOT / "data/v3/questions/beginner_web/questions.jsonl"
SEED = 20261119
CONTENT = ("card", "extract", "llm", "calc")


def head(a, form: str, multi: bool) -> list[str]:
    """비교용 단순안: 첫 문장부터 예산까지 자르기(첫 문장은 넘쳐도 보임)."""
    n_max, c_max = (brief.MULTI_LINES, brief.MULTI_CHARS) if multi else brief.BUDGET[form]
    every = [x.text for s in a.sections for x in s.sentences if x.text not in brief.LEADS]
    if not every:
        return list(a.unknown[:2])
    out, used = [], 0
    for t in every:
        if len(out) >= n_max:
            break
        if out and used + len(t) > c_max:
            continue
        out.append(t)
        used += len(t)
    return out


def row(set_name: str, q: dict, a) -> dict:
    full = [x.text for s in a.sections for x in s.sentences] + list(a.unknown)
    b = a.brief
    lines = [x.text for x in b.lines]
    multi = a.trace.route == "multi"
    n_max, c_max = (brief.MULTI_LINES, brief.MULTI_CHARS) if multi else brief.BUDGET[b.form]
    hd = head(a, b.form, multi)
    bc = sum(len(t) for t in lines)
    yn = b.form == "yesno" and bool(lines)
    return {
        "set": set_name, "id": q["id"], "split": q["split"], "trade": q["trade"], "question": q["text"],
        "route": a.trace.route, "form": b.form,
        "content": any(s.source in CONTENT and s.sentences for s in a.sections),
        "full_chars": sum(len(t) for t in full), "brief_chars": bc, "head_chars": sum(len(t) for t in hd),
        "full_lines": len(full), "brief_lines": len(lines), "more": b.more,
        "over_budget": len(lines) > n_max or (len(lines) > 1 and bc > c_max),
        "yesno_first_brief": bool(brief.YESNO_S.search(lines[0])) if yn else None,
        "yesno_first_head": bool(brief.YESNO_S.search(hd[0])) if yn and hd else None,
        "full": full, "brief": lines, "head": hd,
    }  # fmt: skip


def pct(xs: list[int], p: float) -> int:
    return sorted(xs)[min(len(xs) - 1, int(len(xs) * p))] if xs else 0


def summary(rows: list[dict]) -> dict:
    con = [r for r in rows if r["content"]]
    yn = [r for r in con if r["yesno_first_brief"] is not None]
    return {
        "n": len(rows),
        "content": len(con),
        "full_chars_med_p90": (statistics.median([r["full_chars"] for r in con]) if con else 0, pct([r["full_chars"] for r in con], 0.9)),
        "brief_chars_med_p90": (statistics.median([r["brief_chars"] for r in con]) if con else 0, pct([r["brief_chars"] for r in con], 0.9)),
        "head_chars_med_p90": (statistics.median([r["head_chars"] for r in con]) if con else 0, pct([r["head_chars"] for r in con], 0.9)),
        "brief_over_200": sum(r["brief_chars"] > 200 for r in con),
        "full_over_200": sum(r["full_chars"] > 200 for r in con),
        "over_budget": sum(r["over_budget"] for r in con),
        "folded(more>0)": sum(r["more"] > 0 for r in con),
        "yesno_n": len(yn),
        "yesno_conclusion_first_brief": sum(r["yesno_first_brief"] for r in yn),
        "yesno_conclusion_first_head": sum(bool(r["yesno_first_head"]) for r in yn),
        "brief_differs_from_head": sum(r["brief"] != r["head"] for r in con),
        "forms": dict(Counter(r["form"] for r in rows).most_common()),
    }  # fmt: skip


def main() -> None:
    utf8_stdout()
    rnd = random.Random(SEED)
    sets = [("beginner", jsonl(BEGINNER)), ("bank", bank())]
    rows = []
    for name, qs in sets:
        for q in qs:
            ctx = TurnContext(user_id=uuid.uuid4(), today=TODAY)
            a = asyncio.run(run_turn(q["text"], ctx, kb=kb())).answer
            rows.append(row(name, q, a))
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[f"{r['set']}:{r['split']}"].append(r)
        groups[r["set"]].append(r)
    out = {k: summary(v) for k, v in sorted(groups.items())}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "brief_eval.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS / "brief_answers.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )

    # 판정 묶음: 내용 있는 답 중 head와 brief가 다른 것, A/B 순서 섞기
    items, keys = [], []
    for r in rows:
        if not r["content"] or r["brief"] == r["head"]:
            continue
        pid = f"p{rnd.randrange(16**8):08x}"
        a_is = rnd.choice(["brief", "head"])
        b_is = "head" if a_is == "brief" else "brief"
        items.append({"pid": pid, "question": r["question"], "full": " ".join(r["full"]),
                      "A": " ".join(r[a_is]), "B": " ".join(r[b_is])})  # fmt: skip
        keys.append(
            {
                "pid": pid,
                "set": r["set"],
                "id": r["id"],
                "split": r["split"],
                "form": r["form"],
                "A": a_is,
            }
        )
    rnd.shuffle(items)
    for name, data in (("brief_pairs", items), ("brief_pairs_key", keys)):
        (OUT / f"{name}.jsonl").write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in data), encoding="utf-8"
        )
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"판정 묶음 {len(items)}쌍 → {(OUT / 'brief_pairs.jsonl').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
