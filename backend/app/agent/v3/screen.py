"""보던 화면의 항목 이름 맞추기. 관문(데이터 화면에서 화면 줄 이름 먼저)과 견적 설명이 같이 써요.

이름은 화면 데이터(계산 엔진 줄 정의의 고객 화면 이름) 그대로라, 줄이 늘어도 규칙을 손으로 더하지 않아요.
다른 말('밥값 → 식대')은 여기서 잡지 않아요. LLM 모드 질문 분석기가 맡아요(docs/v3/agent-orchestrator.md).
"""

import re
from collections.abc import Sequence

from app.agent.v3.schemas import ProjectFacts

_SPACE = re.compile(r"\s+")


def first_named(text: str, names: Sequence[str]) -> int | None:
    """text에 가장 먼저 나온 이름의 번호. 이름이 그대로 있거나, 세 글자 넘는 이름은 앞 두 글자
    ('퍼티작업' → '퍼티', '실크벽지' → '실크')가 있으면 맞아요. 두 글자보다 짧은 이름은 보지 않아요."""
    plain = _SPACE.sub("", text or "")
    best: tuple[int, int] | None = None
    for i, name in enumerate(names):
        n = _SPACE.sub("", name or "")
        for probe in (n, n[:2] if len(n) > 2 else ""):
            if len(probe) >= 2 and probe in plain:
                at = plain.index(probe)
                if best is None or at < best[0]:
                    best = (at, i)
                break
    return best[1] if best else None


def items_of(facts: ProjectFacts | None) -> list[str]:
    """화면 사실의 항목 이름. 지금은 업체 자세히 화면의 가견적 줄만 있어요."""
    v = facts.screen.vendor if facts is not None and facts.screen is not None else None
    return [x.name for x in v.lines] if v is not None else []
