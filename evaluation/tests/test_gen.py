"""생성기 공통 도구: 시드 · 고른 배치 · 2:1 · 층화 표본 · 조각 분리 · 근사 중복 · 잡음"""

from collections import Counter

from evaluation.common import gen


def test_rng_same_seed_same_sequence():
    a, b, c = gen.rng("wallpaper"), gen.rng("wallpaper"), gen.rng("carpentry")
    xs = [a.random() for _ in range(5)]
    assert xs == [b.random() for _ in range(5)]
    assert xs != [c.random() for _ in range(5)]


def test_balanced_rows_even_core_cells_and_extra_values():
    rows = gen.balanced_rows(
        gen.rng("t"), 100, {"a": (1, 2), "b": ("x", "y", "z")}, {"c": ("p", "q", "r", "s")}
    )
    cells = Counter((r["a"], r["b"]) for r in rows)
    assert len(cells) == 6 and max(cells.values()) - min(cells.values()) <= 1
    vals = Counter(r["c"] for r in rows)
    assert set(vals) == {"p", "q", "r", "s"} and max(vals.values()) - min(vals.values()) <= 1


def test_assign_splits_is_2to1_overall_and_per_group():
    rows = gen.balanced_rows(gen.rng("t"), 555, {"g": ("a", "b", "c", "d")})
    gen.assign_splits(rows, group=lambda r: r["g"])
    total = Counter(r["split"] for r in rows)
    assert total == {"dev": 370, "heldout": 185}
    for g in "abcd":
        part = Counter(r["split"] for r in rows if r["g"] == g)
        assert abs(part["dev"] - 2 * part["heldout"]) <= 2


def test_allocate_spreads_evenly_and_moves_leftover():
    assert gen.allocate(10, {"a": 100, "b": 100, "c": 100}) == {"a": 4, "b": 3, "c": 3}
    assert gen.allocate(10, {"a": 1, "b": 100}) == {"a": 1, "b": 9}
    assert sum(gen.allocate(500, {"a": 3, "b": 4}).values()) == 7


def test_stratified_sample_keeps_order_and_balance():
    items = [{"i": i, "k": i % 3} for i in range(90)]
    first = gen.stratified_sample(items, 9, key=lambda x: x["k"])
    assert [x["i"] for x in first] == list(range(9))
    r1 = gen.stratified_sample(items, 9, key=lambda x: x["k"], r=gen.rng("s", 1))
    r2 = gen.stratified_sample(items, 9, key=lambda x: x["k"], r=gen.rng("s", 1))
    assert r1 == r2 and Counter(x["k"] for x in r1) == {0: 3, 1: 3, 2: 3}
    assert [x["i"] for x in r1] == sorted(x["i"] for x in r1)


def test_sample_2to1_split_ratio():
    items = [{"i": i, "split": "heldout" if i % 3 == 2 else "dev", "k": i % 5} for i in range(300)]
    s = gen.sample_2to1(items, 30, key=lambda x: x["k"])
    assert Counter(x["split"] for x in s) == {"dev": 20, "heldout": 10}


def test_fragments_never_share_between_splits():
    f = gen.Fragments({"x": [f"조각{i}" for i in range(10)]})
    dev = {i for i, _ in f.part("x", "dev")}
    held = {i for i, _ in f.part("x", "heldout")}
    assert held == {2, 5, 8} and not dev & held and dev | held == set(range(10))
    used: list[str] = []
    got = f.sample(gen.rng("t"), "x", "heldout", 2, used)
    assert len(set(got)) == 2 and all(int(u.split(":")[1]) % 3 == 2 for u in used)


def test_near_dup_ignores_numbers_and_spaces():
    assert gen.norm("34평 112.4㎡ 1,262,725원") == "#평#㎡#원"
    nd = gen.NearDup(0.8)
    assert nd.add("34평 아파트 실크로 벽이랑 천장까지 도배해요", "dev")
    assert not nd.add("25평 아파트 실크로 벽이랑 천장까지 도배해요", "dev")
    assert nd.add("25평 아파트 실크로 벽이랑 천장까지 도배해요", "heldout")
    assert nd.add("욕실 타일 줄눈도 다시 해 주세요", "dev")
    assert gen.jaccard(gen.grams("가나다라"), gen.grams("가나다라")) == 1.0


def test_noisy_is_deterministic_and_reports_changes():
    text = "천장도 해 주세요. 34평이에요."
    a = gen.noisy(text, gen.rng("n"), k=3)
    b = gen.noisy(text, gen.rng("n"), k=3)
    assert a == b
    out, ops = gen.noisy(text, gen.rng("n"), k=1, ops=("ceiling_typo",))
    assert out == "천정도 해 주세요. 34평이에요." and ops == ["ceiling_typo"]
    same, none = gen.noisy("abc", gen.rng("n"), k=1, ops=("ceiling_typo",))
    assert same == "abc" and none == []


def test_jsonl_roundtrip_writes_lf(tmp_path):
    p = tmp_path / "x.jsonl"
    rows = [{"id": "a", "말": "천장"}, {"id": "b", "n": 1}]
    assert gen.write_jsonl(p, rows) == 2
    assert b"\r\n" not in p.read_bytes()
    assert gen.read_jsonl(p) == rows
    assert gen.get(rows[0], "id") == "a" and gen.get(rows[0], "x.y") is None
