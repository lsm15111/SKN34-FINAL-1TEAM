"""v4 비서 의도 모델(intent_v4): 학습 쪽 확률과 같은지 · 라벨 → 단계 카드 · 기준값 · 모델 없음 ·
무료 모드 고객 길 연결(free.customer_intent). 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

from typing import get_args

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free, intent_v4
from app.assistant.schemas import CardKind
from tests.test_v3_visit_kit import customer, vendor
from tests.test_v4_assistant_turns import ask, ok


def test_model_matches_training_probs():
    model = intent_v4._model()
    assert model is not None and model["checks"]
    for check in model["checks"]:
        got = intent_v4.probs(check["text"])
        assert [got[label] for label in model["labels"]] == pytest.approx(check["probs"], abs=1e-5)
        top = max(range(len(check["probs"])), key=check["probs"].__getitem__)
        assert intent_v4.predict(check["text"]).label == model["labels"][top]


def test_labels_map_to_card_kinds():
    model = intent_v4._model()
    assert sorted(model["labels"]) == sorted(intent_v4.LABELS)
    assert set(intent_v4.CARD_OF) == set(intent_v4.LABELS)
    kinds = set(get_args(CardKind))
    assert all(v is None or v in kinds for v in intent_v4.CARD_OF.values())
    assert intent_v4.card_of("vendor_pick") == "vendor_picks"
    assert intent_v4.card_of("knowledge") is None and intent_v4.card_of(None) is None


def test_probs_sum_to_one_and_threshold_decides_sure():
    p = intent_v4.probs("아무 말")
    assert sum(p.values()) == pytest.approx(1.0)
    assert 0 < intent_v4.threshold() < 1
    assert intent_v4.predict("아무 말", cut=0.0).sure
    assert not intent_v4.predict("아무 말", cut=1.01).sure


def test_same_cleaning_as_v1_hides_phone_and_unit():
    # 전화 · 동호수는 가린 뒤에 계산해서 번호가 달라도 확률이 같다
    a = intent_v4.probs("010-0000-0000로 연락 주세요 101동 1001호")
    b = intent_v4.probs("010-1111-2222로 연락 주세요 202동 2002호")
    assert a == b


def test_missing_model_returns_none(monkeypatch):
    monkeypatch.setattr(intent_v4, "MODEL", intent_v4.MODEL.with_name("없는_모델.json.gz"))
    intent_v4._model.cache_clear()
    try:
        assert intent_v4.probs("안녕") is None and intent_v4.predict("안녕") is None
        assert intent_v4.threshold() == intent_v4.DEFAULT_THRESHOLD
        # 모델 파일이 없으면 무료 모드 고객 길은 낱말 규칙 + 입구 관문 단계 카드(옛 길)
        assert free.customer_intent("업체 추천해 주세요") == ("vendors", "gate")
    finally:
        monkeypatch.undo()
        intent_v4._model.cache_clear()


# ---- 무료 모드 고객 길(free.customer_intent): 모델 라벨을 정해 두고 연결만 본다 ----


def fixed(monkeypatch, label: str, conf: float = 0.9):
    found = intent_v4.Guess(label=label, confidence=conf, sure=True)
    monkeypatch.setattr(intent_v4, "predict", lambda _text, cut=None: found)


@pytest.mark.parametrize(
    ("label", "want"),
    [
        ("home_info", ("home", None)),
        ("standard_quote", ("standard", None)),
        ("vendor_pick", ("vendors", None)),
        ("visit", ("slots", None)),
        ("quote_compare", ("compare", None)),
        ("schedule", ("schedule", None)),
        ("knowledge", (None, None)),
        ("out_of_scope", (None, None)),
    ],
)
def test_model_label_picks_handler(monkeypatch, label, want):
    fixed(monkeypatch, label)
    # 낱말 규칙이 다른 의도를 말해도(예: 공정표) 고객 길은 모델 라벨을 따른다(dev로 고른 '모델만')
    assert free.customer_intent("공정표 보여 주세요") == want


def test_guide_is_today_only_when_asking_todays_work(monkeypatch):
    fixed(monkeypatch, "guide")
    assert free.customer_intent("오늘 제가 정할 일 있어요?") == ("today", None)
    # 인사 · 서비스 안내는 answer_only 글 + today 카드
    assert free.customer_intent("안녕하세요 반가워요") == (None, "guide")


@pytest.fixture
def free_mode(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def kinds(ev) -> list[str]:
    return [d["kind"] for e, d, _ in ev if e == "card"]


def test_free_turn_shows_card_the_model_picked(api, free_mode, monkeypatch):
    vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = customer(api)
    text = "도배 잘하는 곳 몇 군데만 골라 주실래요?"
    assert free.intent_of(text, "customer") is None  # 낱말 규칙으로는 못 잡는 말
    fixed(monkeypatch, "vendor_pick")
    ev = ok(ask(api, pid, text))
    assert ev[-1][1]["mode"] == "free"
    assert "vendor_picks" in kinds(ev)


def test_free_turn_knowledge_label_has_no_step_card(api, free_mode, monkeypatch):
    _, pid = customer(api)
    fixed(monkeypatch, "knowledge")
    ev = ok(ask(api, pid, "안녕하세요, 도배 풀은 뭘 써요?"))  # 관문 길이면 인사 → today 카드였을 말
    assert kinds(ev) == ["answer"]
