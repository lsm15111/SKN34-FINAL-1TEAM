"""공정 의견 평가 실행기. 공정 키를 받아 그 공정 에이전트(spec.agent)를 평가한다.

사례마다 상담 카드로 견적(spec.build)과 입력 글(consult.service.plan_text)을 만들고 spec.agent.plan을 부른 뒤
코드로 채점한다. --judge N이면 그중 층화 표본 N개를 판정 LLM(evaluation/judge, 역할 judge)으로 매긴다.
결과는 evaluation/plan/<공정>/results/<날짜-시각>/에 raw.json(원문)과 summary.md(표)로 남는다.

실행 (저장소 루트에서):
    cd backend
    uv run python ../evaluation/run_agent.py --trade dobae --sample 20                 # 호출 수 · 예상 비용만
    uv run python ../evaluation/run_agent.py --trade dobae --sample 20 --fake          # 가짜 LLM, 무료
    uv run python ../evaluation/run_agent.py --trade dobae --sample 20 --fake --batch  # 가짜 Batch, 무료
    uv run python ../evaluation/run_agent.py --trade dobae --sample 20 --live          # 실제 호출 (유료)
    uv run python ../evaluation/run_agent.py --trade dobae --live --batch              # Batch (유료, 50% 할인)
    uv run python ../evaluation/run_agent.py --trade dobae --rescore <결과 폴더>       # 다시 채점만
    uv run python ../evaluation/run_agent.py --trade dobae --sample 20 --fake --plan-prompt v2  # 프롬프트 v2로
--live 없이는 유료 호출을 하지 않는다. 단계마다(T1 20개 · T2 150개 · T3 5,000개) 금액을 먼저 보이고 승인받는다.
--plan-prompt v2: 같은 지식으로 prompts/<지식 이름>_v2.md를 써서 공정 에이전트를 다시 만든다 (v1 · v2를 같은 사례로
비교). 결과 폴더 이름과 summary에 프롬프트 버전이 붙는다.
Batch는 결과 폴더의 batch.json에 Batch id를 적어 두고, 기다리다 끊기면 같은 --out으로 다시 돌려 결과만 받는다.
공정 의견 캐시(LLM_PLAN_CACHE_S)는 평가 동안 끈다.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, runner, trades
from evaluation.judge import judge
from evaluation.plan import config
from evaluation.scorers import trade_plan, witness


def case_dir(trade: str) -> Path:
    return HERE / "plan" / trade


def default_cases(trade: str) -> Path:
    full = case_dir(trade) / "cases_5k.jsonl"
    return full if full.exists() else case_dir(trade) / "sample_100.jsonl"


def ideal(trade: str):
    """모범 답 (가짜 LLM): 설정에 손으로 쓴 답, 없으면 규칙 예문으로 만든 답"""
    cfg = config.get(trade)
    if cfg.witness:
        return cfg.witness
    rules, src, label = trade_plan.rules(trade), trades.sources(trade), trades.label(trade)
    return lambda case: witness.generic(case, label, rules, src)


def plan_agent(trade: str, version: str | None = None):
    """공정 의견 에이전트. version(예: v2)을 주면 같은 지식 · 화면 말로 prompts/<지식 이름>_<버전>.md를 써서
    다시 만든다. 파일이 없으면 FileNotFoundError"""
    agent = trades.agent(trade)
    if not version:
        return agent
    from app.agent import trade as agent_trade

    name = f"{agent.name}_{version}.md"
    if not (Path(agent_trade.__file__).parent / "prompts" / name).exists():
        raise FileNotFoundError(
            f"공정 의견 프롬프트 파일이 없어요: backend/app/agent/prompts/{name} "
            f"(--plan-prompt {version} 옵션은 그 파일이 있는 브랜치에서 써요)"
        )
    return agent_trade.TradeAgent.load(agent.name, trades.label(trade), name)


@contextmanager
def no_plan_cache():
    from app.config import settings

    old = settings.llm_plan_cache_s
    settings.llm_plan_cache_s = 0
    try:
        yield
    finally:
        settings.llm_plan_cache_s = old


def to_result(trade: str, case: dict, call: runner.Call) -> dict:
    res = {
        "id": case["id"],
        "split": case["split"],
        "category": case["category"],
        "status": "ok" if call.error is None else "failed",
        "reason": call.error,
        "raw": call.raw,
        "shown": None,
        "dropped": None,
        "usage": call.usage,
        "scores": None,
    }
    if call.result is not None:
        res["shown"], res["dropped"] = call.result.plan.model_dump(), call.result.dropped
    if call.raw is not None:
        sources = set(trades.sources(trade))
        res["scores"] = trade_plan.score(trade, call.raw, case["expect"], sources)
    return res


async def run(
    trade: str,
    cases: list[dict],
    *,
    judge_ids: set[str],
    mode: str,
    concurrency: int = 4,
    out_dir: Path | None = None,
    poll_s: float | None = None,
    plan_prompt: str | None = None,
) -> list[dict]:
    agent = plan_agent(trade, plan_prompt)

    async def plan(case: dict):
        inp = case["input"]
        return await agent.plan(trades.plan_text(trade, inp), trades.quote(trade, inp))

    batch = (out_dir / "batch.json") if out_dir else None
    with no_plan_cache():
        calls = await runner.run(
            cases,
            plan,
            mode=mode,
            witness=ideal(trade),
            concurrency=concurrency,
            batch_file=batch,
            poll_s=poll_s,
        )
    results = [to_result(trade, c, call) for c, call in zip(cases, calls, strict=True)]
    picked = [c for c, r in zip(cases, results, strict=True) if c["id"] in judge_ids and r["shown"]]
    if picked:
        by_id = {r["id"]: r for r in results}
        skill, src = trades.knowledge(trade), trades.sources(trade)

        async def grade(case: dict):
            text = judge.user(trades.render(trade, case["input"]), by_id[case["id"]]["shown"], src)
            return await judge.judge(skill, text, judge.PLAN)

        jfile = (out_dir / "batch_judge.json") if out_dir else None
        graded = await runner.run(
            picked,
            grade,
            mode=mode,
            witness=lambda case: judge.fake(judge.PLAN),
            concurrency=concurrency,
            batch_file=jfile,
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


def rescore(trade: str, results: list[dict], cases: dict[str, dict]) -> None:
    """저장된 원문으로 코드 채점만 다시 한다 (호출 없음)."""
    sources = set(trades.sources(trade))
    for res in results:
        if res.get("raw") is not None:
            res["scores"] = trade_plan.score(trade, res["raw"], cases[res["id"]]["expect"], sources)


# ---------------------------------------------------------------- 요약 표
def _rate(results: list[dict], pred) -> str:
    rows = [r for r in results if r.get("scores")]
    return runner.pct(sum(bool(pred(r)) for r in rows), len(rows))


def summarize(meta: dict, results: list[dict]) -> str:
    trade = meta["trade"]
    rules = trade_plan.rules(trade)
    by_split = {s: [r for r in results if r["split"] == s] for s in gen.SPLITS}
    groups = {"전체": results, "dev": by_split["dev"], "held-out": by_split["heldout"]}
    head = (
        f"모델 {meta['model']} · effort {meta['effort']} · 프롬프트 {meta['prompt_version']} · "
        f"모드 {meta.get('mode', '-')} · 사례 {len(results)}개 (dev {len(by_split['dev'])} · "
        f"held-out {len(by_split['heldout'])}) · 층 {meta['stratify']} · 시드 {meta['seed']} · "
        f"사례 파일 {meta['cases']}"
    )
    lines = [
        f"# {meta.get('label', trade)} 공정 의견 평가 결과",
        "",
        head,
        "",
        "채점은 모델이 쓴 원문 기준이에요. 화면에는 코드 검사로 버린 항목을 뺀 의견이 보여요.",
        "",
        "| 검사 | " + " | ".join(groups) + " |",
        "| --- |" + " ---: |" * len(groups),
    ]
    ok_row = [runner.pct(sum(r["status"] == "ok" for r in g), len(g)) for g in groups.values()]
    lines.append("| 의견 생성 성공 (화면에 보임) | " + " | ".join(ok_row) + " |")
    dropped = [sum(r["dropped"] or 0 for r in g) for g in groups.values()]
    lines.append("| 규칙 위반으로 버린 항목 수 | " + " | ".join(map(str, dropped)) + " |")
    all_row = [_rate(g, lambda r: all(r["scores"]["checks"].values())) for g in groups.values()]
    lines.append("| **모든 코드 검사 통과** | " + " | ".join(all_row) + " |")
    for cid, desc in trade_plan.CHECKS.items():
        row = [_rate(g, lambda r, cid=cid: r["scores"]["checks"][cid]) for g in groups.values()]
        lines.append(f"| {desc} | " + " | ".join(row) + " |")

    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        for rid, ok in (r.get("scores") or {}).get("rules", {}).items():
            counts[rid][0] += ok
            counts[rid][1] += 1
    lines += ["", "## 규칙별", "", "| 규칙 | 뜻 | 통과 |", "| --- | --- | ---: |"]
    for rid in sorted(counts):
        ok, n = counts[rid]
        desc = rules[rid].desc if rid in rules else "-"
        lines.append(f"| `{rid}` | {desc} | {runner.pct(ok, n)} |")

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
        for key, label in judge.PLAN.criteria.items():
            s = [r["judge"][key]["score"] for r in judged]
            low = sum(x <= 3 for x in s)
            mean = f"{statistics.mean(s):.2f}" if s else "-"
            lines.append(f"| {label} | {mean} | {runner.pct(low, len(s))} |")

    lines += [
        "",
        "## 범주별",
        "",
        "| 범주 | 사례 | 성공 | 모든 검사 | 꼭 언급 | 언급 안 됨 | 쉬운 말 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cat in sorted({r["category"] for r in results}):
        g = [r for r in results if r["category"] == cat]
        cells = [
            runner.pct(sum(r["status"] == "ok" for r in g), len(g)),
            _rate(g, lambda r: all(r["scores"]["checks"].values())),
            _rate(g, lambda r: r["scores"]["checks"]["must"]),
            _rate(g, lambda r: r["scores"]["checks"]["must_not"]),
            _rate(g, lambda r: r["scores"]["checks"]["terms"]),
        ]
        lines.append(f"| {cat} | {len(g)} | " + " | ".join(cells) + " |")

    plan_u = [r["usage"] for r in results if r.get("usage")]
    judge_u = [r["judge_usage"] for r in results if r.get("judge_usage")]
    lines += ["", "## 비용 · 시간", ""]
    lines += runner.cost_table([("공정 의견", plan_u), ("판정", judge_u)])
    if plan_u:
        from evaluation.common import cost

        total = cost.total_cost(plan_u)[0] + cost.total_cost(judge_u)[0]
        lines.append(f"\n사례 1개당 비용 {total / len(results):.4f}달러 · 가격 {cost.PRICE_SOURCE}")

    bad = [
        r
        for r in results
        if r["status"] != "ok" or not r.get("scores") or not all(r["scores"]["checks"].values())
    ]
    if bad:
        lines += ["", "## 실패 예 (앞 15개)", ""]
        for r in bad[:15]:
            if not r.get("scores"):
                lines.append(f"- {r['id']} ({r['category']}): 의견 실패 {r['reason']}")
                continue
            failed = [k for k, ok in r["scores"]["checks"].items() if not ok]
            why = "; ".join(f"{k}: {r['scores']['detail'].get(k, '')}" for k in failed)
            head = f"의견 실패 {r['reason']} · " if r["status"] != "ok" else ""
            lines.append(f"- {r['id']} ({r['category']}): {head}{why}")
    return "\n".join(lines) + "\n"


def write(out_dir: Path, meta: dict, results: list[dict]) -> str:
    report = summarize(meta, results)
    runner.write(out_dir, meta, results, report)
    return report


# ---------------------------------------------------------------- 진입점
def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="공정 의견 평가 실행기")
    ap.add_argument("--trade", required=True, help=f"공정 키 ({', '.join(trades.registered())})")
    ap.add_argument("--judge", type=int, default=0, help="판정 LLM으로 매길 층화 표본 수")
    ap.add_argument(
        "--plan-prompt", help="공정 의견 프롬프트 버전 (예: v2). 비우면 공정 스펙에 등록된 프롬프트"
    )
    runner.add_args(ap)
    args = ap.parse_args()
    trade = args.trade
    trades.spec(trade)  # 등록된 공정인지 먼저 본다
    try:
        agent = plan_agent(trade, args.plan_prompt)
    except FileNotFoundError as e:
        sys.exit(str(e))

    if args.rescore:
        raw = json.loads((args.rescore / "raw.json").read_text(encoding="utf-8"))
        cases = {c["id"]: c for c in gen.read_jsonl(ROOT / raw["meta"]["cases"])}
        rescore(trade, raw["results"], cases)
        print(write(args.rescore, raw["meta"], raw["results"]))
        return

    runner.load_env(ROOT)
    from app.agent import llm
    from app.config import settings

    path = (args.cases or default_cases(trade)).resolve()
    cases = runner.select(
        gen.read_jsonl(path),
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
    model, effort = llm.pick("plan")
    print(f"사례 파일 {path.relative_to(ROOT)} · 층 {args.stratify}: ", end="")
    print(
        ", ".join(
            f"{k} {v}" for k, v in sorted(Counter(gen.get(c, args.stratify) for c in cases).items())
        )
    )
    print(runner.estimate_text(trade, cases, len(judge_ids), model, effort))
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

    stamp = datetime.now().strftime("%Y%m%d-%H%M") + f"-{agent.plan_prompt_version}"
    stamp += "-fake" if args.fake else ""
    out_dir = args.out or case_dir(trade) / "results" / stamp
    meta = {
        "trade": trade,
        "label": trades.label(trade),
        "model": "fake" if args.fake else model,
        "effort": "-" if args.fake else effort,
        "prompt_version": agent.plan_prompt_version,
        "plan_prompt": args.plan_prompt or "스펙에 등록된 것",
        "rubric": judge.PLAN.version if judge_ids else None,
        "mode": mode,
        "cases": path.relative_to(ROOT).as_posix(),
        "split": args.split,
        "sample": args.sample,
        "stratify": args.stratify,
        "seed": args.seed,
        "judge": len(judge_ids),
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    results = asyncio.run(
        run(
            trade,
            cases,
            judge_ids=judge_ids,
            mode=mode,
            concurrency=args.concurrency,
            out_dir=out_dir,
            plan_prompt=args.plan_prompt,
        )
    )
    print()
    print(write(out_dir, meta, results))
    print(f"저장: {out_dir}")


if __name__ == "__main__":
    main()
