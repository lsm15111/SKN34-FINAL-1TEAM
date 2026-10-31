"""LLM SDK를 부르는 유일한 곳 (AGENTS.md 4장). 공급자는 Anthropic Claude.

- LLM_LIVE=false면 부르지 않고 LlmError("stub")를 낸다. 부른 쪽은 계산 결과만 보여 준다.
- 출력은 Pydantic 스키마로 받는다(구조화 출력). 거절 · 잘림 · 형식 오류도 LlmError다.
- 역할(router · expert · plan · sourcing)마다 모델 · 생각 깊이를 따로 둘 수 있다 (config).
- 로그에는 오류 종류와 사용량(역할 · 모델 · 토큰 · 시간)만 남기고 입력 · 출력 내용은 남기지 않는다.
"""

import logging
import time
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

# 안전 분류기가 거절하면 서버가 다른 모델로 이어 받게 할 수 있는 모델
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
ROLES = ("router", "expert", "plan", "sourcing")


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
