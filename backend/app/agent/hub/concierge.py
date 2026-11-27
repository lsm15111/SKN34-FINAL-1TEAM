"""총괄 에이전트(재재) = 입구 관문 + 오케스트레이터를 하나로 합친 것. 한 턴의 입구다.

1. 이해(코드, 늘 돎): 가림 → v3 관문 신호(의도 분류기 · 12공종 낱말 · 정책 표시 · 문장 나누기) → 되물은 칸 답인지
2. 정하기
   - 되물은 칸 답 · 칸 버튼 · 전문가가 있는 공종 하나 → 그 전문가에게 바로 넘긴다(총괄 LLM을 거치지 않음)
   - LLM 모드에서 복합 · 애매함 · 처음 안내 → 총괄 LLM이 도구로 전문가 · v3 담당을 부르고 결론 한 줄을 쓴다
   - 무료 모드 복합에 전문가 공종이 끼면 → 코드로 나눠 전문가 · v3 담당을 부르고 공정 순서로 합친다
   - 그 밖(견적 풀이 · 일정 · 범위 밖 · 아직 전문가가 없는 공종) → v3 한 턴 그대로
3. 묶기: 전문가 몫은 다시 쓰지 않고 이어 붙인다 → 출력 검사(v3 check) → 되물은 칸 · 대화 기억

DB · HTTP를 모른다. 프로젝트 사실 · 지식은 chat.service가 읽어 넘기고, 대화 기억 저장도 chat.service가 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent import llm
from app.agent.hub import experts
from app.agent.hub.core import AgentSpec, Budget, BudgetExceeded, Run, Tool, ToolOut, loop
from app.agent.hub.experts.base import ExpertTask, run_expert
from app.agent.hub.reply import Asked, Memory, Reply
from app.agent.v3 import check, orchestrator, policy, templates, trades
from app.agent.v3 import gate as gate_mod
from app.agent.v3 import turn as v3_turn
from app.agent.v3.answer import KB, Task
from app.agent.v3.schemas import (
    TEXT_MAX,
    AgentAnswer,
    Button,
    GateResult,
    ProjectFacts,
    Route,
    Sentence,
    Trace,
    TurnContext,
    UiCard,
)
from app.agent.v3.trades import BY_CODE
from app.v2 import guard

PROMPT_VERSION = "concierge_v1"
PROMPT = (Path(__file__).with_name("prompts") / f"{PROMPT_VERSION}.md").read_text(encoding="utf-8")
LLM_ROUTES: tuple[Route, ...] = ("multi", "ask_back", "guide")  # 총괄 LLM이 정하는 길
TRADE_CODES = tuple(c for c in BY_CODE if c != "common")
PET = re.compile(r"강아지|고양이|반려\s*(?:견|묘|동물)|애견|애묘|멍멍이|냥이")
STAGE_KO = {
    "info": "기본 정보 넣기", "standard": "표준견적서 보기", "vendors": "업체 고르기", "visit": "실측",
    "after_visit": "실측 견적서 비교", "construction": "공사 중", "done": "공사 끝",
}  # fmt: skip


@dataclass
class HubResult:
    answer: AgentAnswer
    waiting: dict | None  # {route, trade, slot, q}: 다음 턴의 짧은 답을 그 전문가가 받게
    label: str | None
    confidence: float
    source: str
    memory: dict  # 대화 기억(Memory). chat.service가 저장한다


@dataclass
class Understood:
    text: str
    gate: GateResult
    slot: str | None = None
    value: str | None = None
    asked: str = ""


def understand(
    masked: str,
    ctx: TurnContext,
    facts: ProjectFacts | None,
    waiting: dict | None,
    button: Button | None,
    mem: Memory,
) -> Understood:
    g = gate_mod.gate(
        masked, view=ctx.view, waiting=waiting.get("route") if waiting else None, button=button,
        has_project=facts is not None, ignore=v3_turn.ignore_words(facts),
    )  # fmt: skip
    u = Understood(text=masked, gate=g)
    if g.route == "out_of_scope" and g.source != "button":
        # v3 범위 밖 규칙의 잡담 낱말('강아지')은 바닥재 고르기에서는 집 조건이에요
        found = trades.trades_in(gate_mod._strip(masked, v3_turn.ignore_words(facts)))
        if any(experts.get(c) for c in found) and not policy.out_of_scope(
            PET.sub(" ", masked), True
        ):
            route: Route = "multi" if len(found) >= 2 else "trade"
            u.gate = g.model_copy(update={"route": route, "trades": found, "source": "rule"})
    if waiting and waiting.get("slot") and (g.source == "waiting" or (button and button.slot)):
        u.slot = waiting["slot"]
        u.value = (button.value if button and button.value else masked)[:40]
        u.asked = waiting.get("q", "")
        if waiting.get("trade"):
            u.gate = g.model_copy(update={"route": "trade", "trades": [waiting["trade"]]})
    elif button is not None and button.slot and button.trade:  # 기다림이 지워진 뒤 누른 칸 버튼
        u.slot, u.value = button.slot, (button.value or masked)[:40]
        if mem.asked is not None and mem.asked.slot == button.slot:
            u.asked = mem.asked.q
    return u


def _brief(mem: Memory, facts: ProjectFacts | None) -> dict[str, str]:
    return {**(facts.brief if facts else {}), **mem.brief}


def _expert_task(u: Understood, ctx: TurnContext, facts, mem: Memory) -> ExpertTask:
    return ExpertTask(
        text=u.text, ctx=ctx, facts=facts, policy=list(u.gate.policy), brief=_brief(mem, facts),
        slot=u.slot, value=u.value, asked=u.asked,
    )  # fmt: skip


def _v3_part(route: Route, text: str, trades: list[str], ctx, facts, kb: KB) -> Reply:
    task = Task(
        text=text, route=route, trades=trades, policy=policy.policy_of(text), ctx=ctx, facts=facts
    )  # type: ignore[arg-type]
    return Reply.of(orchestrator.AGENTS[route](task, kb), agent=f"v3:{route}")


async def _run_task(
    t: Task, kb: KB, facts, mem: Memory, budget: Budget, whole: str
) -> tuple[Reply, str]:
    """무료 모드 복합의 조각 하나: 전문가가 있으면 전문가, 없으면 v3 담당."""
    code = t.trades[0] if t.route == "trade" and t.trades else None
    x = experts.get(code)
    name = f"{t.route}:{code or '-'}"
    if x is not None:
        task = ExpertTask(
            text=t.text, ctx=t.ctx, facts=facts, policy=list(t.policy), brief=_brief(mem, facts),
            whole=whole,
        )  # fmt: skip
        return await run_expert(x, task, kb, budget=budget, mode=t.ctx.mode), name
    return Reply.of(orchestrator.AGENTS[t.route](t, kb), agent=f"v3:{t.route}"), name


def _prompt_text(prompts: list[str]) -> str | None:
    texts = [PROMPT] if PROMPT_VERSION in prompts else []
    texts += [x.prompt for x in experts.registered().values() if x.prompt_version in prompts]
    return "\n".join(texts) or None


def compose(
    reps: list[Reply],
    u: Understood,
    ctx: TurnContext,
    kb: KB,
    mem: Memory,
    *,
    route: Route,
    names: list[str],
    lead: str = "",
    prompts: list[str] | None = None,
    extra_cards: list[UiCard] | None = None,
) -> HubResult:
    g = u.gate
    part = reps[0] if len(reps) == 1 else orchestrator.merge(list(reps), kb, asked=u.text)
    prompts = list(dict.fromkeys([*(prompts or []), *(p for r in reps for p in r.prompts)]))
    cards = [*part.cards, *(c for c in extra_cards or [] if c not in part.cards)]
    ans = AgentAnswer(
        lead=lead, sections=part.sections, calc=part.calc, cards=cards, ask=part.ask,
        unknown=part.unknown, suggest=list(dict.fromkeys(part.suggest))[:3],
        vendor=list(dict.fromkeys(v for r in reps for v in r.vendor))[:3],
        trace=Trace(
            route=route, source=g.source, confidence=g.confidence, trades=g.trades, policy=g.policy,
            mode=ctx.mode, cards=list(dict.fromkeys(part.used_cards)),
            chunks=list(dict.fromkeys(part.used_chunks)), prompts=prompts, card_set=kb.cards.version,
            parts=names, failed_parts=sum(1 for r in reps if r.empty) if len(reps) > 1 else 0,
            dropped=part.dropped,
        ),
    )  # fmt: skip
    ans = check.final(ans, prompt=_prompt_text(prompts))  # 지시문 누출 검사(쓴 지시문만)
    mem.remember({k: v for r in reps for k, v in r.memory.items()})
    mem.last_trade = next((r.trade for r in reps if r.trade), mem.last_trade)
    waiting = None
    if ans.ask is not None:
        q = u.asked if u.slot and u.asked else u.text
        waiting = {"route": "trade", "trade": ans.ask.trade, "slot": ans.ask.slot, "q": q}
        mem.asked = Asked(trade=ans.ask.trade, slot=ans.ask.slot, q=q)
    else:
        mem.asked = None
    return HubResult(ans, waiting, g.label, g.confidence, g.source, mem.model_dump())


# ---- 총괄 LLM ----
@dataclass
class ConciergeRun(Run):
    u: Understood | None = None
    ctx: TurnContext | None = None
    kb: KB | None = None
    facts: ProjectFacts | None = None
    mem: Memory = field(default_factory=Memory)
    parts: list[Reply] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    lead: str = ""


class ExpertArgs(BaseModel):
    trade: str = Field(description="공종 코드", json_schema_extra={"enum": list(TRADE_CODES)})
    question: str = Field(min_length=1, max_length=300, description="그 공종 몫의 질문(짧게)")


class QuestionArgs(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class NoArgs(BaseModel):
    pass


class FinishArgs(BaseModel):
    lead: str = Field(
        default="", max_length=120, description="결론 한 줄(전문가 답을 되풀이하지 않음)"
    )
    suggest: list[str] = Field(default=[], max_length=3)


def _record(r: ConciergeRun, rep: Reply, name: str) -> ToolOut:
    r.parts.append(rep)
    r.names.append(name)
    said = [x.text for s in rep.sections for x in s.sentences] + rep.unknown + rep.vendor
    return ToolOut(text=f"[{name}] 화면에 그대로 보여요.\n{rep.text()}", evidence="\n".join(said))


def _delegate(r: ConciergeRun) -> str | None:
    try:
        r.budget.take_delegation()
    except BudgetExceeded:
        return "이번 턴에는 더 맡길 수 없어요. finish로 끝내세요."
    return None


async def _ask_expert(r: ConciergeRun, a: ExpertArgs) -> ToolOut:
    if a.trade not in TRADE_CODES:
        return ToolOut(text="없는 공종 코드예요.")
    if stop := _delegate(r):
        return ToolOut(text=stop)
    q = check.mask(a.question).strip()[:TEXT_MAX]
    x = experts.get(a.trade)
    if x is not None:
        task = ExpertTask(
            text=q,
            ctx=r.ctx,
            facts=r.facts,
            policy=policy.policy_of(q),
            brief=_brief(r.mem, r.facts),
        )  # type: ignore[arg-type]
        rep = await run_expert(x, task, r.kb, budget=r.budget, mode=r.ctx.mode)  # type: ignore[arg-type, union-attr]
    else:
        rep = _v3_part("trade", q, [a.trade], r.ctx, r.facts, r.kb)  # type: ignore[arg-type]
    return _record(r, rep, f"trade:{a.trade}")


def _v3_tool(route: Route, need_project: bool = False):
    def run(r: ConciergeRun, a: QuestionArgs) -> ToolOut:
        if need_project and r.facts is None:
            return ToolOut(text="아직 프로젝트가 없어요. 기본 정보를 넣으면 계산해요.")
        if stop := _delegate(r):
            return ToolOut(text=stop)
        q = check.mask(a.question).strip()[:TEXT_MAX]
        return _record(r, _v3_part(route, q, [], r.ctx, r.facts, r.kb), route)  # type: ignore[arg-type]

    return run


def _status(r: ConciergeRun, _: NoArgs) -> ToolOut:
    f = r.facts
    if f is None:
        nxt = templates.NO_PROJECT_NEXT
        text = "프로젝트가 아직 없어요(가입 · 기본 정보 전)."
    else:
        nxt = templates.NEXT.get(f.stage, [])
        lines = [f"지금 단계: {STAGE_KO.get(f.stage, f.stage)}"]
        lines.append(f"고른 공정: {', '.join(BY_CODE[t].ko for t in f.trades) or '없음'}")
        if f.area_m2:
            lines.append(f"면적: {f.area_m2}㎡({'공급' if f.area_basis == 'supply' else '전용'})")
        if f.standard:
            lines.append(f"표준견적서 합계(믿집 계산, 부가세 포함): {f.standard.total:,}원")
        if f.plan:
            lines.append(f"예상 공정표: {templates.md(f.plan.start)} ~ {templates.md(f.plan.end)}")
        if f.estimates:
            lines.append(f"가견적 받은 업체: {len(f.estimates)}곳")
        text = "\n".join(lines)
    if nxt and not any(c.kind == "next_step" for c in r.reply.cards):
        r.reply.cards.append(UiCard(kind="next_step", choices=list(nxt)))
    steps = " · ".join(c.text for c in nxt)
    return ToolOut(text=f"{text}\n다음 할 일 버튼(화면에 붙였어요): {steps}", evidence=text)


def _finish(r: ConciergeRun, a: FinishArgs) -> ToolOut:
    r.lead = a.lead
    r.reply.suggest.extend(a.suggest)
    r.done = True
    return ToolOut(text="끝냈어요.")


def concierge_tools() -> tuple[Tool, ...]:
    return (
        Tool("ask_expert", "공종 질문을 그 공종 전문가(없으면 공종 지식 담당)에게 맡긴다. 답은 화면에 그대로 보인다.",
             ExpertArgs, _ask_expert),
        Tool("explain_my_quote", "고객 프로젝트의 표준견적서 · 가견적 · 실측 견적서 줄과 차이를 풀이한다(계산 엔진 값).",
             QuestionArgs, _v3_tool("quote_explanation", need_project=True)),
        Tool("schedule_help", "고객 프로젝트의 예상 공정표 · 실측 일정 초안을 읽어 준다(계산 엔진 값).",
             QuestionArgs, _v3_tool("schedule", need_project=True)),
        Tool("common_knowledge", "처음 순서 · 용어 · 계약 · 관리사무소 · 하자 기본처럼 공종이 아닌 공통 지식을 답한다.",
             QuestionArgs, _v3_tool("guide")),
        Tool("project_status", "고객 프로젝트의 지금 단계 · 고른 공정 · 계산된 값 · 다음 할 일 버튼을 받는다.",
             NoArgs, _status),
    )  # fmt: skip


def _system(u: Understood, facts: ProjectFacts | None, mem: Memory) -> str:
    g = u.gate
    have = experts.registered()
    lines = [
        PROMPT,
        "## 이번 턴에 코드가 읽은 것",
        f"- 관문 신호: 길 {g.route} · 공종 {', '.join(g.trades) or '없음'} · 정책 {', '.join(g.policy) or '없음'}",
        "- 전문가가 있는 공종: " + (", ".join(f"{c}={BY_CODE[c].ko}" for c in have) or "없음"),
        "- 그 밖 공종(지식 답): "
        + ", ".join(f"{c}={BY_CODE[c].ko}" for c in TRADE_CODES if c not in have),
    ]
    if facts is None:
        lines.append("- 프로젝트: 아직 없음(견적 풀이 · 일정은 못 써요)")
    else:
        lines.append(
            f"- 프로젝트: 단계 {STAGE_KO.get(facts.stage, facts.stage)} · 고른 공정 "
            f"{', '.join(BY_CODE[t].ko for t in facts.trades) or '없음'}"
        )
    if mem.brief:
        lines.append(
            "- 대화에서 알게 된 조건: " + " · ".join(f"{k}={v}" for k, v in mem.brief.items())
        )
    return "\n".join(lines)


def _lead_ok(lead: str, evidence: list[str], user: str) -> str:
    if not lead.strip():
        return ""
    allowed = guard.numbers("\n".join([*evidence, user]))
    ok, _ = check.sentence_ok(Sentence(text=lead), allowed, None, None, PROMPT)
    return ok.text if ok else ""


async def _concierge(
    u: Understood, ctx: TurnContext, kb: KB, facts, mem: Memory, budget: Budget
) -> HubResult | None:
    r = ConciergeRun(
        reply=Reply(agent="concierge", route="multi"), budget=budget, u=u, ctx=ctx, kb=kb,
        facts=facts, mem=mem,
    )  # fmt: skip
    spec = AgentSpec(
        name="concierge", system=_system(u, facts, mem), tools=concierge_tools(),
        finish=Tool("finish", "결론 한 줄과 이어 물을 질문으로 턴을 끝낸다.", FinishArgs, _finish),
        max_rounds=4,
    )  # fmt: skip
    try:
        await loop(spec, r, f"고객 글: {u.text}")
    except (llm.LLMError, BudgetExceeded):
        pass  # 맡긴 몫이 있으면 그것으로, 없으면 v3 한 턴으로
    if not r.parts:
        return None
    lead = _lead_ok(r.lead, r.evidence, u.text)
    route: Route = "multi" if len(r.parts) > 1 else r.parts[0].route
    r.parts[0].suggest[:0] = [s[:60] for s in r.reply.suggest]  # 총괄이 고른 이어 물을 질문을 앞에
    return compose(
        r.parts, u, ctx, kb, mem, route=route, names=r.names, lead=lead,
        prompts=[PROMPT_VERSION], extra_cards=r.reply.cards,
    )  # fmt: skip


# ---- 한 턴 ----
async def run_turn(
    text: str,
    ctx: TurnContext,
    *,
    kb: KB,
    facts: ProjectFacts | None = None,
    waiting: dict | None = None,
    button: Button | None = None,
    memory: dict | None = None,
    load_vectors: v3_turn.VectorLookup | None = None,
) -> HubResult:
    masked = check.mask(text or "").strip()[:TEXT_MAX]
    mem = Memory.model_validate(memory or {})
    u = understand(masked, ctx, facts, waiting, button, mem)
    g = u.gate
    budget = Budget()

    x = experts.get(g.trades[0]) if g.route == "trade" and g.trades else None
    if x is not None:  # 넘겨주기: 전문가 공종 하나 · 되물은 칸 답
        rep = await run_expert(
            x, _expert_task(u, ctx, facts, mem), kb, budget=budget, mode=ctx.mode
        )
        return compose([rep], u, ctx, kb, mem, route="trade", names=[f"trade:{x.code}"])

    if ctx.mode == "llm" and g.route in LLM_ROUTES:
        got = await _concierge(u, ctx, kb, facts, mem, budget)
        if got is not None:
            return got

    if g.route == "multi":
        task = Task(
            text=masked, route="multi", trades=g.trades, policy=g.policy, ctx=ctx, facts=facts
        )
        tasks = orchestrator.split(task)
        if any(t.route == "trade" and t.trades and experts.get(t.trades[0]) for t in tasks):
            done = [await _run_task(t, kb, facts, mem, budget, masked) for t in tasks]
            reps, names = [d[0] for d in done], [d[1] for d in done]
            return compose(reps, u, ctx, kb, mem, route="multi", names=names)

    # 그 밖은 v3 한 턴 그대로(견적 풀이 · 일정 · 범위 밖 · 전문가가 아직 없는 공종)
    res = await v3_turn.run_turn(
        text, ctx, kb=kb, facts=facts, waiting=waiting, button=button, load_vectors=load_vectors
    )
    w = res.waiting
    mem.asked = (
        Asked(trade=w.get("trade") or "", slot=w.get("slot") or "", q=w.get("q") or "")
        if w
        else None
    )
    return HubResult(res.answer, w, res.label, res.confidence, res.source, mem.model_dump())
