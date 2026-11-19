"""v3 검색 하이브리드(search3 dense): 의미 검색 순위가 키워드 순위와 RRF로 합쳐진다. DB 없음(저장소 색인)."""

from v3_kb import repo_index

from app.agent.v3.trades import TAG_TO_CODE
from app.knowledge import search3


def test_dense_hit_joins_the_ranking_and_empty_dense_keeps_keyword_result():
    ix = repo_index()
    q = "도배 끝나고 창문 열어도 되나요?"
    kw = search3.search(ix, q, trades=["dobae"], tags=TAG_TO_CODE, k=8)
    assert search3.search(ix, q, trades=["dobae"], tags=TAG_TO_CODE, k=8, dense=()).hits == kw.hits
    outside = next(x for x in ix.items if x.chunk.ref not in {h.ref for h in kw.hits})
    rid = next(k for k, v in ix.by_rid.items() if v is outside)
    hy = search3.search(ix, q, trades=["dobae"], tags=TAG_TO_CODE, k=8, dense=[rid])
    assert outside.chunk.ref in {h.ref for h in hy.hits} or len(kw.hits) == 8


def test_unknown_dense_keys_are_ignored():
    ix = repo_index()
    q = "몰딩 교체 순서"
    kw = search3.search(ix, q, trades=["mokgong"], tags=TAG_TO_CODE, k=6)
    hy = search3.search(ix, q, trades=["mokgong"], tags=TAG_TO_CODE, k=6, dense=["없는키"])
    assert [h.ref for h in hy.hits] == [h.ref for h in kw.hits]
