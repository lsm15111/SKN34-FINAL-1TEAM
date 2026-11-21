"""v4 비서 의도 분류(무료 모드 단계 카드 고르기): 문장 → (라벨, 신뢰도). LLM 없이 순수 파이썬.

- 모델: TF-IDF(낱말 안 글자 2~4개, sublinear) + 로지스틱 회귀. v1 관문(intent_lr_v1)과 같은 꼴이고 라벨만 비서 9개다.
- 가중치(assistant_intent_v1.json.gz)는 evaluation/v4/intent/train.py가 만든다(scikit-learn은 학습에서만).
  파일 안 checks(학습 쪽 확률)와 같은 값이 나오는지 테스트한다. 온도(확률 보정) · 기준값도 학습이 dev로 골라 파일에 둔다.
- 전처리는 v1과 같은 intent.clean(전화 · 동호수 가림)이다. v3 관문 모델 · 규칙은 바꾸지 않는다.
"""

import gzip
import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

# 두 모델이 같은 전처리 · 글자 묶음을 쓰게 v1 추론에서 가져온다
from app.agent.intent import _grams, clean
from app.assistant.schemas import CardKind

MODEL = Path(__file__).with_name("assistant_intent_v1.json.gz")
LABELS = (
    "home_info", "standard_quote", "vendor_pick", "visit", "quote_compare", "schedule",
    "knowledge", "guide", "out_of_scope",
)  # fmt: skip
# 라벨 → 무료 모드 단계 카드. 지식 · 범위 밖은 카드 없이 답만(지식 답은 answer_only가 만든다)
CARD_OF: dict[str, CardKind | None] = {
    "home_info": "home_info",
    "standard_quote": "standard_quote",
    "vendor_pick": "vendor_picks",
    "visit": "visit_slots",
    "quote_compare": "quote_compare",
    "schedule": "schedule",
    "knowledge": None,
    "guide": "today",
    "out_of_scope": None,
}
DEFAULT_THRESHOLD = 0.5  # 모델 파일에 기준값이 없을 때


@dataclass(frozen=True)
class Guess:
    label: str
    confidence: float
    sure: bool  # 신뢰도 ≥ 기준값. 아니면 부르는 쪽이 옛 길(입구 관문)로 간다


@cache
def _model() -> dict | None:
    if not MODEL.exists():
        return None  # 모델이 없으면 분류하지 않는다(부르는 쪽이 옛 길로)
    return json.loads(gzip.decompress(MODEL.read_bytes()))


def threshold() -> float:
    model = _model()
    return float(model.get("threshold", DEFAULT_THRESHOLD)) if model else DEFAULT_THRESHOLD


def probs(text: str) -> dict[str, float] | None:
    """라벨별 확률(합 1). 모델이 없으면 None."""
    model = _model()
    if model is None:
        return None
    features, labels = model["features"], model["labels"]
    tfidf = {
        g: (1 + math.log(c)) * features[g][0]
        for g, c in _grams(clean(text), *model["ngram"]).items()
        if g in features
    }
    norm = math.sqrt(sum(v * v for v in tfidf.values())) or 1.0
    scores = list(model["intercept"])
    for g, v in tfidf.items():
        for k, w in enumerate(features[g][1:]):
            scores[k] += v / norm * w
    temp = float(model.get("temperature", 1.0))  # 확률 보정(가장 높은 라벨은 그대로)
    scores = [s / temp for s in scores]
    top = max(scores)
    exp = [math.exp(s - top) for s in scores]
    total = sum(exp)
    return {label: e / total for label, e in zip(labels, exp, strict=True)}


def predict(text: str, cut: float | None = None) -> Guess | None:
    """가장 높은 라벨과 신뢰도. cut을 안 주면 모델 파일의 기준값으로 sure를 정한다."""
    p = probs(text)
    if p is None:
        return None
    label = max(p, key=p.__getitem__)
    conf = p[label]
    return Guess(label=label, confidence=conf, sure=conf >= (threshold() if cut is None else cut))


def card_of(label: str | None) -> CardKind | None:
    """라벨의 단계 카드 종류(없으면 None: 답 카드만)."""
    return CARD_OF.get(label) if label else None
