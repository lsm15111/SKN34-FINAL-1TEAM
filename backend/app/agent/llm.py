"""LLM SDK 호출은 이 파일 한 곳 (AGENTS.md 4절). LLM_LIVE=false면 스텁만 써서 유료 호출 0회."""

from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings

Role = Literal["orchestrator", "trade", "quote_explanation", "schedule"]

JEV_URL = "https://openrouter.ai/api/alpha/decisions"

_stubs: dict[Role, BaseModel] = {}
_jev_stub: list[tuple[str, float]] = []


class LLMError(Exception):
    """LLM 실패 · 시간 초과 · 스텁 없음. 받는 쪽은 FAILED_TEXT로 알린다."""


def set_stub(role: Role, answer: BaseModel) -> None:
    """LLM_LIVE=false일 때 role이 돌려줄 답. 테스트 · 로컬 확인용."""
    _stubs[role] = answer


def set_jev_stub(choice: str, confidence: float = 0.9) -> None:
    """LLM_LIVE=false일 때 Jev가 고를 답. 없으면 Jev 실패로 본다."""
    _jev_stub[:] = [(choice, confidence)]


def clear_stubs() -> None:
    _stubs.clear()
    _jev_stub.clear()


async def jev_choice(text: str, instructions: str, criteria: dict[str, str]) -> tuple[str, float]:
    """Jev(decisions)로 criteria 키 중 하나를 고른다. 입구 분류에만 쓴다 (AGENTS.md 4절).

    text는 부르는 쪽이 전화번호 · 동호수를 가려서 넘긴다.
    """
    if not settings.llm_live:
        if not _jev_stub:
            raise LLMError("jev 스텁 없음")
        return _jev_stub[0]
    body = {
        "model": settings.jev_model,
        "state": text,
        "questions": {
            "intent": {"type": "choice", "instructions": instructions, "criteria": criteria}
        },
    }
    key = settings.openrouter_api_key.get_secret_value()
    try:  # 실패 · 시간 초과 · 모르는 답은 LLMError로. 입력값은 남기지 않음
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            answer = r.json()["answers"]["intent"]
        choice = answer["choice"]
        confidence = min(max(float(answer.get("confidence") or 0), 0.0), 1.0)
    except Exception as e:
        raise LLMError("jev 호출 실패") from e
    if choice not in criteria:
        raise LLMError("jev 모르는 답")
    return choice, confidence


async def structured[T: BaseModel](
    role: Role, schema: type[T], messages: list[tuple[str, str]]
) -> T:
    """messages(("system" | "user", 글))를 보내고 schema 모양으로 받는다."""
    if not settings.llm_live:
        return _stub(role, schema)
    # 실호출일 때만 SDK를 불러온다 (CI · 로컬 스텁에서는 import도 하지 않음)
    from langchain_openai import ChatOpenAI

    # 설정 오류(빠진 키 이름 · 틀린 값)는 LLMError로 가리지 않고 그대로 낸다
    model = ChatOpenAI(
        model=settings.openai_agent_model,
        api_key=settings.openai_api_key,
        reasoning_effort=settings.openai_reasoning_effort,
        timeout=30,
        max_retries=1,
    ).with_structured_output(schema, method="json_schema", strict=True)
    try:  # 공급자 오류 · 시간 초과 · 모양 틀림을 한곳에서 LLMError로. 입력값은 남기지 않음
        return schema.model_validate(await model.ainvoke(messages))
    except Exception as e:
        raise LLMError(f"{role} 호출 실패") from e


CHAT_STUB_TEXT = "지금은 AI 답변을 쓸 수 없어요. 버튼으로 이어서 진행해 주세요."


async def chat_tools(system: str, messages: list[dict], tools: list[dict]) -> dict:
    """대화 한 번(도구 부르기 포함). 도구는 부르는 쪽이 실행하고 결과를 messages에 붙여 다시 부른다.

    messages: [{role: user | assistant | tool, content: 글 | [{type: text, text} | {type: image, data}],
    tool_calls?: [{id, name, arguments}], tool_call_id?}], tools: [{name, description, parameters}].
    돌려주는 것: {text, tool_calls: [{id, name, arguments}], stop: tool_calls | stop | refusal}.
    """
    if not settings.llm_live:
        return {"text": CHAT_STUB_TEXT, "tool_calls": [], "stop": "stop"}
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI

    def parts(content):
        if isinstance(content, str):
            return content
        return [
            {"type": "text", "text": p["text"]}
            if p["type"] == "text"
            else {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{p['data']}"}}
            for p in content
        ]

    msgs: list = [SystemMessage(system)]
    for m in messages:
        if m["role"] == "user":
            msgs.append(HumanMessage(parts(m["content"])))
        elif m["role"] == "assistant":
            calls = [
                {"id": c["id"], "name": c["name"], "args": c["arguments"]}
                for c in m.get("tool_calls") or []
            ]
            msgs.append(AIMessage(parts(m["content"]), tool_calls=calls))
        else:
            msgs.append(ToolMessage(parts(m["content"]), tool_call_id=m.get("tool_call_id") or ""))
    model = ChatOpenAI(
        model=settings.openai_agent_model,
        api_key=settings.openai_api_key,
        reasoning_effort=settings.openai_reasoning_effort,
        timeout=30,
        max_retries=1,
    )
    if tools:
        model = model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                    },
                }
                for t in tools
            ]
        )
    try:  # 공급자 오류 · 시간 초과를 한곳에서 LLMError로. 입력값은 남기지 않음
        r = await model.ainvoke(msgs)
    except Exception as e:
        raise LLMError("chat 호출 실패") from e
    calls = [
        {"id": c.get("id") or "", "name": c["name"], "arguments": c.get("args") or {}}
        for c in r.tool_calls
    ]
    text = r.content if isinstance(r.content, str) else r.text
    refusal = r.additional_kwargs.get("refusal")
    if refusal and not text:
        text = refusal
    stop = "tool_calls" if calls else "refusal" if refusal else "stop"
    return {"text": text or "", "tool_calls": calls, "stop": stop}


def _stub[T: BaseModel](role: Role, schema: type[T]) -> T:
    stub = _stubs.get(role)
    try:
        return schema.model_validate(stub.model_dump()) if stub else schema()
    except ValidationError as e:
        raise LLMError(f"{role} 스텁 없음") from e
