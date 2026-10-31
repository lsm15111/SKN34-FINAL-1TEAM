"""모델 가격 · 사용량 → 비용, 실행 전 비용 추정. 표준 라이브러리만 쓴다.

가격 출처: https://platform.claude.com/docs/en/about-claude/pricing (2026-10-31 확인), $/MTok.
- 캐시 쓰기는 5분 TTL 값. 캐시 읽기는 Opus 5.5 · Sonnet 5.5가 입력의 0.05배, Haiku 5.5가 0.1배
- Haiku 5.5는 프롬프트 10만 토큰 이하 값 (평가 입력은 수천 토큰)
- Batch API는 입력 · 출력 모두 50% 할인이고 캐시 배수와 겹쳐 적용된다. 다만 Batch는 캐시 적중이
  보장되지 않아 추정에서는 시스템 프롬프트를 캐시 없이 셈한다 (보수적)
"""

from dataclasses import dataclass

PRICE_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing (2026-10-31 확인)"
BATCH_DISCOUNT = 0.5


@dataclass(frozen=True)
class Price:
    input: float
    cache_write: float  # 5분 TTL
    cache_read: float
    output: float


PRICES = {
    "claude-opus-5-5": Price(4.0, 5.0, 0.20, 20.0),
    "claude-sonnet-5-5": Price(2.0, 2.50, 0.10, 10.0),
    "claude-haiku-5-5": Price(0.10, 0.125, 0.01, 0.50),
}
MODEL_LABEL = {
    "claude-opus-5-5": "Opus 5.5",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-haiku-5-5": "Haiku 5.5",
}


@dataclass(frozen=True)
class CallShape:
    """호출 한 번의 토큰 모양 (평균, 추정용)"""

    uncached: int  # 사례마다 바뀌는 입력 (집 정보 · 견적 줄 · 단계)
    system: int  # 시스템 프롬프트 (캐시)
    output: int  # 출력 (생각 토큰 포함)
    basis: str  # 근거


# 도배 공정 의견: evaluation/dobae/results/20261031-{1645,1649,2013}의 공정 의견 호출 135번
# (Opus 5.5 · effort medium). 입력 평균 353 (글자당 0.84) · 시스템 3,213~3,231 (글자당 1.32) ·
# 출력 평균 1,260 (p90 1,424 · 최대 2,201). 5k 사례는 입력 글이 평균 468자라 입력을 390으로 잡는다
# 목공 공정 의견 · 판정: 실측이 없어 도배 글자당 토큰 비율로 잡은 추정값. T1(공정마다 20개)에서 다시 잰다
#   목공 입력 526자 · 시스템 3,183자 / 판정 시스템(기준표 + 지식) 3,412~4,038자 · 입력(공정 입력 + 의견 1,101자)
SHAPES = {
    "dobae": CallShape(390, 3231, 1260, "도배 실측 135회 평균, 입력은 5k 글자 수로 보정"),
    "mokgong": CallShape(440, 4190, 1400, "추정: 도배 글자당 토큰 비율, 단계가 많아 출력 +10%"),
    "judge": CallShape(1800, 4900, 700, "추정: 도배 글자당 토큰 비율, 출력은 effort low 가정"),
}


def shape(name: str) -> CallShape:
    """호출 토큰 모양. 실측 · 추정이 없는 공정 의견은 목공 값으로 셈한다"""
    return SHAPES.get(name) or SHAPES["mokgong"]


TOKEN_KEYS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def call_cost(usage: dict, model: str | None = None) -> float | None:
    """llm.Usage 한 번의 비용 ($). Batch로 받은 것(batch: true)은 50% 할인. 가격표에 없는 모델이면 None"""
    p = PRICES.get(model or usage["model"])
    if p is None:
        return None
    full = (
        usage["input_tokens"] * p.input
        + usage["cache_write_tokens"] * p.cache_write
        + usage["cache_read_tokens"] * p.cache_read
        + usage["output_tokens"] * p.output
    ) / 1e6
    return full * (BATCH_DISCOUNT if usage.get("batch") else 1)


def total_cost(usages: list[dict]) -> tuple[float, int]:
    """(가격을 아는 호출의 비용 합, 가격을 모르는 호출 수)"""
    costs = [call_cost(u) for u in usages]
    return sum(c for c in costs if c is not None), sum(c is None for c in costs)


def estimate(
    shape: CallShape, n: int, model: str, *, concurrency: int = 4, batch: bool = False
) -> float:
    """n번 부를 때 비용 ($).

    일반: 처음 concurrency번은 시스템 프롬프트를 캐시에 쓰고 나머지는 캐시에서 읽는다고 본다.
    Batch: 캐시 없이 셈하고 50% 할인한다.
    """
    if n <= 0:
        return 0.0
    p = PRICES[model]
    if batch:
        per = (shape.uncached + shape.system) * p.input + shape.output * p.output
        return n * per * BATCH_DISCOUNT / 1e6
    writes = min(n, concurrency)
    per = shape.uncached * p.input + shape.output * p.output
    cached = writes * shape.system * p.cache_write + (n - writes) * shape.system * p.cache_read
    return (n * per + cached) / 1e6


def estimate_table(
    name: str,
    sizes: tuple[int, ...] = (20, 150, 5000),
    judge: int = 0,
    judge_shape: str = "judge",
) -> str:
    """모델별 예상 비용 표 (마크다운). name은 호출 모양 이름, judge는 판정 LLM으로 매길 사례 수"""
    head = " | ".join(f"{n:,}개" for n in sizes)
    out = [
        f"| 모델 | {head} | {sizes[-1]:,}개 Batch |",
        "| --- |" + " ---: |" * (len(sizes) + 1),
    ]
    for model, label in MODEL_LABEL.items():

        def cost(n: int, batch: bool = False, model: str = model) -> float:
            plan = estimate(shape(name), n, model, batch=batch)
            return plan + estimate(SHAPES[judge_shape], min(judge, n), model, batch=batch)

        cells = " | ".join(f"${cost(n):,.2f}" for n in sizes)
        out.append(f"| {label} | {cells} | ${cost(sizes[-1], True):,.2f} |")
    return "\n".join(out)
