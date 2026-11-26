"""바닥 상담 시작점. 범위 밖 · 경계 · 순서 규칙(W6-2)과 전문가 답(W6-3)은 다음 단계에서 더해요."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.v3.answer import KB, Part, Task
    from app.agent.v3.specialists import TradeRunner


def run(task: Task, kb: KB, run_common: TradeRunner) -> Part:
    return run_common(task, kb)
