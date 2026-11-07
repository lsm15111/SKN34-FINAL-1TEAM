"""지식 데이터 · 평가 세트 파일 검사(DB 없이). 데이터는 AI 초안이라 사람 검수 전이다 — 형식만 지킨다."""

import json
from collections import Counter
from pathlib import Path

from app.knowledge import ingest

EVAL = Path(__file__).resolve().parents[2] / "evaluation"
ROUTES = {
    "coach",
    "dobae",
    "mokgong",
    "both",
    "estimate",
    "schedule",
    "howto",
    "oos_trade",
    "oos_other",
    "chitchat",
    "abuse",
    "unclear",
}


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_knowledge_files_pass_checks():
    assert ingest.check() == []


def test_knowledge_coverage():
    cards, chunks = ingest.load("cards.jsonl"), ingest.load("chunks.jsonl")
    assert len(cards) >= 100 and len(ingest.load("terms.jsonl")) >= 60
    assert len(ingest.load("lexicon.jsonl")) >= 50
    per_trade = Counter(c["trade"] for c in chunks)
    assert per_trade["dobae"] >= 20 and per_trade["mokgong"] >= 20 and per_trade["common"] >= 20
    assert {c["phase"] for c in cards} == set(ingest.PHASES)  # 단계마다 카드가 있다


def test_intent_sets_are_labeled_and_split():
    dev, held = rows(EVAL / "intent" / "dev.jsonl"), rows(EVAL / "intent" / "heldout.jsonl")
    ids = [r["id"] for r in dev + held]
    assert len(ids) == len(set(ids)) >= 200
    assert all(r["route"] in ROUTES and r["text"] for r in dev + held)
    assert 1.7 <= len(dev) / len(held) <= 2.3  # dev:held-out = 2:1
    assert {r["route"] for r in held} == {r["route"] for r in dev}  # 경로별로 나눴다


def test_rag_eval_points_to_existing_chunks():
    keys = {c["key"] for c in ingest.load("chunks.jsonl")}
    sets = [rows(EVAL / "rag" / f"{s}.jsonl") for s in ("dev", "heldout")]
    assert len(sets[0]) >= 30
    for r in sets[0] + sets[1]:
        assert r["query"] and r["relevant"] and set(r["relevant"]) <= keys


def test_other_eval_sets_have_required_fields():
    guide = rows(EVAL / "guide" / "dev.jsonl") + rows(EVAL / "guide" / "heldout.jsonl")
    assert len(guide) >= 50 and all(r["question"] and r["must"] for r in guide)
    orch = rows(EVAL / "orchestrator" / "dev.jsonl")
    assert len(orch) >= 30
    for r in orch:  # 경로 하나 또는 다중 경로(실행 순서)
        route = r["expect"]["route"]
        assert set(route if isinstance(route, list) else [route]) <= ROUTES
    consult = rows(EVAL / "consult" / "dev.jsonl")
    assert len(consult) >= 10 and all(r["trade"] in ("dobae", "mokgong") for r in consult)
