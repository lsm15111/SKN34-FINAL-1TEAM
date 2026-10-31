"""공정 의견 실행기 · 공통 실행 도구 · 비용 · 판정 스키마. 가짜 LLM으로만 돌린다 (유료 호출 0회)."""

import asyncio
import copy
import json
from collections import Counter

import pytest

from evaluation import run_agent
from evaluation.common import cost, gen, runner
from evaluation.judge import judge

META = {
    "trade": "dobae",
    "model": "fake",
    "effort": "-",
    "prompt_version": "t",
    "cases": "x",
    "stratify": "category",
    "seed": 1,
}


@pytest.fixture
def wp_sample() -> list[dict]:
    return gen.read_jsonl(run_agent.case_dir("dobae") / "sample_100.jsonl")


def test_select_keeps_2to1_and_strata(wp_sample):
    picked = runner.select(wp_sample, sample=30, seed=1)
    assert Counter(c["split"] for c in picked) == {"dev": 20, "heldout": 10}
    assert len({c["category"] for c in picked}) == 9
    assert picked == runner.select(wp_sample, sample=30, seed=1)
    dev = runner.select(wp_sample, split="dev", sample=9, stratify="strata.occupied")
    assert {c["split"] for c in dev} == {"dev"} and len(dev) == 9


def test_estimate_only_shows_all_models(wp_sample):
    text = runner.estimate_text("dobae", wp_sample[:20], 5, "claude-opus-5-5", "medium")
    assert "에이전트 20번 + 판정 5번" in text
    for label in cost.MODEL_LABEL.values():
        assert f"| {label} |" in text


def test_estimate_counts_cache_per_system_group():
    """공정마다 시스템이 다르면(전문가 답) 캐시 쓰기를 공정마다 센다 → 한 묶음으로 셀 때보다 비싸다"""
    cases = [{"id": f"c{i}", "split": "dev", "trade": "ab"[i % 2]} for i in range(12)]

    def opus(text: str) -> float:
        line = next(x for x in text.splitlines() if x.startswith("| Opus 5.5 |"))
        return float(line.split("|")[2].strip().lstrip("$"))

    args = ("expert", cases, 2, "m", "low", "judge_expert")
    one = runner.estimate_text(*args)
    two = runner.estimate_text(*args, "trade", {"c0", "c1"})
    assert "2묶음" in two and opus(two) > opus(one)


@pytest.mark.parametrize("trade", ["dobae", "mokgong"])
@pytest.mark.parametrize("mode", ["fake", "fake-batch"])
def test_fake_run_end_to_end(tmp_path, trade, mode):
    from app.agent import llm
    from app.config import settings

    cases = gen.read_jsonl(run_agent.case_dir(trade) / "sample_100.jsonl")[:6]
    before, client = llm.parse, llm._client
    results = asyncio.run(
        run_agent.run(trade, cases, judge_ids={cases[0]["id"]}, mode=mode, concurrency=3, poll_s=0)
    )
    assert llm.parse is before and llm._client is client and settings.llm_live is False
    assert settings.llm_plan_cache_s > 0  # 평가 동안만 끈다
    assert [r["id"] for r in results] == [c["id"] for c in cases]
    for r in results:
        assert r["status"] == "ok" and r["dropped"] == 0, r
        assert all(r["scores"]["checks"].values()), r["scores"]["detail"]
        assert r["usage"]["model"] == "fake"
        assert bool(r["usage"].get("batch")) == (mode == "fake-batch")
    assert results[0]["judge"]["correct"]["score"] == 5 and "judge" not in results[1]

    report = run_agent.write(tmp_path, META | {"trade": trade, "mode": mode}, results)
    saved = json.loads((tmp_path / "raw.json").read_text(encoding="utf-8"))
    assert saved["results"] == results
    assert "**모든 코드 검사 통과** | 100% (6/6)" in report
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == report


def test_batch_requests_match_live_requests(wp_sample, tmp_path):
    """Batch로 낸 요청 글이 실시간 호출 글과 같고, Batch id를 적어 두면 다시 내지 않고 결과만 받는다."""
    from app.agent import llm

    cases = wp_sample[:3]
    seen: list[tuple[str, str]] = []

    async def spy(system, user, schema, **kw):
        seen.append((system, user))
        raise llm.LlmError("stub")

    answers = {c["id"]: json.dumps(run_agent.ideal("dobae")(c)) for c in cases}
    fake = runner.FakeBatches(answers)
    saved = tmp_path / "b.json"
    old = llm._client
    llm._client = runner.NS(messages=runner.NS(batches=fake))
    try:
        with run_agent.no_plan_cache():
            with runner._parse(spy):
                asyncio.run(runner._gather(cases, run_agent_plan(), 2, False))
            first = asyncio.run(
                runner.run(cases, run_agent_plan(), mode="batch", batch_file=saved, poll_s=0)
            )
            sent = [
                (r["params"]["system"][0]["text"], r["params"]["messages"][0]["content"])
                for r in fake.requests
            ]
            fake.requests = fake.requests[:1]  # 적어 둔 Batch에 첫 사례 결과만 있다고 치자
            again = asyncio.run(
                runner.run(cases, run_agent_plan(), mode="batch", batch_file=saved, poll_s=0)
            )
    finally:
        llm._client = old
    assert len(seen) == 3 and sorted(sent) == sorted(seen)
    assert all(g.error is None and g.usage["batch"] for g in first)
    assert json.loads(saved.read_text(encoding="utf-8")) == {"batch_id": "fake_batch"}
    assert [g.error for g in again] == [None, "batch_missing", "batch_missing"]


def run_agent_plan():
    from evaluation.common import trades

    agent = trades.agent("dobae")

    async def plan(case):
        inp = case["input"]
        return await agent.plan(trades.plan_text("dobae", inp), trades.quote("dobae", inp))

    return plan


def test_one_broken_case_does_not_stop_the_run(wp_sample):
    broken = copy.deepcopy(wp_sample[0])
    broken["input"]["card"]["area_m2"] = "0.0"  # 카드 검사에서 ValidationError
    results = asyncio.run(
        run_agent.run("dobae", [broken, wp_sample[1]], judge_ids=set(), mode="fake")
    )
    assert results[0]["status"] == "failed" and results[0]["reason"] == "error:ValidationError"
    assert results[0]["scores"] is None and results[1]["status"] == "ok"
    report = run_agent.summarize(META, results)
    assert "의견 생성 성공 (화면에 보임) | 50% (1/2)" in report


def test_plan_prompt_option_reloads_agent_or_fails_clearly(wp_sample):
    """--plan-prompt: 같은 지식으로 그 버전 프롬프트 파일을 써서 다시 만든다. 파일이 없으면 분명한 오류"""
    from evaluation.common import trades

    spec_agent = trades.agent("dobae")
    assert run_agent.plan_agent("dobae") is spec_agent
    again = run_agent.plan_agent("dobae", "v1")  # 스펙에 등록된 v1 파일로 다시 만든 것
    assert again is not spec_agent
    assert (again.plan_prompt_version, again.plan_system, again.sources) == (
        spec_agent.plan_prompt_version,
        spec_agent.plan_system,
        spec_agent.sources,
    )
    with pytest.raises(FileNotFoundError, match="prompts/wallpaper_v9.md"):
        run_agent.plan_agent("dobae", "v9")
    results = asyncio.run(
        run_agent.run("dobae", wp_sample[:2], judge_ids=set(), mode="fake", plan_prompt="v1")
    )
    assert all(r["status"] == "ok" and all(r["scores"]["checks"].values()) for r in results)


def test_rescore_uses_saved_raw(wp_sample):
    cases = wp_sample[:2]
    results = asyncio.run(run_agent.run("dobae", cases, judge_ids=set(), mode="fake"))
    results[0]["raw"]["visit_checks"].append("천장 높이가 2.4m인지 재요.")
    run_agent.rescore("dobae", results, {c["id"]: c for c in cases})
    assert results[0]["scores"]["checks"]["no_digits"] is False
    assert results[1]["scores"]["checks"]["no_digits"] is True


def test_cost_from_usage_and_estimate():
    from evaluation.common import trades

    u = {
        "model": "claude-opus-5-5",
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_read_tokens": 1_000_000,
        "cache_write_tokens": 1_000_000,
        "ms": 1,
    }
    assert cost.call_cost(u) == pytest.approx(4 + 20 + 0.2 + 5)
    assert cost.call_cost(u | {"batch": True}) == pytest.approx((4 + 20 + 0.2 + 5) / 2)
    assert cost.call_cost(u | {"model": "unknown"}) is None
    assert cost.total_cost([u, u | {"model": "x"}]) == (pytest.approx(29.2), 1)
    shape = cost.CallShape(uncached=100, system=1000, output=500, basis="t")
    batch = cost.estimate(shape, 10, "claude-sonnet-5-5", batch=True)
    assert batch == pytest.approx(10 * (1100 * 2 + 500 * 10) / 2 / 1e6)
    normal = cost.estimate(shape, 10, "claude-sonnet-5-5", concurrency=2)
    want = (10 * (100 * 2 + 500 * 10) + 2 * 1000 * 2.5 + 8 * 1000 * 0.1) / 1e6
    assert normal == pytest.approx(want)
    assert "| Haiku 5.5 |" in cost.estimate_table("dobae", judge=10)
    assert cost.shape("probex") == cost.SHAPES["mokgong"]  # 모양이 없는 공정은 목공 값
    for t in trades.registered():  # 10공정 모두 공정 의견 · 판정 모양이 있다
        assert cost.shape(t) is cost.SHAPES[t] and cost.judge_shape(t) == f"judge_{t}"
    assert cost.judge_shape("probex") == "judge"


def test_judge_schema_checks_range_and_renders_answer():
    ok = judge.Judgement(
        **{k: judge.Score(score=4, reason="풀지 않은 말이 하나 있어요") for k in judge.CRITERIA}
    )
    assert judge.check(ok)["plain_words"]["score"] == 4
    bad = ok.model_copy(update={"correct": judge.Score(score=6, reason="x")})
    with pytest.raises(ValueError):
        judge.check(bad)
    plan = {
        "summary": "요약이에요.",
        "steps": [{"key": "paper", "note": "발라요."}],
        "visit_checks": ["물어봐요."],
        "cautions": [{"text": "주의해요.", "source": "field"}],
    }
    text = judge.user("<input>\n집 정보\n</input>", plan, {"field": "현장 후기"})
    assert "<answer>" in text and "(출처: 현장 후기)" in text and "- paper: 발라요." in text
    assert "necessary_only" in judge.system("지식") and judge.system("지식").endswith("지식")
    expert = judge.system("지식", judge.EXPERT)
    assert "answers_question" in expert and "질문에 맞게" in expert
    a = judge.expert_user(
        "면적: 84㎡",
        "실크가 뭐예요?",
        {"answer": "닦을 수 있어요.", "sources": ["pps"]},
        {"pps": "조달청"},
    )
    assert "고객 질문: 실크가 뭐예요?" in a and "(쓴 출처: 조달청)" in a
    assert set(judge.fake(judge.EXPERT)) == set(judge.EXPERT.criteria)
