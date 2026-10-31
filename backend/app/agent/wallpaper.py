"""도배 공정 에이전트. 상담 오케스트레이터가 도배 칸을 다 채우면 도구처럼 부른다 (읽기 전용).

계산 엔진 결과를 받아 할 일 · 실측 때 확인할 것 · 주의사항을 쓴다. 숫자는 쓰지 않는다.
규칙을 어긴 항목은 버리고, 요약이 어긋나면 결과 전체를 버린다.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.agent import llm
from app.agent.schemas import DobaePlan
from app.calc.dobae import DobaeQuote

PROMPT_VERSION = "wallpaper-v1"
_DIR = Path(__file__).parent
SKILL = (_DIR / "skills" / "wallpaper" / "SKILL.md").read_text(encoding="utf-8")
SYSTEM = (
    (_DIR / "prompts" / "wallpaper_v1.md").read_text(encoding="utf-8")
    + "\n\n# 도배 지식\n\n"
    + SKILL
)
# 지식 파일 '출처' 목록: id → 이름. 주의사항의 source는 이 안에 있어야 한다
SOURCES: dict[str, str] = dict(re.findall(r"^- \[(\w+)\] (.+)$", SKILL, re.MULTILINE))

STATE_LABEL = {
    "included": "포함",
    "bundled": "묶음 포함",
    "separate": "따로 계산",
    "optional": "선택",
    "after_visit": "실측 후",
    "excluded": "안 함",
}
_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class PlanResult:
    plan: DobaePlan
    dropped: int  # 규칙을 어겨 버린 항목 수
    usage: llm.Usage


def _input(card_text: str, q: DobaeQuote) -> str:
    lines = "\n".join(
        f"- {ln.key} | {ln.name} | {STATE_LABEL[ln.state]}"
        + (f" | {ln.amount}원" if ln.amount is not None else "")
        for ln in q.lines
    )
    steps = "\n".join(f"- {s.key} | {s.name}" for s in q.steps)
    return (
        f"<input>\n집 정보:\n{card_text}\n\n견적 줄 (키 | 이름 | 상태 | 금액):\n{lines}\n\n"
        f"공정표 단계 (키 | 이름):\n{steps}\n</input>"
    )


def _clean(text: str, limit: int) -> bool:
    return bool(text.strip()) and len(text) <= limit and not _DIGIT.search(text)


def validate(plan: DobaePlan, step_keys: set[str]) -> tuple[DobaePlan, int]:
    """숫자가 든 항목, 없는 단계 키, 목록 밖 출처는 버린다. 요약이 어긋나면 LlmError."""
    if not _clean(plan.summary, 400):
        raise llm.LlmError("invalid_summary")
    seen: set[str] = set()
    steps = []
    for s in plan.steps:
        if s.key in step_keys and s.key not in seen and _clean(s.note, 200):
            seen.add(s.key)
            steps.append(s)
    checks = [c.strip() for c in plan.visit_checks if _clean(c, 200)][:6]
    cautions = [c for c in plan.cautions if c.source in SOURCES and _clean(c.text, 300)][:4]
    dropped = (
        len(plan.steps)
        - len(steps)
        + len(plan.visit_checks)
        - len(checks)
        + len(plan.cautions)
        - len(cautions)
    )
    clean = DobaePlan(
        summary=plan.summary.strip(), steps=steps, visit_checks=checks, cautions=cautions
    )
    return clean, dropped


async def plan(card_text: str, q: DobaeQuote) -> PlanResult:
    raw, usage = await llm.parse(SYSTEM, _input(card_text, q), DobaePlan)
    clean, dropped = validate(raw, {s.key for s in q.steps})
    return PlanResult(clean, dropped, usage)
