"""전문가 답 평가 실행기. 상담과 같은 입력(집 정보 글 + 질문 한 문장)으로 그 공정 에이전트의 answer를 부르고
코드로 채점한다. --judge N이면 층화 표본 N개를 판정 LLM(기준표 rubric_expert_v1, 역할 judge)으로 매긴다.

실행 (저장소 루트에서):
    cd backend
    uv run python ../evaluation/expert/run.py --sample 20                     # 호출 수 · 예상 비용만
    uv run python ../evaluation/expert/run.py --sample 20 --judge 10 --fake   # 가짜 LLM, 무료
    uv run python ../evaluation/expert/run.py --sample 20 --fake --batch      # 가짜 Batch, 무료
    uv run python ../evaluation/expert/run.py --sample 20 --judge 10 --live   # 실제 호출 (유료)
    uv run python ../evaluation/expert/run.py --trade dobae --live --batch    # 한 공정만 Batch (유료, 50% 할인)
    uv run python ../evaluation/expert/run.py --rescore <결과 폴더>           # 다시 채점만
결과: evaluation/expert/results/<날짜-시각>/raw.json · summary.md
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, runner, trades
from evaluation.expert import score as S
from evaluation.judge import judge


def default_cases() -> Path:
    full = HERE / "cases_5k.jsonl"
    return full if full.exists() else HERE / "sample_100.jsonl"


async def call(case: dict):
    inp = case["input"]
    return await trades.agent(case["trade"]).answer(inp["question"], inp["context"])


def to_result(case: dict, c: runner.Call) -> dict:
    return {
        "id": case["id"],
        "split": case["split"],
        "category": case["category"],
        "trade": case["trade"],
        "topic": case["topic"],
        "status": "ok" if c.error is None else "failed",
        "reason": c.error,
        "raw": c.raw,
        "shown": c.result.answer.model_dump() if c.result is not None else None,
        "usage": c.usage,
        "scores": S.score(case, c.raw) if c.raw is not None else None,
    }


async def run(
    cases: list[dict],
    *,
    judge_ids: set[str],
    mode: str,
    concurrency: int = 4,
    out_dir: Path | None = None,
    poll_s: float | None = None,
) -> list[dict]:
    calls = await runner.run(
        cases,
        call,
        mode=mode,
        witness=lambda case: case["expect"]["ideal"],
        concurrency=concurrency,
        batch_file=(out_dir / "batch.json") if out_dir else None,
        poll_s=poll_s,
    )
    results = [to_result(c, x) for c, x in zip(cases, calls, strict=True)]
    by_id = {r["id"]: r for r in results}
    picked = [c for c in cases if c["id"] in judge_ids and by_id[c["id"]]["shown"]]
    if picked:

        async def grade(case: dict):
            t, inp = case["trade"], case["input"]
            text = judge.expert_user(
                inp["context"], inp["question"], by_id[case["id"]]["shown"], trades.sources(t)
            )
            return await judge.judge(trades.knowledge(t), text, judge.EXPERT)

        graded = await runner.run(
            picked,
            grade,
            mode=mode,
            witness=lambda case: judge.fake(judge.EXPERT),
            concurrency=concurrency,
            batch_file=(out_dir / "batch_judge.json") if out_dir else None,
            poll_s=poll_s,
        )
        for case, g in zip(picked, graded, strict=True):
            r = by_id[case["id"]]
            if g.result is not None:
                r["judge"] = g.result
            else:
                r["judge_error"] = g.error
            if g.usage:
                r["judge_usage"] = g.usage
    return results


def rescore(results: list[dict], cases: dict[str, dict]) -> None:
    for r in results:
        if r.get("raw") is not None:
            r["scores"] = S.score(cases[r["id"]], r["raw"])


# ---------------------------------------------------------------- 요약 표
def _rate(rows: list[dict], pred) -> str:
    rows = [r for r in rows if r.get("scores")]
    return runner.pct(sum(bool(pred(r)) for r in rows), len(rows))


def _all(r: dict) -> bool:
    return all(r["scores"]["checks"].values())


def summarize(meta: dict, results: list[dict]) -> str:
    by = {s: [r for r in results if r["split"] == s] for s in gen.SPLITS}
    groups = {"전체": results, "dev": by["dev"], "held-out": by["heldout"]}
    lines = [
        "# 전문가 답 평가 결과",
        "",
        (
            f"모델 {meta['model']} · effort {meta['effort']} · 프롬프트 {meta['prompt_version']} · "
            f"모드 {meta.get('mode', '-')} · 사례 {len(results)}개 (dev {len(by['dev'])} · "
            f"held-out {len(by['heldout'])}) · 층 {meta['stratify']} · 시드 {meta['seed']} · "
            f"사례 파일 {meta['cases']}"
        ),
        "",
        "채점은 모델 원문 기준이에요. 300자를 넘거나 숫자를 지어낸 답은 상담 화면에 보이지 않아요.",
        "",
        "| 검사 | " + " | ".join(groups) + " |",
        "| --- |" + " ---: |" * len(groups),
    ]
    ok = [runner.pct(sum(r["status"] == "ok" for r in g), len(g)) for g in groups.values()]
    lines.append("| 답 생성 성공 (화면에 보임) | " + " | ".join(ok) + " |")
    lines.append(
        "| **모든 코드 검사 통과** | " + " | ".join(_rate(g, _all) for g in groups.values()) + " |"
    )
    for cid, desc in S.CHECKS.items():
        row = [_rate(g, lambda r, cid=cid: r["scores"]["checks"][cid]) for g in groups.values()]
        lines.append(f"| {desc} | " + " | ".join(row) + " |")
    chars = [r["scores"]["chars"] for r in results if r.get("scores")]
    if chars:
        lines.append(f"\n답 길이: 중앙값 {statistics.median(chars):.0f}자 · 최대 {max(chars)}자")

    judged = [r for r in results if r.get("judge")]
    if judged or any("judge_error" in r for r in results):
        errors = sum("judge_error" in r for r in results)
        lines += [
            "",
            f"## 판정 LLM ({meta.get('rubric')}, {len(judged)}개 · 실패 {errors}개)",
            "",
            "| 기준 | 평균 | 3점 이하 |",
            "| --- | ---: | ---: |",
        ]
        for key, label in judge.EXPERT.criteria.items():
            s = [r["judge"][key]["score"] for r in judged]
            mean = f"{statistics.mean(s):.2f}" if s else "-"
            lines.append(f"| {label} | {mean} | {runner.pct(sum(x <= 3 for x in s), len(s))} |")

    for title, key in (("주제별", "topic"), ("공정별", "trade")):
        lines += [
            "",
            f"## {title}",
            "",
            f"| {key} | 사례 | 성공 | 모든 검사 | 숫자 없음 | 쉬운 말 | 핵심 말 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for v in sorted({r[key] for r in results}):
            g = [r for r in results if r[key] == v]
            cells = [
                runner.pct(sum(r["status"] == "ok" for r in g), len(g)),
                _rate(g, _all),
                _rate(g, lambda r: r["scores"]["checks"]["no_number"]),
                _rate(g, lambda r: r["scores"]["checks"]["terms"]),
                _rate(g, lambda r: r["scores"]["checks"]["on_topic"]),
            ]
            lines.append(f"| {v} | {len(g)} | " + " | ".join(cells) + " |")

    use = [r["usage"] for r in results if r.get("usage")]
    judge_u = [r["judge_usage"] for r in results if r.get("judge_usage")]
    lines += ["", "## 비용 · 시간", ""]
    lines += runner.cost_table([("전문가 답", use), ("판정", judge_u)])
    if use:
        from evaluation.common import cost

        total = cost.total_cost(use)[0] + cost.total_cost(judge_u)[0]
        lines.append(f"\n사례 1개당 비용 {total / len(results):.5f}달러 · 가격 {cost.PRICE_SOURCE}")

    bad = [r for r in results if not r.get("scores") or not _all(r)]
    if bad:
        lines += ["", "## 실패 예 (앞 15개)", ""]
        for r in bad[:15]:
            if not r.get("scores"):
                lines.append(f"- {r['id']} ({r['category']}): 답 실패 {r['reason']}")
                continue
            failed = [k for k, ok in r["scores"]["checks"].items() if not ok]
            why = "; ".join(f"{k}: {r['scores']['detail'].get(k, '')}" for k in failed)
            lines.append(f"- {r['id']} ({r['category']}): {why}")
    return "\n".join(lines) + "\n"


def write(out_dir: Path, meta: dict, results: list[dict]) -> str:
    report = summarize(meta, results)
    runner.write(out_dir, meta, results, report)
    return report


# ---------------------------------------------------------------- 진입점
def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="전문가 답 평가 실행기")
    ap.add_argument("--trade", action="append", help="이 공정만 (여러 번 줄 수 있음)")
    ap.add_argument("--judge", type=int, default=0, help="판정 LLM으로 매길 층화 표본 수")
    runner.add_args(ap)
    args = ap.parse_args()

    if args.rescore:
        raw = json.loads((args.rescore / "raw.json").read_text(encoding="utf-8"))
        cases = {c["id"]: c for c in gen.read_jsonl(ROOT / raw["meta"]["cases"])}
        rescore(raw["results"], cases)
        print(write(args.rescore, raw["meta"], raw["results"]))
        return

    runner.load_env(ROOT)
    from app.agent import llm
    from app.agent.trade import EXPERT_PROMPT
    from app.config import settings

    path = (args.cases or default_cases()).resolve()
    cases = gen.read_jsonl(path)
    if args.trade:
        cases = [c for c in cases if c["trade"] in args.trade]
    cases = runner.select(
        cases,
        split=args.split,
        sample=args.sample,
        stratify=args.stratify,
        seed=args.seed,
        ids=args.case,
    )
    if not cases:
        sys.exit("고른 사례가 없어요.")
    jr = gen.rng("judge", args.seed)
    picked = gen.stratified_sample(cases, args.judge, key=lambda c: gen.get(c, args.stratify), r=jr)
    judge_ids = {c["id"] for c in picked} if args.judge else set()
    model, effort = llm.pick("expert")
    counts = Counter(gen.get(c, args.stratify) for c in cases)
    print(f"사례 파일 {path.relative_to(ROOT)} · 층 {args.stratify}: ", end="")
    print(", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(  # 전문가 · 판정 시스템은 공정 지식마다 다르다
        runner.estimate_text(
            "expert", cases, len(judge_ids), model, effort, "judge_expert", "trade", judge_ids
        )
    )
    mode = runner.mode_of(args)
    if mode is None:
        print(
            "\n실제로 돌리려면 --live (유료), 코드 경로만 보려면 --fake (무료). Batch는 --batch를 더한다"
        )
        return
    if args.live:
        if not (os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key):
            sys.exit(".env에 ANTHROPIC_API_KEY를 넣어 주세요.")
        settings.llm_live = True

    stamp = datetime.now().strftime("%Y%m%d-%H%M") + ("-fake" if args.fake else "")
    out_dir = args.out or HERE / "results" / stamp
    meta = {
        "model": "fake" if args.fake else model,
        "effort": "-" if args.fake else effort,
        "prompt_version": EXPERT_PROMPT.removesuffix(".md").replace("_", "-"),
        "rubric": judge.EXPERT.version if judge_ids else None,
        "mode": mode,
        "cases": path.relative_to(ROOT).as_posix(),
        "trades": args.trade or list(trades.registered()),
        "split": args.split,
        "sample": args.sample,
        "stratify": args.stratify,
        "seed": args.seed,
        "judge": len(judge_ids),
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    results = asyncio.run(
        run(cases, judge_ids=judge_ids, mode=mode, concurrency=args.concurrency, out_dir=out_dir)
    )
    print()
    print(write(out_dir, meta, results))
    print(f"저장: {out_dir}")


if __name__ == "__main__":
    main()
