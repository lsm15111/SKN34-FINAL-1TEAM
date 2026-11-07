"""공정별 서브에이전트 설정의 모양. 실행기는 하나(consult_agent), 공정마다 슬롯 · 주의점만 다르다.

슬롯 = 상담으로 채울 조건 하나. affects는 그 조건을 알면 줄어드는 예상 범위 폭의 이유(calc.price_range의 driver),
effort는 고객 수고(1 버튼 하나 · 2 사진이나 확인 · 3 줄자로 재기). 다음 질문은 '줄어드는 폭 ÷ 수고' 순서다.
docs/agent/02-agents.md 2a · 2b.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    key: str
    label: str  # 화면 말
    ask: str  # 기본 질문(서브에이전트가 고객 말투로 다듬음)
    why: str  # 왜 묻는지 한 줄
    choices: tuple[tuple[str, str], ...]  # (값, 화면 말). 'after_visit' = 실측 후
    affects: tuple[str, ...]  # qty:area · cond:removal · scenario:grade …
    effort: int  # 1~3
    base: float = 0.0  # 범위와 상관없이 먼저 물어야 하는 정도(시공 범위처럼)


@dataclass(frozen=True)
class TradeConfig:
    trade: str
    name: str
    slots: tuple[Slot, ...]
    cautions: tuple[str, ...]  # 늘 붙는 주의점(지식 조각 key)

    def slot(self, key: str) -> Slot:
        return next(s for s in self.slots if s.key == key)


def pick_questions(
    cfg: TradeConfig,
    shares: Mapping[str, float],
    answered: Sequence[str],
    limit: int = 2,
) -> list[Slot]:
    """아직 안 물은 슬롯 중 (줄어드는 폭의 몫 + 기본 점수) ÷ 수고가 큰 것부터 limit개.
    shares는 price_range 결과의 {driver: share}(없으면 0)."""
    done = set(answered)
    scored = []
    for i, s in enumerate(cfg.slots):
        if s.key in done:
            continue
        gain = sum(shares.get(d, 0.0) for d in s.affects) + s.base
        scored.append((-(gain / s.effort), i, s))
    scored.sort()
    return [s for score, _, s in scored[:limit] if score < 0]
