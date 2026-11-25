"""v3 검색: 지금 키워드 검색(bm25)을 12공종 무게로 돌린다. DB · HTTP를 모르는 순수 함수.

bm25.search는 도배 · 목공 두 공정만 알아서 다른 공종 조각을 '범위 밖'으로 깎는다(v2 규칙, 그대로 둠).
여기서는 조각의 공정 표시를 부르는 쪽이 넘긴 표(tags: 표시 → 공종 코드)로 읽어,
같은 공종 +, 공통 +, 다른 공종만 −로 무게를 준다(무게 값은 bm25.CONF 그대로).
"""

from collections.abc import Mapping

from app.knowledge import bm25

_scope_cache: dict[int, tuple[Mapping[str, str], dict[str, frozenset[str]]]] = {}


def scopes(ix: bm25.Index, tags: Mapping[str, str]) -> dict[str, frozenset[str]]:
    """조각 번호 → 공종 코드 묶음(표시가 없거나 공통뿐이면 {'common'}). 색인마다 한 번 만든다."""
    hit = _scope_cache.get(id(ix))
    if hit and hit[0] is tags:
        return hit[1]
    out: dict[str, frozenset[str]] = {}
    for x in ix.items:
        got = {tags.get(t) for t in x.chunk.trades} - {None, "common"}
        out[x.chunk.ref] = frozenset(got) if got else frozenset({"common"})  # type: ignore[arg-type]
    _scope_cache[id(ix)] = (tags, out)
    return out


def search(
    ix: bm25.Index,
    q: str,
    *,
    trades: list[str] | tuple[str, ...] = (),
    tags: Mapping[str, str],
    k: int = 6,
    policy_text: str | None = None,
    exclude_kinds: frozenset[str] = frozenset(),
) -> bm25.Result:
    """검색어(+ 동의어)를 BM25로 찾아 RRF로 합치고 출처 등급 · 공종 무게를 더한다.

    법 · 안전 · 금액 질문은 블로그 · 후기를 뺀다(bm25.POLICY). exclude_kinds: 더 뺄 출처 종류(예: 책).
    """
    if not ix.items:
        return bm25.Result([], False, [])
    main = (q or "")[:80]
    qs_all = [main]
    syn = bm25._syn_query(main)
    if syn and syn not in qs_all:
        qs_all.append(syn)
    kinds, exclude = bm25.policy_of(policy_text or main)
    exclude = set(exclude) | set(exclude_kinds)
    want = set(trades) - {"common"}
    sc = scopes(ix, tags)
    fused: dict[bm25.Item, float] = {}
    for qq in qs_all:
        for r, x in enumerate(bm25._bm25(ix, qq, None)):
            if x.doc.kind in exclude:
                continue
            fused[x] = fused.get(x, 0.0) + 1 / (bm25.CONF["rrf_k"] + r + 1)

    def bonus(x: bm25.Item) -> float:
        b = bm25.CONF["tier_w"] * bm25.TIER.get(x.doc.kind, 0.5)
        b += bm25.CONF["high_w"] if x.doc.rel == "high" else 0.0
        if want:
            s = sc.get(x.chunk.ref, frozenset({"common"}))
            if s & want:
                b += bm25.CONF["trade_w"]
            elif s == {"common"}:
                b += bm25.CONF["common_w"]
            else:
                b -= bm25.CONF["out_w"]
        return b

    ranked = sorted(((s + bonus(x), x) for x, s in fused.items()), key=lambda p: -p[0])[:k]
    best = max(bm25._coverage(qq, ranked[0][1]) for qq in qs_all) if ranked else 0.0
    hits = [
        bm25.Hit(
            ref=x.chunk.ref,
            source_type=bm25.TYPE_KO.get(x.doc.kind, "기타"),
            title=x.doc.title,
            publisher=x.doc.pub,
            date=x.doc.date,
            section=x.chunk.sec,
            text=x.chunk.text,
            score=round(s * 1000, 1),
            url=x.doc.url,
            official=bm25.TIER.get(x.doc.kind, 0.5) >= 0.8,
        )
        for s, x in ranked
    ]
    return bm25.Result(hits, best >= bm25.CONF["enough_cov"], kinds)
