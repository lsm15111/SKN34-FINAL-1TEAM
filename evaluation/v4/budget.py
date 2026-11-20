"""실행 전 예상 비용(토큰 어림 × 가격). 상한을 넘으면 종료 코드 2로 멈춰요. 유료 호출 0회.

    cd backend && uv run python ../evaluation/v4/budget.py --max-usd 15
    cd backend && uv run python ../evaluation/v4/budget.py --answers ../evaluation/v4/runs/dry1/answers.jsonl

- 판정: 실제 판정 글(rubric.md + 질문 몫 + 두 답)을 judge.py와 같은 함수로 만들어 글자 수로 토큰을 어림해요.
  --answers가 없거나 스텁 답이 짧으면 답 하나를 MIN_ANSWER_TOK로 잡아요
- 답 만들기 · 시뮬레이터 · 레드팀: 아래 가정(ASSUME)으로 어림해요. 시범 실행(5문항)의 usage로 바꾸기 전까지는 어림이에요
- 가격: prices.py(claude-api 스킬 models.md). 캐시 쓰기 1.25배 · 읽기는 모델별 값
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import prices
from kit import SCENARIOS, SETS, est_tokens, jsonl, utf8_stdout

# 판정 출력 토큰: JSON(7차원 × 이유 한 문장) 약 600 + 생각. Opus 5.5는 생각이 늘 켜져 있어요(effort 기본 medium)
JUDGE_OUT = {"claude-opus-5-5": 1800, "claude-sonnet-5-5": 1500, "claude-haiku-5-5": 1200}
MIN_ANSWER_TOK = 1000  # 답 하나 최소 어림(스텁 답은 짧아서)
FACTS_TOK = 900  # 답 파일 없이 셀 때 '이 답이 받은 계산 값' 어림
ASSUME = {
    # 답 하나(질문 × 시스템). v2: 2026-11-13 v2 답 평가 실측(30문항, OpenAI 토크나이저) 문항당 입력 10,553 · 출력 235
    # · LLM 2.1번 → Claude 토크나이저 1.3배, 출력은 생각을 더해 900. v3: composer_eval 어림(작성기 입력 2,600 · 출력 600)
    # × 질문 분석기까지 1.5번 → 입력 3,900 · 출력 900
    "answer": {
        "v2": {"input": 13_700, "cached_share": 0.5, "output": 900},
        "v3": {"input": 3_900, "cached_share": 0.3, "output": 900},
    },
    # 시뮬레이터: 비서 한 턴 평균 $0.02(계약서 턴 상한 $0.06 · 목표 ≤ $0.03), 사용자 흉내는 Haiku 5.5 한 턴
    # 입력 2,500 · 출력 200, 대화 판정은 Opus 5.5 한 번 입력 9,000 · 출력 1,800. 턴 수는 max_turns × 0.7
    "sim": {"assistant_turn_usd": 0.02, "user_model": "claude-haiku-5-5", "user_in": 2500, "user_out": 200,
            "judge_model": "claude-opus-5-5", "judge_in": 9000, "judge_out": 1800, "turn_share": 0.7, "runs": 3},
    # 레드팀: 문항의 턴마다 비서 한 턴 + 주입 반영 · 지시문 새기 판정(Haiku 5.5 입력 3,000 · 출력 300)
    "redteam": {"assistant_turn_usd": 0.02, "judge_model": "claude-haiku-5-5", "judge_in": 3000, "judge_out": 300},
}  # fmt: skip


def judge_call_usage(
    sys_tok: int, shared_tok: int, ans_tok: int, order: int, warm: bool, out_tok: int
) -> dict:
    """판정 호출 한 번의 어림 usage. 캐시: 루브릭(system)은 첫 호출만 쓰고 뒤로는 읽어요.
    질문 몫(shared)은 순서 1에서 쓰고 순서 2에서 읽어요. 두 답 몫은 늘 새 입력이에요."""
    if order == 1:
        return {"input": ans_tok, "cache_write": shared_tok + (0 if warm else sys_tok),
                "cache_read": sys_tok if warm else 0, "output": out_tok}  # fmt: skip
    return {
        "input": ans_tok,
        "cache_write": 0,
        "cache_read": sys_tok + shared_tok,
        "output": out_tok,
    }


def judge_item_usd(
    model: str, sys_tok: int, shared_tok: int, a1_tok: int, a2_tok: int, *, warm: bool = True
) -> float:
    out = JUDGE_OUT.get(model, 1800)
    u1 = judge_call_usage(sys_tok, shared_tok, a1_tok, 1, warm, out)
    u2 = judge_call_usage(sys_tok, shared_tok, a2_tok, 2, True, out)
    return (prices.cost_usd(model, u1) or 0) + (prices.cost_usd(model, u2) or 0)


def judge_estimate(model: str, answers: Path | None, set_path: Path) -> dict:
    """판정 어림: 쌍마다 judge.py와 같은 글을 만들어 셉니다."""
    import judge as jd

    system = jd.RUBRIC_PATH.read_text(encoding="utf-8")
    sys_tok = est_tokens(system)
    if answers is not None and answers.exists():
        args = jd.parse_args(
            ["--answers", str(answers), "--set", str(set_path), "--tag", "_budget", "--dry-run"]
        )
        items, _ = jd.load_pairs(args)
    else:  # 답 없이: 질문 몫은 실제로, 답은 어림
        items = []
        for q in jsonl(set_path):
            items.append(jd.Item(
                id=q["id"], source=q["source"], split=q["split"], group=q["group"], kind=q.get("kind", ""),
                question=q["turns"][-1], history=q["turns"][:-1], home_text="32평(공급 105.8㎡) 아파트 …",
                expect=q["expect"], avoid=q["avoid"], ref=q["ref"], text={"A": "", "B": ""},
                facts={"A": "", "B": ""},
            ))  # fmt: skip
    total, shared_sum, ans_sum = 0.0, 0, 0
    for i, x in enumerate(items):
        shared = est_tokens(jd.shared_block(x))
        pad = sum(max(0, MIN_ANSWER_TOK - est_tokens(x.text[s])) for s in "AB")
        pad += sum(FACTS_TOK for s in "AB" if not x.facts[s] or x.facts[s] == jd.NO_FACTS)
        a1 = est_tokens(jd.answers_block(x, "A")) + pad
        a2 = est_tokens(jd.answers_block(x, "B")) + pad
        total += judge_item_usd(model, sys_tok, shared, a1, a2, warm=i > 0)
        shared_sum += shared
        ans_sum += a1
    n = len(items)
    return {"items": n, "calls": 2 * n, "model": model, "usd": total,
            "per_call_in": round(sys_tok + (shared_sum + ans_sum) / max(n, 1)),
            "per_call_out": JUDGE_OUT.get(model, 1800), "rubric_tok": sys_tok}  # fmt: skip


def answer_estimate(n_questions: int, systems: list[str], model: str) -> dict:
    p = prices.PRICES[model]
    out = {}
    for s in systems:
        a = ASSUME["answer"][s]
        fresh = a["input"] * (1 - a["cached_share"])
        usd = (
            fresh * p.inp + a["input"] * a["cached_share"] * p.cache_read + a["output"] * p.out
        ) / 1e6
        out[s] = {"answers": n_questions, "usd_each": round(usd, 5), "usd": usd * n_questions}
    return {"model": model, "by_system": out, "usd": sum(v["usd"] for v in out.values())}


def sim_estimate(runs: int | None = None) -> dict:
    a = ASSUME["sim"]
    runs = runs or a["runs"]
    scen = [
        json.loads(p.read_text("utf-8"))
        for p in sorted(SCENARIOS.glob("*.json"))
        if p.stem != "scenario.schema"
    ]
    turns = sum(s["max_turns"] for s in scen) * a["turn_share"] * runs
    user = prices.cost_usd(a["user_model"], {"input": a["user_in"], "output": a["user_out"]}) or 0
    judge = (
        prices.cost_usd(a["judge_model"], {"input": a["judge_in"], "output": a["judge_out"]}) or 0
    )
    usd = turns * (a["assistant_turn_usd"] + user) + len(scen) * runs * judge
    return {"scenarios": len(scen), "runs": runs, "turns": round(turns), "usd": usd,
            "judge_usd": len(scen) * runs * judge}  # fmt: skip


def redteam_estimate() -> dict:
    a = ASSUME["redteam"]
    rows = jsonl(SETS / "redteam.jsonl")
    turns = sum(len(r["turns"]) for r in rows)
    judge = (
        prices.cost_usd(a["judge_model"], {"input": a["judge_in"], "output": a["judge_out"]}) or 0
    )
    return {
        "items": len(rows),
        "turns": turns,
        "usd": turns * a["assistant_turn_usd"] + len(rows) * judge,
    }


def main(argv=None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="v4 평가 예상 비용")
    ap.add_argument("--answers", type=Path, help="답 파일이 있으면 판정 글을 실제 답으로 세요")
    ap.add_argument("--set", type=Path, default=SETS / "compare.jsonl")
    ap.add_argument("--judge-model", default="claude-opus-5-5")
    ap.add_argument(
        "--answer-model",
        default="claude-sonnet-5-5",
        help="답 파이프라인이 쓸 모델(Claude 전환 뒤)",
    )
    ap.add_argument("--systems", default="v2,v3")
    ap.add_argument("--runs", type=int, default=3, help="시뮬레이터 시나리오마다 돌릴 횟수(pass^k)")
    ap.add_argument("--max-usd", type=float, help="넘으면 종료 코드 2")
    a = ap.parse_args(argv)
    n_q = len(jsonl(a.set))
    ans = answer_estimate(n_q, a.systems.split(","), a.answer_model)
    jud = judge_estimate(a.judge_model, a.answers, a.set)
    cheap = judge_estimate("claude-haiku-5-5", a.answers, a.set)
    sim = sim_estimate(a.runs)
    red = redteam_estimate()
    rows = [
        ("비교 실행(답 만들기)", f"{n_q}문항 × {len(ans['by_system'])}시스템", a.answer_model, ans["usd"]),
        ("판정(쌍대, 두 순서)", f"{jud['items']}쌍 × 2 = {jud['calls']}번", a.judge_model, jud["usd"]),
        ("시뮬레이터", f"{sim['scenarios']}개 × {sim['runs']}번 ≈ {sim['turns']}턴", "비서 + Haiku 사용자 + Opus 판정", sim["usd"]),
        ("레드팀", f"{red['items']}문항 · {red['turns']}턴", "비서 + Haiku 판정", red["usd"]),
    ]  # fmt: skip
    total = sum(r[3] for r in rows)
    print("| 항목 | 규모 | 모델 | 어림(달러) |\n| --- | --- | --- | --- |")
    for r in rows:
        print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]:.2f} |")
    print(f"| 합계 | | | {total:.2f} |")
    print(f"- 판정 한 번 어림: 입력 {jud['per_call_in']:,}토큰(루브릭 {jud['rubric_tok']:,}, 캐시 읽기) · "
          f"출력 {jud['per_call_out']:,}(생각 포함 가정)")  # fmt: skip
    print(f"- 값싼 판정(Haiku 5.5)으로 바꾸면 판정 ${cheap['usd']:.2f}")
    print(f"- 시뮬레이터 중 대화 판정 ${sim['judge_usd']:.2f}(끝 상태 채점은 코드라 무료)")
    print("- 가정은 budget.ASSUME. 시범 실행 usage로 바꾸기 전까지는 어림이에요")
    if a.max_usd is not None and total > a.max_usd:
        print(f"상한 ${a.max_usd}을 넘어요(${total:.2f})")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
