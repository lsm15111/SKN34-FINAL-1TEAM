"""한 턴 (무료 · LLM 모드 공통). agents.md 2.1 · 10.1절.

가림 · 길이 → 입구 관문 → (범위 밖 · 되묻기 · 담당 하나 · 오케스트레이터) → 출력 검사.
LLM 모드(guide · trade · multi): 고정 몫(계산 결과 · 정해 둔 글)을 검사해 on_part로 먼저 보내고, 답 작성기 묶음을
그 아래에 붙인다. 먼저 보낸 묶음은 마지막 답에도 그대로 앞에 둬서 화면에 이미 보인 글은 바뀌지 않는다.
DB · HTTP를 모른다: 프로젝트 사실(ProjectFacts)과 지식(KB)은 chat.service가 짧은 DB 세션으로 읽어 넘긴다.
돌려주는 waiting은 되물은 담당의 칸(다음 턴의 짧은 답을 그 담당이 받게). 저장은 chat.service가 한다.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agent.v3 import brief, check, composer, llm_mode, orchestrator, policy, templates
from app.agent.v3 import gate as gate_mod
from app.agent.v3.answer import KB, T_HIGH, Part, Task
from app.agent.v3.schemas import (
    TEXT_MAX,
    AgentAnswer,
    Button,
    GeneralFacts,
    ProjectFacts,
    Section,
    Trace,
    TurnContext,
    UiCard,
)
from app.agent.v3.trades import BY_CODE, trades_in

# 사진 · 그림을 보여 달라는 말: 아직 그림 자료가 없어 안내 한 줄을 앞에 두고, 나머지 질문으로 답해요(ChatGPT 비교 G6)
PHOTO = re.compile(
    r"(?:사진|이미지|그림|영상)\s{0,3}(?:으로|로)?\s{0,3}(?:좀\s{0,2})?(?:보여|볼\s{0,2}수)\S{0,6}"
)
PHOTO_LINE = "사진은 아직 보여 드리지 못해요. 대신 글로 알려 드릴게요."
CHITCHAT = re.compile(r"로또|주식|코인|집값|영화|점심|저녁\s*뭐|강아지|번역|날씨|심심|노래|게임")


@dataclass
class TurnResult:
    answer: AgentAnswer
    waiting: dict | None  # {route, trade, slot, q} — chat.service가 짧게 보관
    label: str | None  # 분류기 라벨(대화 표 intent_label 기록용)
    confidence: float
    source: str


def suggest_of(p: Part) -> list[str]:
    """이어 묻기 버튼. 가까운 카드 질문(near)은 답 전체가 '확인하지 못했어요'일 때만 붙여요."""
    out = list(p.suggest)
    if templates.UNKNOWN in p.unknown:
        out += [x for x in p.near if x not in out]
    return out


def ignore_words(facts: ProjectFacts | None) -> list[str]:
    """업체 이름(예: '마루와벽')을 공종 낱말로 읽지 않게."""
    if facts is None:
        return []
    names = list(facts.visit_draft.vendors) if facts.visit_draft else []
    if facts.visit_draft:
        names += [r.vendor for r in facts.visit_draft.ranges]
    names += [e.vendor for e in facts.estimates]
    return sorted({n for n in names if n}, key=len, reverse=True)


def _out(text: str, flags: list[str], facts: ProjectFacts | None) -> Part:
    part = Part(route="out_of_scope")
    found = trades_in(text)
    if "legal_case" in flags:
        line = templates.OUT["legal"]
    elif policy.calc_request(text) and found and not BY_CODE[found[0]].calc:
        line = templates.OUT["calc"].format(ko=BY_CODE[found[0]].ko)
    elif CHITCHAT.search(text):
        line = templates.OUT["chat"]
    else:
        line = templates.OUT["service"]
    part.add(templates.section([line], route="out_of_scope"), f"{line}\n{templates.ALLOWED}")
    nxt = templates.NEXT.get(facts.stage, []) if facts else templates.NO_PROJECT_NEXT
    part.cards.append(UiCard(kind="next_step", choices=list(nxt)))
    return part


async def _llm(part: Part, kb: KB, question: str) -> tuple[Part, list[str]]:
    """카드 · 조각 묶음만 다시 쓴다. 점수 높은 카드 · 정해 둔 글 · 계산 묶음은 그대로(카드 먼저)."""
    used: list[str] = []
    calc = " ".join(f"{c.label} {c.qty or ''}{c.unit} {c.amount or ''} {c.note}" for c in part.calc)
    out = []
    for sec in part.sections:
        tag = next((c for x in sec.sentences for c in x.cites if c.startswith("card:")), None)
        if sec.source == "card" and tag and part.scores.get(tag, 0) >= T_HIGH:
            out.append(sec)
            continue
        refs = {c for x in sec.sentences for c in x.cites if c.startswith("K")}
        evidence = {r: kb.ix.by_ref[r].chunk.text for r in refs if r in kb.ix.by_ref}
        new, dropped = await llm_mode.rewrite(
            sec, route=sec.route, question=question, evidence=evidence, calc=calc
        )
        part.dropped.extend(dropped)
        if new is not None and sec.route in llm_mode.VERSION:
            used.append(sec.route)
        out.append(new or sec)
    part.sections = out
    return part, list(dict.fromkeys(used))


async def run_turn(
    text: str,
    ctx: TurnContext,
    *,
    kb: KB,
    facts: ProjectFacts | None = None,
    waiting: dict | None = None,
    button: Button | None = None,
    on_part: Callable[[AgentAnswer], Awaitable[None]] | None = None,
    general: GeneralFacts | None = None,
) -> TurnResult:
    masked = check.mask(text or "").strip()[:TEXT_MAX]
    photo = PHOTO.search(masked) is not None
    if photo:
        rest = PHOTO.sub(" ", masked).strip(" ,.?")
        masked = rest or masked
    w_route = waiting.get("route") if waiting else None
    g = gate_mod.gate(
        masked, view=ctx.view, waiting=w_route, button=button, has_project=facts is not None,
        ignore=ignore_words(facts),
    )  # fmt: skip
    slot = value = None
    asked = ""
    if waiting and waiting.get("slot") and (g.source == "waiting" or (button and button.slot)):
        slot = waiting["slot"]
        value = (button.value if button and button.value else masked)[:40]
        asked = waiting.get("q", "")
        if waiting.get("trade"):
            g = g.model_copy(update={"route": "trade", "trades": [waiting["trade"]]})
    task = Task(text=masked, route=g.route, trades=g.trades, policy=g.policy, ctx=ctx, facts=facts,
                slot=slot, value=value, asked=asked, general=general)  # fmt: skip
    names: list[str] = []
    failed_parts = 0
    if g.route == "out_of_scope":
        part = _out(masked, g.policy, facts)
    elif g.route == "ask_back":
        part = Part(route="ask_back")
        part.add(templates.section([templates.ASK_BACK], route="ask_back"), templates.ASK_BACK)
        part.cards.append(UiCard(kind="choices", title="궁금한 것", choices=g.candidates))
    elif g.route == "multi":
        part, names, failed_parts = orchestrator.run(task, kb)
    else:
        part = orchestrator.AGENTS[g.route](task, kb)
    if photo and g.route not in ("out_of_scope", "ask_back"):
        part.sections.insert(0, templates.section([PHOTO_LINE], route=g.route))

    def finish(p: Part, routes: list[str], shown: list[Section] | None = None) -> AgentAnswer:
        """검사 · 짧은 답. shown: 화면에 먼저 보낸 고정 묶음(검사를 마친 것)이라 그대로 앞에 두고 나머지만 검사해요."""
        prompts = [composer.VERSION if r == "composer" else llm_mode.VERSION[r] for r in routes]
        boxes = list({b.ref: b for b in reversed(p.calc)}.values())[::-1]  # 같은 값 상자는 하나만
        rest = (
            p.sections
            if shown is None
            else [s for s in p.sections if s.source not in composer.FIXED]
        )
        ans = AgentAnswer(
            sections=rest, calc=boxes, cards=p.cards, ask=p.ask,
            unknown=p.unknown, suggest=suggest_of(p)[:3],
            trace=Trace(
                route=g.route, source=g.source, confidence=g.confidence, trades=g.trades,
                policy=g.policy, mode=ctx.mode, cards=list(dict.fromkeys(p.used_cards)),
                chunks=list(dict.fromkeys(p.used_chunks)), prompts=prompts,
                card_set=kb.cards.version, parts=names, failed_parts=failed_parts, dropped=p.dropped,
            ),
        )  # fmt: skip
        texts = [composer.rules() if r == "composer" else llm_mode.prompt(r) for r in routes]
        ans = check.final(ans, prompt="\n".join(texts) or None)
        if shown is not None:
            ans.sections = [*shown, *ans.sections]
            ans.failed = not (ans.sections or ans.cards or ans.calc or ans.unknown)
            ans.fixed = len(shown)
            return ans  # 먼저 보인 글이 접힌 짧은 답으로 바뀌지 않게 통째로 보여요(brief 없음)
        ans.brief = brief.make(ans, masked)  # 검사를 통과한 문장에서만 고른다(새 글 없음)
        if "composer" in routes:
            ans.brief = None  # 작성기 답은 블록 한 벌이 이미 짧아서 통째로 보여요
        if ans.sections and ans.sections[0].title == "[시작 순서]":
            ans.brief = None  # 단계 목록은 잘라 보이면 순서가 끊겨서 통째로 보여요
        if any(s.table for s in ans.sections):
            ans.brief = None  # 표는 짧은 답에 들어가지 않아서, 표가 있는 답은 통째로 보여요
        if photo and ans.brief and ans.sections and ans.sections[0].sentences[:1]:
            first = ans.sections[0].sentences[0]
            if first.text == PHOTO_LINE and first not in ans.brief.lines:
                ans.brief.lines = [first, *ans.brief.lines][:3]  # 사진 안내는 짧은 답에도 맨 앞에
        return ans

    routes: list[str] = []
    shown: list[Section] | None = None
    if ctx.mode == "llm" and g.route in ("guide", "trade", "multi"):
        # 고정 몫(계산 결과 · 정해 둔 글)만 검사해 먼저 보낸다. 비어 있어도 보내서 화면이 'AI가 쓰는 중'을 알아요.
        # 카드 · 계산 상자 · 이어 묻기는 마지막 답에만 둬요(먼저 보인 글 아래로 이어 붙게)
        fixed = Part(
            sections=[s for s in part.sections if s.source in composer.FIXED],
            route=part.route, trade=part.trade,
        )  # fmt: skip
        first = finish(fixed, [])
        first.failed, first.brief, first.fixed = False, None, len(first.sections)
        shown = first.sections
        if on_part is not None:
            await on_part(first)
        # 답 작성기 한 번(근거 묶음 → 블록). 근거가 질문에 안 맞거나 실패하면 무료 몫(카드 · 조각)을 붙여요
        composed = await composer.compose(part, kb, masked, trade=g.trades[0] if g.trades else None)
        if composed is not None:
            part, routes = composed, ["composer"]
    ans = finish(part, routes, shown)
    new_wait = None
    if ans.ask is not None:
        new_wait = {"route": "trade", "trade": ans.ask.trade, "slot": ans.ask.slot, "q": masked}
    return TurnResult(ans, new_wait, g.label, g.confidence, g.source)
