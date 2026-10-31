"""공정 의견 생성기 · 무료 점검(T0): 시드를 고정하면 같은 사례가 나오고, 점검이 망가진 사례를 잡는다."""

import copy
import math
from collections import Counter

import pytest

from evaluation import check_cases
from evaluation.common import gen, trades
from evaluation.plan import config, make_cases

TRADES = trades.registered()
COUNTS = {"dobae": (9, 4995), "mokgong": (15, 4995)}  # (범주, 사례): 처음 두 공정은 값으로도 본다


@pytest.fixture(scope="module")
def built() -> dict[str, list[dict]]:
    return {t: make_cases.build(t)[0] for t in TRADES}


@pytest.mark.parametrize("trade", TRADES)
def test_generator_counts_and_2to1(built, trade):
    """범주 = 조건 없는 칸의 값 조합, 범주마다 같은 수 (3의 배수, dev:held-out 2:1)"""
    cases = built[trade]
    cfg = config.get(trade)
    cat_fields, _ = make_cases.layout(trades.spec(trade), cfg)
    n = math.prod(len(make_cases.field_opts(f, cfg)) for f in cat_fields)
    per = max(3, make_cases.TOTAL // n // 3 * 3)
    per_cat = Counter((c["category"], c["split"]) for c in cases)
    cats = {k for k, _ in per_cat}
    assert len(cats) == n and len(cases) == n * per
    assert COUNTS.get(trade, (n, n * per)) == (n, n * per)
    for cat in cats:
        assert per_cat[cat, "dev"] == 2 * per_cat[cat, "heldout"] == per * 2 // 3
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["trade"] for c in cases} == {trade}


@pytest.mark.parametrize("trade", TRADES)
def test_committed_sample_matches_generator(built, trade):
    """커밋한 표본 100개 · README가 지금 생성기와 같다 (생성기 · 스펙을 고치면 다시 만든다)."""
    sample = make_cases.sample(built[trade])
    assert len(sample) == 100
    assert Counter(c["split"] for c in sample) == {"dev": 67, "heldout": 33}
    d = make_cases.out_dir(trade)
    assert sample == gen.read_jsonl(d / "sample_100.jsonl")
    readme = (d / "README.md").read_text(encoding="utf-8")
    assert readme == make_cases.readme(trade, built[trade], sample)


@pytest.mark.parametrize("trade", TRADES)
def test_check_passes_on_committed_sample(trade):
    r = check_cases.check_set(trade, gen.read_jsonl(make_cases.out_dir(trade) / "sample_100.jsonl"))
    assert r["problems"] == {}
    assert check_cases.ok(r, full=False)


@pytest.mark.parametrize("trade", TRADES)
def test_unknown_fields_use_spec_defaults_and_are_left_to_check(built, trade):
    """'모르겠어요'는 스펙 기본값 + to_check, 조건이 꺼진 칸은 비우고, 같이 하는 공정도 칸이 다 찬다"""
    sp = trades.spec(trade)
    for c in built[trade]:
        card = c["input"]["card"]
        v = card["values"][trade]
        for name in card["to_check"]:
            if name.startswith(f"{trade}."):
                assert v[name.split(".")[1]] == sp.field(name.split(".")[1]).unknown
        assert sp.relevant(v) == v and not sp.missing(v)
        for other in card["trades"]:
            assert not trades.spec(other).missing(card["values"].get(other, {}))
    together = [c for c in built[trade] if len(c["input"]["card"]["trades"]) > 1]
    assert together and {c["strata"]["other"] for c in together} == {"one", "many"}


def test_mokgong_door_fields_follow_items(built):
    for c in built["mokgong"]:
        card = c["input"]["card"]
        v = card["values"]["mokgong"]
        if "mokgong.door_frame" in card["to_check"]:
            assert v["door_frame"] == "yes"
        if "door" not in v["items"]:
            assert "doors" not in v and "door_frame" not in v


def test_check_catches_broken_cases():
    sample = gen.read_jsonl(make_cases.out_dir("dobae") / "sample_100.jsonl")
    keys = copy.deepcopy(sample[0])
    keys["expect"]["step_keys"] = ["paper"]  # 계산과 다름
    area = copy.deepcopy(sample[1])
    area["input"]["card"]["area_m2"] = "0.0"  # 스펙 · 카드 검사에 걸림
    clash = copy.deepcopy(next(c for c in sample[2:] if c["input"]["card"]["occupied"]))
    clash["expect"]["must_not"].append("empty.moving")  # 사는 집인데 짐 이야기 금지 → 모순
    good = next(c for c in sample if c["id"] not in (keys["id"], area["id"], clash["id"]))
    r = check_cases.check_set("dobae", [keys, area, clash, good, copy.deepcopy(good)])
    probs = r["problems"]
    assert set(probs) == {keys["id"], area["id"], clash["id"]}
    assert any("단계 키" in e for e in probs[keys["id"]])
    assert any("카드" in e for e in probs[area["id"]])
    errs = " ".join(probs[clash["id"]])
    assert "기대 검사가 지금 규칙과 달라요" in errs and "모범 답이 통과 못 함" in errs
    assert r["dup_ids"] == 1 and r["dup_inputs"] == 1 and not check_cases.ok(r, full=False)


@pytest.mark.parametrize("trade", TRADES)
def test_space_fragments_do_not_cross_splits(built, trade):
    tpl = {s: {x for c in built[trade] if c["split"] == s for x in c["tpl"]} for s in gen.SPLITS}
    assert tpl["dev"] and tpl["heldout"] and not tpl["dev"] & tpl["heldout"]
