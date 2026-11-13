"""지식 키워드 검색(BM25)과 활성 버전 색인. LLM · 임베딩 호출 없음."""

import asyncio

import pytest
from conftest import query

from app.db import SessionLocal
from app.knowledge import bm25, service, suggest
from app.knowledge.json_csv import rows as json_rows
from app.knowledge.sources import assemble
from tests.helpers import knowledge_chunk, knowledge_version


def _ix(*items: tuple[str, str, str, tuple[str, ...]]) -> bm25.Index:
    """(ref, kind, 본문, 공정) 목록으로 작은 색인"""
    chunks = [bm25.Chunk(ref=r, doc=f"d{r}", text=t, trades=tr, rid=r) for r, _, t, tr in items]
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


def test_trade_weight_lifts_same_trade_chunk():
    ix = _ix(
        ("K1", "kcs", "작업 순서와 확인 기준", ("목공",)),
        ("K2", "kcs", "작업 순서와 확인 기준", ("도배",)),
    )
    assert refs(bm25.search(ix, "작업 순서 기준", trade="목공"))[0] == "K1"
    assert refs(bm25.search(ix, "작업 순서 기준", trade="도배"))[0] == "K2"


def test_dense_order_brings_in_chunk_without_shared_words():
    ix = _ix(("K1", "official", "벽지 들뜸 원인", ()), ("K2", "official", "곰팡이 결로 환기", ()))
    assert refs(bm25.search(ix, "벽지 들뜸")) == ["K1"]
    assert refs(bm25.search(ix, "벽지 들뜸", dense=["K2", "K1"])) == ["K1", "K2"]


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


def test_service_searches_active_versions_only():
    active = knowledge_version("consult", "active")
    draft = knowledge_version("book", "draft")
    knowledge_chunk(active, "K1", "벽지 들뜸은 풀칠 부족이 원인")
    knowledge_chunk(draft, "K5001", "벽지 들뜸 현장 보수 순서")

    async def run(q: str) -> list[str]:
        async with SessionLocal() as s:
            return refs(await service.search(s, q))

    assert asyncio.run(run("벽지 들뜸")) == ["K1"]
    # 활성 버전이 바뀌면 색인을 다시 만든다
    query("update ref_dataset_versions set status='active' where id=$1", draft)
    assert set(asyncio.run(run("벽지 들뜸"))) == {"K1", "K5001"}
    query("update ref_dataset_versions set status='retired' where id in ($1, $2)", active, draft)
    assert asyncio.run(run("벽지 들뜸")) == []


def test_service_adds_nearest_chunks_of_same_model():
    v = knowledge_version("consult")
    knowledge_chunk(v, "K1", "벽지 들뜸은 풀칠 부족이 원인", embedding=[0.0, 1.0, 0.0])
    knowledge_chunk(v, "K2", "결로가 생기면 환기부터 해요", embedding=[1.0, 0.0, 0.0])

    async def run(embedding) -> list[str]:
        async with SessionLocal() as s:
            return refs(await service.search(s, "벽지 들뜸", embedding=embedding))

    assert asyncio.run(run(None)) == ["K1"]
    assert asyncio.run(run(("test-model", [1.0, 0.1, 0.0]))) == ["K1", "K2"]
    # 모델 · 차원이 다른 임베딩은 의미 검색에 쓰지 않는다
    assert asyncio.run(run(("other-model", [1.0, 0.1, 0.0]))) == ["K1"]
    assert asyncio.run(run(("test-model", [1.0, 0.1]))) == ["K1"]


def _suggest_ix() -> bm25.Index:
    chunks = [
        bm25.Chunk(ref="K1", doc="d", text="합지는 종이 벽지예요", hints=("합지 벽지는 뭐예요?",), rid="K1"),
        bm25.Chunk(
            ref="K2", doc="d", text="실크 벽지는 물걸레로 닦을 수 있어요",
            hints=("실크 벽지는 닦아도 돼요?", "실크 벽지 비싸요?", "3) 실크 시공", "실크 벽지 브랜드 추천해요?"),
            rid="K2",
        ),
        bm25.Chunk(ref="K3", doc="d", text="초배지는 벽을 고르게 해요", hints=("초배지는 왜 발라요?",), rid="K3"),
        bm25.Chunk(ref="K4", doc="d", text="욕실 벽지는 습기에 약해요", hints=("욕실 벽지도 돼요?",), rid="K4"),
    ]  # fmt: skip
    return bm25.build(chunks, {"d": bm25.Doc(title="벽지 안내", kind="official")})


def test_suggest_pick_filters_form_money_out_and_answered():
    ix = _suggest_ix()
    q = "합지 벽지 특징이 뭐예요?"
    cands = suggest.candidates(ix, q, shown=["K1", "K2"], cited={"K1"})
    texts = [p.text for p in suggest.pick(ix, q, cands=cands, cited={"K1"})]
    assert texts == ["실크 벽지는 닦아도 돼요?"]
    # 빠진 것: 인용한 조각 질문(이미 답함) · 금액 · 제목 · 추천 · 범위 밖(욕실) · 이어지지 않음(초배)
    llm = suggest.candidates(ix, q, shown=[], cited=set(), llm=["합지 벽지 특징은 뭐예요?"])
    assert "합지 벽지 특징은 뭐예요?" not in [
        p.text for p in suggest.pick(ix, q, cands=llm, cited=set())
    ]


def test_suggest_pick_uses_meaning_closeness_when_given():
    ix = _suggest_ix()
    q = "합지 벽지 특징이 뭐예요?"
    cands = suggest.candidates(ix, q, shown=["K1", "K2", "K3"], cited={"K1"})
    sims = {
        "실크 벽지는 닦아도 돼요?": 0.45,
        "초배지는 왜 발라요?": 0.55,
        "합지 벽지는 뭐예요?": 0.9,
    }
    texts = [p.text for p in suggest.pick(ix, q, cands=cands, cited={"K1"}, sims=sims)]
    # 가까운 순, 글자가 안 겹쳐도 뜻이 가까우면 남는다
    assert texts == ["초배지는 왜 발라요?", "실크 벽지는 닦아도 돼요?"]
    far = {t: 0.2 for t in sims} | {
        "초배지는 왜 발라요?": 0.7
    }  # 너무 멀거나 되풀이에 가까우면 뺀다
    assert suggest.pick(ix, q, cands=cands, cited={"K1"}, sims=far) == []
