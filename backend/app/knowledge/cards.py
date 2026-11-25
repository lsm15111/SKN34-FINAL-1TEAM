"""검증된 답 카드: 읽기 · 색인 · 찾기 (ADR agent-07). DB · HTTP를 모르는 순수 함수.

- 카드 파일: `app/agent/cards/<공종>.jsonl`(한 줄에 카드 하나). 운영 이미지는 `app`만 복사해서 data/ 밖에 둔다.
- 찾기: 질문 ↔ 카드 열쇠 질문(keys) 글자 두 개 묶음 TF-IDF 코사인의 최댓값.
- 받아들이기(accept)는 담당이 한다: 점수 ≥ 기준 + 카드 근거 조각이 같은 질문의 검색 위 5개에 있음(맞물림)
  또는 점수 ≥ 높은 기준. 기준값은 E3(dev)로 정한다.
- 카드는 실행 중에 바뀌지 않는다. 바꾸면 판(version)을 올리고 PR로만 들어간다.
"""

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.knowledge import bm25
from app.knowledge.suggest import COMMON

CARD_DIR = Path(__file__).resolve().parents[1] / "agent" / "cards"
Kind = Literal[
    "가격", "자재", "공법", "기간", "하자", "업체", "계약", "순서", "관리사무소", "셀프", "용어", "서비스",
    "준비", "안전",
]  # fmt: skip
CardTrade = Literal[
    "dobae", "mokgong", "floor", "tile", "bath", "kitchen", "paint", "film", "electric",
    "window", "demolition", "plumbing", "common",
]  # fmt: skip
CardIntent = Literal["guide", "trade", "quote_explanation", "schedule"]
# 믿집 서비스 규칙 카드(service.jsonl)가 인용하는 사용자 확정 화면 글 · 설계 결정. 지식 조각이 아니라 제품 규칙이다
DOC_REFS: dict[str, str] = {
    "doc:screen-c07": "9판 C07 표준견적서 화면 글",
    "doc:screen-c09": "9판 C09 AI에게 묻기 첫 알림 글",
    "doc:screen-c10": "9판 C10 업체 보기 화면 글",
    "doc:screen-c13": "9판 C13 · D08 실측 일정 요청서 글",
    "doc:screen-c57": "9판 C57 · C58 로그인 전 표준견적서 글",
    "doc:screen-c59": "9판 C59 가입 · 로그인 카드 글",
    "doc:rule-visit": "dev-04 실측 일정 결정(기한 48시간 · 반나절 고르기)",
    "doc:rule-thread": "dev-05 채팅 결정(실측 확정 뒤 대화)",
}
DOC_REF = re.compile(r"doc:[a-z0-9_.\-]+")


def _refs(v: list[str]) -> list[str]:
    for r in v:
        if not (bm25.REF.fullmatch(r) or r in DOC_REFS):
            raise ValueError(f"조각 번호 모양이 아니에요: {r}")
    return v


class CardSentence(BaseModel):
    text: str = Field(min_length=4, max_length=220)
    cites: list[str] = Field(min_length=1, max_length=4)

    _cites = field_validator("cites")(_refs)


class CardRow(BaseModel):
    cells: list[str] = Field(min_length=2, max_length=4)
    cites: list[str] = Field(min_length=1, max_length=4)

    _cites = field_validator("cites")(_refs)


class CardTable(BaseModel):
    """'종류 · 차이' 질문에 같이 보여 주는 비교표. 칸 글도 카드 문장처럼 근거 조각 안에서만 쓴다."""

    title: str
    cols: list[str] = Field(min_length=2, max_length=4)
    rows: list[CardRow] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def _same_width(self) -> "CardTable":
        if any(len(r.cells) != len(self.cols) for r in self.rows):
            raise ValueError("줄마다 칸 수가 머리줄과 같아야 해요")
        return self


class CardSource(BaseModel):
    ref: str
    title: str
    kind: str  # 출처 종류 코드(kcs · law · maker …)
    publisher: str = ""


class CardAsk(BaseModel):
    slot: str
    question: str
    options: list[str] = Field(min_length=2, max_length=4)
    next: dict[str, str] = {}  # 고른 답 → 이어 보여 줄 카드 id(없으면 원래 질문 + 답으로 다시 찾음)

    @model_validator(mode="after")
    def _next_in_options(self) -> "CardAsk":
        if set(self.next) - set(self.options):
            raise ValueError("next의 열쇠는 options 안에 있어야 해요")
        return self


class CardCalc(BaseModel):
    label: str
    ref: str


class CardVerified(BaseModel):
    by: str
    at: date
    status: Literal["author_checked", "ok", "fix", "fail"]
    checks: list[str] = []


class AnswerCard(BaseModel):
    id: str = Field(pattern=r"^[a-z]+\.[a-z0-9_.\-]+$")
    version: int = Field(ge=1)
    trade: CardTrade
    kind: Kind
    intent: CardIntent = "trade"
    stage: str = "any"
    keys: list[str] = Field(min_length=3, max_length=12)
    answer: list[CardSentence] = Field(min_length=1, max_length=4)
    caution: CardSentence | None = None
    tip: CardSentence | None = None
    calc: list[CardCalc] = []
    actions: list[str] = []
    ask: CardAsk | None = None
    compare: CardTable | None = None
    policy: list[str] = []
    sources: list[CardSource] = []
    guest: bool = False  # 로그인 전 자주 묻는 질문 칩으로 보여도 되는 카드
    verified: CardVerified
    review_by: date

    @property
    def tag(self) -> str:
        return f"card:{self.id}@{self.version}"

    def cites(self) -> list[str]:
        out = [r for s in self.answer for r in s.cites]
        for s in (self.caution, self.tip):
            if s:
                out.extend(s.cites)
        return list(dict.fromkeys(out))


@dataclass(frozen=True)
class Match:
    card: AnswerCard
    score: float
    key: str


@dataclass
class CardSet:
    cards: list[AnswerCard]
    version: str
    idf: dict[str, float] = field(default_factory=dict)
    vecs: list[tuple[int, dict[str, float], float]] = field(
        default_factory=list
    )  # (카드 순번, 벡터, 길이)
    by_id: dict[str, AnswerCard] = field(default_factory=dict)
    by_cite: dict[str, list[int]] = field(
        default_factory=dict
    )  # 조각 번호 → 그 조각을 인용한 카드 순번

    @property
    def n(self) -> int:
        return len(self.cards)


# 질문 끝말 · 흔한 말(어떻게 · 해요 · 돼요 …)은 뜻을 가르지 못해서 카드 찾기 점수에서 뺀다(E3 dev로 확인)
STOP = COMMON | frozenset(
    [
        "떻게",
        "어떻",
        "되나",
        "될까",
        "나요",
        "할까",
        "까요",
        "는게",
        "는지",
        "궁금",
        "금해",
        "해야",
        "있어",
    ]
)


def _tf(text: str) -> Counter[str]:
    return Counter(g for g in bm25.grams(text) if g not in STOP)


def _vec(tf: Counter[str], idf: dict[str, float]) -> tuple[dict[str, float], float]:
    v = {g: (1 + math.log(c)) * idf.get(g, 0.0) for g, c in tf.items() if g in idf}
    return v, math.sqrt(sum(x * x for x in v.values())) or 1.0


def build(cards: list[AnswerCard], version: str = "") -> CardSet:
    df: Counter[str] = Counter()
    tfs: list[tuple[int, Counter[str]]] = []
    for i, c in enumerate(cards):
        for k in c.keys:
            tf = _tf(k)
            tfs.append((i, tf))
            df.update(tf.keys())
    n = max(len(tfs), 1)
    idf = {g: math.log((n + 1) / (d + 1)) + 1 for g, d in df.items()}
    vecs = [(i, *_vec(tf, idf)) for i, tf in tfs]
    by_id = {c.id: c for c in cards}
    if len(by_id) != len(cards):
        raise ValueError("카드 id가 겹쳐요")
    by_cite: dict[str, list[int]] = {}
    for i, c in enumerate(cards):
        for r in c.cites():
            by_cite.setdefault(r, []).append(i)
    return CardSet(cards, version, idf, vecs, by_id, by_cite)


def read_dir(path: Path = CARD_DIR) -> tuple[list[AnswerCard], str]:
    """폴더의 *.jsonl을 읽어 검사한다. 판 = 파일 내용 해시 앞 12자."""
    cards: list[AnswerCard] = []
    h = hashlib.sha256()
    for f in sorted(path.glob("*.jsonl")) if path.is_dir() else []:
        raw = f.read_bytes()
        h.update(f.name.encode() + b"\0" + raw)
        for line in raw.decode("utf-8-sig").splitlines():
            if line.strip():
                cards.append(AnswerCard.model_validate(json.loads(line)))
    return cards, h.hexdigest()[:12]


@cache
def default() -> CardSet:
    cards, ver = read_dir()
    return build(cards, f"cards@{ver}")


def find(
    cs: CardSet,
    q: str,
    *,
    trades: list[str] | tuple[str, ...] | None = None,
    intents: tuple[str, ...] | None = None,
    k: int = 3,
) -> list[Match]:
    """질문과 가장 가까운 카드(카드마다 가장 가까운 열쇠 하나). trades를 주면 그 공종 + 공통 카드만."""
    qv, qn = _vec(_tf(q), cs.idf)
    if not qv:
        return []
    allow = set(trades or ()) | {"common"} if trades else None
    best: dict[int, tuple[float, int]] = {}
    keys_seen: dict[int, int] = {}
    for i, v, n in cs.vecs:
        c = cs.cards[i]
        j = keys_seen.get(i, -1) + 1
        keys_seen[i] = j
        if allow is not None and c.trade not in allow:
            continue
        if intents is not None and c.intent not in intents:
            continue
        dot = sum(w * v.get(g, 0.0) for g, w in qv.items())
        s = dot / (qn * n)
        if s > best.get(i, (-1.0, 0))[0]:
            best[i] = (s, j)
    ranked = sorted(best.items(), key=lambda p: -p[1][0])[:k]
    return [Match(cs.cards[i], round(s, 4), cs.cards[i].keys[j]) for i, (s, j) in ranked]


def score(cs: CardSet, q: str, idxs: list[int]) -> list[Match]:
    """정한 카드들만 질문과의 열쇠 점수를 잰다(검색 맞물림 후보용)."""
    qv, qn = _vec(_tf(q), cs.idf)
    want = set(idxs)
    best: dict[int, tuple[float, int]] = {}
    pos: dict[int, int] = {}
    for i, v, n in cs.vecs:
        j = pos.get(i, -1) + 1
        pos[i] = j
        if i not in want or not qv:
            continue
        s = sum(w * v.get(g, 0.0) for g, w in qv.items()) / (qn * n)
        if s > best.get(i, (-1.0, 0))[0]:
            best[i] = (s, j)
    return [Match(cs.cards[i], round(s, 4), cs.cards[i].keys[j]) for i, (s, j) in best.items()]


def guest_cards(cs: CardSet, limit: int = 12) -> list[AnswerCard]:
    """로그인 전 자주 묻는 질문 칩(카드 파일만 읽음, 서버 계산 없음)."""
    return [c for c in cs.cards if c.guest][:limit]
