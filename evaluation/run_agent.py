"""공정 에이전트 평가 공통 실행기 (도배 wallpaper · 목공 carpentry).

사례마다 계산 엔진으로 견적을 만들고, 상담과 같은 입력 글로 공정 에이전트 plan()을 부른 뒤 코드로 채점한다.
--judge N이면 그중 층화 표본 N개를 판정 LLM(evaluation/judge)으로 매긴다.
결과는 evaluation/<agent>/results/<날짜-시각>/에 raw.json(원문)과 summary.md(표)로 남는다.

실행 (저장소 루트에서):
    cd backend
    uv run python ../evaluation/run_agent.py --agent wallpaper --sample 20              # 호출 수 · 예상 비용만
    uv run python ../evaluation/run_agent.py --agent wallpaper --sample 20 --fake       # 가짜 LLM, 무료
    uv run python ../evaluation/run_agent.py --agent wallpaper --sample 20 --live       # 실제 호출 (유료)
    uv run python ../evaluation/run_agent.py --agent wallpaper --rescore <결과 폴더>    # 다시 채점만
--live 없이는 유료 호출을 하지 않는다. 단계마다(T1 20개 · T2 150개 · T3 5,000개) 금액을 먼저 보이고 승인받는다.
"""

import argparse
import asyncio
import contextvars
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import cost, gen, trades
from evaluation.scorers import trade_plan, witness

LABEL = {"wallpaper": "도배", "carpentry": "목공"}
FAKE_USAGE = {
    "model": "fake",
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "ms": 0,
}
_calls: contextvars.ContextVar[list] = contextvars.ContextVar("calls")
_case: contextvars.ContextVar[dict] = contextvars.ContextVar("case")


def _load_env() -> None:
    """저장소 루트 .env에서 LLM 설정만 읽는다 (값은 화면에 찍지 않는다)."""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            k = k.strip()
            if k in ("ANTHROPIC_API_KEY", "LLM_MODEL", "LLM_EFFORT") and v.strip():
                os.environ.setdefault(k, v.strip())


def default_cases(agent: str) -> Path:
    full = HERE / agent / "cases_5k.jsonl"
    return full if full.exists() else HERE / agent / "sample_100.jsonl"


def select(
    cases: list[dict],
    *,
    split: str = "all",
    sample: int = 0,
    stratify: str = "category",
    seed: int = 1,
    ids: list[str] | None = None,
) -> list[dict]:
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    if split != "all":
        cases = [c for c in cases if c["split"] == split]
    if sample:
        r, key = gen.rng("sample", seed), (lambda c: gen.get(c, stratify))
        # 두 나눔을 같이 뽑을 때는 dev:held-out 2:1을 지킨다
        pick = gen.sample_2to1 if split == "all" else gen.stratified_sample
        cases = pick(cases, sample, key, r)
    return cases


# ---------------------------------------------------------------- 비용 추정 (호출 없음)
def plan_text(agent: str, cases: list[dict], n_judge: int, model: str, effort: str) -> str:
    shape = cost.SHAPES[agent]
    nd = sum(c["split"] == "dev" for c in cases)
    tokens = (
        f"토큰 모양(평균): 공정 의견 입력 {shape.uncached} + 시스템(캐시) {shape.system} · "
        f"출력 {shape.output} ({shape.basis})"
    )
    rows = [
        f"사례 {len(cases)}개 (dev {nd} · held-out {len(cases) - nd})",
        f"호출: 공정 의견 {len(cases)}번 + 판정 {n_judge}번 (지금 설정: {model} · effort {effort})",
        tokens,
        "",
        "| 모델 | 이번 실행 | 같은 사례 Batch |",
        "| --- | ---: | ---: |",
    ]
    for m, label in cost.MODEL_LABEL.items():
        normal = cost.estimate(shape, len(cases), m) + cost.estimate(
            cost.SHAPES["judge"], n_judge, m
        )
        batch = cost.estimate(shape, len(cases), m, batch=True) + cost.estimate(
            cost.SHAPES["judge"], n_judge, m, batch=True
        )
        rows.append(f"| {label} | ${normal:,.2f} | ${batch:,.2f} |")
    rows += ["", f"가격: {cost.PRICE_SOURCE}. 생각 토큰에 따라 달라요."]
    return "\n".join(rows)


# ---------------------------------------------------------------- 실행
def _install(agent: str, fake: bool):
    """llm.parse를 감싸 원문 출력 · 사용량을 남긴다. fake면 부르지 않고 모범 답을 돌려준다."""
    from app.agent import llm

    orig = llm.parse

    async def logged(system, user, schema, **kw):
        if fake:
            out = schema.model_validate(witness.ideal_plan(agent, _case.get()))
            usage = llm.Usage(**FAKE_USAGE)
        else:
            out, usage = await orig(system, user, schema, **kw)
        _calls.get().append((out, usage))
        return out, usage

    llm.parse = logged
    return orig


async def run_case(agent: str, case: dict, mod) -> dict:
    from app.agent.llm import LlmError

    _calls.set([])
    _case.set(case)
    res: dict = {
        "id": case["id"],
        "split": case["split"],
        "category": case["category"],
        "status": "ok",
        "reason": None,
        "raw": None,
        "shown": None,
        "dropped": None,
        "usage": None,
        "scores": None,
    }
    inp = case["input"]
    try:
        r = await mod.plan(trades.card_text(agent, inp), trades.quote(agent, inp))
        res["shown"], res["dropped"] = r.plan.model_dump(), r.dropped
    except LlmError as e:
        res["status"], res["reason"] = "failed", e.reason
    if rec := _calls.get():
        raw, usage = rec[-1]
        res["raw"], res["usage"] = raw.model_dump(), dict(usage.__dict__)
        res["scores"] = trade_plan.score(agent, res["raw"], case["expect"], set(mod.SOURCES))
    return res


async def judge_case(agent: str, case: dict, res: dict, mod, parse, effort: str, fake: bool):
    from app.agent.llm import LlmError
    from evaluation.judge import judge

    if res["shown"] is None:
        return
    if fake:
        res["judge"] = {k: {"score": 5, "reason": "가짜 판정"} for k in judge.CRITERIA}
        res["judge_usage"] = dict(FAKE_USAGE)
        return
    agent_input = trades.render(agent, case["input"])
    try:
        scores, usage = await judge.judge(
            parse, mod.SKILL, agent_input, res["shown"], mod.SOURCES, effort
        )
        res["judge"], res["judge_usage"] = scores, dict(usage.__dict__)
    except (LlmError, ValueError) as e:
        res["judge_error"] = getattr(e, "reason", str(e))


async def run(
    agent: str,
    cases: list[dict],
    *,
    judge_ids: set[str],
    fake: bool,
    concurrency: int = 4,
    judge_effort: str = "low",
) -> list[dict]:
    mod = trades.module(agent)
    orig = _install(agent, fake)
    sem = asyncio.Semaphore(concurrency)

    async def one(case: dict) -> dict:
        async with sem:
            res = await asyncio.create_task(run_case(agent, case, mod))
        if case["id"] in judge_ids:
            async with sem:
                await judge_case(agent, case, res, mod, orig, judge_effort, fake)
        return res

    try:
        return list(await asyncio.gather(*(one(c) for c in cases)))
    finally:
        from app.agent import llm

        llm.parse = orig


def rescore(agent: str, results: list[dict], cases: dict[str, dict]) -> None:
    """저장된 원문으로 코드 채점만 다시 한다 (호출 없음)."""
    sources = trade_plan.skill_sources(agent)
    for res in results:
        if res.get("raw") is not None:
            res["scores"] = trade_plan.score(agent, res["raw"], cases[res["id"]]["expect"], sources)


# ---------------------------------------------------------------- 요약 표
def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}% ({a}/{b})" if b else "-"


def _rate(results: list[dict], pred) -> str:
    rows = [r for r in results if r.get("scores")]
    return _pct(sum(bool(pred(r)) for r in rows), len(rows))


def summarize(meta: dict, results: list[dict]) -> str:
    agent = meta["agent"]
    rules = trade_plan.RULES[agent]
    by_split = {s: [r for r in results if r["split"] == s] for s in gen.SPLITS}
    groups = {"전체": results, "dev": by_split["dev"], "held-out": by_split["heldout"]}
    head = (
        f"모델 {meta['model']} · effort {meta['effort']} · 프롬프트 {meta['prompt_version']} · "
        f"사례 {len(results)}개 (dev {len(by_split['dev'])} · held-out {len(by_split['heldout'])})"
        f" · 층 {meta['stratify']} · 시드 {meta['seed']} · 사례 파일 {meta['cases']}"
    )
    lines = [
        f"# {LABEL[agent]} 공정 의견 평가 결과",
        "",
        head,
        "",
        "채점은 모델이 쓴 원문 기준이에요. 화면에는 코드 검사로 버린 항목을 뺀 의견이 보여요.",
        "",
        "| 검사 | " + " | ".join(groups) + " |",
        "| --- |" + " ---: |" * len(groups),
    ]
    ok_row = [_pct(sum(r["status"] == "ok" for r in g), len(g)) for g in groups.values()]
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
        lines.append(f"| `{rid}` | {rules[rid].desc} | {_pct(ok, n)} |")

    judged = [r for r in results if r.get("judge")]
    if judged or any("judge_error" in r for r in results):
        from evaluation.judge import judge

        errors = sum("judge_error" in r for r in results)
        lines += [
            "",
            f"## 판정 LLM ({meta.get('rubric')}, {len(judged)}개 · 실패 {errors}개)",
            "",
            "| 기준 | 평균 | 3점 이하 |",
            "| --- | ---: | ---: |",
        ]
        for key, label in judge.CRITERIA.items():
            s = [r["judge"][key]["score"] for r in judged]
            low = sum(x <= 3 for x in s)
            mean = f"{statistics.mean(s):.2f}" if s else "-"
            lines.append(f"| {label} | {mean} | {_pct(low, len(s))} |")

    cats = sorted({r["category"] for r in results})
    lines += [
        "",
        "## 범주별",
        "",
        "| 범주 | 사례 | 성공 | 모든 검사 | 꼭 언급 | 언급 안 됨 | 쉬운 말 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cat in cats:
        g = [r for r in results if r["category"] == cat]
        cells = [
            _pct(sum(r["status"] == "ok" for r in g), len(g)),
            _rate(g, lambda r: all(r["scores"]["checks"].values())),
            _rate(g, lambda r: r["scores"]["checks"]["must"]),
            _rate(g, lambda r: r["scores"]["checks"]["must_not"]),
            _rate(g, lambda r: r["scores"]["checks"]["terms"]),
        ]
        lines.append(f"| {cat} | {len(g)} | " + " | ".join(cells) + " |")

    plan_u = [r["usage"] for r in results if r.get("usage")]
    judge_u = [r["judge_usage"] for r in results if r.get("judge_usage")]
    lines += [
        "",
        "## 비용 · 시간",
        "",
        "| 호출 | 횟수 | 입력 | 캐시 읽기 | 캐시 쓰기 | 출력 | 비용 | 지연 중앙값 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, us in (("공정 의견", plan_u), ("판정", judge_u)):
        if not us:
            continue
        total, unknown = cost.total_cost(us)
        tok = [sum(u[k] for u in us) for k in ("input_tokens", "cache_read_tokens")]
        tok += [sum(u[k] for u in us) for k in ("cache_write_tokens", "output_tokens")]
        ms = statistics.median(u["ms"] for u in us) / 1000
        price = f"${total:.3f}" + (f" (가격 모름 {unknown}번)" if unknown else "")
        lines.append(
            f"| {name} | {len(us)} | "
            + " | ".join(f"{t:,}" for t in tok)
            + f" | {price} | {ms:.1f}초 |"
        )
    if plan_u:
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
            if r["status"] != "ok" and not r.get("scores"):
                lines.append(f"- {r['id']} ({r['category']}): 의견 실패 {r['reason']}")
                continue
            failed = [k for k, ok in r["scores"]["checks"].items() if not ok]
            why = "; ".join(f"{k}: {r['scores']['detail'].get(k, '')}" for k in failed)
            head = f"의견 실패 {r['reason']} · " if r["status"] != "ok" else ""
            lines.append(f"- {r['id']} ({r['category']}): {head}{why}")
    return "\n".join(lines) + "\n"


def write(out_dir: Path, meta: dict, results: list[dict]) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = {"meta": meta, "results": results}
    (out_dir / "raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    report = summarize(meta, results)
    (out_dir / "summary.md").write_text(report, encoding="utf-8", newline="\n")
    return report


# ---------------------------------------------------------------- Batch (자리만)
async def run_batch(agent: str, cases: list[dict]) -> list[dict]:
    """자리만 둔다. app/agent/llm.py에 Batch 호출(요청 묶음 제출 → 끝날 때까지 기다림 → 결과 받기)이
    생기면 사례 id를 custom_id로 써서 plan 입력(시스템 프롬프트 · trades.render 글)을 한꺼번에 내고,
    결과를 custom_id로 짝지어 run_case와 같은 모양으로 채점한다. 결과 순서는 보장되지 않는다.
    Batch는 50% 할인이지만 캐시 적중이 보장되지 않고, 끝나기까지 최대 24시간 걸린다.
    """
    raise NotImplementedError("llm.py에 Batch 호출이 생기면 붙여요")


# ---------------------------------------------------------------- 진입점
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서도 한글이 깨지지 않게
    ap = argparse.ArgumentParser(description="공정 에이전트 평가 실행기")
    ap.add_argument("--agent", choices=trades.AGENTS, required=True)
    ap.add_argument(
        "--cases", type=Path, help="사례 jsonl (기본: cases_5k.jsonl, 없으면 sample_100)"
    )
    ap.add_argument("--split", choices=["all", "dev", "heldout"], default="all")
    ap.add_argument("--sample", type=int, default=0, help="층마다 고르게 이만큼만 (0이면 전부)")
    ap.add_argument("--stratify", default="category", help="층 키 (예: category, strata.occupied)")
    ap.add_argument("--seed", type=int, default=1, help="표본 시드")
    ap.add_argument("--case", action="append", help="이 id만 (여러 번 줄 수 있음)")
    ap.add_argument("--judge", type=int, default=0, help="판정 LLM으로 매길 층화 표본 수")
    ap.add_argument("--judge-effort", default="low")
    ap.add_argument("--concurrency", type=int, default=4)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="실제로 호출한다 (유료)")
    mode.add_argument(
        "--fake", action="store_true", help="가짜 LLM(모범 답)으로 코드 경로만 (무료)"
    )
    mode.add_argument("--batch", action="store_true", help="Batch로 낸다 (아직 없음)")
    mode.add_argument(
        "--rescore", type=Path, help="저장된 결과 폴더를 다시 채점만 한다 (호출 없음)"
    )
    ap.add_argument("--out", type=Path, help="결과 폴더 (기본: <agent>/results/<날짜-시각>)")
    args = ap.parse_args()

    if args.rescore:
        raw = json.loads((args.rescore / "raw.json").read_text(encoding="utf-8"))
        cases = {c["id"]: c for c in gen.read_jsonl(ROOT / raw["meta"]["cases"])}
        rescore(args.agent, raw["results"], cases)
        print(write(args.rescore, raw["meta"], raw["results"]))
        return
    if args.batch:
        sys.exit(
            "Batch 실행은 아직 없어요. app/agent/llm.py에 Batch 호출이 생기면 run_batch에 붙여요."
        )

    _load_env()
    from app.config import settings

    path = (args.cases or default_cases(args.agent)).resolve()
    cases = select(
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
    model = "fake" if args.fake else settings.llm_model
    effort = "-" if args.fake else settings.llm_effort
    print(f"사례 파일 {path.relative_to(ROOT)} · 층 {args.stratify}: ", end="")
    print(
        ", ".join(
            f"{k} {v}" for k, v in sorted(Counter(gen.get(c, args.stratify) for c in cases).items())
        )
    )
    print(plan_text(args.agent, cases, len(judge_ids), settings.llm_model, settings.llm_effort))
    if not (args.live or args.fake):
        print("\n실제로 돌리려면 --live (유료), 코드 경로만 보려면 --fake (무료)")
        return
    if args.live:
        if not (os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key):
            sys.exit(".env에 ANTHROPIC_API_KEY를 넣어 주세요.")
        settings.llm_live = True

    mod = trades.module(args.agent)
    meta = {
        "agent": args.agent,
        "model": model,
        "effort": effort,
        "prompt_version": mod.PROMPT_VERSION,
        "rubric": None,
        "cases": path.relative_to(ROOT).as_posix(),
        "split": args.split,
        "sample": args.sample,
        "stratify": args.stratify,
        "seed": args.seed,
        "judge": len(judge_ids),
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    if judge_ids:
        from evaluation.judge import judge

        meta["rubric"] = judge.RUBRIC_VERSION
    results = asyncio.run(
        run(
            args.agent,
            cases,
            judge_ids=judge_ids,
            fake=args.fake,
            concurrency=args.concurrency,
            judge_effort=args.judge_effort,
        )
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M") + ("-fake" if args.fake else "")
    out_dir = args.out or HERE / args.agent / "results" / stamp
    print()
    print(write(out_dir, meta, results))
    print(f"저장: {out_dir}")


if __name__ == "__main__":
    main()
