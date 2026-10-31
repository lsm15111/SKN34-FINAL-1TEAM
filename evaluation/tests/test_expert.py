"""전문가 답 평가: 생성기(2:1 · 조각 나눔 · 표본 · 새 공정), 무료 점검(T0), 채점, 가짜 실행 · 판정."""

import asyncio
import copy
from collections import Counter

import pytest

from evaluation.common import gen, trades
from evaluation.expert import check, make_cases
from evaluation.expert import run as erun
from evaluation.expert import score as S
from evaluation.judge import judge

META = {
    "model": "fake",
    "effort": "-",
    "prompt_version": "expert-v1",
    "mode": "fake",
    "cases": "x",
    "stratify": "category",
    "seed": 1,
    "rubric": judge.EXPERT.version,
}


@pytest.fixture(scope="module")
def built() -> list[dict]:
    return make_cases.build()[0]


@pytest.fixture(scope="module")
def sample() -> list[dict]:
    return gen.read_jsonl(make_cases.SAMPLE)


def first(cases: list[dict], cat: str) -> dict:
    return copy.deepcopy(next(c for c in cases if c["category"] == cat))


def failed(case: dict, answer: str, sources: list[str] | None = None) -> set[str]:
    s = S.score(case, {"answer": answer, "sources": ["field"] if sources is None else sources})
    return {k for k, ok in s["checks"].items() if not ok}


def test_generator_counts_2to1_and_fragments(built):
    """등록된 공정마다 주제 10개 (손으로 쓴 질문이 없는 주제도 스펙 · 지식으로 만든다), 범주마다 같은 수"""
    want = {f"{t}.{topic}" for t in trades.registered() for topic in make_cases.P.TOPICS}
    per = make_cases.TOTAL // len(want) // 3 * 3
    assert len(built) == len(want) * per
    cnt = Counter((c["category"], c["split"]) for c in built)
    cats = {k for k, _ in cnt}
    assert cats == want == {f"{t}.{topic}" for t, topic in make_cases.categories()}
    assert all(cnt[cat, "dev"] == 2 * cnt[cat, "heldout"] for cat in cats)
    hand = {(t, topic) for t, topic, _ in make_cases.P.BANK}
    assert {t for t, _ in hand} == set(trades.registered())  # 10공정 모두 손으로 쓴 질문이 있다
    for t, topic in hand:
        assert set(make_cases.subjects(t, topic)) >= {
            k for tt, tp, k in make_cases.P.BANK if (tt, tp) == (t, topic)
        }  # 손으로 쓴 거리는 모범 답이 채점을 지나 모두 남는다
    r = gen.split_report(built)
    assert (r["dup_ids"], r["dup_inputs"], r["uneven"], r["shared_fragments"]) == (0, 0, [], [])
    qs = {s: {c["input"]["question"] for c in built if c["split"] == s} for s in gen.SPLITS}
    assert not qs["dev"] & qs["heldout"]
    for c in built:  # 상담과 같은 입력: 그 공정 칸 + 공통 칸 (카드에 그 공정이 없으면 공통 칸만)
        has = c["trade"] in c["input"]["card"]["trades"]
        assert (c["strata"]["in_card"] == "yes") == has
        assert c["input"]["context"].startswith("공정: ")


def test_subjects_come_from_spec_and_knowledge():
    assert make_cases.scope_items("dobae") == [
        "단열", "방수", "누수 원인 수리", "바닥", "욕실", "전기", "계약", "결제",
    ]  # fmt: skip
    assert make_cases.scope_items("mokgong")[:4] == ["중문", "가벽", "아트월", "붙박이장"]
    assert set(make_cases.term_words("dobae")) == {"초배", "정배", "퍼티", "샌딩", "덧방", "보양"}
    assert "할증" in make_cases.term_words("mokgong") and "초배" not in make_cases.term_words(
        "mokgong"
    )


def test_committed_sample_matches_generator(built, sample):
    assert make_cases.sample(built) == sample
    assert Counter(c["split"] for c in sample) == {"dev": 67, "heldout": 33}


def test_check_passes_on_committed_sample_and_catches_broken(sample):
    assert check.check_set(sample)["problems"] == {}
    groups = first(sample, "dobae.compare")
    groups["expect"]["groups"] = ["실크"]
    context = first(sample, "mokgong.cost")
    context["input"]["context"] += "\n발코니: 확장했어요"
    subject = first(sample, "dobae.scope")
    subject["strata"]["subject"] = "중문"  # 도배 지식의 범위 밖 목록에 없다
    witness = first(sample, "mokgong.duration")
    witness["expect"]["ideal"]["answer"] = "목공은 하루면 끝나요."
    r = check.check_set([groups, context, subject, witness, first(sample, "dobae.term")])
    probs = r["problems"]
    assert set(probs) == {groups["id"], context["id"], subject["id"], witness["id"]}
    assert any("핵심 말" in e for e in probs[groups["id"]])
    assert any("집 정보 글" in e for e in probs[context["id"]])
    assert any("거리" in e for e in probs[subject["id"]])
    assert any("no_number" in e for e in probs[witness["id"]])


# ---------------------------------------------------------------- 채점
def test_scoring_rules(built):
    compare = first(built, "dobae.compare")
    compare["expect"]["groups"] = [r"합지|저가형|종이", r"실크|기본형|비닐"]
    good = "합지는 종이 벽지라 값이 싸요. 실크는 닦을 수 있어 오래 가요."
    assert failed(compare, good) == set()
    assert failed(compare, "실크는 닦을 수 있어 오래 가요.") == {"on_topic"}  # 한쪽만 말함
    assert failed(compare, good + " 보통 3일 걸려요.") == {"no_number"}
    assert failed(compare, good + " 하루면 끝나요.") == {"no_number"}
    assert failed(compare, good, ["nope"]) == {"sources_known"}
    assert failed(compare, good + " 실크가 낫다.") == {"style"}
    assert failed(compare, good + " 어떤 벽지를 원하세요?") == {"no_ask"}
    assert failed(compare, good + " 덧방은 싸요.") == {"terms"}
    assert failed(compare, good + " 떼지 않고 위에 바로 바르는 덧방은 싸요.") == set()
    assert failed(compare, good + " 좋아요." * 3) == {"short"}
    assert len(good * 10) > S.LIMIT and "answer_ok" in failed(compare, good * 10)
    assert "answer_ok" in failed(compare, "")

    cost = first(built, "mokgong.cost")
    assert failed(cost, "비용은 화면의 표준견적서에서 볼 수 있어요.") == set()
    assert failed(cost, "목공은 꼼꼼히 하는 게 중요해요.") == {"on_topic"}
    scope = first(built, "dobae.scope")
    assert failed(scope, "그 일은 도배와 따로 하는 공사예요.") == set()
    assert failed(scope, "곰팡이는 금방 고칠 수 있어요.") == {"on_topic"}


# ---------------------------------------------------------------- 새 공정 (가짜 스펙)
KNOWLEDGE = """## 쓰는 법

- 믿집 시험 공사는 마감 칠하기다. 중문 · 단열 · 계약 · 결제는 판단하지 않고 '이번 시험 공사 밖의 일'이라고만 말한다.

## 작업 순서

- prep 짐 정리 · 보양: 사는 집이면 가구를 덮는다.

## 출처

- [field] 현장
"""


def test_new_trade_gets_generic_questions(monkeypatch):
    from app.agent.trade import TradeAgent
    from app.consult.trades import REGISTRY
    from app.consult.trades.base import Choice, FieldSpec, TradeSpec

    agent = TradeAgent("probe", "시험", "probe-v1", "시스템", "답", {"field": "현장"})
    spec = TradeSpec(
        key="probe",
        label="시험",
        order=55,
        fields=(
            FieldSpec(
                "finish",
                "마감 종류",
                "어떤 마감?",
                "choice",
                (Choice("matte", "무광 마감"), Choice("gloss", "유광 마감")),
                unknown="matte",
            ),
            FieldSpec(
                "parts",
                "시공 부위",
                "어디?",
                "multi",
                (Choice("x", "거실 벽"), Choice("y", "주방 벽")),
                max=2,
            ),
        ),
        agent=agent,
        build=lambda c, v: None,
        card_lines=lambda c, v: [],
    )
    knowledge = trades.knowledge
    monkeypatch.setitem(REGISTRY, "probe", spec)
    monkeypatch.setattr(trades, "ORDER", ("mokgong", "probe", "dobae"))
    monkeypatch.setattr(trades, "knowledge", lambda t: KNOWLEDGE if t == "probe" else knowledge(t))
    caches = (make_cases.subjects, make_cases.bank)
    for c in caches:
        c.cache_clear()
    try:
        subs = {topic: set(make_cases.subjects("probe", topic)) for topic in make_cases.P.TOPICS}
        assert subs["compare"] == {"finish"} and subs["choose"] == {"finish", "parts"}
        assert subs["scope"] == {"중문", "단열", "계약", "결제"} and subs["term"] == {"보양"}
        assert subs["cost"] == {"general"}
        cases, _ = make_cases.build(900)
        probe = [c for c in cases if c["trade"] == "probe"]
        assert len({c["category"] for c in probe}) == 10
        assert check.check_set(cases)["problems"] == {}
        q = {c["input"]["question"] for c in probe if c["topic"] == "compare"}
        assert any("무광 마감" in x and "유광 마감" in x for x in q)
    finally:
        for c in caches:
            c.cache_clear()


# ---------------------------------------------------------------- 가짜 실행
def test_fake_run_with_judge_and_batch(sample, tmp_path):
    cases = sample[:12]
    ids = {cases[0]["id"], cases[1]["id"]}
    res = asyncio.run(erun.run(cases, judge_ids=ids, mode="fake"))
    assert all(r["status"] == "ok" and all(r["scores"]["checks"].values()) for r in res)
    assert [r["id"] for r in res if "judge" in r] == [c["id"] for c in cases[:2]]
    assert res[0]["judge"]["answers_question"]["score"] == 5
    batch = asyncio.run(
        erun.run(cases, judge_ids=ids, mode="fake-batch", out_dir=tmp_path, poll_s=0)
    )
    assert [r["raw"] for r in batch] == [r["raw"] for r in res]
    assert all(r["usage"]["batch"] for r in batch) and batch[0]["judge_usage"]["batch"]
    report = erun.write(tmp_path, META, res)
    assert (
        "질문에 맞게 답함 | 5.00" in report and "**모든 코드 검사 통과** | 100% (12/12)" in report
    )
    res[2]["raw"]["answer"] = "도배는 하루면 끝나요."
    erun.rescore(res, {c["id"]: c for c in cases})
    assert not res[2]["scores"]["checks"]["no_number"]
