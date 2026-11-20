"""답 작성기 (LLM 모드, 지시문 composer_v3). 무료 답을 다시 쓰는 대신 근거 묶음으로 답 한 벌을 블록으로 쓴다.

흐름: 무료 몫(Part) → 근거 묶음(카드 · 조각 · 검색 위 조각 · 계산 결과 · 정해 둔 글, 모두 코드가 고름)
→ LLM 1회(JSON: verdict · lead · blocks · follow) → 블록을 Section으로 → 출력 검사(숫자 · 인용 · 금지 표현 · 누출)
→ 고정 몫(source=calc · template, 계산 결과 · 정해 둔 글)은 원래 순서대로 앞에 그대로 두고 작성기 묶음을 붙인다.
  고정 몫은 화면에 먼저 보이고(SSE part), 작성기 묶음은 그 아래에 이어 붙어요. 이미 보인 글은 바꾸지 않아요.
- 계산만 있는 답도 부른다: 검색 위 조각으로 숫자를 읽는 법 · 늘어나는 조건 · 준비를 덧붙인다(숫자 되풀이는 뺌).
- 숫자는 계산 결과 · 근거 글에 있는 것만 통과한다(check.section). 인용은 이번 근거 묶음 ref만 남는다.
- verdict가 unknown이거나 첫 문장(lead)이 검사에서 빠지면 None → 부르는 쪽은 무료 답을 그대로 쓴다.
- 지시문은 고정 글이라 앞쪽 1,600토큰쯤이 캐시돼요(OpenAI 자동 캐시는 1,024토큰부터).
"""

import json
import math
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agent import llm
from app.agent.v3 import check, llm_mode, templates
from app.agent.v3.answer import KB, T_HIGH, Part, search
from app.agent.v3.schemas import Section, Sentence, TradeCode
from app.knowledge import bm25, cards

PROMPTS = Path(__file__).with_name("prompts")
VERSION = "composer_v3"
TOP_CHUNKS = 6  # 검색 위 조각을 몇 개 더 넣을지
CHUNK_CHARS = 420  # 조각 글 앞 몇 글자
MAX_BLOCKS = 4
MAX_ITEMS = 5
# 고정 몫: 코드가 만든 글(계산 결과 · 정해 둔 글). 작성기 답에서도 앞에 그대로 남아요
FIXED = ("calc", "template")


class CItem(BaseModel):
    text: str
    cites: list[str]


class CBlock(BaseModel):
    kind: Literal["body", "steps", "compare", "caution"]
    items: list[CItem]
    rows: list[list[str]]


class Composed(BaseModel):
    verdict: Literal["answer", "partial", "unknown"]
    lead: CItem
    blocks: list[CBlock]
    follow: list[str]


@cache
def prompt() -> str:
    return (PROMPTS / f"{VERSION}.md").read_text(encoding="utf-8")


@cache
def rules() -> str:
    """누출 검사에 쓰는 지시문 앞부분(규칙). 예시 답은 고객 답과 비슷한 게 정상이라 뺀다."""
    return prompt().split("## 예시")[0]


def _clean(s: str) -> str:
    return llm_mode._data(s)  # 경계 문자 · 숨은 글자 떼기(LLM 모드와 같은 규칙)


def evidence(part: Part, kb: KB, question: str, trade: TradeCode | None) -> dict:
    """근거 묶음(코드가 고름). 반환: {kind: [...]} + 'refs'(인용 허용 ref) + 'text'(숫자 허용 글)."""
    calc = [x.text for s in part.sections if s.source == "calc" for x in s.sentences]
    fixed = [x.text for s in part.sections if s.source == "template" for x in s.sentences]
    cards: list[dict] = []
    chunks: dict[str, dict] = {}
    for sec in part.sections:
        if sec.source not in ("card", "extract"):
            continue
        tag = next((c for x in sec.sentences for c in x.cites if c.startswith("card:")), None)
        if tag:
            cards.append({"ref": tag, "글": " ".join(x.text for x in sec.sentences)})
        for x in sec.sentences:
            for c in x.cites:
                if c.startswith("K") and c in kb.ix.by_ref and c not in chunks:
                    it = kb.ix.by_ref[c]
                    chunks[c] = {
                        "ref": c,
                        "제목": it.doc.title[:60],
                        "글": it.chunk.text[:CHUNK_CHARS],
                    }
    own = trade in (None, "common", "dobae", "mokgong")
    for h in search(kb, question, trade).hits[:TOP_CHUNKS]:
        if h.ref in kb.ix.by_ref and h.ref not in chunks:
            it = kb.ix.by_ref[h.ref]
            if own and it.scope == (bm25.OUT,):
                continue  # 도배 · 목공 · 공통 질문에 다른 공종(창호 등) 조각은 넣지 않아요
            chunks[h.ref] = {
                "ref": h.ref,
                "제목": it.doc.title[:60],
                "글": it.chunk.text[:CHUNK_CHARS],
            }
    data = {
        "계산 결과": [_clean(x) for x in calc],
        "정해 둔 글": [_clean(x) for x in fixed],
        "카드": [{**c, "글": _clean(c["글"])} for c in cards],
        "근거": [{**c, "글": _clean(c["글"])} for c in chunks.values()],
    }
    refs = {c["ref"] for c in cards} | set(chunks)
    allowed = "\n".join(
        [*calc, *fixed, *(c["글"] for c in cards), *(c["글"] for c in chunks.values()), question]
    )
    return {
        "data": data, "refs": refs, "allowed": allowed, "calc": " ".join(calc), "fixed": " ".join(fixed),
    }  # fmt: skip


def _sources(kb: KB, refs: set[str], part: Part) -> list[dict]:
    """인용한 조각의 출처 칸(원문 없음). 카드 ref는 그 카드 묶음이 이미 가진 출처를 쓴다."""
    out: list[dict] = []
    seen: set[str] = set()
    for sec in part.sections:
        tag = next((c for x in sec.sentences for c in x.cites if c.startswith("card:")), None)
        if tag in refs:
            for src in sec.sources:
                if src.get("ref") and src["ref"] not in seen:
                    out.append(src)
                    seen.add(src["ref"])
    for r in sorted(refs):
        if r.startswith("K") and r in kb.ix.by_ref and r not in seen:
            it = kb.ix.by_ref[r]
            out.append(
                {"ref": r, "title": it.doc.title, "kind": it.doc.kind, "publisher": it.doc.pub}
            )
            seen.add(r)
    return out


def _card_chunks(part: Part, tag: str) -> list[str]:
    """카드 ref를 인용한 문장 → 그 카드가 인용한 조각 ref(출처 번호가 붙게)."""
    for sec in part.sections:
        if any(tag in x.cites for x in sec.sentences):
            return [c for x in sec.sentences for c in x.cites if c.startswith("K")]
    return []


def to_sections(
    c: Composed, ev: dict, part: Part, kb: KB, *, route, trade, dropped: list[str]
) -> list[Section] | None:
    """블록 → 검사를 지난 Section들. lead가 빠지면 None."""
    refs: set[str] = ev["refs"]
    allowed, calc = ev["allowed"], ev["calc"]

    card_text = {c["ref"]: c["글"] for c in ev.get("data", {}).get("카드", [])}
    weight = _idf(kb) if kb is not None else None

    def support(text: str, ref: str) -> float:
        """문장과 인용(조각 · 카드)의 글자 묶음 겹침을 드문 묶음에 무게를 줘서 잰 값(0~1)."""
        sg = _grams(text)
        if ref.startswith("card:"):
            other = _grams(card_text.get(ref, ""))
        else:
            it = kb.ix.by_ref.get(ref) if kb is not None else None
            other = set(it.tf) if it is not None else set()
        if not sg or weight is None:
            return 1.0 if weight is None else 0.0
        tot = sum(weight(g) for g in sg)
        return sum(weight(g) for g in sg if g in other) / tot

    def sent(it: CItem) -> Sentence | None:
        """인용이 문장과 맞는지 본다(c2 답으로 고른 기준 SUPPORT). 맞는 인용만 남기고, 다 안 맞으면
        근거 묶음에서 가장 맞는 조각으로 고쳐요. 어느 조각과도 맞지 않으면 None(근거 없는 문장이라 뺌)."""
        cites: list[str] = []
        for x in [x for x in it.cites[:3] if x in refs]:
            if support(it.text, x) >= SUPPORT:
                cites.append(x)
        if not cites and weight is not None and refs:
            best = max(sorted(refs), key=lambda r: support(it.text, r))
            if support(it.text, best) >= SUPPORT:
                cites = [best]
                if it.cites:
                    dropped.append("인용 고침")
            else:
                dropped.append("인용 안 맞음")
                return None
        for x in list(cites):
            if x.startswith("card:"):
                cites += _card_chunks(part, x)
        return Sentence(text=it.text.strip(), cites=list(dict.fromkeys(cites)))

    def sents(items: list[CItem]) -> list[Sentence]:
        return [x for x in (sent(i) for i in items) if x is not None]

    calc_nums = check.guard.numbers(calc) if calc else set()
    shown = [_grams(x.text) for s in part.sections if s.source in FIXED for x in s.sentences]
    fixed_grams: set[str] = set().union(*shown) if shown else set()

    def covered(g: set[str]) -> bool:
        """문장 글자 묶음이 고정 몫(화면에 먼저 보인 글)에 이만큼(COVER, 드문 묶음에 무게) 들어 있으면 말만 바꾼 되풀이."""
        if not (g and fixed_grams and weight is not None):
            return False
        tot = sum(weight(x) for x in g)
        return tot > 0 and sum(weight(x) for x in g if x in fixed_grams) / tot >= COVER

    def repeat(text: str) -> str | None:
        n = check.guard.numbers(text)
        g = _grams(text)
        if calc_nums and n and n <= calc_nums:
            return "계산 되풀이"  # 계산 묶음이 이미 보이는 숫자만 든 문장 · 표 줄
        if any(_overlap(g, h) >= SAME for h in shown) or covered(g):
            return "정해 둔 글 되풀이"
        if fixed_grams and VAGUE.search(text.strip()):
            return "뻔한 말"  # 계산 · 정해 둔 글 아래에 '~에 따라 달라져요'만 덧붙이면 새 정보가 없어요
        return None

    def checked(sec: Section) -> Section | None:
        keep = []
        for x in sec.sentences:
            why = repeat(x.text)
            if why:
                dropped.append(why)
            elif META.search(x.text):
                dropped.append(
                    "자료 말"
                )  # '자료로 확인하지 못했어요' 같은 말은 답 문장에 두지 않아요
            else:
                keep.append(x)
        if not keep:
            return None
        sec = sec.model_copy(update={"sentences": keep})
        kept, why = check.section(sec, allowed, calc_text=calc or None, shown=None, prompt=rules())
        dropped.extend(why)
        return kept

    used: set[str] = set()
    first = sents([c.lead])
    lead = (
        checked(Section(sentences=first, source="llm", route=route, trade=trade)) if first else None
    )
    if lead is None and not (calc or ev.get("fixed")):
        return None  # 고정 몫(계산 · 정해 둔 글)이 있으면 그 글이 첫 줄 노릇을 해서 lead가 빠져도 이어 간다
    out = [lead] if lead else []
    for b in c.blocks[:MAX_BLOCKS]:
        items = sents([x for x in b.items[:MAX_ITEMS] if x.text.strip()])
        if b.kind == "caution":
            if items and out:
                one = checked(Section(sentences=items[:1], source="llm", route=route, trade=trade))
                if one is not None:
                    out[-1] = out[-1].model_copy(update={"caution": one.sentences[0]})
            continue
        if b.kind == "compare":
            rows = []
            for r in b.rows[:4]:
                if len(r) != 2:
                    continue
                why = repeat(" ".join(r))
                if why:
                    dropped.append(why)  # 계산 상자 · 계산 묶음이 이미 보인 값을 표로 다시 쓴 줄
                    continue
                cells = [Sentence(text=x.strip()) for x in r]
                ok = [
                    check.sentence_ok(x, check.guard.numbers(allowed), None, None, rules())[0]
                    for x in cells
                ]
                if all(ok):
                    rows.append([x.text for x in ok])  # type: ignore[union-attr]
            if len(rows) >= 2:
                cap = (
                    checked(Section(sentences=items, source="llm", route=route, trade=trade))
                    if items
                    else None
                )
                out.append(
                    Section(
                        sentences=cap.sentences if cap else [],
                        table=rows,
                        source="llm",
                        route=route,
                        trade=trade,
                    )
                )
            continue
        if not items:
            continue
        sec = checked(
            Section(
                sentences=items, source="llm", route=route, trade=trade, steps=b.kind == "steps"
            )
        )
        if sec is not None:
            out.append(sec)
    if not out:
        return None
    for sec in out:
        used |= {x for s in sec.sentences for x in s.cites}
        if sec.caution:
            used |= set(sec.caution.cites)
    srcs = _sources(kb, used, part)
    if srcs:
        out[0] = out[0].model_copy(update={"sources": srcs})
    return out


async def compose(part: Part, kb: KB, question: str, *, trade: TradeCode | None) -> Part | None:
    """작성기 한 번. 쓸 수 없으면 None(부르는 쪽은 무료 답 그대로).
    계산만 있는 답도 불러요: 숫자는 계산 묶음이 이미 보여서, 작성기는 검색 위 조각으로 덧붙일 것만 써요.
    카드 · 조각 근거가 하나도 없으면 부르지 않아요(덧붙일 것이 없어요)."""
    ev = evidence(part, kb, question, trade)
    if not (ev["data"]["카드"] or ev["data"]["근거"]):
        part.dropped.append("작성기: 근거 없음")
        return None
    messages = [
        ("system", prompt()),
        (
            "user",
            f"<자료>{json.dumps(ev['data'], ensure_ascii=False)}</자료>\n고객 질문: {check.mask(question)}",
        ),
    ]
    try:
        c = await llm.structured("composer", Composed, messages)
    except llm.LLMError:
        part.dropped.append("작성기 실패")
        return None
    if c.verdict == "unknown":
        part.dropped.append("작성기: 근거 부족")
        return None
    dropped: list[str] = []
    secs = to_sections(c, ev, part, kb, route=part.route, trade=part.trade, dropped=dropped)
    part.dropped.extend(dropped)
    if not secs:
        return None
    fixed = [s for s in part.sections if s.source in FIXED]
    new = Part(
        sections=[*fixed, *secs], calc=list(part.calc), cards=list(part.cards), ask=part.ask,
        # 일부만 답했으면 '확인하지 못했어요'는 빼고 확인할 곳 줄만 둬요(답 뒤에 모름이 붙으면 앞뒤가 안 맞아요)
        unknown=[] if c.verdict == "answer" else [u for u in part.unknown if u != templates.UNKNOWN],
        suggest=_follow(c.follow, kb) or list(part.suggest), near=list(part.near), used_cards=list(part.used_cards),
        used_chunks=list(part.used_chunks), dropped=list(part.dropped), route=part.route,
        trade=part.trade, scores=dict(part.scores),
    )  # fmt: skip
    return new


SAME = 0.5  # 정해 둔 글 · 계산 문장과 글자 묶음이 이만큼 겹치면 되풀이로 봐요
# 작성기 문장이 고정 몫 글에 이만큼(IDF 무게 포함률) 들어 있으면 말만 바꾼 되풀이로 빼요.
# c5 고정 몫 턴 AI 문장 44개: 되풀이는 0.47 이상, 새 정보는 0.36 이하(composer-v3.md)
COVER = 0.45
# 고정 몫 아래에 붙인 '~에 따라 (비용이) 달라져요' 같은 뻔한 끝맺음 문장(c6 · c7 금액 · 기간 질문에서 본 것)
VAGUE = re.compile(
    r"(?:에|과|와|지)\s{0,2}따라\s{0,2}(?:\S+\s{1,2}){0,3}"
    r"(?:달라(?:요|져요|질\s{1,2}수\s{1,2}있어요)|차이가\s{1,2}(?:있어요|나요|날\s{1,2}수\s{1,2}있어요))[.!]?$"
)
# 인용 지지 기준(IDF 무게 겹침). c2 답 인용 154쌍: 맞는 짝 86% 통과 · 섞은 짝 6.5% 통과(support_cal)
SUPPORT = 0.18


_IDF: dict[int, tuple[object, dict[str, float], float]] = {}  # 색인 하나만 들고 있어요


def _idf(kb: KB) -> Callable[[str], float]:
    """색인의 글자 묶음 IDF(흔한 '해요' · '에서'는 가볍게). 색인이 바뀔 때만 다시 셈."""
    ix = kb.ix
    hit = _IDF.get(id(ix))
    if hit is None or hit[0] is not ix:
        n = len(ix.items)
        table = {g: math.log((n + 1) / (d + 1)) + 1 for g, d in ix.df.items()}
        hit = (ix, table, math.log(n + 1) + 1)
        _IDF.clear()
        _IDF[id(ix)] = hit
    _, table, top = hit
    return lambda g: table.get(g, top)


META = re.compile(
    r"자료(?:로|에서|에는|에|상|만으로)|확인하지\s{0,2}못했|확인하기\s{0,2}어렵|근거(?:가|로|에)"
)


def _grams(t: str) -> set[str]:
    return set(bm25.grams(t))


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


ASK_USER = re.compile(r"(?:실래요|주실|주세요|알려\s{0,2}주|말씀해|인가요\?$|이신가요|하시나요)")


def _follow(qs: list[str], kb: KB | None) -> list[str]:
    """이어 물을 질문: 답할 수 있는 카드의 열쇠 질문으로만(누르면 그 카드가 답해요).
    고객에게 되묻는 말 · 숫자 든 말 · 카드와 멀리 떨어진 말은 버려요."""
    if kb is None:
        return []
    out: list[str] = []
    for q in qs[:3]:
        q = q.strip()
        if not (4 <= len(q) <= 30) or re.search(r"\d", q) or ASK_USER.search(q):
            continue
        best = cards.find(kb.cards, q, k=1)
        if best and best[0].score >= T_HIGH:
            key = best[0].card.keys[0]
            if key not in out:
                out.append(key)
    return out
