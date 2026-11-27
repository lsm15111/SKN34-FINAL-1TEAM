"""공종 전문가 에이전트의 공통 틀.

전문가 하나 = 공종 설정(v3 TradeSpec: 낱말 · 순서) + 전문 지식 묶음(Pack) + 도구 + 지시문 + 무료 모드 판단.

- 전문 지식 묶음(pack.json): 자재 · 조건(브리프 칸) · 조건별 맞춤 규칙 · 체크리스트 · 업체에 물을 말.
  문장마다 근거 조각 번호를 단다(시험이 실제 조각인지 본다). 금액 · 기간 숫자는 쓰지 않는다.
- RAG: 공종 무게 키워드 검색(knowledge.search3) + 검증된 답 카드(v3 answer.knowledge).
- LLM 모드: 전문가가 도구로 근거를 찾고 화면 조각을 만든 뒤 answer 도구로 답한다.
  LLM이 실패하거나 턴 예산을 넘기면 같은 도구 · 같은 지식으로 무료 모드 답을 낸다(지어낸 설명으로 채우지 않음).
- 무료 모드: 공종 폴더의 offline.run이 코드로 고른다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from app.agent import llm
from app.agent.hub.core import AgentSpec, Budget, BudgetExceeded, Run, Tool, ToolOut, loop
from app.agent.hub.reply import Reply
from app.agent.v3 import templates
from app.agent.v3.answer import KB
from app.agent.v3.schemas import AskSlot, ProjectFacts, Section, Sentence, TurnContext
from app.agent.v3.trades import BY_CODE, TradeSpec
from app.knowledge import search3


# ---- 전문 지식 묶음 ----
class Cited(BaseModel):
    text: str
    cites: list[str] = []


class Material(BaseModel):
    key: str
    name: str
    words: list[str]  # 질문에서 이 자재를 찾는 말
    good: list[Cited]
    watch: list[Cited]
    short_good: str  # 비교표 칸(근거 문장을 줄인 말)
    short_watch: str


class Condition(BaseModel):
    """브리프 칸 하나. 고객이 고르거나 말하면 대화 기억에 담긴다."""

    key: str  # 예: floor.family
    label: str  # 화면 말(예: 가족)
    question: str
    options: list[str]


class FitRule(BaseModel):
    """조건 → 자재 점수. 이유 문장은 근거가 있는 것만."""

    when: dict[str, str]  # 칸 → 값
    prefer: dict[str, int] = {}  # 자재 key → 점수(음수는 덜 맞음)
    why: list[Cited]


class CheckItem(BaseModel):
    who: str  # 직접 · 업체 · 같이
    text: str
    cites: list[str] = []


class Checklist(BaseModel):
    title: str
    items: list[CheckItem]


class VendorQuestion(BaseModel):
    text: str
    topics: list[str]
    cites: list[str] = []


class Pack(BaseModel):
    version: str
    trade: str
    materials: list[Material]
    conditions: list[Condition]
    rules: list[FitRule]
    checklists: dict[str, Checklist]
    vendor_questions: list[VendorQuestion]
    notes: dict[str, list[Cited]] = {}

    @model_validator(mode="after")
    def _keys(self) -> Pack:
        mats = {m.key for m in self.materials}
        conds = {c.key: set(c.options) for c in self.conditions}
        for r in self.rules:
            for k, v in r.when.items():
                if k not in conds or v not in conds[k]:
                    raise ValueError(f"규칙 조건이 조건 목록에 없어요: {k}={v}")
            if set(r.prefer) - mats:
                raise ValueError(f"규칙 자재가 자재 목록에 없어요: {sorted(set(r.prefer) - mats)}")
        return self

    def material(self, key: str) -> Material:
        return next(m for m in self.materials if m.key == key)

    def condition(self, key: str) -> Condition | None:
        return next((c for c in self.conditions if c.key == key), None)

    def refs(self) -> set[str]:
        out: set[str] = set()
        for m in self.materials:
            out |= {r for x in (*m.good, *m.watch) for r in x.cites}
        out |= {r for x in self.rules for c in x.why for r in c.cites}
        out |= {r for c in self.checklists.values() for i in c.items for r in i.cites}
        out |= {r for q in self.vendor_questions for r in q.cites}
        out |= {r for xs in self.notes.values() for x in xs for r in x.cites}
        return out

    def all_text(self) -> str:
        """숫자 검사 허용 글: 묶음에 적힌 문장 전부."""
        return self.model_dump_json()


def load_pack(path: Path) -> Pack:
    return Pack.model_validate(json.loads(path.read_text(encoding="utf-8")))


# ---- 한 번의 맡김 ----
@dataclass
class ExpertTask:
    text: str  # 고객 글(가린 뒤)
    ctx: TurnContext
    facts: ProjectFacts | None = None
    policy: list[str] = field(default_factory=list)
    brief: dict[str, str] = field(default_factory=dict)  # 대화 기억 + 프로젝트 브리프
    slot: str | None = None  # 되물은 칸에 답한 턴
    value: str | None = None
    asked: str = ""  # 되물은 원래 질문
    whole: str = ""  # 복합 질문을 나눴을 때 고객 글 전체(다른 공종 이야기를 가려 보는 데만 씀)

    @property
    def question(self) -> str:
        """칸 답 턴이면 원래 질문으로 이어 간다."""
        return self.asked if self.slot and self.asked else self.text


@dataclass
class ExpertRun(Run):
    expert: Expert | None = None
    task: ExpertTask | None = None
    kb: KB | None = None

    @property
    def x(self) -> Expert:
        assert self.expert is not None
        return self.expert

    @property
    def t(self) -> ExpertTask:
        assert self.task is not None
        return self.task

    def known(self) -> dict[str, str]:
        """지금 아는 조건: 대화 기억 + 이번 턴에 알게 된 것."""
        return {**self.t.brief, **self.reply.memory}


@dataclass(frozen=True)
class Expert:
    code: str
    pack: Pack
    prompt: str
    prompt_version: str
    tools: tuple[Tool, ...]
    offline: Callable[[ExpertRun], None]

    @property
    def spec(self) -> TradeSpec:
        return BY_CODE[self.code]

    @property
    def ko(self) -> str:
        return self.spec.ko


# ---- 여러 전문가가 같이 쓰는 도구 · 글 ----
class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=120, description="찾을 말(고객 질문을 짧게)")


def search_tool(code: str, k: int = 6) -> Tool:
    def run(r: ExpertRun, a: SearchArgs) -> ToolOut:
        assert r.kb is not None
        res = search3.search(
            r.kb.ix, a.query, trades=[code], tags=r.kb.tags, k=k, policy_text=r.t.question
        )
        if not res.hits:
            return ToolOut(text="찾은 자료가 없어요.")
        lines = [f"[{h.ref}] {h.title[:40]} · {h.source_type}: {h.text[:220]}" for h in res.hits]
        if not res.enough:
            lines.append("(질문 낱말을 다 덮는 자료는 아니에요. 모르는 부분은 모른다고 하세요.)")
        r.reply.used_chunks.extend(h.ref for h in res.hits)
        return ToolOut(
            text="\n".join(lines),
            evidence="\n".join(f"{h.title} {h.text}" for h in res.hits),
            refs=tuple(h.ref for h in res.hits),
        )

    return Tool(
        name="search_knowledge",
        description="믿집 지식 자료(표준시방서 · 제조사 안내 · 공공 자료 · 분쟁 사례)에서 이 공종 근거를 찾는다. "
        "근거 번호 [K…]를 답 문장에 인용한다.",
        args=SearchArgs,
        run=run,
    )


class AnswerSentence(BaseModel):
    text: str = Field(max_length=300)
    cites: list[str] = Field(default=[], max_length=4)


class AnswerArgs(BaseModel):
    sentences: list[AnswerSentence] = Field(min_length=1, max_length=6)
    ask_slot: str | None = Field(
        default=None, description="조건을 하나 되물을 때 그 칸 key(아는 칸은 다시 묻지 않음)"
    )
    suggest: list[str] = Field(default=[], max_length=3, description="이어 물을 짧은 질문")


def answer_tool() -> Tool:
    def run(r: ExpertRun, a: AnswerArgs) -> ToolOut:
        sec = Section(
            title=f"[{r.x.ko}]",
            sentences=[Sentence(text=s.text, cites=s.cites) for s in a.sentences],
            source="llm",
            route="trade",
            trade=r.x.code,  # type: ignore[arg-type]
            sources=sources_of(r, [c for s in a.sentences for c in s.cites]),
        )
        allowed = "\n".join([*r.evidence, r.t.text, r.t.asked, r.x.pack.all_text()])
        before = len(r.reply.sections)
        r.reply.add(sec, allowed)
        if len(r.reply.sections) > before:  # 답 글이 도구가 만든 조각보다 먼저 보이게
            r.reply.sections.insert(0, r.reply.sections.pop())
        if a.ask_slot:
            ask_condition(r, a.ask_slot)
        r.reply.suggest.extend(x[:60] for x in a.suggest)
        r.done = True
        return ToolOut(text="답을 보냈어요.")

    return Tool(
        name="answer",
        description="고객에게 보일 답. 문장마다 근거 번호를 단다. 근거에 없는 숫자 · 업체 · 제품 이름은 쓰지 않는다.",
        args=AnswerArgs,
        run=run,
    )


def sources_of(r: ExpertRun, refs: list[str]) -> list[dict]:
    out, seen = [], set()
    for ref in refs:
        if r.kb is None or ref in seen or ref not in r.kb.ix.by_ref:
            continue
        seen.add(ref)
        it = r.kb.ix.by_ref[ref]
        out.append(
            {"ref": ref, "title": it.doc.title, "kind": it.doc.kind, "publisher": it.doc.pub}
        )
    return out


def cited_section(
    r: ExpertRun, lines: list[Cited], *, title: str = "", source: str = "card"
) -> Section | None:
    """묶음에 적어 둔 검증 문장을 그대로 묶음으로. 근거 번호는 보인 것으로 센다."""
    if not lines:
        return None
    refs = [c for x in lines for c in x.cites]
    r.shown.update(refs)
    r.reply.used_chunks.extend(refs)
    return Section(
        title=title or f"[{r.x.ko}]",
        sentences=[Sentence(text=x.text, cites=list(x.cites)) for x in lines],
        source=source,  # type: ignore[arg-type]
        route="trade",
        trade=r.x.code,  # type: ignore[arg-type]
        sources=sources_of(r, refs),
    )


def add_cited(r: ExpertRun, lines: list[Cited], *, title: str = "", source: str = "card") -> None:
    sec = cited_section(r, lines, title=title, source=source)
    if sec is not None:
        allowed = f"{r.x.pack.all_text()}\n{r.t.text}"
        r.reply.add(sec, allowed)


def ask_condition(r: ExpertRun, key: str) -> bool:
    """조건 하나를 되묻는다. 모르는 칸 · 이미 아는 칸이면 묻지 않는다."""
    c = r.x.pack.condition(key)
    if c is None or key in r.known() or r.reply.ask is not None:
        return False
    r.reply.ask = AskSlot(trade=r.x.code, slot=c.key, question=c.question, options=list(c.options))  # type: ignore[arg-type]
    return True


def match_option(cond: Condition, value: str) -> str | None:
    """고객 답에서 선택지 하나를 고른다(버튼 글 그대로 또는 답 안에 선택지 낱말)."""
    flat = re.sub(r"[\s·,]", "", value or "")
    for opt in cond.options:
        if re.sub(r"[\s·,]", "", opt) in flat:
            return opt
    return None


def policy_lines(spec: TradeSpec, flags: set[str]) -> list[str]:
    """정책 표시 질문에 먼저 붙이는 정해 둔 글(계산 엔진이 없는 공종 기준)."""
    lines: list[str] = []
    if "price" in flags and not spec.calc:
        lines.append(templates.PRICE_KNOWLEDGE.format(ko=spec.ko))
    if "period" in flags and not spec.calc:
        lines.append(templates.PERIOD_KNOWLEDGE.format(ko=spec.ko))
    if "vendor_reco" in flags:
        lines.append(templates.VENDOR_RECO)
    if "brand_reco" in flags:
        lines.append(templates.BRAND_RECO)
    if "defect_judgement" in flags:
        lines.append(templates.DEFECT)
    if "legal_case" in flags:
        lines.append(templates.OUT["legal"])
    if "diy" in flags and spec.risky_diy:
        lines.append(templates.DIY_RISKY.format(ko=spec.ko))
    if "my_house" in flags and not ({"price", "period"} & flags):
        lines.append(templates.MY_HOUSE)
    return lines


# ---- 전문가 한 번 돌리기 ----
def _user_text(r: ExpertRun) -> str:
    t = r.t
    known = r.known()
    lines = [f"고객 질문: {t.question}"]
    if t.slot and t.value:
        lines.append(f"되물은 칸({t.slot})에 고객이 답했어요: {t.value}")
    if known:
        lines.append("지금까지 알게 된 조건: " + " · ".join(f"{k}={v}" for k, v in known.items()))
    if t.policy:
        lines.append("정책 표시: " + ", ".join(t.policy))
    f = t.facts
    if f is not None:
        lines.append(
            f"프로젝트: 단계 {f.stage} · 고른 공정 {', '.join(f.trades) or '없음'} · "
            f"거주 {f.living or '모름'}"
        )
    return "\n".join(lines)


def system_text(x: Expert) -> str:
    conds = "\n".join(
        f"- {c.key}: {c.question} ({' / '.join(c.options)})" for c in x.pack.conditions
    )
    mats = ", ".join(f"{m.key}={m.name}" for m in x.pack.materials)
    return f"{x.prompt}\n\n## 브리프 칸\n{conds}\n\n## 자재 key\n{mats}"


def _new_run(x: Expert, task: ExpertTask, kb: KB, budget: Budget) -> ExpertRun:
    reply = Reply(route="trade", trade=x.code, agent=x.code)  # type: ignore[arg-type]
    return ExpertRun(reply=reply, budget=budget, expert=x, task=task, kb=kb)


def _slot_answer(r: ExpertRun) -> None:
    t = r.t
    if not (t.slot and t.value):
        return
    cond = r.x.pack.condition(t.slot)
    if cond is None:
        return
    got = match_option(cond, t.value)
    if got:
        r.reply.memory[cond.key] = got


async def run_expert(
    x: Expert, task: ExpertTask, kb: KB, *, budget: Budget, mode: str = "free"
) -> Reply:
    """전문가에게 맡긴다. LLM 모드면 도구 루프, 실패하면 무료 모드 판단으로 같은 몫을 낸다."""
    if mode == "llm":
        r = _new_run(x, task, kb, budget)
        _slot_answer(r)
        spec = AgentSpec(
            name=x.code, system=system_text(x), tools=x.tools, finish=answer_tool(), max_rounds=3
        )
        try:
            text = await loop(spec, r, _user_text(r))
            if not r.done and text:  # answer 도구 없이 글로 끝나면 그 글을 같은 검사로
                answer_tool().run(
                    r, AnswerArgs.model_validate({"sentences": [{"text": text[:300]}]})
                )
            if r.reply.sections or r.reply.cards or r.reply.vendor:
                r.reply.how = "llm"
                r.reply.prompts.append(x.prompt_version)
                return _finish(r)
        except (llm.LLMError, BudgetExceeded):
            pass  # 아래 무료 모드 답으로
    r = _new_run(x, task, kb, budget)
    _slot_answer(r)
    x.offline(r)
    r.reply.how = "offline"
    return _finish(r)


def _finish(r: ExpertRun) -> Reply:
    rep = r.reply
    rep.suggest = list(dict.fromkeys(s for s in rep.suggest if s))[:3]
    rep.used_chunks = list(dict.fromkeys(rep.used_chunks))
    if not rep.sections and not rep.cards and not rep.vendor and not rep.ask and not rep.unknown:
        where = r.x.spec.check_where
        rep.unknown = [templates.UNKNOWN, templates.UNKNOWN_WHERE.format(where=where)]
    return rep
