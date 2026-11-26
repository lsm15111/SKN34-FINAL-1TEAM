"""공종 에이전트 판단 루프(LLM 모드에서만, docs/v3/floor-agent.md 4.2 · 4.4). 처음 적용한 공종은 바닥이에요.

- LLM은 도구를 고르고 인자만 채워요. 실행 · 결과 · 검사는 코드가 해요. DB에 쓰지 않아요.
- 상한: 도구 라운드 4번 · LLM 호출 6번(v2/ask.py와 같음). 도구 라운드를 다 쓰면 도구 없이 답만 받아요.
- 응답 형식(JSON): {"sentences": [{"text", "cites"}]}. 형식이 틀리면 한 번만 다시 쓰게 해요.
- LLM 실패 · 상한 초과 · 검사 뒤 남은 문장 없음 → part=None(호출한 쪽이 규칙 기반 기본 응답(폴백)을 그대로 씀).
- 근거 검사: 문장과 근거 글의 2-gram(바이그램)이 OVERLAP 이상 겹친 근거 번호만 남겨요. 근거 없는 설명 문장은
  빼고, 확인할 곳을 알려 주는 문장만 근거 없이 둬요.
- 범위 검사: 공종 도구 모음의 scope가 고정 정책 문구를 돌려주면 그 문장을 그 문구로 바꿔요.
- 답 먼저: 에이전트 응답이 맨 앞이라 첫 문장부터 답해요. 기본 응답의 고정 정책 문구(정책 · 주의 고지)는
  '꼭 알릴 것'으로 넘겨 답 안에 넣게 하고, 코드는 그 뜻이 빠졌는지만 봐서(COVER) 빠진 고지만 답 뒤에 붙여요.
- 공종 도구 모음(Toolbox)의 상태 객체는 hits(보인 근거) · calc_refs(계산 상자 번호) · ask · handoff를 가져야 해요.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.agent import llm
from app.agent.v3 import check, templates
from app.agent.v3.answer import KB, Part, Task, calc_box
from app.agent.v3.llm_mode import LlmSection
from app.agent.v3.llm_mode import _data as data_text
from app.agent.v3.schemas import Section, Sentence
from app.agent.v3.specialists import registered
from app.agent.v3.trades import BY_CODE
from app.knowledge import bm25

VERSION = (
    "trade_agent_v3"  # v1 첫 평가(근거 맞는 답 44/60) · v2 첫 문장 답 · 다시 검색 · v3 꼭 알릴 것
)
PROMPT = Path(__file__).with_name("prompts") / f"{VERSION}.md"
MAX_TOOL_ROUNDS = 4
MAX_CALLS = 6
MAX_CALLS_PER_ROUND = 3
MAX_SENTENCES = 5
FIX = '응답 형식(JSON)이 맞지 않아요. {"sentences": [{"text": "...", "cites": ["K123"]}]} JSON 하나로만 다시 써 주세요.'
_JSON = re.compile(r"\{.*\}", re.DOTALL)
# 문장 2-gram(바이그램) 중 근거 글에도 있는 비율. 카드 문장 1,414개로 측정(2026-11-26): 0.25면 사람이 쓴 문장의
# 99.2%가 넘고, 무관한 근거 글과 짝지으면 0.8%만 넘어요
OVERLAP = 0.25
# 고객 질문 낱말을 받아 쓴 답('고무 매트를 오래 깔아 두면 …')은 근거만으로 0.25가 안 나와요. 근거와 0.15 이상,
# 근거 + 질문과 0.4 이상 겹치면 통과(카드 문장으로 측정: 사람이 쓴 문장 99.3% · 무관한 글 1.1% 통과, 2026-11-26)
OVERLAP_LOW, OVERLAP_Q = 0.15, 0.4
# 앞 문장이 검사에서 빠진 뒤 남은 첫 문장 앞의 접속사는 떼요(바닥 평가 f52)
LEAD = re.compile(r"^(?:다만|또한|그리고|그래서|따라서|하지만|그러나|게다가|특히)\s*,?\s*")
GUIDE = re.compile(r"확인|물어|문의")
# (고정 정책 문구에 든 열쇠 말, 그 뜻이 에이전트 응답에 이미 있는지 보는 패턴). 열쇠는 templates 문구의 일부라
# 문구를 바꾸면 같이 맞춰요. 짝이 없는 고지는 늘 답 뒤에 붙여요
COVER = (
    ("금액은 실측 뒤 업체 견적서", re.compile(r"견적서|견적.{0,12}(?:확인|비교|받)")),
    ("기간은 집을 본 뒤", re.compile(r"기간.{0,24}(?:업체|실측|집을 본)|(?:업체|실측).{0,24}기간")),
    (
        "믿집이 판정하지 않아요",
        re.compile(
            r"(?:판정|단정|판단).{0,40}(?:사진|기록)|(?:사진|기록).{0,40}(?:업체|상담|1372)"
        ),
    ),
    ("추천하지 않아요", re.compile(r"추천(?:하지|은\s*하지|드리지|은\s*어려|하기\s*어려)")),
    ("전문 업체에 맡기는 게 안전", re.compile(r"전문\s*업체")),
    ("직접 봐야 정확히", re.compile(r"실측|직접\s*(?:보|확인)")),
)


@dataclass(frozen=True)
class Toolbox:
    defs: list[dict]
    call: Callable[..., Any]  # (name, arguments, task, kb, state) → Out(content, ok, end_turn)
    state: Callable[[], Any]
    scope: Callable[[str], str | None] | None = None  # 범위 밖 말이면 바꿔 넣을 고정 정책 문구


@dataclass
class Result:
    part: Part | None
    why: str  # ok · ask · llm_error · over_budget · bad_format · all_dropped
    calls: int = 0
    rounds: int = 0
    tools: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "cached": 0, "output": 0})
    dropped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # 근거 검사에서 빠진 문장(평가 기록용)


def system(code: str) -> str:
    base = PROMPT.read_text(encoding="utf-8").rstrip()
    sp = registered().get(code)
    if sp is None or sp.prompt_path is None:
        return base
    return f"{base}\n\n{sp.prompt_path.read_text(encoding='utf-8')}"


def user_message(task: Task, notes: list[str] | None = None) -> str:
    lines = [f"고객 질문: {check.mask(task.text)}"]
    if task.slot and task.value:
        lines += [
            f"앞에서 물은 것: {check.mask(task.asked)}",
            f"고객이 고른 답: {check.mask(task.value)}",
        ]
    if notes:
        lines.append("꼭 알릴 것(첫 문장은 질문의 답으로 두고, 이 뜻을 답 안에 자연스럽게 넣어):")
        lines += [f"- {n}" for n in notes]
    return "\n".join(lines)


def notices(free: Part) -> list[str]:
    """규칙 기반 기본 응답에 든 고정 정책 문구(고지) 문장들."""
    return [x.text for sec in free.sections if sec.source == "template" for x in sec.sentences]


def missing(notes: list[str], sents: list[Sentence]) -> list[str]:
    """에이전트 응답에 뜻이 빠진 고지만 돌려줘요. COVER 패턴이 없는 고지는 늘 남겨요."""
    text = " ".join(x.text for x in sents)
    out = []
    for n in notes:
        rule = next((pat for key, pat in COVER if key in n), None)
        if rule is None or not rule.search(text):
            out.append(n)
    return out


def parse(text: str) -> list[Sentence] | None:
    m = _JSON.search(text or "")
    if m is None:
        return None
    try:
        sec = LlmSection.model_validate(json.loads(m.group(0)))
    except (json.JSONDecodeError, ValidationError):
        return None
    out = [Sentence(text=x.text.strip(), cites=x.cites) for x in sec.sentences if x.text.strip()]
    return out[:MAX_SENTENCES] or None


def overlap(text: str, refs: list[str], kb: KB, extra: str = "") -> float:
    g = set(bm25.grams(text))
    have = {x for r in refs if r in kb.ix.by_ref for x in bm25.grams(kb.ix.by_ref[r].chunk.text)}
    have |= set(bm25.grams(extra))
    return len(g & have) / len(g) if g else 0.0


def grounded(text: str, refs: list[str], kb: KB, question: str) -> bool:
    c = overlap(text, refs, kb)
    return c >= OVERLAP or (c >= OVERLAP_LOW and overlap(text, refs, kb, question) >= OVERLAP_Q)


def ground(
    sec: Section, kb: KB, scope: Callable[[str], str | None] | None, question: str = ""
) -> tuple[Section | None, list[str], list[str]]:
    """범위 밖 문장은 고정 정책 문구로 바꾸고, 근거와 안 맞는 번호 · 문장은 빼요. 남은 문장이 없으면 None.

    고정 정책 문구는 고객이 그 일을 물었을 때만 넣고, 묻지 않았는데 나온 범위 밖 문장은 빼기만 해요."""
    out: list[Sentence] = []
    dropped: list[str] = []
    removed: list[str] = []  # 빠진 문장(평가 기록용, 답 · 로그에는 남기지 않음)
    asked = scope(question) if scope else None
    for x in sec.sentences:
        fixed = scope(x.text) if scope else None
        if fixed and fixed == asked:
            if all(o.text != fixed for o in out):
                out.append(Sentence(text=fixed))
            dropped.append("범위 밖 말을 정해 둔 글로 바꿈")
            continue
        if fixed:
            dropped.append("묻지 않은 범위 밖 말")
            continue
        refs = [r for r in x.cites if r in kb.ix.by_ref]
        good = [r for r in refs if grounded(x.text, [r], kb, question)]
        if not good and refs and grounded(x.text, refs, kb, question):
            good = refs  # 근거 둘을 합쳐 한 문장으로 쓴 경우
        if good:
            out.append(x.model_copy(update={"cites": good}))
        elif GUIDE.search(x.text):
            out.append(x.model_copy(update={"cites": []}))
        else:
            dropped.append("근거와 안 맞는 문장" if refs else "근거 없는 문장")
            removed.append(x.text)
    if not out:
        return None, dropped, removed
    if sec.sentences and out[0].text != sec.sentences[0].text:  # 첫 문장이 빠졌으면 접속사를 뗀다
        first = LEAD.sub("", out[0].text)
        out[0] = out[0].model_copy(update={"text": first or out[0].text})
    return sec.model_copy(update={"sentences": out}), dropped, removed


def _merge(part: Part, other: Part) -> None:
    part.sections += other.sections
    part.calc += other.calc
    part.cards += other.cards
    part.unknown += other.unknown
    part.used_cards += other.used_cards
    part.used_chunks += other.used_chunks
    part.dropped += other.dropped


def _ask_part(task: Task, free: Part, st: Any) -> Part:
    code = st.ask.trade
    part = Part(route="trade", trade=code, ask=st.ask)
    part.add(
        templates.section(
            [st.ask.question], title=f"[{BY_CODE[code].ko}]", route="trade", trade=code
        ),
        st.ask.question,
    )
    notes = notices(free)
    if notes:  # 되묻기가 먼저, 고지는 뒤에
        part.add(templates.section(notes, route="trade", trade=code), "\n".join(notes))
    return part


def build(
    task: Task,
    kb: KB,
    free: Part,
    st: Any,
    sents: list[Sentence],
    prompt: str,
    tool_text: list[str],
    scope: Callable[[str], str | None] | None = None,
    removed: list[str] | None = None,
) -> tuple[Part | None, list[str]]:
    """에이전트 응답을 검사해 담당 응답(Part)으로 만든다. 숫자 · 근거 번호 · 지시문 누출은 check.section이 걸러요."""
    code = free.trade or task.trades[0]
    hits = st.hits
    boxes = [b for b in (calc_box(r, task.facts) for r in st.calc_refs) if b is not None]
    calc_text = " ".join(
        f"{c.label} {c.qty or ''}{c.unit} {c.amount or ''} {c.note}" for c in boxes
    )
    sec = Section(
        title=f"[{BY_CODE[code].ko}]", source="llm", route="trade", trade=code, sentences=sents
    )
    evidence = [kb.ix.by_ref[r].chunk.text for r in hits if r in kb.ix.by_ref]
    notes = notices(free)
    allowed = "\n".join(
        [*evidence, *tool_text, *notes, task.text, task.asked, task.value or "", calc_text]
    )
    kept, dropped = check.section(sec, allowed, calc_text=calc_text, shown=set(hits), prompt=prompt)
    if kept is not None:
        kept, more, gone = ground(kept, kb, scope, task.search_text)
        dropped += more
        if removed is not None:
            removed += gone
    if kept is None:
        return None, dropped
    cited = list(dict.fromkeys(c for x in kept.sentences for c in x.cites if c in hits))
    kept.sources = [
        {
            "ref": r,
            "title": hits[r].title,
            "kind": hits[r].source_type,
            "publisher": hits[r].publisher,
        }
        for r in cited
    ]
    part = Part(route="trade", trade=code)  # type: ignore[arg-type]
    part.sections = [kept]
    tail = missing(notes, kept.sentences)
    if tail:  # 에이전트 응답에 뜻이 빠진 고지만 답 뒤에(제목 없이)
        part.sections.append(templates.section(tail, route="trade", trade=code))
    part.calc = boxes
    part.cards = [c for c in free.cards if c.kind == "next_step"]
    part.used_chunks = cited
    part.dropped = dropped
    if st.handoff is not None:
        _merge(part, st.handoff)
    return part, dropped


async def run(task: Task, kb: KB, free: Part, box: Toolbox) -> Result:
    """한 턴 판단 루프. free는 같은 턴의 규칙 기반 기본 응답(고정 정책 문구의 출처이자 폴백)."""
    code = free.trade or task.trades[0]
    prompt = system(code)
    st = box.state()
    messages: list[dict] = [{"role": "user", "content": user_message(task, notices(free))}]
    res = Result(part=None, why="over_budget")
    tool_text: list[str] = []
    retried = False
    while res.calls < MAX_CALLS:
        offer = box.defs if res.rounds < MAX_TOOL_ROUNDS else []
        try:
            r = await llm.chat_tools(prompt, messages, offer)
        except llm.LLMError:
            res.why = "llm_error"
            return res
        res.calls += 1
        for k in res.usage:
            res.usage[k] += int((r.get("usage") or {}).get(k) or 0)
        calls = r.get("tool_calls") or []
        if calls and offer:
            res.rounds += 1
            messages.append(
                {"role": "assistant", "content": r.get("text") or "", "tool_calls": calls}
            )
            for i, c in enumerate(calls):
                if i >= MAX_CALLS_PER_ROUND:
                    content = json.dumps(
                        {"error": "한 번에 도구는 3개까지예요"}, ensure_ascii=False
                    )
                    end = False
                else:
                    out = box.call(c["name"], c.get("arguments"), task, kb, st)
                    res.tools.append(c["name"])
                    content, end = data_text(out.content), out.end_turn
                    tool_text.append(content)
                messages.append(
                    {"role": "tool", "tool_call_id": c.get("id") or "", "content": content}
                )
                if end:
                    res.part, res.why = _ask_part(task, free, st), "ask"
                    return res
            continue
        sents = parse(r.get("text") or "")
        if sents is None:
            if retried:
                res.why = "bad_format"
                return res
            retried = True
            messages += [
                {"role": "assistant", "content": r.get("text") or ""},
                {"role": "user", "content": FIX},
            ]
            continue
        res.part, res.dropped = build(
            task, kb, free, st, sents, prompt, tool_text, box.scope, res.removed
        )
        res.why = "ok" if res.part is not None else "all_dropped"
        return res
    return res
