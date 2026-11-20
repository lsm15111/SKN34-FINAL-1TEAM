"""v4 비서 의도 모델(intent_v4): 학습 쪽 확률과 같은지 · 라벨 → 단계 카드 · 기준값 · 모델 없음 ·
무료 모드 고객 길 연결(free.customer_intent). 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

from typing import get_args

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free, intent_v4
from app.assistant.schemas import CardKind
from tests.test_v3_visit_kit import customer, requested, vendor
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


def test_how_question_after_a_wish_goes_to_knowledge(monkeypatch):
    # 2판: 바람 · 진술 뒤 순서 · 시기 · 방법 질문은 모델이 집 정보 · 표준견적서로 봐도 지식(카드 없음)
    fixed(monkeypatch, "home_info")
    assert free.customer_intent("몰딩도 바꾸고 싶은데 도배 전에 해야 해요?") == (None, None)
    assert free.customer_intent("문틀 바꾸고 나서 언제 도배해요?") == (None, None)
    # 묻지 않는 바람 · 진술은 집 정보 그대로
    assert free.customer_intent("몰딩도 이번에 같이 바꾸고 싶어요.") == ("home", None)
    assert free.customer_intent("신혼집 들어가기 전에 몰딩도 바꾸고 싶어요") == ("home", None)
    fixed(monkeypatch, "standard_quote")
    # 돈 · 기간 질문은 표준견적서 그대로
    assert free.customer_intent("몰딩까지 하면 금액이 어떻게 돼요?") == ("standard", None)
    fixed(monkeypatch, "vendor_pick")
    # 다른 라벨은 그대로
    assert free.customer_intent("업체는 어떻게 골라요?") == ("vendors", None)


def test_flow_questions_with_the_real_model():
    # 오늘 흐름에서 나빠졌던 두 질문(실제 모델 + 2판 규칙)
    assert free.customer_intent("몰딩도 바꾸고 싶은데 도배 전에 해야 해요?") == (None, None)
    assert free.customer_intent("몰딩 교체는 언제 해요?") == (None, None)


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


def test_home_card_shows_before_lock_and_not_after(api, free_mode, monkeypatch):
    """집 정보는 실측 요청 전까지만 고칠 수 있어요. 잠긴 공사에는 집 정보 카드를 다시 띄우지 않고 답만 해요."""
    fixed(monkeypatch, "home_info")
    _, pid = customer(api, "open@mitjip.test")
    assert "home_info" in kinds(ok(ask(api, pid, "저희 집 34평이에요")))
    f = requested(api)  # 실측을 요청하면 집 정보가 잠겨요
    ev = ok(ask(api, f["pid"], "저희 집 34평이에요"))
    assert "home_info" not in kinds(ev) and kinds(ev)[-1] == "answer"
