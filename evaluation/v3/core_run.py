"""핵심 질문 32개 답 뽑기(무료 모드, 유료 호출 0회): 두 맥락으로 돌려 화면에 가는 답(chat.service._public)을 저장해요.

    cd backend && LLM_LIVE=false OPENAI_API_KEY= PYTHONPATH=".;tests;../evaluation;../evaluation/v3" \
        uv run python ../evaluation/v3/core_run.py --tag r1 [--sample 60]

- 맥락: project = coverage_check.FACTS(69.4㎡ · 표준견적서 · 예상 공정표 · 실측 초안 · 가견적), none = 프로젝트 없음
- 지식: tests/v3_kb.repo_kb(저장소 CSV + v3 지식 요지 + 카드, DB 없음). 의미 검색 순위는 넣지 않아요(키 없는 무료 모드와 같음)
- 운영(chat.service.ai_turn)과 같게: run_turn이 general 인자를 받으면 tools.general_facts(가린 질문)도 넘겨요
  (질문 평수 · 예시 평수 계산, DB 없음). ai_turn이 run_turn 앞에서 더 넣는 값이 생기면 one()에도 같이 넣어요
- 유료 호출 막기: LLM_LIVE=true면 멈추고, llm.structured · jev_choice · embed_query · embed_texts · chat_tools는 부르면 오류
- 같은 tag가 있으면 멈춰요(--force로 덮어쓰기). 결과 줄의 how = 답 출처 종류(card · extract · unknown …)
- --sample N(기본 60, 0이면 안 함): coverage_check.load_sets()에서 공종이 도배 · 목공 · 공통인 질문 N개를
  고정 시드로 더 뽑아 그 질문의 맥락(has_project)으로 돌려요
- 저장(git 밖): .cache/<tag>/core_answers.jsonl(한 줄 = 질문 하나 × 맥락 하나) · core_answers.txt(읽기용) · core_meta.json
"""

import argparse
import asyncio
import inspect
import json
import random
import subprocess
import sys
import time
import traceback
import uuid
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "backend", ROOT / "backend/tests", ROOT / "evaluation", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import coverage_check as cc

from app.agent import llm
from app.agent.v3 import check, templates
from app.agent.v3.schemas import TurnContext
from app.agent.v3.turn import run_turn
from app.chat.service import _public
from app.config import settings

CORE = HERE / "core_questions.jsonl"
SEED = 20261119
SAMPLE_TRADES = ("dobae", "mokgong", "common")
WARMUP = "도배 비용 얼마예요?"  # 첫 턴의 늦은 불러오기(분류기 · 형태소)를 시간에서 빼려고 한 번 먼저 돌려요


def _general_fn():
    """운영 ai_turn이 run_turn에 넘기는 질문 계산 값(general). 그 인자 · 함수가 없는 판이면 None."""
    if "general" not in inspect.signature(run_turn).parameters:
        return None
    from app.chat import tools

    return getattr(tools, "general_facts", None)


GENERAL = _general_fn()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
        ).stdout.strip()
    except OSError:
        return ""


def sample_rows(n: int, core_texts: set[str]) -> tuple[list[dict], int]:
    """표본 질문과 뽑은 모집단 크기. 같은 질문 · 핵심 질문과 같은 글은 한 번만."""
    pool, seen = [], set(core_texts)
    for q in cc.load_sets():
        if q.get("gold_trade") not in SAMPLE_TRADES or q["text"] in seen:
            continue
        seen.add(q["text"])
        pool.append(q)
    picked = random.Random(SEED).sample(pool, min(n, len(pool)))
    return [
        {"set": "sample", "id": f"{q['set']}:{q['id']}", "q": q["text"],
         "ctx": "project" if q.get("has_project") else "none", "gold_trade": q.get("gold_trade"),
         "gold_route": q.get("gold_route"), "bank_expect": q.get("expect")}
        for q in picked
    ], len(pool)  # fmt: skip


async def one(row: dict, kb) -> dict:
    facts = cc.FACTS if row["ctx"] == "project" else None
    ctx = TurnContext(
        user_id=uuid.UUID(int=0),
        project_id=uuid.UUID(int=1) if facts is not None else None,
        today=cc.TODAY,
        mode="free",
    )
    out = dict(row)
    t0 = time.perf_counter()
    try:
        extra = {"general": GENERAL(check.mask(row["q"]))} if GENERAL else {}
        res = await run_turn(row["q"], ctx, kb=kb, facts=facts, **extra)
        pub = _public(res.answer)
        out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        a = res.answer
        out |= {
            "route": a.trace.route, "trades": a.trace.trades, "policy": a.trace.policy,
            "source": a.trace.source, "confidence": a.trace.confidence, "label": res.label,
            "how": cc.answer_kind(a), "says_unknown": templates.UNKNOWN in a.unknown,  # 답 출처 종류
            "waiting": res.waiting, "answer": pub.model_dump(mode="json"),
            "trace": a.trace.model_dump(mode="json"),  # 화면에는 안 가는 흔적(카드 · 조각 · 뺀 이유)
        }  # fmt: skip
    except Exception as e:  # noqa: BLE001
        out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["error"] = f"{type(e).__name__}: {e}"
        out["tb"] = traceback.format_exc(limit=6)
    return out


def view(r: dict) -> str:
    """읽기용 한 덩어리: 짧은 답 · 묶음 · 계산 상자 · 카드 · 되묻기."""
    head = f"### {r['id']} [{r['ctx']}] {r['q']}\n담당 {r.get('route')} {r.get('trades')} · {r.get('ms')}ms"
    if "error" in r:
        return f"{head}\n오류 {r['error']}\n"
    a = r["answer"]
    lines = [head + f" · 답 {r.get('how')}" + (" · 모름 문장" if r.get("says_unknown") else "")]
    if a.get("brief"):
        b = a["brief"]
        lines.append(f"[짧은 답 {b['form']} · 더 {b['more']}]")
        lines += [f"  > {x}" for x in b["lines"]]
    for s in a["sections"]:
        lines.append(f"[묶음 {s['route']}/{s.get('trade')} {s['source']}] {s['title']}")
        lines += [f"  - {x}" for x in s["sentences"]]
        if s.get("caution"):
            lines.append(f"  ! {s['caution']}")
        if s.get("tip"):
            lines.append(f"  * {s['tip']}")
        if s.get("sources"):
            lines.append("  출처 " + " / ".join(x["title"] for x in s["sources"])[:200])
    for c in a["calc"]:
        lines.append(
            f"[계산] {c['label']} ({c['ref']}) 수량 {c.get('qty')}{c.get('unit')} 단가 {c.get('unit_price')}"
            f" 금액 {c.get('amount')} 합계에 {c.get('in_total')} {c.get('note')}"
        )
    for c in a["cards"]:
        ch = " | ".join(
            f"{x['text']}({x.get('action') or x.get('route') or ''})" for x in c.get("choices", [])
        )
        calc = "; ".join(
            f"{x['label']} {x.get('amount')} {x.get('note')}" for x in c.get("calc", [])
        )
        draft = c.get("draft")
        lines.append(
            f"[카드 {c['kind']}] {c.get('title')} {c.get('text')} {ch} {calc}"
            + (f" 초안 {draft}" if draft else "")
        )
    if a.get("ask"):
        lines.append(f"[되묻기] {a['ask']['question']} {a['ask']['options']}")
    for u in a["unknown"]:
        lines.append(f"[모름] {u}")
    if a.get("suggest"):
        lines.append("[이어 묻기] " + " | ".join(a["suggest"]))
    return "\n".join(lines) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="r1", help="결과 폴더 .cache/<tag>/ (회차마다 다르게)")
    ap.add_argument("--sample", type=int, default=60, help="더 돌릴 표본 질문 수(0이면 안 함)")
    ap.add_argument("--force", action="store_true", help="이미 있는 회차 결과를 덮어써요")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if settings.llm_live:
        sys.exit("LLM_LIVE=true 라서 멈춰요(유료 호출 막기)")
    out = HERE / ".cache" / a.tag  # git 밖
    if (out / "core_answers.jsonl").exists() and not a.force:
        sys.exit(f"{out}에 이미 답이 있어요. 새 회차는 --tag를 바꾸고, 덮어쓰려면 --force를 줘요")
    for name in ("structured", "jev_choice", "embed_query", "embed_texts", "chat_tools"):
        setattr(llm, name, cc._no_paid)
    from v3_kb import repo_kb

    kb = repo_kb()
    core = cc.jsonl(CORE)
    rows = [
        {"set": "core", "id": q["id"], "kind": q["kind"], "q": q["q"], "expect": q["expect"],
         "avoid": q["avoid"], "ctx": ctx}
        for ctx in ("project", "none") for q in core
    ]  # fmt: skip
    pool_n = 0
    if a.sample > 0:
        extra, pool_n = sample_rows(a.sample, {q["q"] for q in core})
        rows += extra

    w = await one({"set": "warmup", "id": "W", "q": WARMUP, "ctx": "none"}, kb)
    done = [await one(r, kb) for r in rows]

    out.mkdir(parents=True, exist_ok=True)
    with (out / "core_answers.jsonl").open("w", encoding="utf-8") as f:
        for r in done:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    (out / "core_answers.txt").write_text("\n".join(view(r) for r in done), encoding="utf-8")
    ok = [r for r in done if "error" not in r]
    meta = {
        "tag": a.tag, "head": _git("rev-parse", "HEAD"), "branch": _git("branch", "--show-current"),
        "dirty": _git("status", "--short").splitlines(), "today": cc.TODAY.isoformat(), "mode": "free",
        "kb": {"chunks": kb.ix.n, "cards": len(kb.cards.cards), "card_set": kb.cards.version, "dense": False},
        "general": GENERAL is not None,  # 질문 계산 값(general)을 넘겼는지(운영 ai_turn과 같게)
        "seed": SEED, "sample": a.sample, "sample_pool": pool_n, "warmup_ms": w.get("ms"),
        "rows": len(done), "errors": len(done) - len(ok),
        "route": {s: dict(Counter(f"{r['ctx']}:{r.get('route')}" for r in done if r["set"] == s))
                  for s in ("core", "sample")},
        "ms_mean": round(sum(r["ms"] for r in ok) / max(1, len(ok)), 1),
        "ms_max": max((r["ms"] for r in ok), default=0),
        "says_unknown": sum(1 for r in ok if r.get("says_unknown")),
    }  # fmt: skip
    (out / "core_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"저장: {out / 'core_answers.jsonl'}")


if __name__ == "__main__":
    asyncio.run(main())
