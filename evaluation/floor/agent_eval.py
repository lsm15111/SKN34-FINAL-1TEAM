"""바닥 에이전트(LLM 켬) 60문항 평가. 기준선은 같은 문항의 LLM 끔 답(coverage.md 'v3 한 턴')이에요.

- 지식: coverage.py와 같은 dev 자료(저장소 RAG CSV + v3 지식)로 만든 색인 · 카드. DB를 쓰지 않아요.
- 한 문항: turn.run_turn(mode=llm) 한 번(프로젝트 · 대화 맥락 없음). 같은 문항을 LLM 끔으로도 돌려 나란히 둬요.
- 근거 판정: 보여 준 글 + 답이 인용한 조각 원문에 문항의 근거 낱말 규칙이 다 들면 '근거 맞음'(coverage.py와 같음).
- 기록: 에이전트를 탔는지 · 끝난 까닭(ok · ask · llm_error · bad_format · all_dropped · over_budget) ·
  LLM 호출 수 · 도구 · 검사에서 빠진 문장 · 토큰 · 비용 · 시간.
- --dry: LLM을 부르지 않아요. 정해 둔 가짜 응답(검색 한 번 → 첫 근거 글로 답)으로 흐름과 지시문 · 도구 결과
  크기만 재서 비용을 어림해요. 실제 답 품질 평가가 아니에요.
- 바닥 판단 루프 밖의 LLM 다시 쓰기(llm.structured)는 막아요. 그 문항은 LLM 끔 답 그대로예요.
- 실제 호출: LLM_LIVE=true와 키가 있어야 해요. 누적 비용이 --cap 달러를 넘으면 그 뒤 호출을 막고 멈춰요.

    cd backend
    .venv/Scripts/python.exe -I -X utf8 ../evaluation/floor/agent_eval.py --dry --out <저장소 밖 결과.json>
"""

import argparse
import asyncio
import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 같은 폴더 coverage.py(색인 · 근거 판정). 같은 이름 패키지와 헷갈리지 않게 파일 경로로 불러요
_spec = importlib.util.spec_from_file_location("floor_coverage", HERE / "coverage.py")
cov = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cov)  # backend 경로도 여기서 sys.path에 들어가요

from app.agent import llm
from app.agent.v3 import agent_loop
from app.agent.v3.answer import KB
from app.agent.v3.schemas import TurnContext
from app.agent.v3.turn import run_turn
from app.config import settings
from app.knowledge import cards

# evaluation/answer/run.py와 같은 공식 가격(2026-11-13), 달러/100만 토큰 (입력 · 캐시 입력 · 출력)
PRICE = {"gpt-6.1-terra": (1.0, 0.05, 5.0)}


def cost(model: str, usage: dict) -> float:
    p_in, p_cached, p_out = PRICE[model]
    fresh = usage["input"] - usage["cached"]
    return (fresh * p_in + usage["cached"] * p_cached + usage["output"] * p_out) / 1e6


class Meter:
    """chat_tools를 감싸 호출 수 · 토큰 · 비용 · 글 크기를 센다. cap을 넘으면 더 부르지 않는다."""

    def __init__(self, inner, model: str, cap: float):
        self.inner, self.model, self.cap = inner, model, cap
        self.spent, self.stopped = 0.0, False
        self.reset()

    def reset(self) -> None:
        self.calls, self.chars, self.secs = 0, [], 0.0
        self.usage = {"input": 0, "cached": 0, "output": 0}

    async def __call__(self, system, messages, tools):
        if self.spent >= self.cap:
            self.stopped = True
            raise llm.LLMError("비용 상한")
        size = len(system) + len(json.dumps(tools, ensure_ascii=False))
        size += sum(len(m["content"]) if isinstance(m["content"], str) else 0 for m in messages)
        self.chars.append(size)
        t = time.perf_counter()
        r = await self.inner(system, messages, tools)
        self.secs += time.perf_counter() - t
        self.calls += 1
        for k in self.usage:
            self.usage[k] += int((r.get("usage") or {}).get(k) or 0)
        self.spent = self.spent_before + cost(self.model, self.usage)
        return r

    def start(self) -> None:
        self.spent_before = self.spent
        self.reset()


async def fake_chat(system, messages, tools):
    """--dry: 첫 호출은 질문으로 검색, 다음은 마지막 검색 결과 첫 글 낱말로 답한다(LLM 호출 없음)."""
    tool = [m for m in messages if m["role"] == "tool"]
    if tools and not tool:
        q = messages[0]["content"].split(":", 1)[-1].strip()
        return {"text": "", "tool_calls": [{"id": "d0", "name": "search_knowledge",
                "arguments": {"query": q}}], "stop": "tool_calls", "usage": {}}  # fmt: skip
    body = json.loads(tool[-1]["content"]) if tool else {}
    data = body.get("data") or []
    if not data:
        return {"text": "{}", "tool_calls": [], "stop": "stop", "usage": {}}
    d = data[0]
    words = " ".join(w for w in d["text"].split() if not any(c.isdigit() for c in w))[:80]
    out = {"sentences": [{"text": words, "cites": [d["ref"]]}]}
    return {
        "text": json.dumps(out, ensure_ascii=False),
        "tool_calls": [],
        "stop": "stop",
        "usage": {},
    }


def judge(kb: KB, rule, ans) -> dict:
    t = ans.trace
    plain = ans.plain()
    cited = [cov.nz(kb.ix.by_ref[r].chunk.text) for r in t.chunks if r in kb.ix.by_ref]
    agent = agent_loop.VERSION in t.prompts
    if t.route in ("out_of_scope", "ask_back"):
        how = t.route
    elif ans.ask is not None:
        how = "ask"
    elif agent:
        how = "agent"
    elif t.cards:
        how = "card"
    elif t.chunks:
        how = "extract"
    else:
        how = "unknown" if ans.unknown else "template"
    shown = [cov.nz(plain)] + cited if how in ("agent", "card", "extract") else []
    return {
        "route": t.route, "trades": t.trades, "how": how, "chunks": t.chunks[:6],
        "shown_ok": cov.all_ok(rule, shown), "dropped": t.dropped, "plain": plain[:600],
    }  # fmt: skip


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, default=HERE / "questions.jsonl")
    ap.add_argument("--out", type=Path, required=True, help="문항별 결과 JSON(저장소 밖)")
    ap.add_argument("--dry", action="store_true", help="LLM 호출 없이 흐름 · 크기만 잰다")
    ap.add_argument("--cap", type=float, default=4.0, help="누적 비용 상한(달러)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 몇 문항만(0이면 전부)")
    a = ap.parse_args()

    model = settings.openai_agent_model
    if not a.dry and (not settings.llm_live or model not in PRICE):
        sys.exit("LLM_LIVE=true와 PRICE에 있는 모델이 필요해요(--dry는 LLM 호출 없음)")
    qs = [json.loads(x) for x in a.questions.read_text(encoding="utf-8").splitlines() if x.strip()]
    qs = qs[: a.limit] if a.limit else qs
    sets = [cov.read_csv(p) for d in cov.DIRS for p in sorted(d.glob("*_rag.csv"))]
    sets += [cov.v3_dataset(p, s, k) for p, s, k in cov.V3 if p.exists()]
    kb = KB(ix=cov.index(sets), cards=cards.default())

    results: list = []
    real_run = agent_loop.run

    async def record(*args, **kw):
        res = await real_run(*args, **kw)
        results.append(res)
        return res

    agent_loop.run = record

    async def no_rewrite(*args, **kw):
        raise llm.LLMError("평가에서 끔")

    # 바닥 판단 루프만 잰다. 다른 담당의 다시 쓰기(structured)는 부르지 않아 셈에 없는 비용이 생기지 않게
    llm.structured = no_rewrite
    meter = Meter(fake_chat if a.dry else llm.chat_tools, model if model in PRICE else "gpt-6.1-terra",
                  a.cap)  # fmt: skip
    rows = []
    for q in qs:
        rule = cov.compile_rule(q["evidence"])
        ctx_free = TurnContext(user_id=uuid.UUID(int=0), today=cov.TODAY)
        llm.chat_tools = meter
        free = asyncio.run(run_turn(q["text"], ctx_free, kb=kb)).answer
        results.clear()
        meter.start()
        t0 = time.perf_counter()
        ctx = ctx_free.model_copy(update={"mode": "llm"})
        ans = asyncio.run(run_turn(q["text"], ctx, kb=kb)).answer
        res = results[-1] if results else None
        rows.append({
            "id": q["id"], "split": q["split"], "category": q["category"], "text": q["text"],
            "free": judge(kb, rule, free), "llm": judge(kb, rule, ans),
            "loop": None if res is None else {"why": res.why, "calls": res.calls, "rounds": res.rounds,
                                             "tools": res.tools, "dropped": res.dropped, "removed": res.removed},
            "calls": meter.calls, "usage": dict(meter.usage), "chars": meter.chars,
            "cost": round(cost(meter.model, meter.usage), 5), "secs": round(time.perf_counter() - t0, 2),
        })  # fmt: skip
        if meter.stopped:
            break
    a.out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"dry": a.dry, "model": meter.model, "effort": settings.openai_reasoning_effort,
            "questions": len(rows), "spent": round(meter.spent, 4), "stopped_by_cap": meter.stopped,
            "prompt": agent_loop.VERSION, "today": cov.TODAY.isoformat()}  # fmt: skip
    a.out.write_text(json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")  # fmt: skip
    report(rows, meta)


def report(rows: list[dict], meta: dict) -> None:
    n = len(rows)
    pct = cov.pct
    print(f"## 바닥 에이전트 평가({'LLM 호출 없음 · 가짜 응답' if meta['dry'] else 'LLM 켬'})\n")
    print(f"- 문항 {n} · 모델 {meta['model']}(추론 {meta['effort']}) · 지시문 {meta['prompt']}")
    print("| | LLM 끔 | LLM 켬 |\n| --- | --- | --- |")
    for label, f in (
        ("근거 맞는 답", lambda r: r["shown_ok"]),
        ("모름", lambda r: r["how"] == "unknown"),
        ("되묻기", lambda r: r["how"] == "ask"),
    ):
        print(
            f"| {label} | {pct(sum(f(r['free']) for r in rows), n)} | {pct(sum(f(r['llm']) for r in rows), n)} |"
        )
    whys: dict[str, int] = {}
    for r in rows:
        w = r["loop"]["why"] if r["loop"] else "루프 안 탐(" + r["llm"]["route"] + ")"
        whys[w] = whys.get(w, 0) + 1
    print("\n- 끝난 까닭: " + " · ".join(f"{k} {v}" for k, v in sorted(whys.items())))
    calls = sum(r["calls"] for r in rows)
    sizes = [c for r in rows for c in r["chars"]]
    print(f"- LLM 호출 {calls}번(문항당 {calls / n:.1f}) · 호출 입력 글 크기 평균 {sum(sizes) / max(len(sizes), 1):,.0f}자 "
          f"· 최대 {max(sizes, default=0):,}자")  # fmt: skip
    print(f"- 비용 ${meta['spent']:.4f} · 문항당 평균 {sum(r['secs'] for r in rows) / n:.1f}초")
    drops = sum(len(r["loop"]["dropped"]) for r in rows if r["loop"])
    print(f"- 검사에서 빠지거나 바뀐 문장 {drops}개")


if __name__ == "__main__":
    main()
