"""에이전트 런타임: 도구 정의 · 에이전트 한 번의 LLM ↔ 도구 루프 · 턴 예산.

- LLM 호출은 app.agent.llm.chat_tools 한 곳에서만 한다. 여기는 루프 · 인자 검사 · 되풀이 막기만 한다.
- 도구 인자는 Pydantic 모델이고, 그 JSON 스키마를 그대로 LLM에 준다. 같은 도구 · 같은 인자는 한 번만 돈다.
- 도구가 돌려준 원문(evidence)과 보인 근거 번호(shown)를 모은다. 마지막 답 글의 숫자 · 인용은 이것으로 검사한다.
- 화면 조각(비교표 · 체크리스트 · 업체에 보낼 말)은 도구가 바로 답(Reply)에 담는다. LLM이 다시 옮겨 쓰지 않아
  검증된 글이 바뀌지 않는다.
- 예산(Budget)은 한 턴 전체가 같이 쓴다. 넘치면 BudgetExceeded를 내고, 부르는 쪽은 무료 모드 답으로 간다.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent import llm
from app.agent.hub.reply import Reply

TOOL_TEXT_MAX = 3000  # LLM에 돌려주는 도구 결과 길이


class BudgetExceeded(Exception):
    """한 턴 호출 상한에 닿음. 부르는 쪽은 지금까지 확인한 것 또는 무료 모드 답으로 끝낸다."""


@dataclass
class Budget:
    """한 턴 상한. LLM 호출 수와 다른 에이전트에 맡기는 수를 센다."""

    llm_calls: int = 8
    delegations: int = 3
    used_llm: int = 0
    used_delegations: int = 0

    def take_llm(self) -> None:
        if self.used_llm >= self.llm_calls:
            raise BudgetExceeded("LLM 호출 상한")
        self.used_llm += 1

    def take_delegation(self) -> None:
        if self.used_delegations >= self.delegations:
            raise BudgetExceeded("맡기기 상한")
        self.used_delegations += 1


@dataclass
class ToolOut:
    text: str  # LLM에 돌려줄 짧은 글
    evidence: str = ""  # 숫자 검사에 쓰는 원문(근거 조각 원문 · 계산 결과)
    refs: tuple[str, ...] = ()  # 이번에 보인 근거 번호(K#### · card:…)


type ToolFn = Callable[[Any, Any], ToolOut | Awaitable[ToolOut]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: ToolFn

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": params(self.args)}


@dataclass
class Run:
    """에이전트 한 번 돌리는 동안의 상태. 전문가 · 총괄이 이것을 넓혀 쓴다."""

    reply: Reply
    budget: Budget
    evidence: list[str] = field(default_factory=list)
    shown: set[str] = field(default_factory=set)
    seen_calls: set[str] = field(default_factory=set)
    done: bool = False


@dataclass(frozen=True)
class AgentSpec:
    name: str
    system: str
    tools: tuple[Tool, ...]
    finish: Tool  # 마지막 답 도구. run에서 state.done = True로 만든다
    max_rounds: int = 4  # 도구를 부를 수 있는 차례. 그다음 차례에는 마지막 답 도구만 준다


def params(model: type[BaseModel]) -> dict:
    """Pydantic JSON 스키마에서 $ref를 풀고 title을 뺀다(공급자마다 $defs 처리가 달라서)."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(x: Any) -> Any:
        if isinstance(x, dict):
            if "$ref" in x:
                return walk(defs[x["$ref"].rsplit("/", 1)[1]])
            return {k: walk(v) for k, v in x.items() if k != "title"}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(raw)


def _args_of(call: dict) -> dict:
    raw = call.get("arguments") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


async def call_tool(spec: AgentSpec, state: Run, call: dict) -> str:
    tools = {t.name: t for t in (*spec.tools, spec.finish)}
    tool = tools.get(call.get("name", ""))
    if tool is None:
        return "없는 도구예요. 주어진 도구만 쓰세요."
    raw = _args_of(call)
    key = f"{tool.name}:{json.dumps(raw, sort_keys=True, ensure_ascii=False)}"
    if key in state.seen_calls and tool is not spec.finish:
        return "같은 인자로 이미 불렀어요. 앞 결과를 쓰세요."
    state.seen_calls.add(key)
    try:
        args = tool.args.model_validate(raw)
    except ValidationError as e:  # 입력값은 돌려주지 않고 칸 이름만
        where = sorted({".".join(str(p) for p in x["loc"]) for x in e.errors()})
        return f"인자가 맞지 않아요: {', '.join(where)[:200]}"
    out = tool.run(state, args)
    if inspect.isawaitable(out):
        out = await out
    state.reply.tools.append(tool.name)
    if out.evidence:
        state.evidence.append(out.evidence)
    state.shown.update(out.refs)
    return out.text[:TOOL_TEXT_MAX]


async def loop(spec: AgentSpec, state: Run, user: str, history: list[dict] | None = None) -> str:
    """LLM ↔ 도구를 돌린다. 마지막 답 도구가 불리면 ''를, 도구 없이 글로 끝나면 그 글을 돌려준다.

    LLMError · BudgetExceeded는 그대로 올린다(부르는 쪽이 무료 모드로).
    """
    messages: list[dict] = [*(history or []), {"role": "user", "content": user}]
    for i in range(spec.max_rounds + 1):
        tools = [*spec.tools, spec.finish] if i < spec.max_rounds else [spec.finish]
        state.budget.take_llm()
        r = await llm.chat_tools(spec.system, messages, [t.schema() for t in tools])
        calls = r.get("tool_calls") or []
        if not calls:
            return r.get("text") or ""
        messages.append({"role": "assistant", "content": r.get("text") or "", "tool_calls": calls})
        for c in calls:
            text = await call_tool(spec, state, c)
            messages.append({"role": "tool", "tool_call_id": c.get("id") or "", "content": text})
            if state.done:
                return ""
    return ""
