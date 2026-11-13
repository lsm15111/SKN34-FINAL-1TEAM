"""LLM SDK 호출은 이 파일 한 곳 (AGENTS.md 4절). LLM_LIVE=false면 스텁만 써서 유료 호출 0회."""

import math
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings

Role = Literal["orchestrator", "trade", "quote_explanation", "schedule"]

JEV_URL = "https://openrouter.ai/api/alpha/decisions"

_stubs: dict[Role, BaseModel] = {}
_jev_stub: list[tuple[str, float]] = []
_embed_stub: list[tuple[str, list[float]]] = []
EMBED_DIMENSIONS = 1536  # 지식 조각 임베딩과 같은 차원 (data_ingest 기본값)


def model_for(role: Role) -> tuple[str, str]:
    """역할에 맞는 (모델, 추론 effort). 짧은 구조화 출력 역할은 작은 모델로 비용을 줄인다."""
    light = {r.strip() for r in settings.openai_light_roles.split(",") if r.strip()}
    if settings.openai_light_model and role in light:
        return settings.openai_light_model, settings.openai_light_effort
    return settings.openai_agent_model, settings.openai_reasoning_effort


class LLMError(Exception):
    """LLM 실패 · 시간 초과 · 스텁 없음. 받는 쪽은 FAILED_TEXT로 알린다."""


def set_stub(role: Role, answer: BaseModel) -> None:
    """LLM_LIVE=false일 때 role이 돌려줄 답. 테스트 · 로컬 확인용."""
    _stubs[role] = answer


def set_jev_stub(choice: str, confidence: float = 0.9) -> None:
    """LLM_LIVE=false일 때 Jev가 고를 답. 없으면 Jev 실패로 본다."""
    _jev_stub[:] = [(choice, confidence)]


def set_embed_stub(model: str, vector: list[float]) -> None:
    """LLM_LIVE=false일 때 검색어 임베딩이 돌려줄 (모델, 벡터). 없으면 의미 검색 없이 찾는다."""
    _embed_stub[:] = [(model, vector)]


def clear_stubs() -> None:
    _stubs.clear()
    _jev_stub.clear()
    _embed_stub.clear()


async def embed_query(text: str) -> tuple[str, list[float]] | None:
    """검색어 임베딩 (의미 검색용, 질문 하나에 수십 토큰). 실패하면 None: 부르는 쪽은 키워드로만 찾는다."""
    if not settings.llm_live:
        return _embed_stub[0] if _embed_stub else None
    from openai import AsyncOpenAI, OpenAIError

    model = settings.openai_embedding_model
    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(), timeout=10, max_retries=1
    )
    try:  # 공급자 오류 · 시간 초과는 조용히 키워드 검색으로. 입력값은 남기지 않음
        r = await client.embeddings.create(
            model=model, input=text[:300], dimensions=EMBED_DIMENSIONS
        )
        return model, list(r.data[0].embedding)
    except OpenAIError:
        return None
    finally:
        await client.close()


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
        confidence = float(answer.get("confidence") or 0)
    except Exception as e:
        raise LLMError("jev 호출 실패") from e
    if not isinstance(choice, str) or choice not in criteria:
        raise LLMError("jev 모르는 답")
    if not math.isfinite(confidence):
        raise LLMError("jev 신뢰도 이상")
    return choice, min(max(confidence, 0.0), 1.0)


async def structured[T: BaseModel](
    role: Role, schema: type[T], messages: list[tuple[str, str]]
) -> T:
    """messages(("system" | "user", 글))를 보내고 schema 모양으로 받는다."""
    if not settings.llm_live:
        return _stub(role, schema)
    # 실호출일 때만 SDK를 불러온다 (CI · 로컬 스텁에서는 import도 하지 않음)
    from langchain_openai import ChatOpenAI

    # 설정 오류(빠진 키 이름 · 틀린 값)는 LLMError로 가리지 않고 그대로 낸다
    name, effort = model_for(role)
    model = ChatOpenAI(
        model=name,
        api_key=settings.openai_api_key,
        reasoning_effort=effort,
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
