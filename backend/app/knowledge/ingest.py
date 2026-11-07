"""지식 데이터 파일 검사 (적재 전 단계). 원본은 knowledge/data/*.jsonl이고 PR로 고친다.

DB 적재(임베딩 · upsert)는 지식 표 migration과 함께 더한다(docs/agent/04-knowledge.md 5절).
지금은 파일 형식 · 키 중복 · 길이 · 출처 연결만 본다. 하나라도 틀리면 아무것도 적재하지 않는다.
실행: python -m app.knowledge.ingest
"""

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from app.knowledge.triggers import TRIGGERS

DATA = Path(__file__).resolve().parent / "data"

TRADES = ("common", "dobae", "mokgong", "oos")
STAGES = ("start", "quote", "consult", "pick", "visit", "deal", "work", "after", "any")
PHASES = ("P0", "P1", "P2", "P3", "P4", "P5", "P6")
WHY = ("money", "schedule", "defect", "safety", "legal", "paper")
KINDS = ("guide", "faq", "recipe", "defect", "rule", "check")
RELIABILITY = ("official", "industry", "news", "community")
RAG_POLICY = ("full", "summary", "facts", "link", "blocked")
INTENTS = ("style", "texture", "color", "function", "budget", "schedule", "scope", "structure")
# T1~T7 = 조사 트랙 번호, T0 = 메인 세션이 원문을 직접 확인한 출처(docs/research/verify_log.md)
SOURCE_KEY = re.compile(r"^S-T[0-7]-[0-9A-Z]{1,8}$")
CARD_KEY = re.compile(r"^(common|dobae|mokgong|oos)\.[a-z0-9_]{2,40}$")
CHUNK_KEY = re.compile(r"^(common|dobae|mokgong|oos)\.[a-z0-9_.]{2,57}$")


def load(name: str, base: Path = DATA) -> list[dict]:
    path = base / name
    if not path.exists():
        return []
    rows = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{name}:{no} JSON 형식이 아니에요: {e.msg}") from e
    return rows


def _dupes(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for v in values:
        if v in seen:
            out.append(v)
        seen.add(v)
    return out


def _check_sources(rows: list[dict]) -> list[str]:
    bad = [f"sources: 키 중복 {k}" for k in _dupes(r.get("key", "") for r in rows)]
    for r in rows:
        k = r.get("key", "")
        if not SOURCE_KEY.match(k):
            bad.append(f"sources: 키 형식 {k!r}")
        if not str(r.get("url", "")).startswith("http"):
            bad.append(f"sources: {k} url 없음")
        if r.get("reliability") not in RELIABILITY or r.get("rag_policy") not in RAG_POLICY:
            bad.append(f"sources: {k} 신뢰도 · 이용 조건 값")
    return bad


def _check_refs(name: str, key: str, refs: list[str], known: set[str]) -> list[str]:
    if not refs:
        return [f"{name}: {key} 출처 없음"]
    return [f"{name}: {key} 모르는 출처 {s}" for s in refs if s not in known]


def _check_cards(rows: list[dict], known: set[str]) -> list[str]:
    bad = [f"cards: 키 중복 {k}" for k in _dupes(r.get("key", "") for r in rows)]
    for r in rows:
        k = r.get("key", "")
        if not CARD_KEY.match(k):
            bad.append(f"cards: 키 형식 {k!r}")
        if (
            r.get("trade") not in TRADES
            or r.get("stage") not in STAGES
            or r.get("phase") not in PHASES
            or r.get("why") not in WHY
            or r.get("level") not in (1, 2, 3)
        ):
            bad.append(f"cards: {k} 분류 값")
        if not 0 < len(r.get("title", "")) <= 40 or not 0 < len(r.get("body", "")) <= 300:
            bad.append(f"cards: {k} 제목 40자 · 본문 300자")
        if not isinstance(r.get("priority"), int) or not 0 <= r["priority"] <= 100:
            bad.append(f"cards: {k} priority 0~100")
        if r.get("trigger") not in TRIGGERS:
            bad.append(f"cards: {k} 모르는 trigger {r.get('trigger')!r}")
        bad += _check_refs("cards", k, r.get("sources", []), known)
    return bad


def _check_terms(rows: list[dict], known: set[str]) -> list[str]:
    bad = [f"terms: 용어 중복 {t}" for t in _dupes(r.get("term", "") for r in rows)]
    for r in rows:
        t = r.get("term", "")
        if r.get("trade") not in TRADES:
            bad.append(f"terms: {t} 공정 값")
        if not 0 < len(r.get("easy", "")) <= 60 or not 0 < len(r.get("detail", "")) <= 200:
            bad.append(f"terms: {t} 쉬운 말 60자 · 설명 200자")
        bad += _check_refs("terms", t, r.get("sources", []), known)
    return bad


def _check_chunks(rows: list[dict], known: set[str]) -> list[str]:
    bad = [f"chunks: 키 중복 {k}" for k in _dupes(r.get("key", "") for r in rows)]
    for r in rows:
        k = r.get("key", "")
        if not CHUNK_KEY.match(k) or len(k) > 64:
            bad.append(f"chunks: 키 형식 {k!r}")
        if (
            r.get("kind") not in KINDS
            or r.get("trade") not in TRADES
            or r.get("stage") not in STAGES
            or r.get("level") not in (1, 2, 3)
        ):
            bad.append(f"chunks: {k} 분류 값")
        if not 0 < len(r.get("title", "")) <= 80 or not 0 < len(r.get("body", "")) <= 600:
            bad.append(f"chunks: {k} 제목 80자 · 본문 600자")
        bad += _check_refs("chunks", k, r.get("sources", []), known)
    return bad


def _check_lexicon(rows: list[dict], known: set[str]) -> list[str]:
    bad = [f"lexicon: 표현 중복 {p}" for p in _dupes(r.get("phrase", "") for r in rows)]
    for r in rows:
        p = r.get("phrase", "")
        if r.get("intent") not in INTENTS or not r.get("options"):
            bad.append(f"lexicon: {p} 의도 · 옵션")
        c = r.get("confidence")
        if not isinstance(c, (int, float)) or not 0 <= c <= 1:
            bad.append(f"lexicon: {p} confidence 0~1")
        bad += _check_refs("lexicon", p, r.get("sources", []), known)
    return bad


def check(base: Path = DATA) -> list[str]:
    """데이터 파일 문제 목록. 빈 목록이면 적재해도 된다."""
    sources = load("sources.jsonl", base)
    known = {r.get("key", "") for r in sources}
    return [
        *_check_sources(sources),
        *_check_cards(load("cards.jsonl", base), known),
        *_check_terms(load("terms.jsonl", base), known),
        *_check_chunks(load("chunks.jsonl", base), known),
        *_check_lexicon(load("lexicon.jsonl", base), known),
    ]


if __name__ == "__main__":
    problems = check()
    for p in problems:
        print(p)
    print(f"문제 {len(problems)}개")
    sys.exit(1 if problems else 0)
