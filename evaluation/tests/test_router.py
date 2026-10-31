"""라우터 평가: 생성기(2:1 · 조각 나눔 · 표본), 무료 점검(T0), 채점(바뀐 칸 · 공정 더하기 · 범위 · 답), 가짜 실행."""

import asyncio
import copy
from collections import Counter

import pytest

from app.consult import service
from app.consult.schemas import ConsultCard
from evaluation.common import gen, trades
from evaluation.router import check, make_cases
from evaluation.router import run as rrun
from evaluation.router import score as S

TRADE_KEYS = ("effect_exact", "no_missed", "trades_exact", "raw_in_card", "raw_valid")


@pytest.fixture(scope="module")
def built() -> list[dict]:
    return make_cases.build()[0]


@pytest.fixture(scope="module")
def sample() -> list[dict]:
    return gen.read_jsonl(make_cases.SAMPLE)


def first(cases: list[dict], cat: str, pred=lambda c: True) -> dict:
    return next(c for c in cases if c["category"] == cat and pred(c))


def raw_of(case: dict, **over) -> dict:
    return copy.deepcopy(case["expect"]["ideal"]) | over


def test_generator_counts_2to1_and_fragments(built):
    assert len(built) == 4980
    cnt = Counter((c["category"], c["split"]) for c in built)
    cats = {k for k, _ in cnt}
    assert cats == set(make_cases.CATEGORIES) and len(cats) == 20
    assert all(cnt[cat, "dev"] == 2 * cnt[cat, "heldout"] for cat in cats)
    r = gen.split_report(built)
    assert (r["dup_ids"], r["dup_inputs"], r["uneven"], r["shared_fragments"]) == (0, 0, [], [])
    msgs = {s: {c["input"]["message"] for c in built if c["split"] == s} for s in gen.SPLITS}
    assert not msgs["dev"] & msgs["heldout"]


def test_trade_categories_follow_router_v5(built):
    for c in built:
        cat, ideal, card = c["category"], c["expect"]["ideal"], c["input"]["card"]
        moved = "trades" in c["expect"]["effect"]
        assert moved == (cat in ("trade.add", "trade.remove")), c["id"]
        if cat == "trade.add":
            assert ideal["trades_add"] and not set(ideal["trades_add"]) & set(card["trades"])
        if cat == "trade.remove":
            assert len(card["trades"]) >= 2 and set(ideal["trades_remove"]) <= set(card["trades"])
        if cat == "trade.ask":  # 묻기만 함 → 더하지 않고 그 공정 전문가에게 넘긴다
            assert not ideal["trades_add"] and c["expect"]["questions"]
            assert not set(c["expect"]["questions"]) & set(card["trades"])
        if cat == "vendor":  # 업체 소개 · 견적 요청은 범위 안 (v5)
            assert not c["expect"]["out_of_scope"] and c["expect"]["reply_has"] == ["가견적"]
    oos = {c["input"]["message"] for c in built if c["category"] == "out_of_scope"}
    assert not any("업체" in m or "방수" in m for m in oos)


def test_committed_sample_matches_generator(built, sample):
    assert make_cases.sample(built) == sample
    assert Counter(c["split"] for c in sample) == {"dev": 67, "heldout": 33}


def test_check_passes_on_committed_sample(sample):
    r = check.check_set(sample)
    assert r["problems"] == {}


def test_check_catches_broken_cases(sample):
    wrong = copy.deepcopy(first(sample, "field.choice"))
    k = next(iter(wrong["expect"]["effect"]))
    wrong["expect"]["effect"][k] = "nope"
    extra = copy.deepcopy(first(sample, "no_change"))
    extra["expect"]["ideal"]["occupied"] = not extra["input"]["card"]["occupied"]
    card = copy.deepcopy(
        next(
            c
            for c in sample
            if c["input"]["card"]["trades"] == ["dobae"]
            and "grade" not in c["input"]["card"]["values"].get("dobae", {})
        )
    )
    card["input"]["card"]["to_check"].append(
        "dobae.grade"
    )  # 값 없는 칸 확인 표시: normalize가 지운다
    bad = copy.deepcopy(first(sample, "question"))
    bad["input"]["card"]["to_check"].append("nope.field")  # 스펙 검사에 걸림
    good = first(sample, "common.area", lambda c: c["id"] != card["id"])
    r = check.check_set([wrong, extra, card, bad, good])
    assert set(r["problems"]) == {wrong["id"], extra["id"], card["id"], bad["id"]}
    assert any("기대 바뀐 칸" in e for e in r["problems"][wrong["id"]])
    assert any("기대 바뀐 칸" in e for e in r["problems"][extra["id"]])
    assert any("normalize" in e for e in r["problems"][card["id"]])
    assert any("상담 API 모양" in e for e in r["problems"][bad["id"]])


# ---------------------------------------------------------------- 채점
def test_multi_add_scores_same_as_set(built):
    c = first(built, "field.multi", lambda c: c["expect"]["ideal"]["changes"][0]["op"] == "add")
    ch = c["expect"]["ideal"]["changes"][0]
    field = ch["field"]
    whole = c["expect"]["effect"][field].split("+")
    raw = raw_of(c, changes=[{"field": field, "op": "set", "value": ",".join(whole)}])
    s = S.score(c, raw)
    assert all(s["checks"].values()), s["detail"]


def test_invented_change_is_caught(built):
    c, t, f = next(
        (c, t, f)
        for c in built
        if c["category"] == "no_change" and c["strata"]["form"] == "chitchat"
        for t in c["input"]["card"]["trades"]
        for f in trades.spec(t).fields
        if f.kind == "choice" and f.asks(c["input"]["card"]["values"].get(t, {}))
    )
    cur = c["input"]["card"]["values"].get(t, {}).get(f.key)
    value = next(v for v in f.values if v != cur)
    s = S.score(c, raw_of(c, changes=[{"field": f"{t}.{f.key}", "op": "set", "value": value}]))
    assert not s["checks"]["no_invented"] and s["checks"]["no_missed"]
    assert s["counts"]["fp"] == 1 and s["counts"]["tp"] == 0


def test_trade_add_remove_and_ask_only(built):
    ask = first(built, "trade.ask")
    x = ask["expect"]["questions"][0]
    s = S.score(ask, raw_of(ask, trades_add=[x]))  # 묻기만 했는데 더함
    assert not s["checks"]["trades_exact"] and not s["checks"]["no_invented"]
    assert s["checks"]["raw_trades"] and s["counts"]["t_fp"] == 1

    already = first(built, "no_change", lambda c: c["strata"]["form"] == "already")
    have = already["input"]["card"]["trades"][0]
    s = S.score(already, raw_of(already, trades_add=[have]))  # 이미 있는 공정: 코드가 무시
    assert s["checks"]["trades_exact"] and not s["checks"]["raw_trades"]

    rem = first(built, "trade.remove")
    s = S.score(rem, raw_of(rem, trades_remove=["nope"]))
    assert not s["checks"]["raw_trades"] and not s["checks"]["trades_exact"]
    assert s["counts"]["t_fn"] == 1


def test_scoring_runs_without_trade_fields(built):
    """기준 커밋 라우터 원문(trades_add 칸 없음)도 채점된다. 공정을 더해야 하는 사례만 틀린다"""
    add = first(built, "trade.add", lambda c: c["strata"]["form"] == "with_field")
    raw = raw_of(add)
    raw.pop("trades_add"), raw.pop("trades_remove")
    s = S.score(add, raw)
    assert not s["checks"]["trades_exact"] and s["counts"]["t_fn"] == 1
    assert not s["checks"]["raw_in_card"]  # 더하지 못한 공정의 칸을 바꾸려 함
    plain = first(built, "field.choice")
    raw = raw_of(plain)
    raw.pop("trades_add"), raw.pop("trades_remove")
    assert all(S.score(plain, raw)["checks"].values())


def test_apply_trades_matches_router_v5_rules():
    reg = trades.registered()
    one = ConsultCard(trades=[reg[-1]], area_m2="84.0", area_basis="supply", occupied=False)
    added = S._apply_trades(one, [reg[0], "nope"], [])
    assert added.trades == list(reg[:1]) + [reg[-1]]  # 등록된 공정만, 공정 순서대로
    assert S._apply_trades(one, [], [reg[-1]]).trades == [reg[-1]]  # 마지막 공정은 남긴다
    assert S._apply_trades(added, [reg[0]], [reg[0]]).trades == [reg[-1]]  # 빼기가 이긴다
    if hasattr(service, "apply_trades"):  # v5 뒤: 상담 코드와 같은지
        for add, rem in (([reg[0], "nope"], []), ([], [reg[-1]]), ([reg[0]], [reg[0]])):
            assert S._apply_trades(one, add, rem) == service.apply_trades(one, add, rem)


def test_scope_and_reply_rules(built):
    vendor = first(built, "vendor")
    s = S.score(vendor, raw_of(vendor, out_of_scope=True, reply="업체 소개는 못 해요."))
    assert not s["checks"]["out_of_scope"] and not s["checks"]["reply_guides"]
    oos = first(built, "out_of_scope")
    assert not S.score(oos, raw_of(oos, out_of_scope=False))["checks"]["out_of_scope"]

    plain = first(built, "field.choice")
    s = S.score(plain, raw_of(plain, reply="알겠어요. 도배는 30만 원이에요."))
    assert not s["checks"]["reply_ok"]
    assert not S.score(plain, raw_of(plain, reply="천장도 할까요?"))["checks"]["reply_no_ask"]
    assert not S.score(plain, raw_of(plain, reply="바꾼 값으로 계산함."))["checks"]["reply_style"]
    q = first(built, "question")
    assert not S.score(q, raw_of(q, reply="알겠어요."))["checks"]["reply_empty_when_asked"]
    s = S.score(q, raw_of(q, questions=[]))
    assert not s["checks"]["questions_exact"] and s["counts"]["q_fn"] == 1


# ---------------------------------------------------------------- 가짜 실행
def test_fake_run_and_fake_batch_score_ideal_outputs(sample, tmp_path):
    res = asyncio.run(rrun.run(sample, mode="fake"))
    bad = {r["id"]: r for r in res if not all(r["scores"]["checks"].values())}
    if S.HAS_TRADES:
        assert not bad
    else:  # v5 전 라우터 스키마는 공정 더하기 · 빼기를 못 낸다 → 그 사례만 그 검사로 틀린다
        assert {r["category"] for r in bad.values()} == {"trade.add", "trade.remove"}
        for r in bad.values():
            assert {k for k, ok in r["scores"]["checks"].items() if not ok} <= set(TRADE_KEYS)
    batch = asyncio.run(rrun.run(sample, mode="fake-batch", out_dir=tmp_path, poll_s=0))
    assert [r["raw"] for r in batch] == [r["raw"] for r in res]
    assert all(r["usage"]["batch"] for r in batch)
    meta = {
        "model": "fake",
        "effort": "-",
        "prompt_version": "-",
        "mode": "fake",
        "cases": "x",
        "stratify": "category",
        "seed": 1,
    }
    report = rrun.summarize(meta, res)
    assert "바뀐 칸 정밀도" in report and "공정 더하기 · 빼기 재현율" in report
    rrun.rescore(res, {c["id"]: c for c in sample})
    assert rrun.summarize(meta, res) == report
