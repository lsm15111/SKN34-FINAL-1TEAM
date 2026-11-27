"""v3 지식 요지 202개(data/v3/knowledge/chunks.jsonl)를 임베딩 없이 키워드 검색에 넣는 길(B6).

- CSV는 에이전트 담당 변환기(`app.knowledge.v3_csv`, 번호 `v3_csv.START`~ = K20001~)로 만들어요. 번호 규칙을 한 곳에만 둬요.
- 적재 · 활성화는 테스트 DB에서만 해요. 유료 API는 부르지 않아요.
"""

import asyncio
import csv
import hashlib
import json
from pathlib import Path

import pytest
from conftest import query

from app import data_ingest as ingest
from app.db import SessionLocal, engine
from app.knowledge import ingest as rag
from app.knowledge import service, v3_csv
from app.knowledge.json_csv import EXTRA, REQUIRED

SRC = Path(__file__).resolve().parents[2] / "data" / "v3" / "knowledge" / "chunks.jsonl"
MODEL, DIMS, PROFILE = "text-embedding-3-small", 3, ingest.BUILD_PROFILE
N = 202  # chunks.jsonl 조각 수(K20001~K20202)


def build(tmp_path: Path) -> tuple[Path, list[dict]]:
    """chunks.jsonl → tmp_path/v3_knowledge_rag.csv (변환기 CLI와 같은 결과)"""
    raw = SRC.read_bytes()
    lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
    rows = v3_csv.rows(lines, hashlib.sha256(raw).hexdigest())
    path = tmp_path / "v3_knowledge_rag.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUIRED + EXTRA, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path, lines


def ref_of(lines: list[dict], words: str) -> str:
    idx = next(i for i, c in enumerate(lines) if words in c["title"])
    return f"K{v3_csv.START + idx}"


async def activate(paths, require_embeddings):
    async with ingest.execution_lock(engine):
        return await ingest.activate_versions(
            SessionLocal,
            [ingest.inspect_csv(p) for p in paths],
            MODEL,
            DIMS,
            PROFILE,
            require_embeddings=require_embeddings,
        )


def test_v3_chunks_make_a_knowledge_csv(tmp_path):
    path, lines = build(tmp_path)
    data = ingest.inspect_csv(path)
    assert data.kind == "knowledge" and data.key == "v3_knowledge_rag"
    assert len(data.hashes) == len(lines) == N
    with path.open(encoding="utf-8-sig", newline="") as f:
        refs = [r["ref"] for r in csv.DictReader(f)]
    first, last = v3_csv.START, v3_csv.START + N - 1
    assert len(set(refs)) == N and (refs[0], refs[-1]) == (f"K{first}", f"K{last}")


def test_keyword_only_activation_makes_chunks_searchable(tmp_path, monkeypatch):
    path, lines = build(tmp_path)
    monkeypatch.setattr(service, "_cache", None)
    want = ref_of(lines, "도배바름 하루 시공량")

    async def run():
        await ingest.load_dataset(SessionLocal, ingest.inspect_csv(path), MODEL, DIMS, PROFILE)
        # 임베딩을 요구하는 기본 활성화는 막혀요(임베딩 0행)
        with pytest.raises(ValueError, match=f"임베딩 미완료 {N}행"):
            await activate([path], require_embeddings=True)
        result = await activate([path], require_embeddings=False)
        assert result[0]["status"] is True and result[0]["embedding_missing"] == N
        async with SessionLocal() as s:
            found = await service.search(s, "도배바름 하루 시공량 표준품셈", k=3)
        refs = [h.ref for h in found.hits]
        assert want in refs and all(v3_csv.START <= int(r[1:]) < v3_csv.START + N for r in refs)

    asyncio.run(run())
    assert query("select count(*) n from rag_chunks where embedding is null")[0]["n"] == N
    assert query("select status from ref_dataset_versions")[0]["status"] is True


def test_keyword_only_is_only_for_knowledge(tmp_path):
    processed = Path(__file__).resolve().parents[2] / "data" / "processed" / "02_unit_price.csv"
    with processed.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        row = next(reader)
        header = reader.fieldnames
    unit = tmp_path / "02_unit_price.csv"
    with unit.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerow(dict(row, id="one", parent_id=""))

    async def run():
        await ingest.load_dataset(SessionLocal, ingest.inspect_csv(unit), MODEL, DIMS, PROFILE)
        with pytest.raises(ValueError, match="지식 CSV에만"):
            await activate([unit], require_embeddings=False)

    asyncio.run(run())
    assert query("select status from ref_dataset_versions")[0]["status"] is False


def test_keyword_only_cli(tmp_path, monkeypatch, capsys):
    build(tmp_path)
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    monkeypatch.setattr(service, "_cache", None)
    base = ["--directory", str(tmp_path), "--dimensions", "3", "--dataset", "v3_knowledge_rag"]
    for bad in (
        ["verify", *base, "--keyword-only"],  # --activate 없이
        ["verify", *base, "--keyword-only", "--activate", "--require-embeddings"],
        ["load", *base, "--keyword-only", "--activate"],
    ):
        with pytest.raises(ValueError, match="--"):
            asyncio.run(ingest.run(ingest.parser().parse_args(bad)))
    assert query("select count(*) n from ref_dataset_versions")[0]["n"] == 0
    asyncio.run(ingest.run(ingest.parser().parse_args(["load", *base, "--execute"])))
    capsys.readouterr()
    asyncio.run(
        ingest.run(ingest.parser().parse_args(["verify", *base, "--keyword-only", "--activate"]))
    )
    out = capsys.readouterr().out
    assert "활성화 완료" in out and "키워드 검색에만" in out and f"{N}행" in out
    assert query("select status from ref_dataset_versions")[0]["status"] is True
