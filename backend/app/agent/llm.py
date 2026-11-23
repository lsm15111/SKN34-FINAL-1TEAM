"""LLM SDK 호출은 이 파일 한 곳 (AGENTS.md 4절). LLM_LIVE=false면 스텁 · 대본만 써서 유료 호출 0회.

- 공급자: LLM_PROVIDER=anthropic(기본, Claude) · openai. 임베딩은 늘 OpenAI다. openai면 v4 비서 · 조사 · 기억 ·
  먼저 권하기 · 업체 문장(claude_stream · claude_json)도 OpenAI Responses로 보낸다(도면 읽기만 Claude, 아래 OpenAI
  Responses 길).
- 유료 호출은 모두 _guard(usage.allow: 비용 상한) → 호출 → _sink(usage.record: 토큰 · 비용 장부)를 지난다.
  상한을 넘으면 OverBudget(LLMError)이라 부르는 쪽은 지금처럼 무료 · 실패 길로 간다. 임베딩 · Jev는 장부 밖이다.
  부르는 쪽 시간 제한으로 끊겨 usage를 못 받은 호출은 보수적 추정치로 남긴다(error ESTIMATED).
- 누가 · 어느 턴에서 · 무슨 일로 부르는지는 CALL_CTX에 둔다. 장부와 로그에는 글을 남기지 않는다.
- usage(기반)는 함수 안에서 늦게 import한다: 계약서 1장이 정한 층 규칙 예외(agent.llm → usage).
- Claude: 강제 tool_choice는 400이라 auto + strict로 쓴다. 생각(thinking)은 모델 기본(adaptive)이고 effort로 줄인다.
  temperature 같은 표본 값과 assistant 미리 채우기(prefill)는 보내지 않는다.
"""

import asyncio
import json
import logging
import math
import re
import time
import uuid
import weakref
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal, Self, get_args

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

Role = Literal[
    "orchestrator", "trade", "quote_explanation", "schedule", "composer", "general", "planner"
]
# 장부(llm_usage.purpose)에 남기는 목적. usage/models.py의 PURPOSES와 같다(시험이 맞춰 본다)
Purpose = Literal[
    "assistant", "floorplan", "nudge", "memory", "v2_chat", "research",
    "orchestrator", "trade", "quote_explanation", "schedule", "composer", "general", "planner",
    "judge", "check",
]  # fmt: skip
PURPOSES: frozenset[str] = frozenset(get_args(Purpose))
# 기본 모델(Sonnet)을 쓰는 목적. 판정은 Opus, 그 밖(짧은 문장 · 분류 · 기억 · 가벼운 역할)은 Haiku
MAIN_PURPOSES = frozenset({"assistant", "floorplan", "v2_chat", "research"})
# 거절 · 잘림이면 장부에 실패로 적는다(stop_reason 그대로)
BAD_STOPS = frozenset({"refusal", "max_tokens", "model_context_window_exceeded"})

JEV_URL = "https://openrouter.ai/api/alpha/decisions"

_stubs: dict[Role, BaseModel] = {}
_jev_stub: list[tuple[str, float]] = []
_embed_stub: list[tuple[str, list[float]]] = []
EMBED_DIMENSIONS = 1536  # 지식 조각 임베딩과 같은 차원 (data_ingest 기본값)
# 평가 · 비용 기록용: structured 호출마다 {role, model, input, cached, output, reasoning} 토큰을 받아요(값만, 글 없음)
USAGE_HOOK: Callable[[dict], None] | None = None


class LLMError(Exception):
    """LLM 실패 · 시간 초과 · 스텁 없음. 받는 쪽은 FAILED_TEXT로 알린다."""


class LLMOff(LLMError):
    """LLM_LIVE=false · 키 없음 · 공급자가 Claude가 아님: 유료 호출을 하지 않았다(무료 모드로)."""


class OverBudget(LLMError):
    """비용 상한(사용자 하루 · 새 계정 · 서비스 하루 · 전체)의 90%를 넘었거나 셀 수 없어 막았다(무료 모드로).

    scope: user_day · new_user_day · new_pool_day · service_day · total(usage.Scope) 또는 셀 수 없으면 unknown.
    """

    def __init__(self, scope: str) -> None:
        super().__init__(f"LLM 비용 상한({scope})")
        self.scope = scope


# 요청 자체가 틀렸다는 공급자 응답(빈 글 블록 · 너무 긴 요청 · 꼴 틀림): 같은 요청을 다시 보내도 같다
REJECTED_STATUS = frozenset({400, 413, 422})


class LLMRejected(LLMError):
    """공급자가 요청 자체를 거절했다(400 · 413 · 422). 같은 요청을 다시 보내지 않고 서비스 차단기에도 세지 않는다
    (한 사람의 틀린 요청이 모든 사람을 무료 모드로 만들지 않게)."""


class LLMBadOutput(LLMError):
    """답은 왔지만 쓸 수 없다(거절 · 잘림 · 꼴 틀림). 같은 요청을 다시 보내면 비용만 다시 든다."""


@dataclass
class CallCtx:
    """누가 · 어느 턴에서 · 무슨 일로 부르는지. 부르는 쪽(비서 runtime · worker)이 CALL_CTX에 둔다."""

    user_id: uuid.UUID | None = None
    turn_id: uuid.UUID | None = None
    purpose: Purpose | None = None
    spent_micros: int = 0  # 이 문맥에서 장부에 적은 비용 합(마이크로달러). 비서 턴 상한이 읽는다


CALL_CTX: ContextVar[CallCtx | None] = ContextVar("llm_call_ctx", default=None)


@contextmanager
def call_ctx(
    user_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    purpose: Purpose | None = None,
) -> Iterator[CallCtx]:
    """with 안의 호출을 이 사용자 · 턴 · 목적으로 장부에 남긴다. 비용은 돌려준 ctx.spent_micros에 쌓인다."""
    ctx = CallCtx(user_id, turn_id, purpose)
    token = CALL_CTX.set(ctx)
    try:
        yield ctx
    finally:
        CALL_CTX.reset(token)


@dataclass
class ClaudeReply:
    """claude_stream 한 번의 결과. content는 다음 요청에 assistant로 그대로 붙인다(생각 블록 포함)."""

    text: str
    content: list[dict]
    # [{id, name, input}]. 거절 · 잘림이면 비운다(잘린 인자로 도구를 돌리지 않게)
    tool_calls: list[dict]
    stop: str  # end_turn · tool_use · pause_turn · refusal · max_tokens ...
    # {input, cache_read, cache_write_5m, cache_write_1h, output, web_searches, thinking}
    usage: dict[str, int]
    cost_micros: int
    model: str
    # 코드 실행 컨테이너(웹 도구 동적 거르기). pause_turn을 이을 때 다시 보낸다
    container: str | None = None


def _usage(role: str, name: str, raw: Any) -> dict:
    um = getattr(raw, "usage_metadata", None) or {}
    return {
        "role": role,
        "model": name,
        "input": int(um.get("input_tokens") or 0),
        "cached": int((um.get("input_token_details") or {}).get("cache_read") or 0),
        "output": int(um.get("output_tokens") or 0),
        "reasoning": int((um.get("output_token_details") or {}).get("reasoning") or 0),
    }


def model_for(role: Role) -> tuple[str, str]:
    """OpenAI 길(되돌리기용)에서 역할에 맞는 (모델, 추론 effort). 짧은 구조화 출력 역할은 작은 모델로 비용을 줄인다."""
    light = {r.strip() for r in settings.openai_light_roles.split(",") if r.strip()}
    if settings.openai_light_model and role in light:
        return settings.openai_light_model, settings.openai_light_effort
    return settings.openai_agent_model, settings.openai_reasoning_effort


def claude_model_for(purpose: str) -> tuple[str, str]:
    """목적 · 역할에 맞는 (Claude 모델, effort).

    판정은 Opus, 비서 · 도면 · v2 대화와 가볍지 않은 역할은 Sonnet, 나머지(짧은 문장 · 분류 · 기억 ·
    LLM_CLAUDE_LIGHT_ROLES 역할)는 Haiku.
    """
    if purpose == "judge":
        return settings.llm_claude_judge_model, settings.llm_claude_effort
    light = {r.strip() for r in settings.llm_claude_light_roles.split(",") if r.strip()}
    if purpose in MAIN_PURPOSES or (purpose in get_args(Role) and purpose not in light):
        return settings.llm_claude_model, settings.llm_claude_effort
    return settings.llm_claude_light_model, settings.llm_claude_light_effort


def available() -> bool:
    """유료 LLM을 부를 수 있는지(LLM_LIVE=true이고 고른 공급자의 키가 있음). 무료 모드 판단에 쓴다."""
    if not settings.llm_live:
        return False
    key = (
        settings.anthropic_api_key
        if settings.llm_provider == "anthropic"
        else settings.openai_api_key
    )
    return bool(key.get_secret_value())


async def budget_ok(user_id: uuid.UUID | None, label: str = "turn") -> bool:
    """비용 상한(사용자 하루 · 새 계정 · 서비스 하루 · 전체)의 90% 안인지. 턴 시작에 무료 모드로 갈지 정할 때 쓴다.

    셀 수 없으면 False(닫힘 쪽). 호출마다 _guard가 다시 본다. label은 로그에만 쓴다.
    """
    from app.usage import service as usage  # 층 규칙 예외(계약서 1장): agent.llm → usage

    try:
        await usage.allow(user_id, label)
    except (usage.OverCap, *usage.DB_ERRORS):
        return False
    return True


def set_stub(role: Role, answer: BaseModel) -> None:
    """LLM_LIVE=false일 때 role이 돌려줄 답. 테스트 · 로컬 확인용."""
    _stubs[role] = answer


def set_jev_stub(choice: str, confidence: float = 0.9) -> None:
    """LLM_LIVE=false일 때 Jev가 고를 답. 없으면 Jev 실패로 본다."""
    _jev_stub[:] = [(choice, confidence)]


def set_embed_stub(model: str, vector: list[float]) -> None:
    """LLM_LIVE=false일 때 검색어 임베딩이 돌려줄 (모델, 벡터). 없으면 의미 검색 없이 찾는다."""
    _embed_stub[:] = [(model, vector)]


@dataclass
class _ScriptState:
    on: bool = False
    steps: list = field(default_factory=list)
    log: list[dict] = field(default_factory=list)


_SCRIPT = _ScriptState()


def set_claude_script(steps: Sequence[dict | BaseException]) -> list[dict]:
    """시험용 Claude 대본(유료 호출 0회). 켜 두면 structured · chat_tools · claude_*가 SDK 대신 대본을 쓴다.

    부를 때마다 앞에서 한 단계씩 꺼내 응답으로 쓴다. 단계가 예외면 그 예외가 공급자 오류처럼 난다.
    단계(dict): text · json(구조화 답) · thinking(True면 생각 블록) · tool_calls([{id, name, input}]) ·
    blocks(그 밖의 응답 블록) · stop(기본: 도구가 있으면 tool_use, 없으면 end_turn) · model ·
    usage({input, output, cache_read, cache_write, cache_write_1h, web_searches}) · fail(스트림 글 뒤에 낼 예외).
    돌려주는 목록에 보낸 요청(모델 · 도구 · 메시지 · 설정)이 쌓인다. 단계가 떨어지면 공급자 오류로 본다.
    """
    _SCRIPT.on = True
    _SCRIPT.steps[:] = list(steps)
    _SCRIPT.log.clear()
    return _SCRIPT.log


def clear_stubs() -> None:
    _stubs.clear()
    _jev_stub.clear()
    _embed_stub.clear()
    _SCRIPT.on = False
    _SCRIPT.steps.clear()


async def embed_texts(texts: list[str]) -> tuple[str, list[list[float]]] | None:
    """글 여러 개 임베딩 (검색어 · 추천 질문 후보, 한 번에 수백 토큰). 실패하면 None: 부르는 쪽은 임베딩 없이 간다.

    키가 비었으면 부르지 않고 None(openai 2.x는 빈 키로 클라이언트를 만들 때 OpenAIError를 낸다, QA r3).
    클라이언트 만들기 · 호출 · 닫기의 어떤 실패도 None이다(지식 답은 키워드 검색으로 물러선다)."""
    if not texts:
        return None
    if not settings.llm_live:
        return (_embed_stub[0][0], [_embed_stub[0][1]] * len(texts)) if _embed_stub else None
    key = settings.openai_api_key.get_secret_value()
    if not key:
        return None
    model = settings.openai_embedding_model
    client = None
    try:  # 공급자 오류 · 시간 초과 · 클라이언트 오류는 조용히 임베딩 없이. 입력값은 남기지 않음
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=key, timeout=10, max_retries=1)
        r = await client.embeddings.create(
            model=model, input=[t[:300] for t in texts], dimensions=EMBED_DIMENSIONS
        )
        return model, [list(d.embedding) for d in sorted(r.data, key=lambda d: d.index)]
    except Exception as e:  # noqa: BLE001 - 임베딩은 없어도 되는 값(종류 이름만 로그)
        log.warning("임베딩 실패 (%s)", type(e).__name__)
        return None
    finally:
        if client is not None:
            with suppress(Exception):  # 닫기 실패는 결과와 상관없음
                await client.close()


async def embed_query(text: str) -> tuple[str, list[float]] | None:
    """검색어 임베딩 (의미 검색용). 실패하면 None: 부르는 쪽은 키워드로만 찾는다."""
    r = await embed_texts([text])
    return (r[0], r[1][0]) if r else None


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


# ── 비용 상한 · 장부 ─────────────────────────────────────────────


@dataclass
class _Call:
    ctx: CallCtx | None
    purpose: str
    user_id: uuid.UUID | None
    turn_id: uuid.UUID | None
    t0: float


async def _guard(purpose: str | None, default: str) -> _Call:
    """유료 호출 전: 목적을 정하고(인자 > CALL_CTX > 기본) 비용 상한을 본다. 넘었거나 셀 수 없으면 OverBudget."""
    ctx = CALL_CTX.get()
    p = purpose or (ctx.purpose if ctx else None) or default
    if p not in PURPOSES:
        raise ValueError(f"모르는 purpose: {p}")
    from app.usage import service as usage  # 층 규칙 예외(계약서 1장): agent.llm → usage

    user = ctx.user_id if ctx else None
    try:
        await usage.allow(user, p)
    except usage.OverCap as e:
        raise OverBudget(e.scope) from None
    except Exception as e:  # DB까지 안 되면 셀 수 없으니 막는다(닫힘 쪽)
        log.warning("LLM 비용 상한을 확인하지 못해 유료 호출을 막아요 (%s)", p)
        raise OverBudget("unknown") from e
    return _Call(ctx, p, user, ctx.turn_id if ctx else None, time.monotonic())


async def _sink(call: _Call, model: str, u: dict[str, int], error: str | None = None) -> int:
    """호출 뒤: 장부에 한 줄(글 없음). 비용(마이크로달러)을 돌려주고 CALL_CTX에 쌓는다."""
    from app.usage import service as usage

    # 장부 · 카운터 오류는 record가 로그만 남기고 삼킨다(호출 결과는 살린다)
    cost = await usage.record(
        user_id=call.user_id,
        turn_id=call.turn_id,
        purpose=call.purpose,
        model=model,
        input_tokens=u.get("input", 0),
        cache_read=u.get("cache_read", 0),
        cache_write_5m=u.get("cache_write_5m", 0),
        cache_write_1h=u.get("cache_write_1h", 0),
        output_tokens=u.get("output", 0),
        web_searches=u.get("web_searches", 0),
        error=error,
        latency_ms=int((time.monotonic() - call.t0) * 1000),
    )
    if call.ctx is not None:
        call.ctx.spent_micros += cost
    return cost


def _kind(e: BaseException) -> str:
    """장부 · 로그에 남길 오류 종류 이름(메시지 · 입력값 없음)."""
    return type(e).__name__


def _failed(purpose: str, e: BaseException) -> LLMError:
    """공급자 오류 → LLMError. 요청 자체가 틀렸으면(REJECTED_STATUS) LLMRejected. 입력값은 남기지 않는다."""
    from anthropic import APIStatusError

    if isinstance(e, APIStatusError) and e.status_code in REJECTED_STATUS:
        return LLMRejected(f"{purpose} 요청 거절({e.status_code})")
    return LLMError(f"{purpose} 호출 실패")


# ── Claude 요청 · 응답 꼴 ─────────────────────────────────────────


def to_claude_tools(
    tools: Sequence[dict], *, strict: bool = True, cache: bool = True
) -> list[dict]:
    """도구 정의 → Claude 꼴. OpenAI 함수 꼴({name, description, parameters})도 받는다.

    이름순으로 고정하고(캐시 앞부분이 바뀌지 않게) 끝 도구에 cache_control을 둔다. 직접 만든 도구는 strict로 두고
    스키마는 SDK transform_schema로 Claude 엄격 꼴에 맞춘다(additionalProperties false, 받지 않는 제약은 설명으로).
    서버 도구(type만 있는 web_search 등)는 그대로 둔다.
    """
    from anthropic import transform_schema

    out: list[dict] = []
    for t in sorted(tools, key=lambda t: str(t.get("name", ""))):
        if "type" in t and "input_schema" not in t and "parameters" not in t:
            out.append(dict(t))
            continue
        d = {k: v for k, v in t.items() if k not in ("parameters", "strict")}
        schema = (
            t.get("input_schema") or t.get("parameters") or {"type": "object", "properties": {}}
        )
        # 도구마다 끌 수 있다(Claude는 엄격 도구를 한 요청에 20개까지 받는다)
        on = bool(t.get("strict", strict))
        d["input_schema"] = transform_schema(schema) if on else schema
        if on:
            d["strict"] = True
        out.append(d)
    if cache and out and "cache_control" not in out[-1]:
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def _system_blocks(system: str | Sequence[str] | Sequence[dict] | None) -> list[dict]:
    """지시문 → 글 블록. 판이 고정된 앞부분이라 끝 블록에 cache_control을 둔다."""
    parts = [system] if isinstance(system, str) else list(system or [])
    blocks = [p if isinstance(p, dict) else {"type": "text", "text": p} for p in parts if p]
    if blocks and "cache_control" not in blocks[-1]:
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    return blocks


def _usage_of(msg: Any) -> dict[str, int]:
    """응답 usage → 장부 토큰. input은 캐시 밖 입력만이다(전체 프롬프트 = input + 캐시 읽기 + 캐시 쓰기)."""
    u = getattr(msg, "usage", None)
    if u is None:
        return {}
    total = u.cache_creation_input_tokens or 0
    if u.cache_creation is not None:
        w5 = u.cache_creation.ephemeral_5m_input_tokens or 0
        w1 = u.cache_creation.ephemeral_1h_input_tokens or 0
        w5 += max(total - w5 - w1, 0)
    else:
        w5, w1 = total, 0
    st, od = u.server_tool_use, u.output_tokens_details
    return {
        "input": u.input_tokens or 0,
        "cache_read": u.cache_read_input_tokens or 0,
        "cache_write_5m": w5,
        "cache_write_1h": w1,
        "output": u.output_tokens or 0,
        "web_searches": (st.web_search_requests or 0) if st is not None else 0,
        "thinking": (od.thinking_tokens or 0) if od is not None else 0,
    }


def _prompt_tokens(u: dict[str, int]) -> int:
    return sum(u.get(k, 0) for k in ("input", "cache_read", "cache_write_5m", "cache_write_1h"))


def _block_out(b: Any) -> dict | None:
    """응답 블록 하나 → dict(빈 글 블록은 None: 다시 보내면 400이다). 생각 블록은 서명까지 받은 그대로 둔다."""
    if b.type == "text":
        if not b.text and not getattr(b, "citations", None):
            return None
        d: dict = {"type": "text", "text": b.text}
        if getattr(b, "citations", None):
            d["citations"] = [c.to_dict() for c in b.citations]
        return d
    if b.type == "thinking":
        return {"type": "thinking", "thinking": b.thinking, "signature": b.signature}
    if b.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": b.data}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return b.to_dict()  # 서버 도구 블록(server_tool_use · web_search_tool_result 등)은 받은 그대로


def _blocks_out(content: Sequence[Any]) -> list[dict]:
    """응답 블록 → 다음 요청에 붙일 assistant 블록."""
    return [d for d in (_block_out(b) for b in content) if d is not None]


# ── 대본(시험) · 클라이언트 ─────────────────────────────────────


def _next_step(req: dict) -> dict:
    _SCRIPT.log.append(json.loads(json.dumps(req, ensure_ascii=False, default=str)))
    if not _SCRIPT.steps:
        raise RuntimeError("Claude 대본이 끝났어요")
    step = _SCRIPT.steps.pop(0)
    if isinstance(step, BaseException):
        raise step
    return step


def _fake_message(step: dict, req: dict) -> Any:
    from anthropic.types import Message

    content: list[dict] = []
    if step.get("thinking"):
        content.append({"type": "thinking", "thinking": "", "signature": "script-signature"})
    text = json.dumps(step["json"], ensure_ascii=False) if "json" in step else step.get("text")
    if text:
        content.append({"type": "text", "text": text})
    calls = step.get("tool_calls") or []
    for i, c in enumerate(calls):
        content.append(
            {
                "type": "tool_use",
                "id": c.get("id") or f"toolu_script_{i}",
                "name": c["name"],
                "input": c.get("input") or {},
            }
        )
    content.extend(step.get("blocks") or [])
    u = step.get("usage") or {}
    w5, w1 = u.get("cache_write", 0), u.get("cache_write_1h", 0)
    box = step.get("container")  # 코드 실행 컨테이너 id(웹 도구 동적 거르기 대본)
    return Message.model_validate(
        {
            "id": "msg_script",
            "type": "message",
            "role": "assistant",
            "model": step.get("model") or req["model"],
            "content": content,
            "stop_reason": step.get("stop") or ("tool_use" if calls else "end_turn"),
            "stop_sequence": None,
            "container": {"id": box, "expires_at": "2099-01-01T00:00:00Z"} if box else None,
            "usage": {
                "input_tokens": u.get("input", 0),
                "output_tokens": u.get("output", 0),
                "cache_read_input_tokens": u.get("cache_read", 0),
                "cache_creation_input_tokens": w5 + w1,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": w5,
                    "ephemeral_1h_input_tokens": w1,
                },
                "server_tool_use": {
                    "web_search_requests": u.get("web_searches", 0),
                    "web_fetch_requests": u.get("web_fetches", 0),
                },
            },
        }
    )


class _ScriptStream:
    """messages.stream 자리: message_start → 블록마다 content_block_start(글이면 글 조각 text) → get_final_message."""

    def __init__(self, req: dict) -> None:
        self._req = req
        self._msg: Any = None
        self._fail: BaseException | None = None

    async def __aenter__(self) -> Self:
        step = _next_step(self._req)  # 대본의 예외는 여기서 난다(연결 실패처럼)
        self._fail = step.get("fail")
        self._msg = _fake_message(step, self._req)
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def __aiter__(self):
        yield SimpleNamespace(type="message_start", message=self._msg)
        for b in self._msg.content:
            yield SimpleNamespace(type="content_block_start", content_block=b)
            if b.type == "text":
                for i in range(0, len(b.text), 6):
                    yield SimpleNamespace(type="text", text=b.text[i : i + 6])
            yield SimpleNamespace(type="content_block_stop", content_block=b)
        if self._fail is not None:
            raise self._fail

    async def get_final_message(self) -> Any:
        return self._msg


class _ScriptMessages:
    async def create(self, **req: Any) -> Any:
        return _fake_message(_next_step(req), req)

    def stream(self, **req: Any) -> _ScriptStream:
        return _ScriptStream(req)


_SCRIPT_CLIENT = SimpleNamespace(messages=_ScriptMessages())
# 이벤트 루프마다 클라이언트 하나(연결을 다시 쓴다. 루프가 사라지면 같이 사라진다)
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = weakref.WeakKeyDictionary()


def _claude() -> Any:
    """대본이 켜져 있으면 대본, 아니면 이 이벤트 루프의 Claude 클라이언트. 부를 수 없으면 LLMOff."""
    if _SCRIPT.on:
        return _SCRIPT_CLIENT
    if not settings.llm_live or settings.llm_provider != "anthropic":
        raise LLMOff("LLM 꺼짐")
    key = settings.anthropic_api_key.get_secret_value()
    if not key:
        raise LLMOff("Claude 키 없음")
    from anthropic import AsyncAnthropic  # 실호출일 때만 SDK를 불러온다

    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None:
        client = _clients[loop] = AsyncAnthropic(
            api_key=key, base_url=settings.llm_anthropic_base_url, timeout=60, max_retries=1
        )
    return client


def warm() -> None:
    """실호출 SDK(anthropic · openai)를 미리 불러온다. 함수 안 늦은 import가 처음이면 anthropic 12~14초 · openai
    6초쯤 걸리고(Windows 개발 PC에서 잼) 그동안 이벤트 루프가 멈춰, 프로세스의 첫 LLM 턴이 그만큼 늦었다(QA r2 c5 첫
    턴 33.5초). 앱 시작 때 작업 스레드로 부른다. LLM이 꺼져 있으면 아무것도 하지 않는다."""
    if not settings.llm_live:
        return
    try:
        import anthropic  # noqa: F401
        import openai  # noqa: F401
    except ImportError as e:  # 없으면 실호출 때 같은 오류가 난다(시작은 막지 않는다)
        log.warning("LLM SDK 미리 불러오기 실패 (%s)", type(e).__name__)


def estimate(req: dict, *, output: bool = True) -> dict[str, int]:
    """끊겨 usage를 못 받은 호출의 보수적 추정 토큰(장부 error ESTIMATED): 입력은 보낸 글(지시문 · 메시지 · 도구 ·
    출력 꼴)의 글자 수를 토큰 수로(한국어 · 영어 모두 실제보다 많게), 출력은 max_tokens 전부."""
    sent = json.dumps(
        [req.get(k) for k in ("system", "messages", "tools", "output_config")],
        ensure_ascii=False,
        default=str,
    )
    return {"input": len(sent), "output": int(req.get("max_tokens") or 0) if output else 0}


# 부르는 쪽 시간 제한(asyncio.wait_for: 먼저 말 걸기 판정 · 문장 10초, 턴 45초)으로 끊겨 공급자 usage를 못 받은 호출.
# 공급자는 청구할 수 있어 장부에 보수적 추정치(estimate)로 남기고 이 표시를 붙인다
ESTIMATED = "cancelled_estimate"


async def _create(purpose: str | None, default: str, req: dict) -> tuple[Any, _Call]:
    """스트림 아닌 Claude 호출 한 번: 클라이언트 → 상한 → 호출. 장부는 부르는 쪽이 결과를 보고 남긴다.
    부르는 쪽 시간 제한으로 끊기면 추정치 한 줄(ESTIMATED)을 남기고 그대로 끊는다."""
    client = _claude()
    call = await _guard(purpose, default)
    try:  # 공급자 오류 · 시간 초과를 한곳에서 LLMError로(요청이 틀렸으면 LLMRejected). 입력값은 남기지 않음
        msg = await client.messages.create(**req)
    except asyncio.CancelledError:
        await asyncio.shield(_sink(call, req["model"], estimate(req), ESTIMATED))
        raise
    except Exception as e:
        await _sink(call, req["model"], {}, _kind(e))
        raise _failed(call.purpose, e) from e
    return msg, call


async def _json_call[T: BaseModel](
    purpose: str,
    schema: type[T],
    system: str | Sequence[str] | None,
    messages: list[dict],
    *,
    model: str,
    effort: str,
    max_tokens: int,
) -> tuple[T, dict[str, int], int]:
    """구조화 출력(output_config.format) 한 번 → (schema 값, 토큰, 비용). 거절 · 잘림 · 꼴 틀림은 LLMBadOutput."""
    from anthropic import transform_schema

    req: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": transform_schema(schema)},
        },
    }
    blocks = _system_blocks(system)
    if blocks:
        req["system"] = blocks
    msg, call = await _create(purpose, purpose, req)
    stop = msg.stop_reason or "end_turn"
    error = stop if stop in BAD_STOPS else None
    out: T | None = None
    if error is None:
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            out = schema.model_validate_json(text)
        except ValidationError:
            error = "invalid_output"
    u = _usage_of(msg)
    cost = await _sink(call, msg.model or model, u, error)
    if out is None:
        raise LLMBadOutput(f"{call.purpose} 답 꼴 틀림({error})")
    return out, u, cost


# ── 공개 함수 ─────────────────────────────────────────────────


async def structured[T: BaseModel](
    role: Role, schema: type[T], messages: list[tuple[str, str]]
) -> T:
    """messages(("system" | "user", 글))를 보내고 schema 모양으로 받는다."""
    if not _SCRIPT.on and not settings.llm_live:
        return _stub(role, schema)
    if settings.llm_provider == "openai" and not _SCRIPT.on:
        return await _openai_structured(role, schema, messages)
    name, effort = claude_model_for(role)
    system = [t for r, t in messages if r == "system"]
    convo = [{"role": r, "content": t} for r, t in messages if r != "system"]
    out, u, cost = await _json_call(
        role, schema, system, convo, model=name, effort=effort, max_tokens=8000
    )
    if USAGE_HOOK is not None:  # 토큰 수(캐시 읽기 포함)만 넘겨요
        USAGE_HOOK(
            {
                "role": role,
                "model": name,
                "input": _prompt_tokens(u),
                "cached": u.get("cache_read", 0),
                "output": u.get("output", 0),
                "reasoning": u.get("thinking", 0),
                "cost_micros": cost,
            }
        )
    return out


async def claude_json[T: BaseModel](
    purpose: Purpose,
    schema: type[T],
    system: str | Sequence[str] | None,
    messages: str | list[dict],
    *,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int = 2048,
) -> T:
    """짧은 구조화 답 한 번(문장 · 분류 · 기억 · 판정). 모델은 목적에 맞게(기본 Haiku, 판정 Opus).

    messages가 글이면 user 한 줄로 보낸다. 꺼져 있으면 LLMOff, 상한이면 OverBudget,
    공급자 오류 · 거절 · 잘림 · 꼴 틀림이면 LLMError. 생각(thinking)도 max_tokens 안에서 쓴다.
    공급자가 openai면 OpenAI Responses 구조화 출력으로 보낸다(_oa_json, 꼴 · 오류는 같다).
    """
    msgs = [{"role": "user", "content": messages}] if isinstance(messages, str) else list(messages)
    if _oa_route(purpose, purpose):
        got, _, _ = await _oa_json(
            purpose, schema, system, msgs, model=model, effort=effort, max_tokens=max_tokens
        )
        return got
    name, eff = claude_model_for(purpose)
    out, _, _ = await _json_call(
        purpose,
        schema,
        system,
        msgs,
        model=model or name,
        effort=effort or eff,
        max_tokens=max_tokens,
    )
    return out


class _CallbackError(Exception):
    """on_text가 낸 오류를 LLM 실패와 나눠 그대로 다시 낸다."""

    def __init__(self, error: Exception) -> None:
        super().__init__("on_text 실패")
        self.error = error


async def claude_stream(
    system: str | Sequence[str] | Sequence[dict] | None,
    messages: list[dict],
    *,
    tools: Sequence[dict] = (),
    on_text: Callable[[str], Awaitable[None]] | None = None,
    purpose: Purpose | None = None,
    model: str | None = None,
    effort: str | None = None,
    thinking: dict | None = None,
    tool_choice: dict | None = None,
    max_tokens: int = 8000,
    container: str | None = None,
    on_block: Callable[[str, str | None], Awaitable[None]] | None = None,
    on_block_end: Callable[[dict], Awaitable[None]] | None = None,
) -> ClaudeReply:
    """Claude 한 번을 스트림으로 부른다(비서 턴의 LLM 1회). 글 조각은 받는 대로 on_text로 넘긴다.

    messages는 Claude 꼴 그대로(role: user · assistant · system, 앞 응답의 ClaudeReply.content 포함)다.
    캐시: 도구(이름순, 끝에 cache_control) → 지시문(끝 블록에 cache_control) → 대화 끝(자동 캐시).
    tool_choice는 기본 auto다(Sonnet 5.5 · Opus 5.5는 any · tool이 400). thinking을 끄려면 Sonnet 5.5는
    {"type": "between_tools"}(disabled는 400). 목적은 인자 > CALL_CTX > assistant 순으로 정한다.
    꺼져 있으면 LLMOff, 상한이면 OverBudget, 공급자 오류 · 끊김이면 LLMError(요청 자체가 틀렸으면 LLMRejected).
    on_text 오류는 그대로 낸다. 거절 · 잘림이어도 오류를 내지 않고 stop으로 알린다(부르는 쪽이 무료 모드 · 끊긴 문장
    버리기를 정한다).
    container: pause_turn을 이을 때 앞 응답의 코드 실행 컨테이너(웹 도구 동적 거르기). on_block: 블록이 시작될
    때마다 (블록 종류, 서버 도구 이름)을 넘긴다(조사 진행 단계). on_block_end: 블록이 끝날 때마다 다 모인 블록
    (dict, 서버 도구 입력 포함)을 넘긴다(조사 진행 기록: 검색어 · 읽은 곳). 두 알림의 오류도 그대로 낸다.
    공급자가 openai면 도면 읽기 말고는 OpenAI Responses 스트림으로 보낸다(_oa_stream, 꼴 · 알림 · 오류는 같다).
    """
    if _oa_route(purpose, "assistant"):
        return await _oa_stream(
            system,
            messages,
            tools=tools,
            on_text=on_text,
            purpose=purpose,
            model=model,
            effort=effort,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            on_block=on_block,
            on_block_end=on_block_end,
        )
    client = _claude()
    call = await _guard(purpose, "assistant")
    default_model, default_effort = claude_model_for(call.purpose)
    name = model or default_model
    req: dict[str, Any] = {
        "model": name,
        "max_tokens": max_tokens,
        "messages": list(messages),
        "output_config": {"effort": effort or default_effort},
        "cache_control": {"type": "ephemeral"},  # 늘어나는 대화 끝(자동 캐시)
    }
    blocks = _system_blocks(system)
    if blocks:
        req["system"] = blocks
    claude_tools = to_claude_tools(tools)
    if claude_tools:
        req["tools"] = claude_tools
        req["tool_choice"] = tool_choice or {"type": "auto"}
    if thinking is not None:
        req["thinking"] = thinking
    if container:
        req["container"] = container
    seen: dict[str, int] = {}  # 끊겼을 때 장부에 남길 만큼(시작 때 입력 · 지금까지 출력)
    try:
        async with client.messages.stream(**req) as stream:
            async for ev in stream:
                if ev.type == "message_start":
                    seen = _usage_of(ev.message)
                elif ev.type == "message_delta" and getattr(ev, "usage", None) is not None:
                    seen["output"] = ev.usage.output_tokens or 0
                elif ev.type == "text" and on_text is not None:
                    try:
                        await on_text(ev.text)
                    except Exception as e:
                        raise _CallbackError(e) from e
                elif ev.type == "content_block_start" and on_block is not None:
                    b = ev.content_block
                    try:
                        await on_block(b.type, getattr(b, "name", None))
                    except Exception as e:
                        raise _CallbackError(e) from e
                elif ev.type == "content_block_stop" and on_block_end is not None:
                    done = _block_out(ev.content_block) if hasattr(ev, "content_block") else None
                    if done is not None:
                        try:
                            await on_block_end(done)
                        except Exception as e:
                            raise _CallbackError(e) from e
            msg = await stream.get_final_message()
    except _CallbackError as e:
        await _sink(call, name, seen, "callback")
        raise e.error from None
    except asyncio.CancelledError:  # 턴 시간 상한 등으로 끊김: 쓴 만큼 남기고 그대로 끊는다
        # 첫 이벤트(입력 토큰) 전에 끊겼으면 입력만 보수적 추정치로(출력은 아직 없다)
        used, why = (seen, "cancelled") if seen else (estimate(req, output=False), ESTIMATED)
        await asyncio.shield(_sink(call, name, used, why))
        raise
    except Exception as e:  # 공급자 오류 · 시간 초과 · 끊김. 입력값은 남기지 않음
        await _sink(call, name, seen, _kind(e))
        raise _failed(call.purpose, e) from e
    stop = msg.stop_reason or "end_turn"
    error = stop if stop in BAD_STOPS else None
    u = _usage_of(msg)
    cost = await _sink(call, msg.model or name, u, error)
    calls = (
        []
        if error
        else [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in msg.content
            if b.type == "tool_use"
        ]
    )
    box = getattr(msg, "container", None)
    return ClaudeReply(
        text="".join(b.text for b in msg.content if b.type == "text"),
        content=_blocks_out(msg.content),
        tool_calls=calls,
        stop=stop,
        usage=u,
        cost_micros=cost,
        model=msg.model or name,
        container=box.id if box is not None else None,
    )


CHAT_STUB_TEXT = "지금은 AI 답변을 쓸 수 없어요. 버튼으로 이어서 진행해 주세요."


def _parts(content: Any) -> list[dict]:
    """v2 글 · 조각([{type: text, text} | {type: image, data}]) → Claude 블록. 빈 글은 뺀다."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else []
    out: list[dict] = []
    for p in content or []:
        if p.get("type") == "image":
            src = {"type": "base64", "media_type": "image/jpeg", "data": p["data"]}
            out.append({"type": "image", "source": src})
        elif str(p.get("text") or "").strip():
            out.append({"type": "text", "text": p["text"]})
    return out


def _from_v2(messages: list[dict]) -> tuple[list[dict], set[str]]:
    """v2 대화 꼴(user · assistant(+tool_calls) · tool) → (Claude messages, 앞서 부른 도구 이름).

    v2는 글과 도구 호출만 저장해 생각(thinking) 블록을 다시 보내지 않는다(빼고 보내도 되는 길이고 그 추론만 빠진다).
    같은 역할이 이어지면 한 메시지로 합치고(도구 결과가 먼저), 빈 assistant와 맨 앞 assistant는 뺀다.
    """
    out: list[dict] = []
    used: set[str] = set()

    def push(role: str, blocks: list[dict]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        role = m.get("role")
        if role == "assistant":
            blocks = _parts(m.get("content"))
            for c in m.get("tool_calls") or []:
                call = {"type": "tool_use", "id": c["id"], "name": c["name"]}
                blocks.append({**call, "input": c.get("arguments") or {}})
                used.add(c["name"])
            push("assistant", blocks)
        elif role == "tool":
            content = m.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            tool_id = m.get("tool_call_id") or ""
            push("user", [{"type": "tool_result", "tool_use_id": tool_id, "content": content}])
        else:
            push("user", _parts(m.get("content")))
    # Claude는 user로 시작해야 한다(지난 대화가 답부터 잘렸을 때)
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out, used


async def chat_tools(system: str, messages: list[dict], tools: list[dict]) -> dict:
    """대화 한 번(도구 부르기 포함). 도구는 부르는 쪽이 실행하고 결과를 messages에 붙여 다시 부른다.

    messages: [{role: user | assistant | tool, content: 글 | [{type: text, text} | {type: image, data}],
    tool_calls?: [{id, name, arguments}], tool_call_id?}], tools: [{name, description, parameters}].
    돌려주는 것: {text, tool_calls: [{id, name, arguments}], stop: tool_calls | stop | refusal,
    usage: {input, cached, output, cost_micros}} (usage는 비용 기록용, 모르면 0).
    tools가 비었는데 앞서 도구를 불렀으면 그 이름만 적은 도구를 두고 tool_choice none으로 막는다
    (Claude는 도구 기록이 있으면 도구 정의가 있어야 한다).
    """
    if not _SCRIPT.on and not settings.llm_live:
        return {
            "text": CHAT_STUB_TEXT,
            "tool_calls": [],
            "stop": "stop",
            "usage": {"input": 0, "cached": 0, "output": 0},
        }
    if settings.llm_provider == "openai" and not _SCRIPT.on:
        return await _openai_chat_tools(system, messages, tools)
    name, effort = claude_model_for("v2_chat")
    convo, used = _from_v2(messages)
    req: dict[str, Any] = {
        "model": name,
        "max_tokens": 8000,
        "messages": convo,
        "output_config": {"effort": effort},
        "cache_control": {"type": "ephemeral"},  # 한 턴 안 도구 루프에서 앞 대화를 다시 읽는다
    }
    blocks = _system_blocks(system)
    if blocks:
        req["system"] = blocks
    claude_tools = to_claude_tools(tools)
    known = {t["name"] for t in tools}
    old = [
        {
            "name": n,
            "description": "이 대화에서 앞서 쓴 도구예요. 지금은 부르지 않아요.",
            "input_schema": {"type": "object", "properties": {}},
        }
        for n in sorted(used - known)
    ]
    if claude_tools or old:
        req["tools"] = claude_tools + old
        req["tool_choice"] = {"type": "auto"} if claude_tools else {"type": "none"}
    msg, call = await _create("v2_chat", "v2_chat", req)
    stop = msg.stop_reason or "end_turn"
    error = stop if stop in BAD_STOPS else None
    u = _usage_of(msg)
    cost = await _sink(call, msg.model or name, u, error)
    calls = (
        []
        if error
        else [
            {"id": b.id, "name": b.name, "arguments": b.input or {}}
            for b in msg.content
            if b.type == "tool_use"
        ]
    )
    return {
        "text": "".join(b.text for b in msg.content if b.type == "text"),
        "tool_calls": calls,
        "stop": "tool_calls" if calls else "refusal" if stop == "refusal" else "stop",
        "usage": {
            "input": _prompt_tokens(u),
            "cached": u.get("cache_read", 0),
            "output": u.get("output", 0),
            "cost_micros": cost,
        },
    }


# ── OpenAI 길(LLM_PROVIDER=openai, 되돌리기용) ───────────────────


def _openai_tokens(raw: Any) -> dict[str, int]:
    """LangChain usage_metadata → 장부 토큰(OpenAI 입력 토큰은 캐시 읽기를 포함한다)."""
    um = getattr(raw, "usage_metadata", None) or {}
    total = int(um.get("input_tokens") or 0)
    cached = int((um.get("input_token_details") or {}).get("cache_read") or 0)
    return {
        "input": max(total - cached, 0),
        "cache_read": cached,
        "output": int(um.get("output_tokens") or 0),
    }


async def _openai_structured[T: BaseModel](
    role: Role, schema: type[T], messages: list[tuple[str, str]]
) -> T:
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
    ).with_structured_output(schema, method="json_schema", strict=True, include_raw=True)
    call = await _guard(role, role)
    out: dict = {}
    try:  # 공급자 오류 · 시간 초과 · 모양 틀림을 한곳에서 LLMError로. 입력값은 남기지 않음
        out = await model.ainvoke(messages)
        if out.get("parsing_error") is not None or out.get("parsed") is None:
            raise ValueError("모양 틀림")
        parsed = schema.model_validate(out["parsed"])
    except Exception as e:
        await _sink(call, name, _openai_tokens(out.get("raw")), _kind(e))
        raise LLMError(f"{role} 호출 실패") from e
    await _sink(call, name, _openai_tokens(out.get("raw")))
    if USAGE_HOOK is not None:  # 토큰 수(캐시 읽기 포함)만 넘겨요
        USAGE_HOOK(_usage(role, name, out.get("raw")))
    return parsed


async def _openai_chat_tools(system: str, messages: list[dict], tools: list[dict]) -> dict:
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
    call = await _guard("v2_chat", "v2_chat")
    try:  # 공급자 오류 · 시간 초과를 한곳에서 LLMError로. 입력값은 남기지 않음
        r = await model.ainvoke(msgs)
    except Exception as e:
        await _sink(call, settings.openai_agent_model, {}, _kind(e))
        raise LLMError("chat 호출 실패") from e
    tokens = _openai_tokens(r)
    cost = await _sink(call, settings.openai_agent_model, tokens)
    calls = [
        {"id": c.get("id") or "", "name": c["name"], "arguments": c.get("args") or {}}
        for c in r.tool_calls
    ]
    text = r.content if isinstance(r.content, str) else r.text
    refusal = r.additional_kwargs.get("refusal")
    if refusal and not text:
        text = refusal
    stop = "tool_calls" if calls else "refusal" if refusal else "stop"
    usage = {
        "input": tokens["input"] + tokens["cache_read"],
        "cached": tokens["cache_read"],
        "output": tokens["output"],
        "cost_micros": cost,
    }
    return {"text": text or "", "tool_calls": calls, "stop": stop, "usage": usage}


# ── OpenAI Responses 길(LLM_PROVIDER=openai): 비서 · 조사 · 기억 · 먼저 권하기 · 업체 문장 ─────────
# claude_stream · claude_json을 OpenAI Responses API로 보낸다(2026-11-23 사용자 결정 '도면 읽기 빼고 다'). 부르는 쪽은
# Claude 꼴(messages · 도구 정의 · 답 블록)을 그대로 쓰고 여기서 두 꼴을 바꾼다. 도면 읽기(OPENAI_SKIP)는 옮기지 않아
# OpenAI 길에서는 꺼진다(LLMOff → 공공 링크만).
# - 웹 도구(Claude web_search · web_fetch)는 OpenAI web_search 하나로 바꾸고, 그 부름(web_search_call)을 Claude 서버
#   도구 블록 꼴(server_tool_use + web_search_tool_result · web_fetch_tool_result)로 돌려준다(조사 진행 기록 · 링크
#   뽑기가 그대로 읽는다). OpenAI는 막을 곳(blocked_domains)을 받지 않아 지시문에 적고, 링크 · 기록에서는 부르는 쪽
#   코드가 거른다. 가져온 글은 오지 않는다(숫자 근거는 목표 · 집 조건뿐이라 근거 없는 숫자 문장은 빠진다).
# - 생각(reasoning) 항목은 다음 요청에 보내지 않는다(store=false, 앞 응답 id를 쓰지 않음). 그림은 data URL로 보낸다.
# - 꼴은 openai SDK 2.54.0 형(types/responses)을 따랐다. 가격은 usage/prices.py.
OPENAI_SKIP = frozenset({"floorplan"})
# 부르는 쪽이 준 Claude effort → OpenAI 추론 강도
OPENAI_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
OA_TIMEOUT = 90  # 초. 웹 검색이 도는 동안 조각이 뜸할 수 있다(부르는 쪽 시간 제한이 먼저 끊는다)
OA_WEB_TOOL = {
    "type": "web_search",
    "search_context_size": "medium",
    "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"},
}
OA_INCLUDE = ["web_search_call.action.sources"]  # 검색이 본 페이지 주소(조사 진행 기록 · 링크)
_OA_ROLES = frozenset({"user", "assistant", "system", "developer"})
_OA_UTM = re.compile(r"([?&])utm_source=openai(&?)")
_oa_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = (
    weakref.WeakKeyDictionary()
)


class _OaFailed(Exception):
    """스트림이 response.failed · error로 끝났다(장부에는 이 종류 이름만 남긴다)."""


def _oa_route(purpose: str | None, default: str) -> bool:
    """이 호출을 OpenAI로 보낼지: 공급자가 openai이고 Claude 시험 대본이 꺼져 있고 옮기지 않은 목적이 아니면."""
    if settings.llm_provider != "openai" or _SCRIPT.on:
        return False
    ctx = CALL_CTX.get()
    return (purpose or (ctx.purpose if ctx else None) or default) not in OPENAI_SKIP


def openai_model_for(purpose: str) -> tuple[str, str]:
    """목적 → (OpenAI 모델, 추론 강도). Claude가 Sonnet · Opus를 쓰는 자리(비서 · 조사 · v2 대화 · 판정 · 무거운
    역할)는 agent 모델, Haiku 자리(짧은 문장 · 분류 · 기억 · OPENAI_LIGHT_ROLES 역할)는 light 모델."""
    light = {r.strip() for r in settings.openai_light_roles.split(",") if r.strip()}
    heavy = (
        purpose == "judge"
        or purpose in MAIN_PURPOSES
        or (purpose in get_args(Role) and purpose not in light)
    )
    if heavy or not settings.openai_light_model:
        return settings.openai_agent_model, settings.openai_reasoning_effort
    return settings.openai_light_model, settings.openai_light_effort


def _oa_pick(purpose: str, model: str | None, effort: str | None) -> tuple[str, str]:
    """목적의 기본 (모델, 강도)에 부르는 쪽 값을 얹는다. Claude 모델 이름은 OpenAI에 없어 쓰지 않는다."""
    name, eff = openai_model_for(purpose)
    if model and not model.startswith("claude"):
        name = model
    if effort:
        eff = OPENAI_EFFORT.get(effort, eff)
    return name, eff


def _openai() -> Any:
    """이 이벤트 루프의 OpenAI 클라이언트. 부를 수 없으면 LLMOff(시험은 이 함수를 바꿔 끼운다)."""
    if not settings.llm_live:
        raise LLMOff("LLM 꺼짐")
    key = settings.openai_api_key.get_secret_value()
    if not key:
        raise LLMOff("OpenAI 키 없음")
    from openai import AsyncOpenAI  # 실호출일 때만 SDK를 불러온다

    loop = asyncio.get_running_loop()
    client = _oa_clients.get(loop)
    if client is None:
        client = _oa_clients[loop] = AsyncOpenAI(api_key=key, timeout=OA_TIMEOUT, max_retries=1)
    return client


def _oa_clean(text: str) -> str:
    """OpenAI가 인용 주소에 붙이는 utm_source=openai를 뗀다(검색 결과 주소와 같은 페이지로 맞추게)."""

    def fix(m: re.Match[str]) -> str:
        lead, tail = m.group(1), m.group(2)
        return ("?" if tail else "") if lead == "?" else tail

    return _OA_UTM.sub(fix, text)


def _oa_instructions(system: str | Sequence[str] | Sequence[dict] | None) -> str:
    """지시문(글 · 글 블록) → instructions 한 덩이."""
    parts = [system] if isinstance(system, str) else list(system or [])
    texts = [p if isinstance(p, str) else str(p.get("text") or "") for p in parts]
    return "\n\n".join(t for t in texts if t.strip())


def _oa_web_note(tools: Sequence[dict]) -> str:
    """웹 도구를 OpenAI web_search 하나로 바꿀 때 지시문 끝에 붙이는 말: 도구 이름 · Claude 도구의 막은 곳."""
    never: set[str] = set()
    closed: set[str] = set()
    for t in tools:
        kind = str(t.get("type") or "")
        if kind.startswith("web_search"):
            never.update(t.get("blocked_domains") or ())
        elif kind.startswith("web_fetch"):
            closed.update(t.get("blocked_domains") or ())
    note = "웹 도구: 검색과 페이지 열기는 모두 web_search 하나로 해(web_fetch는 따로 없어)."
    if never:
        note += f" 이 곳(하위 도메인 포함)은 열지도 인용하지도 마: {', '.join(sorted(never))}."
    if closed - never:
        note += f" 이 곳은 검색 결과로만 보고 열지는 마: {', '.join(sorted(closed - never))}."
    return note


def _oa_text(content: Any) -> str:
    """도구 결과 content(글 · 글 블록 목록) → 글."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text") or "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if content is None else json.dumps(content, ensure_ascii=False, default=str)


def _oa_image(b: dict) -> dict | None:
    src = b.get("source") if isinstance(b.get("source"), dict) else {}
    if src.get("type") == "base64" and src.get("data"):
        url = f"data:{src.get('media_type') or 'image/jpeg'};base64,{src['data']}"
    elif src.get("type") == "url" and src.get("url"):
        url = str(src["url"])
    else:
        return None
    return {"type": "input_image", "image_url": url, "detail": "auto"}


def _oa_flush(out: list[dict], role: str, parts: list[dict]) -> None:
    """모은 글 · 그림 → 메시지 하나(assistant는 글만 한 덩이로)."""
    if not parts:
        return
    if role == "assistant":
        text = "".join(p["text"] for p in parts if p["type"] == "input_text")
        if text.strip():
            out.append({"role": role, "content": text})
    else:
        out.append({"role": role, "content": list(parts)})
    parts.clear()


def _oa_input(messages: Sequence[dict]) -> list[dict]:
    """Claude 꼴 messages → Responses input 항목(차례 그대로).

    글 · 그림은 메시지, tool_use는 function_call, tool_result는 function_call_output이다. 생각 블록 · 서버 도구
    블록(검색 · 가져오기 · 코드 실행)은 OpenAI가 받지 않아 뺀다."""
    out: list[dict] = []
    for m in messages:
        role = str(m.get("role")) if m.get("role") in _OA_ROLES else "user"
        content = m.get("content")
        if isinstance(content, str):
            if content.strip():
                out.append({"role": role, "content": content})
            continue
        parts: list[dict] = []
        for b in content or []:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text" and str(b.get("text") or "").strip():
                parts.append({"type": "input_text", "text": str(b["text"])})
            elif kind == "image" and role != "assistant":
                img = _oa_image(b)
                if img is not None:
                    parts.append(img)
            elif kind == "tool_use":
                _oa_flush(out, role, parts)
                out.append(
                    {
                        "type": "function_call",
                        "call_id": str(b.get("id") or ""),
                        "name": str(b.get("name") or ""),
                        "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False),
                    }
                )
            elif kind == "tool_result":
                _oa_flush(out, role, parts)
                out.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(b.get("tool_use_id") or ""),
                        "output": _oa_text(b.get("content")),
                    }
                )
        _oa_flush(out, role, parts)
    return out


def _oa_tools(tools: Sequence[dict]) -> tuple[list[dict], int]:
    """도구 정의(Claude · OpenAI 함수 꼴) → (Responses 도구, 웹 도구 부름 상한 합. 웹 도구가 없으면 0).

    직접 만든 도구는 함수 도구로 둔다(strict 끔: 스키마를 OpenAI 엄격 꼴로 바꾸지 않고, 입력은 부르는 쪽이 검사한다).
    Claude 웹 검색 · 가져오기는 OpenAI web_search 하나(한국 · 서울 시간대)로 바꾸고, 다른 서버 도구는 뺀다."""
    out: list[dict] = []
    web = 0
    for t in sorted(tools, key=lambda t: str(t.get("name", ""))):
        kind = str(t.get("type") or "")
        if kind.startswith(("web_search", "web_fetch")):
            web += int(t.get("max_uses") or 4)
            continue
        if kind and "input_schema" not in t and "parameters" not in t:
            continue
        schema = (
            t.get("input_schema") or t.get("parameters") or {"type": "object", "properties": {}}
        )
        out.append(
            {
                "type": "function",
                "name": str(t["name"]),
                "description": str(t.get("description") or ""),
                "parameters": schema,
                "strict": False,
            }
        )
    if web:
        out.append(dict(OA_WEB_TOOL))
    return out, web


def _oa_choice(choice: dict | None) -> Any:
    """Claude tool_choice → Responses tool_choice."""
    c = choice or {}
    if c.get("type") == "none":
        return "none"
    if c.get("type") == "any":
        return "required"
    if c.get("type") == "tool" and c.get("name"):
        return {"type": "function", "name": str(c["name"])}
    return "auto"


def _oa_num(obj: Any, key: str) -> int:
    """SDK 값 · dict(형에 없는 새 칸은 dict로 온다)에서 정수 칸 하나. 없으면 0."""
    v = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return int(v or 0)


def _oa_usage(resp: Any, web_calls: int) -> dict[str, int]:
    """Responses usage → 장부 토큰(Claude와 같은 뜻: input은 캐시 밖 입력). OpenAI 입력 토큰은 캐시 읽기 · 쓰기를
    포함한다(2026-11-23 실측: 같은 요청 두 번의 input_tokens가 같고 쓰기 · 읽기만 바뀜). 캐시 쓰기는 30분 · 12시간
    나눔(cache_write_tokens_details)을 짧은 · 긴 칸에 두고, 나눔이 없으면 모두 30분(기본 ttl)으로 본다.
    웹 부름은 열기 · 찾기까지 모두 센다(상한 쪽으로 안전)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return {"web_searches": web_calls}
    det = getattr(u, "input_tokens_details", None)
    cached = _oa_num(det, "cached_tokens")
    wrote = _oa_num(det, "cache_write_tokens")
    split = det.get("cache_write_tokens_details") if isinstance(det, dict) else None
    split = split or getattr(det, "cache_write_tokens_details", None)
    long_ = min(_oa_num(split, "ttl_12h_tokens"), wrote) if split is not None else 0
    od = getattr(u, "output_tokens_details", None)
    return {
        "input": max(_oa_num(u, "input_tokens") - cached - wrote, 0),
        "cache_read": cached,
        "cache_write_5m": wrote - long_,
        "cache_write_1h": long_,
        "output": _oa_num(u, "output_tokens"),
        "web_searches": web_calls,
        "thinking": _oa_num(od, "reasoning_tokens"),
    }


def _oa_estimate(req: dict, output: int = 0) -> dict[str, int]:
    """끊긴 OpenAI 호출의 보수적 추정 토큰: 입력은 보낸 글자 수, 출력은 받은 글자 수(모르면 0)."""
    sent = {
        "system": req.get("instructions"),
        "messages": req.get("input"),
        "tools": req.get("tools"),
        "output_config": req.get("text"),
    }
    return {"input": estimate(sent, output=False)["input"], "output": output}


def _oa_failed(purpose: str, e: BaseException) -> LLMError:
    """OpenAI 오류 → LLMError. 요청 자체가 틀렸으면(REJECTED_STATUS) LLMRejected. 입력값은 남기지 않는다."""
    from openai import APIStatusError

    if isinstance(e, APIStatusError) and e.status_code in REJECTED_STATUS:
        return LLMRejected(f"{purpose} 요청 거절({e.status_code})")
    return LLMError(f"{purpose} 호출 실패")


def _oa_stop(resp: Any, refused: bool, called: bool) -> str:
    """Responses 끝 → Claude stop 이름(refusal · max_tokens · tool_use · end_turn)."""
    if refused:
        return "refusal"
    if getattr(resp, "status", None) == "incomplete":
        why = getattr(getattr(resp, "incomplete_details", None), "reason", None)
        return "refusal" if why == "content_filter" else "max_tokens"
    return "tool_use" if called else "end_turn"


def _oa_args(raw: Any) -> dict:
    """함수 부름 인자(JSON 글) → dict. 깨졌으면 빈 dict(부르는 쪽 입력 검사가 고칠 칸을 알려 준다)."""
    try:
        got = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _oa_web_name(action: Any) -> str:
    return (
        "web_fetch"
        if getattr(action, "type", None) in ("open_page", "find_in_page")
        else "web_search"
    )


def _oa_web_blocks(item: Any) -> list[dict]:
    """web_search_call 하나 → Claude 서버 도구 블록(부름 + 결과). find_in_page(연 쪽 안 찾기)는 블록이 없다.

    검색은 검색어(여럿이면 ' / '로) + 본 페이지 주소(제목은 끝에 인용 제목으로 채운다), 페이지 열기는 주소만(OpenAI는
    가져온 글을 주지 않는다). 실패한 부름은 오류 결과다(열기 실패는 열리지 않는 페이지로 센다)."""
    ref = str(getattr(item, "id", "") or "")
    action = getattr(item, "action", None)
    kind = getattr(action, "type", None)
    failed = getattr(item, "status", None) == "failed"
    if kind == "search":
        q = getattr(action, "query", None) or " / ".join(getattr(action, "queries", None) or [])
        sources = getattr(action, "sources", None) or []
        urls = [_oa_clean(str(getattr(s, "url", "") or "")) for s in sources]
        found: Any = (
            {"type": "web_search_tool_result_error", "error_code": "unavailable"}
            if failed
            else [{"type": "web_search_result", "url": u, "title": ""} for u in urls if u]
        )
        return [
            {"type": "server_tool_use", "id": ref, "name": "web_search", "input": {"query": q}},
            {"type": "web_search_tool_result", "tool_use_id": ref, "content": found},
        ]
    url = _oa_clean(str(getattr(action, "url", "") or "")) if kind == "open_page" else ""
    if not url:
        return []
    got = (
        {"type": "web_fetch_tool_error", "error_code": "unavailable"}
        if failed
        else {"type": "web_fetch_result", "url": url, "content": {"type": "document", "title": ""}}
    )
    return [
        {"type": "server_tool_use", "id": ref, "name": "web_fetch", "input": {"url": url}},
        {"type": "web_fetch_tool_result", "tool_use_id": ref, "content": got},
    ]


class _OaTurn:
    """Responses 스트림 한 번 → Claude 꼴 블록 · 도구 부름. 블록 알림(on_block · on_block_end)은 Claude 스트림과 같은
    차례(블록 시작 → 글 조각 → 블록 끝)로 낸다. 알림의 오류는 _CallbackError로 감싼다."""

    def __init__(
        self,
        on_text: Callable[[str], Awaitable[None]] | None,
        on_block: Callable[[str, str | None], Awaitable[None]] | None,
        on_block_end: Callable[[dict], Awaitable[None]] | None,
    ) -> None:
        self.on_text, self.on_block, self.on_block_end = on_text, on_block, on_block_end
        self.content: list[dict] = []
        self.calls: list[dict] = []
        self.refused = False
        self.began = False
        self.web = 0
        self.out_chars = 0
        self.final: Any = None
        self.started: dict[str, str] = {}  # 웹 부름 id → 시작 때 알린 도구 이름
        self.titles: dict[str, str] = {}  # 인용 주소 → 제목

    async def _say(self, fn: Callable[..., Awaitable[None]] | None, *args: Any) -> None:
        if fn is None:
            return
        try:
            await fn(*args)
        except Exception as e:
            raise _CallbackError(e) from e

    async def feed(self, ev: Any) -> None:
        self.began = True
        kind = getattr(ev, "type", "")
        if kind == "response.output_text.delta":
            delta = str(getattr(ev, "delta", "") or "")
            self.out_chars += len(delta)
            if delta:
                await self._say(self.on_text, delta)
        elif kind == "response.output_item.added":
            await self._start(ev.item)
        elif kind == "response.output_item.done":
            await self._done(ev.item)
        elif kind in ("response.completed", "response.incomplete"):
            self.final = ev.response
        elif kind == "response.failed":
            self.final = ev.response
            raise _OaFailed("response_failed")
        elif kind == "error":
            raise _OaFailed("stream_error")

    async def _start(self, item: Any) -> None:
        kind = getattr(item, "type", "")
        if kind == "message":
            await self._say(self.on_block, "text", None)
        elif kind == "function_call":
            await self._say(self.on_block, "tool_use", getattr(item, "name", None))
        elif kind == "web_search_call":
            name = _oa_web_name(getattr(item, "action", None))
            self.started[str(getattr(item, "id", "") or "")] = name
            await self._say(self.on_block, "server_tool_use", name)

    async def _done(self, item: Any) -> None:
        kind = getattr(item, "type", "")
        if kind == "message":
            await self._message(item)
        elif kind == "function_call":
            args = _oa_args(getattr(item, "arguments", None))
            b = {"type": "tool_use", "id": str(item.call_id), "name": str(item.name), "input": args}
            self.content.append(b)
            self.calls.append({"id": b["id"], "name": b["name"], "input": args})
            await self._say(self.on_block_end, b)
        elif kind == "web_search_call":
            self.web += 1
            for b in _oa_web_blocks(item):
                if b["type"] != "server_tool_use":
                    await self._say(self.on_block, b["type"], None)
                elif self.started.get(b["id"]) != b["name"]:  # 시작 때와 다른 일(열기)이었다
                    await self._say(self.on_block, "server_tool_use", b["name"])
                self.content.append(b)
                await self._say(self.on_block_end, b)

    async def _message(self, item: Any) -> None:
        texts: list[str] = []
        for part in getattr(item, "content", None) or []:
            kind = getattr(part, "type", "")
            if kind == "refusal":
                self.refused = True
            elif kind == "output_text":
                texts.append(str(getattr(part, "text", "") or ""))
                for a in getattr(part, "annotations", None) or []:
                    if getattr(a, "type", "") == "url_citation" and getattr(a, "url", None):
                        url = _oa_clean(str(a.url))
                        self.titles.setdefault(url, str(getattr(a, "title", "") or ""))
        text = _oa_clean("".join(texts))
        if text:
            b = {"type": "text", "text": text}
            self.content.append(b)
            await self._say(self.on_block_end, b)

    def finish(self) -> None:
        """인용 제목으로 웹 결과 블록의 빈 제목을 채우고, 결과에 없던 인용 주소는 마지막 웹 결과 뒤에 결과 블록 하나로
        더한다(링크 뽑기용. 진행 기록에는 넣지 않고, 끝 정리 글은 여전히 마지막 서버 블록 뒤에 온다)."""
        if not self.titles:
            return
        seen: set[str] = set()
        last = -1
        for i, b in enumerate(self.content):
            c = b.get("content")
            if b["type"] == "web_search_tool_result" and isinstance(c, list):
                for r in c:
                    seen.add(r["url"])
                    r["title"] = r.get("title") or self.titles.get(r["url"], "")
            elif b["type"] == "web_fetch_tool_result" and isinstance(c, dict):
                doc = c.get("content")
                if c.get("type") == "web_fetch_result" and isinstance(doc, dict):
                    seen.add(str(c.get("url")))
                    doc["title"] = doc.get("title") or self.titles.get(str(c.get("url")), "")
            if b["type"] != "text":
                last = i
        extra = [
            {"type": "web_search_result", "url": u, "title": t}
            for u, t in self.titles.items()
            if u not in seen
        ]
        if extra:
            block = {"type": "web_search_tool_result", "tool_use_id": "oa_cited", "content": extra}
            self.content.insert(last + 1, block)


async def _oa_stream(
    system: str | Sequence[str] | Sequence[dict] | None,
    messages: list[dict],
    *,
    tools: Sequence[dict],
    on_text: Callable[[str], Awaitable[None]] | None,
    purpose: Purpose | None,
    model: str | None,
    effort: str | None,
    tool_choice: dict | None,
    max_tokens: int,
    on_block: Callable[[str, str | None], Awaitable[None]] | None,
    on_block_end: Callable[[dict], Awaitable[None]] | None,
) -> ClaudeReply:
    """claude_stream의 OpenAI 길(답 꼴 · 오류 · 장부는 Claude 길과 같다). thinking · container는 Claude 값이라 뺀다."""
    client = _openai()
    call = await _guard(purpose, "assistant")
    name, eff = _oa_pick(call.purpose, model, effort)
    oa_tools, web = _oa_tools(tools)
    req: dict[str, Any] = {
        "model": name,
        "input": _oa_input(messages),
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": eff},
        "store": False,
        "stream": True,
        "prompt_cache_key": f"mitjip-{call.purpose}",
    }
    note = _oa_web_note(tools) if web else ""
    instructions = "\n\n".join(x for x in (_oa_instructions(system), note) if x)
    if instructions:
        req["instructions"] = instructions
    if oa_tools:
        req["tools"] = oa_tools
        req["tool_choice"] = _oa_choice(tool_choice)
    if web:
        req["include"] = OA_INCLUDE
        req["max_tool_calls"] = web
    turn = _OaTurn(on_text, on_block, on_block_end)
    try:
        stream = await client.responses.create(**req)
        async with stream:
            async for ev in stream:
                await turn.feed(ev)
    except _CallbackError as e:
        await _sink(call, name, _oa_estimate(req, turn.out_chars), "callback")
        raise e.error from None
    except asyncio.CancelledError:  # 턴 시간 상한 등으로 끊김: 보수적 추정치를 남기고 그대로 끊는다
        await asyncio.shield(_sink(call, name, _oa_estimate(req, turn.out_chars), ESTIMATED))
        raise
    except _OaFailed as e:
        usage = getattr(turn.final, "usage", None)
        used = _oa_usage(turn.final, turn.web) if usage else _oa_estimate(req, turn.out_chars)
        await _sink(call, name, used, str(e))
        raise LLMError(f"{call.purpose} 호출 실패") from None
    except Exception as e:  # 공급자 오류 · 시간 초과 · 끊김. 입력값은 남기지 않음
        used = _oa_estimate(req, turn.out_chars) if turn.began else {}
        await _sink(call, name, used, _kind(e))
        raise _oa_failed(call.purpose, e) from e
    resp = turn.final
    if resp is None:  # 끝 알림 없이 스트림이 닫혔다
        await _sink(call, name, _oa_estimate(req, turn.out_chars), "no_final")
        raise LLMError(f"{call.purpose} 호출 실패")
    stop = _oa_stop(resp, turn.refused, bool(turn.calls))
    error = stop if stop in BAD_STOPS else None
    u = _oa_usage(resp, turn.web)
    got = str(getattr(resp, "model", None) or name)
    cost = await _sink(call, got, u, error)
    turn.finish()
    return ClaudeReply(
        text="".join(b["text"] for b in turn.content if b["type"] == "text"),
        content=turn.content,
        tool_calls=[] if error else turn.calls,
        stop=stop,
        usage=u,
        cost_micros=cost,
        model=got,
    )


def _oa_format(schema: type[BaseModel]) -> dict:
    """pydantic 모델 → Responses json_schema 꼴(엄격). 엄격 꼴로 못 바꾸면 꼴만 알려 주고 받은 뒤 검사한다."""
    name = re.sub(r"[^A-Za-z0-9_-]", "_", schema.__name__)[:64] or "answer"
    try:
        # SDK의 responses.parse가 쓰는 바꾸기(모든 칸 required · additionalProperties false)
        from openai.lib._pydantic import to_strict_json_schema

        return {
            "type": "json_schema",
            "name": name,
            "schema": to_strict_json_schema(schema),
            "strict": True,
        }
    except Exception:  # noqa: BLE001 - 엄격 꼴이 안 되는 스키마도 꼴 검사(model_validate_json)는 한다
        return {
            "type": "json_schema",
            "name": name,
            "schema": schema.model_json_schema(),
            "strict": False,
        }


async def _oa_json[T: BaseModel](
    purpose: str,
    schema: type[T],
    system: str | Sequence[str] | None,
    messages: list[dict],
    *,
    model: str | None,
    effort: str | None,
    max_tokens: int,
) -> tuple[T, dict[str, int], int]:
    """claude_json의 OpenAI 길: json_schema 구조화 출력 한 번 → (schema 값, 토큰, 비용).
    거절 · 잘림 · 꼴 틀림은 LLMBadOutput, 공급자 실패(failed)는 LLMError."""
    client = _openai()
    call = await _guard(purpose, purpose)
    name, eff = _oa_pick(call.purpose, model, effort)
    req: dict[str, Any] = {
        "model": name,
        "input": _oa_input(messages),
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": eff},
        "store": False,
        "text": {"format": _oa_format(schema)},
        "prompt_cache_key": f"mitjip-{call.purpose}",
    }
    instructions = _oa_instructions(system)
    if instructions:
        req["instructions"] = instructions
    try:
        resp = await client.responses.create(**req)
    except asyncio.CancelledError:
        await asyncio.shield(_sink(call, name, _oa_estimate(req, max_tokens), ESTIMATED))
        raise
    except Exception as e:  # 공급자 오류 · 시간 초과. 입력값은 남기지 않음
        await _sink(call, name, {}, _kind(e))
        raise _oa_failed(call.purpose, e) from e
    got = str(getattr(resp, "model", None) or name)
    u = _oa_usage(resp, 0)
    if getattr(resp, "status", None) == "failed":
        await _sink(call, got, u, "response_failed")
        raise LLMError(f"{call.purpose} 호출 실패")
    refused = any(
        getattr(p, "type", "") == "refusal"
        for it in getattr(resp, "output", None) or []
        if getattr(it, "type", "") == "message"
        for p in getattr(it, "content", None) or []
    )
    stop = _oa_stop(resp, refused, False)
    error = stop if stop in BAD_STOPS else None
    out: T | None = None
    if error is None:
        try:
            out = schema.model_validate_json(str(getattr(resp, "output_text", "") or ""))
        except ValidationError:
            error = "invalid_output"
    cost = await _sink(call, got, u, error)
    if out is None:
        raise LLMBadOutput(f"{call.purpose} 답 꼴 틀림({error})")
    return out, u, cost


def _stub[T: BaseModel](role: Role, schema: type[T]) -> T:
    stub = _stubs.get(role)
    try:
        return schema.model_validate(stub.model_dump()) if stub else schema()
    except ValidationError as e:
        raise LLMError(f"{role} 스텁 없음") from e
