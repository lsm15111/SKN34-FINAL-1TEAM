"""바닥 상담 시작점(docs/v3/floor-agent.md 4.2).

- LLM 끔: run_common(규칙 흐름) 그대로예요.
- LLM 켬: turn이 규칙 흐름 답을 만든 뒤 run_llm을 불러 판단 루프(agent_loop)를 돌려요.
  실패하면 None을 돌려주고 turn은 규칙 흐름 답을 그대로 써요.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.v3.agent_loop import Result
    from app.agent.v3.answer import KB, Part, Task
    from app.agent.v3.specialists import TradeRunner


def run(task: Task, kb: KB, run_common: TradeRunner) -> Part:
    return run_common(task, kb)


async def loop(task: Task, kb: KB, free: Part) -> Result:
    from app.agent.v3 import agent_loop
    from app.agent.v3.specialists.floor import tools

    box = agent_loop.Toolbox(
        defs=tools.defs(), call=tools.call, state=tools.State, scope=tools.scope
    )
    return await agent_loop.run(task, kb, free, box)


async def run_llm(task: Task, kb: KB, free: Part) -> Part | None:
    return (await loop(task, kb, free)).part
