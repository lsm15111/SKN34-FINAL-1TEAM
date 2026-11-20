"""v4 비서 의도 모델(intent_v4): 학습 쪽 확률과 같은지 · 라벨 → 단계 카드 · 기준값 · 모델 없음."""

from typing import get_args

import pytest

from app.assistant import intent_v4
from app.assistant.schemas import CardKind


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
    finally:
        monkeypatch.undo()
        intent_v4._model.cache_clear()
