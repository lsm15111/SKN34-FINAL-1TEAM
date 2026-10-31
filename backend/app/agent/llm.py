"""LLM SDK를 부르는 유일한 곳 (AGENTS.md 4장). 공급자는 Anthropic Claude.

- LLM_LIVE=false면 부르지 않고 LlmError("stub")를 낸다. 부른 쪽은 계산 결과만 보여 준다.
- 출력은 Pydantic 스키마로 받는다(구조화 출력). 거절 · 잘림 · 형식 오류도 LlmError다.
- 역할(router · expert · plan · sourcing · judge)마다 모델 · 생각 깊이를 따로 둘 수 있다 (config).
  judge는 평가(evaluation/)의 판정용이다.
- parse_batch: 같은 일을 Batch로 한꺼번에 낸다 (50% 할인, 24시간 안에 끝남). 평가 실행용이다.
- 로그에는 오류 종류와 사용량(역할 · 모델 · 토큰 · 시간)만 남기고 입력 · 출력 내용은 남기지 않는다.
"""

import asyncio
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

# 안전 분류기가 거절하면 서버가 다른 모델로 이어 받게 할 수 있는 모델
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
ROLES = ("router", "expert", "plan", "sourcing", "judge")
# Batch 요청 id 규칙 (API): 영문 · 숫자 · _ · - 64자 이하, 묶음 안에서 겹치지 않는다
_CUSTOM_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
BATCH_POLL_S = 30.0
BATCH_WAIT_S = 24 * 3600.0  # Batch는 24시간 안에 끝난다 (못 끝낸 요청은 expired)


class LlmError(Exception):
    """LLM 결과를 쓸 수 없음. reason은 로그 · 평가용 짧은 이름이다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    ms: int
    role: str = "default"


_client: anthropic.AsyncAnthropic | None = None


def _get() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        try:
            _client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key or None,
                timeout=settings.llm_timeout_s,
                max_retries=2,
            )
        except anthropic.AnthropicError as exc:
            raise _fail("no_key", exc) from exc
    return _client


def _fail(reason: str, exc: Exception) -> LlmError:
    log.warning("LLM 호출 실패: %s (%s)", reason, type(exc).__name__)
    return LlmError(reason)


def pick(role: str = "default") -> tuple[str, str]:
    """역할의 (모델, 생각 깊이). 역할 설정이 비어 있으면 LLM_MODEL · LLM_EFFORT를 쓴다."""
    if role == "default":
        return settings.llm_model, settings.llm_effort
    if role not in ROLES:
        raise ValueError(f"모르는 LLM 역할이에요: {role}")
    return (
        getattr(settings, f"llm_model_{role}") or settings.llm_model,
        getattr(settings, f"llm_effort_{role}") or settings.llm_effort,
    )


def _usage(r, started: float, role: str) -> Usage:
    u = r.usage
    usage = Usage(
        model=r.model,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=u.cache_read_input_tokens or 0,
        cache_write_tokens=u.cache_creation_input_tokens or 0,
        ms=int((time.perf_counter() - started) * 1000),
        role=role,
    )
    log.info(
        "LLM 사용량 role=%s model=%s in=%d out=%d cache_read=%d cache_write=%d ms=%d",
        usage.role,
        usage.model,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        usage.ms,
    )
    return usage


def _fallbacks(model: str) -> dict:
    if model not in _FALLBACK_MODELS:
        return {}
    return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


async def parse[T: BaseModel](
    system: str,
    user: str,
    schema: type[T],
    *,
    role: str = "default",
    live: bool | None = None,
    effort: str | None = None,
) -> tuple[T, Usage]:
    """시스템 프롬프트(캐시) + 사용자 글 하나로 부르고, 스키마에 맞는 결과만 돌려준다."""
    model, role_effort = pick(role)
    if not (settings.llm_live if live is None else live):
        raise LlmError("stub")
    started = time.perf_counter()
    try:
        r = await _get().beta.messages.parse(
            model=model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": effort or role_effort},
            **_fallbacks(model),
        )
    except anthropic.RateLimitError as exc:
        raise _fail("rate_limit", exc) from exc
    except anthropic.APIStatusError as exc:
        raise _fail(f"http_{exc.status_code}", exc) from exc
    except anthropic.APIConnectionError as exc:  # 시간 초과 포함
        raise _fail("connection", exc) from exc
    except ValidationError as exc:
        raise _fail("schema", exc) from exc
    if r.stop_reason != "end_turn" or r.parsed_output is None:
        raise LlmError(r.stop_reason or "no_output")
    return r.parsed_output, _usage(r, started, role)


async def chat(messages: list[dict], *, effort: str | None = None) -> tuple[str, list, Usage]:
    """시스템 프롬프트 없이 대화를 보내고 글로 받는다. 평가의 'Claude에게 그냥 묻기' 기준선 전용.

    다음 턴에 이어 보내려면 돌려준 content(생각 블록 포함)를 assistant 차례에 그대로 넣는다.
    """
    model = settings.llm_model
    started = time.perf_counter()
    try:
        r = await _get().beta.messages.create(
            model=model,
            max_tokens=16000,
            messages=messages,
            output_config={"effort": effort or settings.llm_effort},
            **_fallbacks(model),
        )
    except anthropic.RateLimitError as exc:
        raise _fail("rate_limit", exc) from exc
    except anthropic.APIStatusError as exc:
        raise _fail(f"http_{exc.status_code}", exc) from exc
    except anthropic.APIConnectionError as exc:
        raise _fail("connection", exc) from exc
    if r.stop_reason != "end_turn":
        raise LlmError(r.stop_reason or "no_output")
    text = "".join(b.text for b in r.content if b.type == "text")
    return text, list(r.content), _usage(r, started, "default")


# ---------------------------------------------------------------- Batch (평가 실행용)
def _batch_params(system: str, user: str, schema: type[BaseModel], model: str, effort: str) -> dict:
    """parse와 같은 요청. Batch에서는 서버 쪽 다른 모델 이어 받기를 쓰지 않는다 (거절은 그 줄의 오류)."""
    return {
        "model": model,
        "max_tokens": 16000,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)},
        },
    }


async def _batch_api(call):
    try:
        return await call
    except anthropic.RateLimitError as exc:
        raise _fail("rate_limit", exc) from exc
    except anthropic.APIStatusError as exc:
        raise _fail(f"http_{exc.status_code}", exc) from exc
    except anthropic.APIConnectionError as exc:  # 시간 초과 포함
        raise _fail("connection", exc) from exc


async def submit_batch(
    items: Sequence[tuple[str, str, str]],
    schema: type[BaseModel],
    *,
    role: str = "default",
    live: bool | None = None,
    effort: str | None = None,
) -> str:
    """(custom_id, 시스템 프롬프트, 사용자 글) 묶음을 Batch로 내고 Batch id를 돌려준다."""
    model, role_effort = pick(role)
    if not (settings.llm_live if live is None else live):
        raise LlmError("stub")
    ids = [cid for cid, _, _ in items]
    if not ids or len(set(ids)) != len(ids) or not all(_CUSTOM_ID.fullmatch(i) for i in ids):
        raise ValueError("Batch 요청 id는 겹치지 않는 영문 · 숫자 · _ · - 64자 이하예요")
    requests = [
        {"custom_id": cid, "params": _batch_params(s, u, schema, model, effort or role_effort)}
        for cid, s, u in items
    ]
    b = await _batch_api(_get().messages.batches.create(requests=requests))
    log.info("LLM Batch 제출 role=%s model=%s 요청=%d id=%s", role, model, len(requests), b.id)
    return b.id


async def wait_batch(
    batch_id: str, *, poll_s: float = BATCH_POLL_S, max_wait_s: float = BATCH_WAIT_S
) -> None:
    """Batch가 끝날 때까지 기다린다. 너무 오래 걸리면 LlmError("batch_timeout") (id로 다시 받는다)."""
    started = time.monotonic()
    while True:
        b = await _batch_api(_get().messages.batches.retrieve(batch_id))
        if b.processing_status == "ended":
            return
        if time.monotonic() - started >= max_wait_s:
            raise LlmError("batch_timeout")
        await asyncio.sleep(poll_s)


def _batch_row[T: BaseModel](result, schema: type[T], role: str) -> tuple[T, Usage] | LlmError:
    if result.type != "succeeded":
        kind = result.error.error.type if result.type == "errored" else result.type
        return LlmError(f"batch_{kind}")
    msg = result.message
    if msg.stop_reason != "end_turn":
        return LlmError(msg.stop_reason or "no_output")
    try:
        out = schema.model_validate_json("".join(b.text for b in msg.content if b.type == "text"))
    except ValidationError:
        return LlmError("schema")
    u = msg.usage
    usage = Usage(
        model=msg.model,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=u.cache_read_input_tokens or 0,
        cache_write_tokens=u.cache_creation_input_tokens or 0,
        ms=0,  # Batch는 줄마다 걸린 시간을 알 수 없다
        role=role,
    )
    return out, usage


async def batch_results[T: BaseModel](
    batch_id: str, schema: type[T], *, role: str = "default"
) -> dict[str, tuple[T, Usage] | LlmError]:
    """끝난 Batch의 결과를 custom_id로 돌려준다 (결과 순서는 요청 순서와 다르다)."""
    out: dict[str, tuple[T, Usage] | LlmError] = {}
    rows = await _batch_api(_get().messages.batches.results(batch_id))
    async for r in rows:
        out[r.custom_id] = _batch_row(r.result, schema, role)
    failed = sum(isinstance(v, LlmError) for v in out.values())
    log.info(
        "LLM Batch 결과 role=%s id=%s 성공=%d 실패=%d", role, batch_id, len(out) - failed, failed
    )
    return out


async def parse_batch[T: BaseModel](
    items: Sequence[tuple[str, str, str]],
    schema: type[T],
    *,
    role: str = "default",
    live: bool | None = None,
    effort: str | None = None,
    poll_s: float = BATCH_POLL_S,
    max_wait_s: float = BATCH_WAIT_S,
) -> dict[str, tuple[T, Usage] | LlmError]:
    """parse를 Batch로: 제출 → 끝날 때까지 기다림 → custom_id별 (결과, 사용량).

    실패한 줄(오류 · 취소 · 만료 · 거절 · 형식 오류 · 결과 없음)은 그 자리에 LlmError를 둔다.
    """
    batch_id = await submit_batch(items, schema, role=role, live=live, effort=effort)
    await wait_batch(batch_id, poll_s=poll_s, max_wait_s=max_wait_s)
    got = await batch_results(batch_id, schema, role=role)
    return {cid: got.get(cid, LlmError("batch_missing")) for cid, _, _ in items}
