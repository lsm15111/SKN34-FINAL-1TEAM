"""공정 에이전트(TradeAgent): 공정 하나의 지식(SKILL)으로 공정 의견(plan)과 전문가 답(answer)을 만든다.

상담 오케스트레이터가 도구처럼 부른다 (읽기 전용, DB에 쓰지 않는다). 숫자는 쓰지 않는다.
- plan: 칸이 다 차면 계산 엔진 결과를 받아 할 일 · 실측 때 확인할 것 · 주의사항을 쓴다.
  규칙을 어긴 항목은 버리고, 요약이 어긋나면 결과 전체를 버린다. 입력이 같으면 하루 동안 캐시를 쓴다.
- answer: 고객 질문에 그 공정 지식만으로 짧게 답한다. 지어낸 금액 · 기간 · 면적이 있으면 버린다.
새 공정은 모듈을 따로 만들지 않고 consult/trades/<공정>.py에서 TradeAgent.load(...)로 만든다.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.agent import cache, llm
from app.agent.schemas import ExpertAnswer, TradePlan
from app.calc.common import Line, Step
from app.config import settings

_DIR = Path(__file__).parent
EXPERT_PROMPT = "expert_v1.md"
STATE_LABEL = {
    "included": "포함",
    "bundled": "묶음 포함",
    "separate": "따로 계산",
    "optional": "선택",
    "after_visit": "실측 후",
    "excluded": "안 함",
}
_DIGIT = re.compile(r"\d")
# 금액 · 기간 · 면적 · 길이를 새로 만든 글 (숫자는 계산 엔진만 만든다)
NUMBER_CLAIM = re.compile(r"\d[\d,.]*\s*(원|만|천|억|%|일|시간|주|㎡|m|제곱|미터)")


class Quote(Protocol):
    lines: list[Line]
    steps: list[Step]


@dataclass(frozen=True)
class PlanResult:
    plan: TradePlan
    dropped: int  # 규칙을 어겨 버린 항목 수
    usage: llm.Usage | None  # 캐시에서 꺼냈으면 None (LLM을 부르지 않음)


@dataclass(frozen=True)
class AnswerResult:
    answer: ExpertAnswer
    usage: llm.Usage


def skill(name: str) -> str:
    return (_DIR / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def system(prompt: str, title: str, knowledge: str) -> str:
    return (
        (_DIR / "prompts" / prompt).read_text(encoding="utf-8") + f"\n\n# {title}\n\n" + knowledge
    )


def sources(knowledge: str) -> dict[str, str]:
    """지식 파일 '출처' 목록: id → 이름. 주의사항의 source는 이 안에 있어야 한다."""
    return dict(re.findall(r"^- \[(\w+)\] (.+)$", knowledge, re.MULTILINE))


def render(card_text: str, q: Quote) -> str:
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


def validate(plan: TradePlan, step_keys: set[str], known: dict[str, str]) -> tuple[TradePlan, int]:
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
    cautions = [c for c in plan.cautions if c.source in known and _clean(c.text, 300)][:4]
    dropped = (
        len(plan.steps)
        - len(steps)
        + len(plan.visit_checks)
        - len(checks)
        + len(plan.cautions)
        - len(cautions)
    )
    clean = TradePlan(
        summary=plan.summary.strip(), steps=steps, visit_checks=checks, cautions=cautions
    )
    return clean, dropped


@dataclass
class TradeAgent:
    """공정 하나의 에이전트. 지식 · 프롬프트는 만들 때 읽어 고정한다 (프롬프트 캐시가 맞게)."""

    name: str  # 지식 폴더 이름 (agent/skills/<name>/SKILL.md)
    label: str  # 화면 말 (예: 도배)
    plan_prompt_version: str  # 예: wallpaper-v1
    plan_system: str
    answer_system: str
    sources: dict[str, str]  # 지식 '출처' id → 이름

    @classmethod
    def load(cls, name: str, label: str, plan_prompt_file: str) -> "TradeAgent":
        knowledge = skill(name)
        return cls(
            name=name,
            label=label,
            plan_prompt_version=plan_prompt_file.removesuffix(".md").replace("_", "-"),
            plan_system=system(plan_prompt_file, f"{label} 지식", knowledge),
            answer_system=system(EXPERT_PROMPT, f"{label} 지식", knowledge),
            sources=sources(knowledge),
        )

    def validate(self, plan: TradePlan, step_keys: set[str]) -> tuple[TradePlan, int]:
        return validate(plan, step_keys, self.sources)

    def _plan_key(self, user: str) -> str:
        model, effort = llm.pick("plan")
        system_hash = hashlib.sha256(self.plan_system.encode()).hexdigest()
        return cache.key("plan", model, effort, self.plan_prompt_version, system_hash, user)

    async def plan(self, card_text: str, q: Quote) -> PlanResult:
        """모델 · 프롬프트 · 지식 · 입력(집 정보 · 견적)이 같으면 캐시를 쓴다. 검사를 지난 결과만 넣는다."""
        user = render(card_text, q)
        ttl = settings.llm_plan_cache_s
        k = self._plan_key(user) if ttl > 0 else ""
        if k and (hit := await cache.get(k)):
            try:
                return PlanResult(TradePlan.model_validate(hit["plan"]), int(hit["dropped"]), None)
            except (KeyError, TypeError, ValueError):
                pass  # 모양이 맞지 않으면 새로 만든다
        raw, usage = await llm.parse(self.plan_system, user, TradePlan, role="plan")
        clean, dropped = self.validate(raw, {s.key for s in q.steps})
        if k:
            await cache.put(k, {"plan": clean.model_dump(), "dropped": dropped}, ttl)
        return PlanResult(clean, dropped, usage)

    def check_answer(self, a: ExpertAnswer) -> ExpertAnswer:
        """비었거나 300자를 넘거나 금액 · 기간 · 면적을 지어냈으면 LlmError. 목록 밖 출처는 버린다."""
        text = a.answer.strip()
        if not text or len(text) > 300 or NUMBER_CLAIM.search(text):
            raise llm.LlmError("invalid_answer")
        known = [s for s in dict.fromkeys(a.sources) if s in self.sources]
        return ExpertAnswer(answer=text, sources=known)

    async def answer(self, question: str, card_text: str) -> AnswerResult:
        user = f"<input>\n집 정보:\n{card_text}\n\n고객 질문: {question}\n</input>"
        raw, usage = await llm.parse(self.answer_system, user, ExpertAnswer, role="expert")
        return AnswerResult(self.check_answer(raw), usage)
