"""생성기 · 무료 점검(T0): 시드를 고정하면 같은 사례가 나오고, 점검이 망가진 사례를 잡는다."""

import copy
from collections import Counter

import pytest

from evaluation import check_cases
from evaluation.carpentry import make_cases as cp_make
from evaluation.common import gen
from evaluation.wallpaper import make_cases as wp_make

MAKERS = {"wallpaper": wp_make, "carpentry": cp_make}


@pytest.fixture(scope="module")
def built() -> dict[str, list[dict]]:
    return {agent: m.build() for agent, m in MAKERS.items()}


@pytest.mark.parametrize("agent", MAKERS)
def test_generator_counts_and_2to1(built, agent):
    cases = built[agent]
    assert len(cases) == 4995
    per_cat = Counter((c["category"], c["split"]) for c in cases)
    cats = {k for k, _ in per_cat}
    assert len(cats) == {"wallpaper": 9, "carpentry": 15}[agent]
    for cat in cats:
        assert per_cat[cat, "dev"] == 2 * per_cat[cat, "heldout"]
    assert len({c["id"] for c in cases}) == len(cases)


@pytest.mark.parametrize("agent", MAKERS)
def test_committed_sample_matches_generator(built, agent):
    """커밋한 표본 100개가 지금 생성기와 같다 (생성기를 고치면 표본도 다시 만든다)."""
    sample = MAKERS[agent].sample(built[agent])
    assert len(sample) == 100
    assert Counter(c["split"] for c in sample) == {"dev": 67, "heldout": 33}
    assert sample == gen.read_jsonl(MAKERS[agent].SAMPLE)


@pytest.mark.parametrize("agent", MAKERS)
def test_check_passes_on_committed_sample(agent):
    r = check_cases.check_set(agent, gen.read_jsonl(MAKERS[agent].SAMPLE))
    assert r["problems"] == {}
    assert check_cases.ok(r, full=False)


def test_check_catches_broken_cases():
    sample = gen.read_jsonl(wp_make.SAMPLE)
    keys = copy.deepcopy(sample[0])
    keys["expect"]["step_keys"] = ["paper"]  # 계산과 다름
    area = copy.deepcopy(sample[1])
    area["input"]["common"]["area_m2"] = "0.0"  # 범위 밖
    clash = copy.deepcopy(next(c for c in sample[2:] if c["input"]["common"]["occupied"]))
    clash["expect"]["must_not"].append("empty.moving")  # 사는 집인데 짐 이야기 금지 → 모순
    good = next(c for c in sample if c["id"] not in (keys["id"], area["id"], clash["id"]))
    r = check_cases.check_set("wallpaper", [keys, area, clash, good, copy.deepcopy(good)])
    probs = r["problems"]
    assert set(probs) == {keys["id"], area["id"], clash["id"]}
    assert any("단계 키" in e for e in probs[keys["id"]])
    assert any("면적" in e for e in probs[area["id"]])
    errs = " ".join(probs[clash["id"]])
    assert "기대 검사가 지금 규칙과 달라요" in errs and "모범 답이 통과 못 함" in errs
    assert r["dup_ids"] == 1 and r["dup_inputs"] == 1 and not check_cases.ok(r, full=False)


def test_carpentry_space_fragments_do_not_cross_splits(built):
    tpl = {
        s: {x for c in built["carpentry"] if c["split"] == s for x in c["tpl"]} for s in gen.SPLITS
    }
    assert tpl["dev"] and tpl["heldout"] and not tpl["dev"] & tpl["heldout"]
