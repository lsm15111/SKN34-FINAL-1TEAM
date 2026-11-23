"""모델 가격(달러 / 100만 토큰)과 호출 한 번의 비용. 판정 · 비교 실행 · 예산 어림이 같이 써요.

- Claude: claude-api 스킬 `shared/models.md` · `shared/prompt-caching.md`(2026-11 캐시)
  - Opus 5.5 입력 $4 · 출력 $20 · 캐시 읽기 $0.20
  - Sonnet 5.5 입력 $2 · 출력 $10 · 캐시 읽기 $0.10
  - Haiku 5.5 입력 $0.10 · 출력 $0.50(프롬프트 10만 토큰 이하, 넘으면 $0.50 · $2.50).
    캐시 읽기 값은 문서에 따로 없어 입력의 0.1배로 둬요(확인 필요)
  - 캐시 쓰기는 입력의 1.25배(5분) · 2배(1시간), Batch는 50%
  - 생각(thinking) 토큰은 출력 토큰으로 매겨요
- OpenAI(지금 `app/agent/llm.py` 공급자): `evaluation/v3/composer_eval.py` PRICE(agent-web C15)와 같아요
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    inp: float
    out: float
    cache_read: float
    long_inp: float | None = None  # 긴 프롬프트 값(Haiku 5.5)
    long_out: float | None = None
    long_from: int | None = None  # 이 토큰 수를 넘으면 긴 프롬프트 값


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(4.00, 20.00, 0.20),
    "claude-sonnet-5-5": Price(2.00, 10.00, 0.10),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, long_inp=0.50, long_out=2.50, long_from=100_000),
    "gpt-6.1-sol": Price(2.00, 10.00, 0.10),  # OpenAI 가격 문서(2026-11-23 확인)
    "gpt-6.1-terra": Price(1.00, 5.00, 0.05),
    "gpt-6-luna": Price(0.10, 0.50, 0.01),
}
CACHE_WRITE = {"5m": 1.25, "1h": 2.0}
BATCH = 0.5
PRICE_NOTE = "claude-api 스킬 models.md(2026-11) · OpenAI는 composer_eval.py 값"


def usage_of(raw) -> dict:
    """공급자마다 다른 사용량을 한 모양으로: {input(캐시 아닌 입력), cache_write, cache_read, output}.

    - Anthropic 응답 usage(객체 · dict): input_tokens · cache_creation_input_tokens · cache_read_input_tokens · output_tokens
    - 백엔드 장부 관문(llm._sink의 u): input · cache_read · cache_write_5m · cache_write_1h · output (· web_searches)
    - 옛 llm.py USAGE_HOOK(OpenAI): input(캐시 포함 전체) · cached · output
    - 이 폴더의 어림: input · cache_write · cache_read · output
    """
    if raw is None:
        return {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    get = raw.get if isinstance(raw, dict) else (lambda k, d=None: getattr(raw, k, d))
    if get("cache_write_5m") is not None or get("cache_write_1h") is not None:
        return {
            "input": int(get("input") or 0),
            "cache_write": int(get("cache_write_5m") or 0) + int(get("cache_write_1h") or 0),
            "cache_read": int(get("cache_read") or 0),
            "output": int(get("output") or 0),
        }
    if get("input_tokens") is not None:
        return {
            "input": int(get("input_tokens") or 0),
            "cache_write": int(get("cache_creation_input_tokens") or 0),
            "cache_read": int(get("cache_read_input_tokens") or 0),
            "output": int(get("output_tokens") or 0),
        }
    if get("cached") is not None:
        total, cached = int(get("input") or 0), int(get("cached") or 0)
        return {
            "input": max(total - cached, 0),
            "cache_write": 0,
            "cache_read": cached,
            "output": int(get("output") or 0),
        }
    return {k: int(get(k) or 0) for k in ("input", "cache_write", "cache_read", "output")}


def cost_usd(model: str | None, usage, *, batch: bool = False, ttl: str = "5m") -> float | None:
    """호출 한 번 비용(달러). 모르는 모델이면 None(0으로 치지 않아요)."""
    p = PRICES.get(model or "")
    if p is None:
        return None
    u = usage_of(usage)
    prompt = u["input"] + u["cache_write"] + u["cache_read"]
    inp, out = p.inp, p.out
    if p.long_from is not None and prompt > p.long_from:
        inp, out = p.long_inp or inp, p.long_out or out
    usd = (
        u["input"] * inp
        + u["cache_write"] * inp * CACHE_WRITE[ttl]
        + u["cache_read"] * p.cache_read
        + u["output"] * out
    ) / 1e6
    return usd * (BATCH if batch else 1.0)


def most_expensive(models) -> str:
    """값을 모르는 호출을 셀 때 쓰는 가장 비싼 모델(어림을 크게 잡아요)."""
    known = [m for m in models if m in PRICES] or list(PRICES)
    return max(known, key=lambda m: PRICES[m].out)
