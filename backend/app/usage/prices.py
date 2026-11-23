"""Claude · OpenAI 가격표와 호출 한 번의 비용 셈(마이크로달러 정수). DB · 시계를 모르는 순수 함수다.

출처
- Claude(2026-11-21 확인): 공식 가격 문서 https://platform.claude.com/docs/en/about-claude/pricing (Model pricing ·
  Long context pricing · Web search tool 절), claude-api 스킬 shared/models.md, shared/model-migration.md(Opus 5.5 ·
  Sonnet 5.5 · Haiku 5.5 절), shared/managed-agents-core.md(웹 검색 1,000번에 $10)
- OpenAI(2026-11-23 확인): 공식 가격 문서 https://developers.openai.com/api/docs/pricing (Standard 표: 입력 · 캐시 읽기 ·
  30분 쓰기 · 12시간 쓰기 · 출력, 입력이 27만 2천 토큰을 넘으면 Long context 값. Tools 표: 웹 검색 1,000번에 $10 +
  검색 글 토큰은 모델 값 = 입력 토큰에 든다)
- Haiku 5.5 · OpenAI 모델은 프롬프트(입력 + 캐시 읽기 + 캐시 쓰기)가 기준을 넘으면 비싼 표를 쓴다.
  Sonnet 5.5 · Opus 5.5는 길이와 상관없이 같은 값이다. 실패한 웹 검색은 값을 받지 않는다(사용량에 안 잡힘).
"""

PRICE_VER = "2026-11-23"

# (입력, 짧은 캐시 쓰기, 긴 캐시 쓰기, 캐시 읽기, 출력): 백만 토큰당 달러 × 1000.
# 짧은 · 긴 캐시 쓰기는 Claude 5분 · 1시간, OpenAI 30분 · 12시간이다(장부 칸 cache_write_5m · cache_write_1h).
# 백만 토큰당 $1 = 토큰당 1마이크로달러라서, 토큰 수 × 이 값 = 나노달러다(소수 없이 셈)
Rate = tuple[int, int, int, int, int]
RATES: dict[str, Rate] = {
    "claude-opus-5-5": (4000, 5000, 8000, 200, 20000),  # $4 · $5 · $8 · $0.20 · $20
    "claude-sonnet-5-5": (2000, 2500, 4000, 100, 10000),  # $2 · $2.50 · $4 · $0.10 · $10
    "claude-haiku-5-5": (100, 125, 200, 10, 500),  # $0.10 · $0.125 · $0.20 · $0.01 · $0.50
    "gpt-6.1-terra": (1000, 1250, 2500, 50, 5000),  # $1 · $1.25 · $2.50 · $0.05 · $5
    "gpt-6-luna": (100, 125, 250, 10, 500),  # $0.10 · $0.125 · $0.25 · $0.01 · $0.50
}
# 프롬프트 길이로 값이 바뀌는 모델: (넘으면 비싸지는 토큰 수, 비싼 표)
LONG: dict[str, tuple[int, Rate]] = {
    # $0.50 · $0.625 · $1 · $0.05 · $2.50
    "claude-haiku-5-5": (100_000, (500, 625, 1000, 50, 2500)),
    # $2 · $2.50 · $5 · $0.10 · $7.50
    "gpt-6.1-terra": (272_000, (2000, 2500, 5000, 100, 7500)),
    # $0.20 · $0.25 · $0.50 · $0.02 · $0.75
    "gpt-6-luna": (272_000, (200, 250, 500, 20, 750)),
}
WEB_SEARCH_NANOS = 10_000_000  # 웹 검색 1번 $0.01 (Claude · OpenAI 모두 1,000번에 $10)
# 표에 없는 모델은 가장 비싼 값으로 어림한다(상한 쪽으로 안전)
FALLBACK = "claude-opus-5-5"


def model_key(model: str) -> str | None:
    """응답의 모델 이름 → 가격표 키. 날짜가 붙은 이름도 앞부분으로 찾는다. 없으면 None."""
    if model in RATES:
        return model
    return next((k for k in RATES if model.startswith(k)), None)


def cost(
    model: str,
    *,
    input_tokens: int = 0,
    cache_read: int = 0,
    cache_write_5m: int = 0,
    cache_write_1h: int = 0,
    output_tokens: int = 0,
    web_searches: int = 0,
) -> tuple[int, str]:
    """호출 한 번의 비용(마이크로달러, 올림)과 가격표 판. 표에 없는 모델이면 판 뒤에 ':fallback'."""
    key = model_key(model)
    rate = RATES[key or FALLBACK]
    prompt = input_tokens + cache_read + cache_write_5m + cache_write_1h
    if key in LONG and prompt > LONG[key][0]:
        rate = LONG[key][1]
    i, w5, w1, r, o = rate
    nanos = (
        input_tokens * i
        + cache_write_5m * w5
        + cache_write_1h * w1
        + cache_read * r
        + output_tokens * o
        + web_searches * WEB_SEARCH_NANOS
    )
    return -(-nanos // 1000), PRICE_VER if key else f"{PRICE_VER}:fallback"
