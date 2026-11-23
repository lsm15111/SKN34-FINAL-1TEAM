"""공정 지식 묶음(app.knowledge.expert_pack): 파일 꼴 · 공정 범위 읽기 · 번호 · CSV · 넣기 멱등(테스트 DB).

유료 API는 부르지 않아요(임베딩 없이 키워드 검색으로만 켜요).
"""

import asyncio
import csv
import json
import shutil
from pathlib import Path

import pytest
from conftest import query

from app import data_ingest
from app.knowledge import bm25, expert_pack, service
from app.knowledge import ingest as rag
from app.knowledge.sources import assemble

SCOPE = {"dobae": "도배", "mokgong": "목공", "common": bm25.COMMON}


def good_chunk(i: int = 1, trade: str = "dobae") -> dict:
    return {
        "id": f"{trade}-{i:03d}",
        "trade": trade,
        "also": [],
        "tags": ["바탕"],
        "title": "바탕 습도 재기",
        "body": "초배 전에 전자습도계로 바탕 습도를 재요.",
        "hints": ["벽이 말랐는지 어떻게 알아요?"],
        "sources": [
            {
                "org": "한국토지주택공사(LH)",
                "doc": "LHCS 41 51 05 도배공사",
                "url": "https://www.lh.or.kr",
                "section": "3.2 (4)",
                "checked": "2026-11-23",
                "kind": "kcs",
            }
        ],
    }


def write_pack(root: Path, data: dict[str, list[dict]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for trade in expert_pack.TRADES:
        rows = data.get(trade, [])
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        (root / f"{trade}.jsonl").write_text(text, encoding="utf-8")


def test_pack_files_pass_check():
    data, problems = expert_pack.check()
    assert problems == []
    n = {t: len(data[t]) for t in expert_pack.TRADES}
    assert n["dobae"] >= 50 and n["mokgong"] >= 50 and n["common"] >= 25


def test_primers_are_short_and_have_no_money():
    for trade in ("dobae", "mokgong"):
        p = expert_pack.DIR / f"{trade}_primer.md"
        size = p.stat().st_size
        text = p.read_text(encoding="utf-8")
        assert 4000 <= size <= 6000, (p.name, size)
        assert not expert_pack.MONEY.search(text)
        for head in (
            "핵심 개념",
            "판단 기준",
            "흔한 하자",
            "검수",
            "고객에게 물을 조건",
            "다른 공정과 순서",
            "출처",
        ):
            assert head in text, (p.name, head)


def test_check_catches_bad_chunks(tmp_path):
    bad = [
        dict(good_chunk(1), body="벽지 값은 평당 3만 원이에요."),  # 금액
        dict(good_chunk(2), tags=["가격"]),  # 목록 밖 주제
        dict(good_chunk(3), body="가" * (expert_pack.BODY_MAX + 1)),  # 너무 김
        dict(good_chunk(4), trade="mokgong"),  # 파일과 다른 공정
        dict(good_chunk(5), sources=[dict(good_chunk()["sources"][0], url="repo:data/x.pdf")]),
        dict(good_chunk(6), also=["common"]),
        good_chunk(7),
        good_chunk(7),  # id 겹침
    ]
    write_pack(tmp_path, {"dobae": bad})
    _, problems = expert_pack.check(tmp_path)
    text = "\n".join(map(str, problems))
    for words in ("금액", "tags", "body", "trade", "url", "also", "겹쳐요"):
        assert words in text, words
    write_pack(tmp_path, {"dobae": [good_chunk()]})
    assert expert_pack.check(tmp_path)[1] == []


def test_refs_are_stable_and_scope_reads_trade():
    data, _ = expert_pack.check()
    rows = expert_pack.rows(data)
    refs = [r["ref"] for r in rows]
    assert len(refs) == len(set(refs))
    for r in rows:
        trade = r["id"].split("-")[0]
        n = int(r["id"].split("-")[1])
        assert r["ref"] == f"K{expert_pack.START[trade] + n - 1}"
        scope = bm25.scope_of(tuple(r["trades"].split(";")))
        assert SCOPE[trade] in scope, (r["id"], scope)
        if trade == "common":
            assert scope == (bm25.COMMON,)
    # 다른 지식 자료와 번호가 겹치지 않아요(assemble가 겹치면 ValueError)
    from v3_kb import datasets

    chunks, _ = assemble([*datasets(), (expert_pack.KEY, rows)])
    ix = bm25.build(chunks, {}, "t")
    expert = [x for x in ix.items if x.chunk.rid.startswith(expert_pack.KEY)]
    assert len(expert) == len(rows)
    assert {x.scope for x in expert} <= {("도배",), ("목공",), ("공통",), ("도배", "목공")}


def test_csv_is_deterministic(tmp_path):
    a = expert_pack.write_csv(tmp_path / "a")
    b = expert_pack.write_csv(tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()
    found = data_ingest.inspect_csv(a)
    assert found.kind == "knowledge" and found.key == expert_pack.KEY
    with a.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(found.hashes) == len(rows) == sum(len(v) for v in expert_pack.check()[0].values())
    assert all(r["pack"] == expert_pack.PACK_VERSION for r in rows)


def test_ingest_is_idempotent_and_searchable(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "token_counter", lambda: lambda _: 10)
    monkeypatch.setattr(service, "_cache", None)
    out = tmp_path / "csv"
    expert_pack.write_csv(out)
    n = sum(len(v) for v in expert_pack.check()[0].values())

    asyncio.run(expert_pack.ingest(out, execute=False))  # 계획만: DB를 바꾸지 않아요
    assert query("select count(*) n from ref_dataset_versions")[0]["n"] == 0
    for _ in range(2):  # 두 번 넣어도 버전 하나
        asyncio.run(expert_pack.ingest(out, execute=True))
    rows = query("select version, status, provenance from ref_dataset_versions")
    assert [(r["version"], r["status"]) for r in rows] == [(1, True)]
    assert json.loads(rows[0]["provenance"])["row_count"] == n
    assert query("select count(*) n from rag_chunks where embedding is null")[0]["n"] == n

    async def find():
        from app.db import SessionLocal

        async with SessionLocal() as s:
            return await service.search(s, "곰팡이 벽 도배 전에 할 일 방균 풀", trade="도배", k=5)

    hits = asyncio.run(find()).hits
    assert hits and all(int(h.ref[1:]) >= expert_pack.START["dobae"] for h in hits)
    assert any(h.scope == ("도배",) for h in hits)

    # 조각 하나를 고치면 새 버전이 켜지고 옛 버전은 꺼져요
    root = tmp_path / "pack"
    shutil.copytree(expert_pack.DIR, root)
    data, _ = expert_pack.check(root)
    data["common"][0]["body"] += " 고친 문장이에요."
    write_pack(root, data)
    out2 = tmp_path / "csv2"
    expert_pack.write_csv(out2, root)
    monkeypatch.setattr(service, "_cache", None)
    asyncio.run(expert_pack.ingest(out2, execute=True))
    rows = query("select version, status from ref_dataset_versions order by version")
    assert [(r["version"], r["status"]) for r in rows] == [(1, False), (2, True)]


def test_cli_refuses_bad_pack(tmp_path, capsys, monkeypatch):
    write_pack(tmp_path, {"dobae": [dict(good_chunk(), body="벽지 값은 삼십만 원이에요.")]})
    monkeypatch.setattr(expert_pack, "DIR", tmp_path)
    assert expert_pack.main(["check"]) == 1
    with pytest.raises(ValueError, match="검사 실패"):
        expert_pack.write_csv(tmp_path / "out", tmp_path)
