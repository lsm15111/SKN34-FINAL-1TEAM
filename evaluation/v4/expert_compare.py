"""공정 전문가 무료 비교(LLM 0회): run_v4_answers 답 파일에서 시스템마다 길이 · 숫자 · 출처 · 물음 · 실패 · 비용 · 시간을 견줘요.

    cd backend
    uv run python ../evaluation/v4/expert_compare.py --answers ../evaluation/v4/runs/expert-cmp67/answers.jsonl
    uv run python ../evaluation/v4/expert_compare.py --pick      # 공정 고르기(코드)를 RAG 질문 390개 공정 표시로 재요
    uv run python ../evaluation/v4/expert_compare.py --kb        # K 문항(sets/trade_*.jsonl) 정답 사실이 받는 자료에 드는 몫

- 전체 · 묶음(group)별 · '전문가가 실제로 답한 문항'(v4_expert의 answer_question이 expert 길로 간 질문)만 따로 봐요.
  마지막 묶음이 새 엔진이 바꾼 몫이라 두 시스템 차이는 여기서 커요(나머지는 같은 v2g · v3 길).
- 길이: 보이는 글(카드 글 포함, 코드가 붙인 다음 할 일 줄 포함) 글자 · 문장 수. 숫자: 글의 숫자 수와 그중 '받은 계산 값 ·
  질문'에 없는 숫자 수(받은 값은 판정기용 요약이라 잘려 있어 많게 셀 수 있어요). 출처: 모델에 간 출처 이름 수(sources ·
  hits 제목)와 글에 출처 말(시방서 · 기준 · 자료 · 가이드 …)이 있는 답 수. 물음: 글이 물음표로 끝나는 답 수.
- 실패: 오류 줄 · 끝나지 않은 턴 · answer_question 오류 · 전문가 실패(물러섬)를 나눠 세요.
- 비교는 판정이 아니에요. 품질 판정은 grade.py(Opus, 리드)가 해요.
- --kb(공정 지식 묶음이 병합된 갈래에서): K 갈래 문항(gold = 정답 사실 낱말, `|`는 다른 표기)마다 글 쓰는 모델이 받는
  자료에 정답 사실이 몇 몫 드는지 견줘요(LLM · 임베딩 없음, 저장소 지식 + 공정 지식 묶음 색인).
  - v2g: 지금 엔진이 비서에게 주는 조각(질문 낱말로 공정 하나일 때만 그 공정, k=6, 조각 글 앞 320자) + 공정 설정 줄.
  - expert_evidence: 전문가가 받는 조각(공정 고르기 → 그 공정 + 공통 8개, 520자). 고른 공정이 없으면 v2g와 같아요.
  - expert_all: 위 조각 + 전문가 지시문 · 입문서(전문 지식 G). 전문가가 '알 수 있는' 몫이에요(답에 쓴 몫이 아님).
  - 비교 글 맞추기는 trade_kb_eval.norm과 같아요(소문자 · 공백 · 숫자 쉼표 · 단위 표기).
"""

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from kit import jsonl, utf8_stdout

NUM = re.compile(r"\d+(?:[.,]\d+)*")
SENT = re.compile(r"(?<=[.!?요])\s+|\n+")
SOURCE_WORDS = re.compile(
    r"시방서|표준|기준|자료|가이드|안내서|매뉴얼|법|고시|소비자원|LH|KCS|환경부|국토교통부|제조사|품셈"
)


def numbers(text: str) -> list[str]:
    return [m.group(0).replace(",", "") for m in NUM.finditer(text or "")]


def sentences(text: str) -> int:
    return len([s for s in SENT.split(text or "") if s.strip()])


def sources_given(row: dict) -> set[str]:
    """모델에 간 출처 이름(answer_question · search_knowledge 결과의 sources · hits 제목)."""
    got: set[str] = set()
    for t in row.get("tool_rows") or []:
        seen = t.get("seen") or {}
        got |= {s for s in seen.get("sources") or [] if isinstance(s, str)}
        got |= {
            h.get("title") for h in seen.get("hits") or [] if isinstance(h, dict) and h.get("title")
        }
    return got


def expert_used(row: dict) -> bool:
    return any(
        (p.get("expert") or {}).get("used") == "expert" for p in row.get("answer_paths") or []
    )


def pctl(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


def stats(rows: list[dict], errors: list[dict]) -> dict:
    texts = [r.get("text") or "" for r in rows]
    nums = [numbers(t) for t in texts]
    loose = []
    for r, ns in zip(rows, nums, strict=True):
        known = set(numbers(f"{r.get('facts_given') or ''} {r.get('question') or ''}"))
        loose.append(sum(1 for n in ns if n not in known))
    given = [len(sources_given(r)) for r in rows]
    cost = [float(r.get("cost_usd") or 0) for r in rows]
    ms = [r["ms"] for r in rows if isinstance(r.get("ms"), (int, float))]
    tool_err = sum(
        1 for r in rows for p in r.get("answer_paths") or [] if p.get("error")
    )  # answer_question 오류
    fell = Counter(
        (p.get("expert") or {}).get("why_v2g")
        for r in rows
        for p in r.get("answer_paths") or []
        if (p.get("expert") or {}).get("why_v2g")
    )
    return {
        "n": len(rows),
        "errors": len(errors),
        "not_done": sum(r.get("turn_status") != "done" for r in rows),
        "tool_errors": tool_err,
        "expert_used": sum(expert_used(r) for r in rows),
        "fallback": dict(fell),
        "chars_mean": round(statistics.mean(len(t) for t in texts), 1) if texts else None,
        "chars_median": pctl([len(t) for t in texts], 0.5),
        "sentences_mean": round(statistics.mean(sentences(t) for t in texts), 2) if texts else None,
        "numbers_total": sum(len(x) for x in nums),
        "answers_with_numbers": sum(bool(x) for x in nums),
        "numbers_not_in_given": sum(loose),
        "sources_given_mean": round(statistics.mean(given), 2) if given else None,
        "answers_with_sources_given": sum(g > 0 for g in given),
        "answers_with_source_words": sum(bool(SOURCE_WORDS.search(t)) for t in texts),
        "ends_with_question": sum(t.rstrip().endswith("?") for t in texts),
        "cost_usd": round(sum(cost), 4),
        "turn_usd_median": pctl(cost, 0.5),
        "turn_usd_p90": pctl(cost, 0.9),
        "turn_ms_median": pctl(ms, 0.5),
        "turn_ms_p90": pctl(ms, 0.9),
        "llm_calls_mean": round(statistics.mean(r.get("llm_calls") or 0 for r in rows), 2)
        if rows
        else None,
    }


GROUP_KEYS = (
    "n",
    "expert_used",
    "chars_mean",
    "numbers_total",
    "sources_given_mean",
    "ends_with_question",
    "turn_usd_median",
    "turn_ms_median",
)


def compare(answers: Path) -> dict:
    rows = jsonl(answers)
    errors = jsonl(answers.with_name("errors.jsonl"))
    systems = list(dict.fromkeys(r["system"] for r in rows))
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["system"]].append(r)
    used = {r["id"] for r in by.get("v4_expert", []) if expert_used(r)}
    out: dict = {
        "answers": str(answers),
        "systems": systems,
        "all": {},
        "expert_used": {},
        "groups": {},
    }
    for s in systems:
        errs = [e for e in errors if e["system"] == s]
        out["all"][s] = stats(by[s], errs)
        out["expert_used"][s] = stats([r for r in by[s] if r["id"] in used], [])
        groups = sorted({r["group"] for r in by[s]})
        out["groups"][s] = {
            g: {
                k: v
                for k, v in stats([r for r in by[s] if r["group"] == g], []).items()
                if k in GROUP_KEYS
            }
            for g in groups
        }
    out["expert_used_ids"] = sorted(used)
    return out


# ---- 공정 고르기(코드) ----
RAG_SETS = [ROOT / "evaluation/rag/questions.jsonl", ROOT / "evaluation/rag/questions_300.jsonl"]


def pick_eval() -> dict:
    """RAG 질문(공정 표시: 도배 · 목공 · 공통)에 이 공사 공정이 둘(도배 · 목공)인 집으로 공정을 골라요(질문 낱말 →
    다른 공정 → 지식 조각 갈래). 맞음: 도배 · 목공 질문이 그 공정(둘 다 포함)으로, 공통 질문이 공통(모름 · 다른 공정)으로."""
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT / "backend/tests"))
    from v3_kb import eval_index

    from app.assistant.experts import pick as picking
    from app.knowledge import bm25, other_trades

    ix = eval_index()
    qs = [json.loads(x) for p in RAG_SETS for x in p.read_text(encoding="utf-8").splitlines() if x]
    out: dict = {}
    for split in ("dev", "heldout"):
        c: Counter = Counter()
        how: Counter = Counter()
        for q in (x for x in qs if x["split"] == split):
            text, label = q["text"], q["trade"]
            got = picking.pick(
                text, ("도배", "목공"), other=other_trades.notes_for(text) is not None
            )
            if got.why == "unknown":
                got = picking.infer(bm25.search(ix, text, k=14).hits)
            how[got.why] += 1
            if label == "공통":
                ok = "맞음" if not got.trades else "공통이 전문가로"
            elif label in got.trades:
                ok = "맞음" if len(got.trades) == 1 else "맞음(둘 다)"
            else:
                ok = "공통 근거로" if not got.trades else "다른 공정 전문가로"
            c[(label, ok)] += 1
        out[split] = {
            "n": sum(c.values()),
            "by_label": {f"{k[0]}:{k[1]}": v for k, v in sorted(c.items())},
            "how": dict(how),
        }
    return out


# ---- K 문항으로 받는 자료 견주기(--kb) ----
KB_SETS = [HERE / "sets/trade_dobae.jsonl", HERE / "sets/trade_mokgong.jsonl"]
KO = {"dobae": "도배", "mokgong": "목공"}
_SUBS = [("㎡", "m2"), ("m²", "m2"), ("°c", "℃"), ("º c", "℃"), ("㎜", "mm"), ("㎝", "cm"), ("㎏", "kg"),
         ("×", "x")]  # fmt: skip


def norm(text: str) -> str:
    t = (text or "").lower()
    for a, b in _SUBS:
        t = t.replace(a, b)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"[∼～〜]", "~", t)
    t = re.sub(r"['\"‘’“”`]", "", t)
    return re.sub(r"\s+", "", t)


def gold_found(gold: list[str], text: str) -> list[bool]:
    t = norm(text)
    return [any(norm(alt) in t for alt in g.split("|") if alt.strip()) for g in gold]


def kb_index():
    """평가 색인(tests/v3_kb.eval_index: 저장소 지식 + 공정 지식 묶음). run_v4_answers와 같아요."""
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT / "backend/tests"))
    from v3_kb import eval_index

    return eval_index()


def kb_eval(sets: list[Path]) -> dict:
    from app.agent.trades import TRADES
    from app.assistant.experts import agent as experts
    from app.assistant.experts import pick as picking
    from app.assistant.tools import cards
    from app.knowledge import bm25, other_trades

    ix = kb_index()
    by_name = {c.name: c for c in TRADES.values()}
    rows = [r for p in sets for r in jsonl(p)]
    per: list[dict] = []
    for r in rows:
        q = r["text"]
        one = bm25.trade_of(q)  # v2 grounds: 공정 하나일 때만
        v2 = bm25.search(ix, q, trade=one, k=6).hits
        seen = [
            f"{cards.clean_name(h.title)} {h.section} {cards.clean_source_text(h.text)[:320]}"
            for h in v2
        ]
        if one in by_name:
            c = by_name[one]
            seen += [*c.cautions, *c.survey_vars, *c.prep]
        got = picking.pick(q, ("도배", "목공"), other=other_trades.notes_for(q) is not None)
        if got.why == "unknown":
            got = picking.infer(bm25.search(ix, q, k=experts.SEARCH_K).hits)
        ev: list[str] = []
        guide: list[str] = []
        for t in got.trades:
            hits = experts.evidence(bm25.search(ix, q, trade=t, k=experts.SEARCH_K).hits, t)
            ev += [f"{p.title} {p.section} {p.text}" for p in map(experts.piece_of, hits)]
            guide.append(experts.system_of(experts.SPECS[t]))
        ev = ev or seen  # 고른 공정이 없으면 v2g로 물러서요
        f = {
            "v2g": gold_found(r["gold"], " ".join(seen)),
            "expert_evidence": gold_found(r["gold"], " ".join(ev)),
            "expert_all": gold_found(r["gold"], " ".join([*ev, *guide])),
        }
        per.append({"trade": r["trade"], "split": r["split"], "why": got.why, "picked": got.trades,
                    **{k: sum(v) / len(v) for k, v in f.items()},
                    **{f"{k}_all": all(v) for k, v in f.items()}})  # fmt: skip
    out: dict = {"n": len(per), "pick": dict(Counter(p["why"] for p in per))}
    out["routed_right"] = sum(KO[p["trade"]] in p["picked"] for p in per)
    for key in ("all", "dev", "heldout", "dobae", "mokgong"):
        rs = [p for p in per if key == "all" or key in (p["split"], p["trade"])]
        if not rs:
            continue
        out[key] = {"n": len(rs)} | {
            f"{k}{suf}": round(statistics.mean(float(p[k + suf]) for p in rs), 3)
            for k in ("v2g", "expert_evidence", "expert_all")
            for suf in ("", "_all")
        }
    return out


def main(argv=None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="공정 전문가 무료 비교")
    ap.add_argument(
        "--answers", type=Path, action="append", help="run_v4_answers answers.jsonl(여러 번)"
    )
    ap.add_argument("--pick", action="store_true", help="공정 고르기를 RAG 질문으로 재요")
    ap.add_argument("--kb", action="store_true", help="K 문항 정답 사실이 받는 자료에 드는 몫")
    ap.add_argument(
        "--kb-sets", type=Path, action="append", help="--kb 문항 파일(기본 sets/trade_*.jsonl)"
    )
    ap.add_argument("--out", type=Path, help="결과 JSON을 쓸 곳")
    a = ap.parse_args(argv)
    got: dict = {}
    if a.pick:
        got["pick"] = pick_eval()
    if a.kb:
        got["kb"] = kb_eval(a.kb_sets or KB_SETS)
    for p in a.answers or []:
        got[p.parent.name] = compare(p)
    text = json.dumps(got, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
