"""지식 키워드 검색(BM25)과 활성 버전 색인. LLM · 임베딩 호출 없음."""

import asyncio
import json
import uuid

import pytest
from conftest import query

from app.db import SessionLocal
from app.knowledge import bm25, service
from app.knowledge.json_csv import rows as json_rows
from app.knowledge.sources import assemble


def _ix(*items: tuple[str, str, str, tuple[str, ...]]) -> bm25.Index:
    """(ref, kind, 본문, 공정) 목록으로 작은 색인"""
    chunks = [bm25.Chunk(ref=r, doc=f"d{r}", text=t, trades=tr) for r, _, t, tr in items]
    docs = {f"d{r}": bm25.Doc(title="", kind=kind) for r, kind, _, _ in items}
    return bm25.build(chunks, docs)


def refs(result: bm25.Result) -> list[str]:
    return [h.ref for h in result.hits]


def test_grams_split_korean_into_pairs():
    assert bm25.grams("도배풀 PVC, 벽") == ["도배", "배풀", "pvc", "벽"]


def test_trade_of_picks_only_single_trade():
    assert bm25.trade_of("벽지 들뜸") == "도배"
    assert bm25.trade_of("벽지랑 몰딩") is None
    assert bm25.trade_of("관리사무소 신고") is None


def test_synonym_query_finds_other_word():
    ix = _ix(
        ("K1", "official", "굽도리 시공 순서와 마감", ()), ("K2", "official", "창호 교체 안내", ())
    )
    assert refs(bm25.search(ix, "걸레받이"))[:1] == ["K1"]


def test_money_question_excludes_blogs():
    ix = _ix(
        ("K1", "blog", "도배 비용 후기 평당 얼마", ("도배",)),
        ("K2", "consumer_agency", "도배 비용 분쟁 안내", ("도배",)),
    )
    r = bm25.search(ix, "도배 비용 얼마예요")
    assert refs(r) == ["K2"] and "money" in r.policy
    assert "K1" in refs(bm25.search(ix, "도배 후기"))


def test_field_slot_puts_trade_book_chunk_in():
    ix = _ix(
        ("K1", "kcs", "초배 정배 순서 초배 정배 순서", ("도배",)),
        ("K2", "kcs", "초배 정배 순서 기준", ("도배",)),
        ("K3", "book", "현장에서 초배 정배 순서는 이렇게", ("도배",)),
    )
    assert refs(bm25.search(ix, "초배 정배 순서", k=2))[-1] == "K3"


def test_enough_is_false_for_unrelated_question():
    ix = _ix(("K1", "official", "석고보드 이음 처리", ("목공",)))
    assert bm25.search(ix, "석고보드 이음").enough
    assert not bm25.search(ix, "주차장 출입 등록 방법").enough


def test_verify_cites_drops_unrelated_reference():
    ix = _ix(
        ("K1", "official", "석고보드 이음은 퍼티로 메운다", ()),
        ("K2", "official", "엘리베이터 사용 신고", ()),
    )
    text, dropped = bm25.verify_cites(ix, "석고보드 이음은 퍼티로 메워요 [K1][K2]")
    assert dropped == 1 and "[K1]" in text and "[K2]" not in text


def test_assemble_numbers_team_rows_and_keeps_own_refs():
    team = [
        {"id": "B", "content": "둘", "section": "2절", "page": "3", "source": "기준.pdf", "source_org": "LH", "source_url": ""},
        {"id": "A", "content": "하나", "section": "1절", "page": "", "source": "기준.pdf", "source_org": "LH", "source_url": ""},
    ]  # fmt: skip
    own = json_rows(
        {"version": "v1", "docs": {"d": {"title": "안내", "kind": "gov"}},
         "chunks": [{"k": "K7", "doc": "d", "text": "본문", "hints": ["질문?"], "trades": ["도배"]}]},
        "0" * 64,
    )  # fmt: skip
    chunks, docs = assemble([("05_lhcs_wallpaper_rag", team), ("consult", own)])
    assert [(c.ref, c.text, c.sec) for c in chunks] == [
        ("K7", "본문", ""), ("K2001", "하나", "1절"), ("K2002", "둘", "2절 · 3쪽"),
    ]  # fmt: skip
    assert chunks[0].hints == ("질문?",) and chunks[0].trades == ("도배",)
    assert (
        docs["team:05_lhcs_wallpaper_rag"].title == "기준"
        and docs["team:05_lhcs_wallpaper_rag"].kind == "official"
    )
    with pytest.raises(ValueError):
        assemble([("a", own), ("b", own)])


def _version(key: str, status: str) -> uuid.UUID:
    ident = uuid.uuid4()
    query(
        """insert into ref_dataset_versions
        (id,dataset_key,kind,version,source,processed_path,processed_sha256,build_profile,
         historical,current_rule_usable,calculation_usable,reference_usable,
         embedding_model,embedding_dimensions,provenance,status)
        values ($1,$2,'knowledge',1,'synthetic.pdf','synthetic.csv',$3,'test-v1',
                false,false,false,true,'test-model',3,'{}'::jsonb,$4)""",
        ident, key, uuid.uuid4().hex * 2, status,
    )  # fmt: skip
    return ident


def _chunk(dataset: uuid.UUID, ref: str, content: str) -> None:
    prov = {"id": ref, "ref": ref, "doc": "d", "source": "안내", "source_org": "믿집",
            "source_url": "", "source_type": "official", "trades": "도배", "hints": "[]"}  # fmt: skip
    query(
        """insert into rag_chunks
        (dataset_id,dataset_kind,record_key,section,content,page_numbers,content_hash,provenance)
        values ($1,'knowledge',$2,'',$3,'{1}',$4,$5::jsonb)""",
        dataset, ref, content, "a" * 64, json.dumps(prov, ensure_ascii=False),
    )  # fmt: skip


def test_service_searches_active_versions_only():
    active = _version("consult", "active")
    draft = _version("book", "draft")
    _chunk(active, "K1", "벽지 들뜸은 풀칠 부족이 원인")
    _chunk(draft, "K5001", "벽지 들뜸 현장 보수 순서")

    async def run(q: str) -> list[str]:
        async with SessionLocal() as s:
            return refs(await service.search(s, q))

    assert asyncio.run(run("벽지 들뜸")) == ["K1"]
    # 활성 버전이 바뀌면 색인을 다시 만든다
    query("update ref_dataset_versions set status='active' where id=$1", draft)
    assert set(asyncio.run(run("벽지 들뜸"))) == {"K1", "K5001"}
    query("update ref_dataset_versions set status='retired' where id in ($1, $2)", active, draft)
    assert asyncio.run(run("벽지 들뜸")) == []
