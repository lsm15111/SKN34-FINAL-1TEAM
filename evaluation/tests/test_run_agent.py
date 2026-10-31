"""실행기 · 비용 · 판정 스키마. 가짜 LLM으로만 돌린다 (유료 호출 0회)."""

import asyncio
import json
from collections import Counter

import pytest

from evaluation import run_agent
from evaluation.common import cost, gen
from evaluation.judge import judge


@pytest.fixture
def wp_sample() -> list[dict]:
    return gen.read_jsonl(run_agent.HERE / "wallpaper" / "sample_100.jsonl")


def test_select_keeps_2to1_and_strata(wp_sample):
    picked = run_agent.select(wp_sample, sample=30, seed=1)
    assert Counter(c["split"] for c in picked) == {"dev": 20, "heldout": 10}
    assert len({c["category"] for c in picked}) == 9
    assert picked == run_agent.select(wp_sample, sample=30, seed=1)
    dev = run_agent.select(wp_sample, split="dev", sample=9, stratify="strata.occupied")
    assert {c["split"] for c in dev} == {"dev"} and len(dev) == 9


def test_estimate_only_shows_all_models(wp_sample):
    text = run_agent.plan_text("wallpaper", wp_sample[:20], 5, "claude-opus-5-5", "medium")
    assert "공정 의견 20번 + 판정 5번" in text
    for label in cost.MODEL_LABEL.values():
        assert f"| {label} |" in text


@pytest.mark.parametrize("agent", ["wallpaper", "carpentry"])
def test_fake_run_end_to_end(tmp_path, agent):
    from app.agent import llm
    from app.config import settings

    cases = gen.read_jsonl(run_agent.HERE / agent / "sample_100.jsonl")[:6]
    before = llm.parse
    results = asyncio.run(
        run_agent.run(agent, cases, judge_ids={cases[0]["id"]}, fake=True, concurrency=3)
    )
    assert llm.parse is before and settings.llm_live is False
    assert [r["id"] for r in results] == [c["id"] for c in cases]
    for r in results:
        assert r["status"] == "ok" and r["dropped"] == 0
        assert all(r["scores"]["checks"].values()), r["scores"]["detail"]
    assert results[0]["judge"]["correct"]["score"] == 5 and "judge" not in results[1]

    meta = {
        "agent": agent,
        "model": "fake",
        "effort": "-",
        "prompt_version": "test",
        "rubric": judge.RUBRIC_VERSION,
        "cases": "x.jsonl",
        "stratify": "category",
        "seed": 1,
    }
    report = run_agent.write(tmp_path, meta, results)
    saved = json.loads((tmp_path / "raw.json").read_text(encoding="utf-8"))
    assert saved["results"] == results
    assert "**모든 코드 검사 통과** | 100% (6/6)" in report
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == report


def test_one_broken_case_does_not_stop_the_run(wp_sample):
    import copy

    broken = copy.deepcopy(wp_sample[0])
    broken["input"]["common"]["area_m2"] = "0.0"  # 계산 엔진이 ValueError
    results = asyncio.run(
        run_agent.run("wallpaper", [broken, wp_sample[1]], judge_ids=set(), fake=True)
    )
    assert results[0]["status"] == "failed" and results[0]["reason"] == "error:ValueError"
    assert results[0]["scores"] is None and results[1]["status"] == "ok"
    assert "의견 생성 성공 (화면에 보임) | 50% (1/2)" in run_agent.summarize(
        {
            "agent": "wallpaper",
            "model": "fake",
            "effort": "-",
            "prompt_version": "t",
            "cases": "x",
            "stratify": "category",
            "seed": 1,
        },
        results,
    )


def test_rescore_uses_saved_raw(wp_sample):
    cases = wp_sample[:2]
    results = asyncio.run(run_agent.run("wallpaper", cases, judge_ids=set(), fake=True))
    results[0]["raw"]["visit_checks"].append("천장 높이가 2.4m인지 재요.")
    run_agent.rescore("wallpaper", results, {c["id"]: c for c in cases})
    assert results[0]["scores"]["checks"]["no_digits"] is False
    assert results[1]["scores"]["checks"]["no_digits"] is True


def test_cost_from_usage_and_estimate():
    u = {
        "model": "claude-opus-5-5",
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_read_tokens": 1_000_000,
        "cache_write_tokens": 1_000_000,
        "ms": 1,
    }
    assert cost.call_cost(u) == pytest.approx(4 + 20 + 0.2 + 5)
    assert cost.call_cost(u | {"model": "unknown"}) is None
    assert cost.total_cost([u, u | {"model": "x"}]) == (pytest.approx(29.2), 1)
    shape = cost.CallShape(uncached=100, system=1000, output=500, basis="t")
    batch = cost.estimate(shape, 10, "claude-sonnet-5-5", batch=True)
    assert batch == pytest.approx(10 * (1100 * 2 + 500 * 10) / 2 / 1e6)
    normal = cost.estimate(shape, 10, "claude-sonnet-5-5", concurrency=2)
    want = (10 * (100 * 2 + 500 * 10) + 2 * 1000 * 2.5 + 8 * 1000 * 0.1) / 1e6
    assert normal == pytest.approx(want)
    assert "| Haiku 5.5 |" in cost.estimate_table("wallpaper", judge=10)


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
