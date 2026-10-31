"""라우터 평가 실행기. 상담과 같은 입력(ROUTER_SYSTEM · 앞 대화 20개 + 이번 말 · 고객 공정 · 카드)으로
app.agent.consult.route를 부르고, 원문(RouterOut)을 상담 코드에 넣어 바뀐 칸 · 공정 · 질문 · 범위 · 답을 채점한다.
판정 LLM은 쓰지 않는다 (기대가 칸 값이라 코드로 다 맨다).

실행 (저장소 루트에서):
    cd backend
    uv run python ../evaluation/router/run.py --sample 20                 # 호출 수 · 예상 비용만
    uv run python ../evaluation/router/run.py --sample 20 --fake          # 가짜 LLM(모범 출력), 무료
    uv run python ../evaluation/router/run.py --sample 20 --fake --batch  # 가짜 Batch, 무료
    uv run python ../evaluation/router/run.py --sample 20 --live          # 실제 호출 (유료)
    uv run python ../evaluation/router/run.py --live --batch              # Batch (유료, 50% 할인)
    uv run python ../evaluation/router/run.py --rescore <결과 폴더>       # 다시 채점만
결과: evaluation/router/results/<날짜-시각>/raw.json · summary.md
"""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, runner, trades
from evaluation.router import score as S

NO_CHANGE = ("question", "question.other", "trade.ask", "vendor", "out_of_scope", "no_change")


def default_cases() -> Path:
    full = HERE / "cases_5k.jsonl"
    return full if full.exists() else HERE / "sample_100.jsonl"


async def call(case: dict):
    """상담 service.turn과 같은 모양으로 라우터를 부른다"""
    from app.agent import consult as router_agent
    from app.consult import service

    inp = case["input"]
    card = trades.card(inp)
    turns = [(t["role"], t["text"]) for t in inp["history"][-20:]]
    turns.append(("user", inp["message"].strip()))
    return await router_agent.route(
        service.ROUTER_SYSTEM, turns, card.trades, card.model_dump(mode="json")
    )


def to_result(case: dict, c: runner.Call) -> dict:
    return {
        "id": case["id"],
        "split": case["split"],
        "category": case["category"],
        "status": "ok" if c.error is None else "failed",
        "reason": c.error,
        "raw": c.raw,
        "usage": c.usage,
        "scores": S.score(case, c.raw) if c.raw is not None else None,
    }


async def run(
    cases: list[dict],
    *,
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
    return [to_result(c, x) for c, x in zip(cases, calls, strict=True)]


def rescore(results: list[dict], cases: dict[str, dict]) -> None:
    for r in results:
        if r.get("raw") is not None:
            r["scores"] = S.score(cases[r["id"]], r["raw"])


# ---------------------------------------------------------------- 요약 표
def _rate(rows: list[dict], pred) -> str:
    rows = [r for r in rows if r.get("scores")]
    return runner.pct(sum(bool(pred(r)) for r in rows), len(rows))


def _ok(r: dict, *ids: str) -> bool:
    return all(r["scores"]["checks"][i] for i in ids)


def _pr(rows: list[dict], p: str = "") -> tuple[str, str]:
    """(정밀도, 재현율) — 사례 전체를 모아 셈"""
    n = Counter()
    for r in rows:
        if r.get("scores"):
            n.update({k: v for k, v in r["scores"]["counts"].items() if k.startswith(p)})
    tp, fp, fn = n[f"{p}tp"], n[f"{p}fp"], n[f"{p}fn"]
    return runner.pct(tp, tp + fp), runner.pct(tp, tp + fn)


def summarize(meta: dict, results: list[dict]) -> str:
    by = {s: [r for r in results if r["split"] == s] for s in gen.SPLITS}
    groups = {"전체": results, "dev": by["dev"], "held-out": by["heldout"]}
    lines = [
        "# 라우터 평가 결과",
        "",
        (
            f"모델 {meta['model']} · effort {meta['effort']} · 프롬프트 {meta['prompt_version']} · "
            f"모드 {meta.get('mode', '-')} · 사례 {len(results)}개 (dev {len(by['dev'])} · "
            f"held-out {len(by['heldout'])}) · 층 {meta['stratify']} · 시드 {meta['seed']} · "
            f"사례 파일 {meta['cases']} · 공정 더하기 칸 {'있음' if S.HAS_TRADES else '없음 (v5 전)'}"
        ),
        "",
        "채점은 모델 원문을 상담 코드(apply_route · normalize)에 넣어 바뀐 칸으로 해요.",
        "",
        "| 지표 | " + " | ".join(groups) + " |",
        "| --- |" + " ---: |" * len(groups),
    ]
    ok = [runner.pct(sum(r["status"] == "ok" for r in g), len(g)) for g in groups.values()]
    lines.append("| 호출 성공 | " + " | ".join(ok) + " |")
    lines.append(
        "| **모든 코드 검사 통과** | "
        + " | ".join(
            _rate(g, lambda r: all(r["scores"]["checks"].values())) for g in groups.values()
        )
        + " |"
    )
    for name, p in (("바뀐 칸", ""), ("공정 더하기 · 빼기", "t_"), ("질문 넘기기", "q_")):
        prs = [_pr(g, p) for g in groups.values()]
        lines.append(f"| {name} 정밀도 | " + " | ".join(a for a, _ in prs) + " |")
        lines.append(f"| {name} 재현율 | " + " | ".join(b for _, b in prs) + " |")
    still = [
        _rate([r for r in g if r["category"] in NO_CHANGE], lambda r: not r["scores"]["effect"])
        for g in groups.values()
    ]
    lines.append("| 안 바꿔야 할 말에서 안 바꿈 | " + " | ".join(still) + " |")
    for cid, desc in S.CHECKS.items():
        row = [_rate(g, lambda r, cid=cid: r["scores"]["checks"][cid]) for g in groups.values()]
        lines.append(f"| {desc} | " + " | ".join(row) + " |")

    oos = [r for r in results if r.get("scores")]
    miss = sum(r["category"] == "out_of_scope" and not r["raw"].get("out_of_scope") for r in oos)
    false = sum(r["category"] != "out_of_scope" and r["raw"].get("out_of_scope") for r in oos)
    vendor = sum(r["category"] == "vendor" and r["raw"].get("out_of_scope") for r in oos)
    lines += [
        "",
        f"범위 밖을 놓침 {miss}번 · 범위 안을 범위 밖으로 {false}번 (업체 소개 · 견적 요청 {vendor}번)",
        "",
        "## 범주별",
        "",
        "| 범주 | 사례 | 성공 | 모든 검사 | 바뀐 칸 똑같음 | 지어낸 변경 없음 | 공정 · 질문 · 범위 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cat in sorted({r["category"] for r in results}):
        g = [r for r in results if r["category"] == cat]
        cells = [
            runner.pct(sum(r["status"] == "ok" for r in g), len(g)),
            _rate(g, lambda r: all(r["scores"]["checks"].values())),
            _rate(g, lambda r: _ok(r, "effect_exact")),
            _rate(g, lambda r: _ok(r, "no_invented")),
            _rate(g, lambda r: _ok(r, "trades_exact", "questions_exact", "out_of_scope")),
        ]
        lines.append(f"| {cat} | {len(g)} | " + " | ".join(cells) + " |")

    usage = [r["usage"] for r in results if r.get("usage")]
    lines += ["", "## 비용 · 시간", ""]
    lines += runner.cost_table([("라우터", usage)])
    if usage:
        from evaluation.common import cost

        total = cost.total_cost(usage)[0]
        lines.append(f"\n사례 1개당 비용 {total / len(results):.5f}달러 · 가격 {cost.PRICE_SOURCE}")

    bad = [r for r in results if not r.get("scores") or not all(r["scores"]["checks"].values())]
    if bad:
        lines += ["", "## 실패 예 (앞 15개)", ""]
        for r in bad[:15]:
            if not r.get("scores"):
                lines.append(f"- {r['id']} ({r['category']}): 호출 실패 {r['reason']}")
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
    ap = argparse.ArgumentParser(description="라우터 평가 실행기")
    runner.add_args(ap)
    args = ap.parse_args()

    if args.rescore:
        raw = json.loads((args.rescore / "raw.json").read_text(encoding="utf-8"))
        cases = {c["id"]: c for c in gen.read_jsonl(ROOT / raw["meta"]["cases"])}
        rescore(raw["results"], cases)
        print(write(args.rescore, raw["meta"], raw["results"]))
        return

    runner.load_env(ROOT)
    from app.agent import consult as router_agent
    from app.agent import llm
    from app.config import settings

    path = (args.cases or default_cases()).resolve()
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
    model, effort = llm.pick("router")
    counts = Counter(gen.get(c, args.stratify) for c in cases)
    print(f"사례 파일 {path.relative_to(ROOT)} · 층 {args.stratify}: ", end="")
    print(", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(runner.estimate_text("router", cases, 0, model, effort))
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
        "prompt_version": router_agent.PROMPT_VERSION,
        "mode": mode,
        "cases": path.relative_to(ROOT).as_posix(),
        "split": args.split,
        "sample": args.sample,
        "stratify": args.stratify,
        "seed": args.seed,
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    results = asyncio.run(run(cases, mode=mode, concurrency=args.concurrency, out_dir=out_dir))
    print()
    print(write(out_dir, meta, results))
    print(f"저장: {out_dir}")


if __name__ == "__main__":
    main()
