"""답 작성기 (LLM 모드, 지시문 composer_v1). 무료 답을 다시 쓰는 대신 근거 묶음으로 답 한 벌을 블록으로 쓴다.

흐름: 무료 몫(Part) → 근거 묶음(카드 · 조각 · 검색 위 조각 · 계산 결과 · 정해 둔 글, 모두 코드가 고름)
→ LLM 1회(JSON: verdict · lead · blocks · follow) → 블록을 Section으로 → 출력 검사(숫자 · 인용 · 금지 표현 · 누출)
→ 계산 묶음(source=calc)은 앞에 그대로 두고 작성기 묶음을 붙인다.
- 숫자는 계산 결과 · 근거 글에 있는 것만 통과한다(check.section). 인용은 이번 근거 묶음 ref만 남는다.
- verdict가 unknown이거나 첫 문장(lead)이 검사에서 빠지면 None → 부르는 쪽은 무료 답을 그대로 쓴다.
- 지시문은 고정 글이라 앞쪽 1,600토큰쯤이 캐시돼요(OpenAI 자동 캐시는 1,024토큰부터).
"""

import json
import re
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agent import llm
from app.agent.v3 import check, llm_mode
from app.agent.v3.answer import KB, Part, search
from app.agent.v3.schemas import Section, Sentence, TradeCode

PROMPTS = Path(__file__).with_name("prompts")
VERSION = "composer_v1"
TOP_CHUNKS = 6  # 검색 위 조각을 몇 개 더 넣을지
CHUNK_CHARS = 420  # 조각 글 앞 몇 글자
MAX_BLOCKS = 4
MAX_ITEMS = 5


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
    for h in search(kb, question, trade).hits[:TOP_CHUNKS]:
        if h.ref in kb.ix.by_ref and h.ref not in chunks:
            it = kb.ix.by_ref[h.ref]
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
    return {"data": data, "refs": refs, "allowed": allowed, "calc": " ".join(calc)}


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

    def sent(it: CItem) -> Sentence:
        cites: list[str] = []
        for x in it.cites[:3]:
            if x in refs:
                cites.append(x)
                if x.startswith("card:"):
                    cites += _card_chunks(part, x)
        return Sentence(text=it.text.strip(), cites=list(dict.fromkeys(cites)))

    calc_nums = check.guard.numbers(calc) if calc else set()

    def checked(sec: Section) -> Section | None:
        if calc_nums:  # 계산 묶음이 이미 보이는 숫자만 든 문장은 되풀이라서 뺀다
            keep = []
            for x in sec.sentences:
                n = check.guard.numbers(x.text)
                if n and n <= calc_nums:
                    dropped.append("계산 되풀이")
                else:
                    keep.append(x)
            if not keep:
                return None
            sec = sec.model_copy(update={"sentences": keep})
        kept, why = check.section(sec, allowed, calc_text=calc or None, shown=None, prompt=rules())
        dropped.extend(why)
        return kept

    used: set[str] = set()
    lead = checked(Section(sentences=[sent(c.lead)], source="llm", route=route, trade=trade))
    if lead is None and not calc:
        return None  # 계산 묶음이 있으면 그 묶음이 첫 줄 노릇을 해서 lead가 빠져도 이어 간다
    out = [lead] if lead else []
    for b in c.blocks[:MAX_BLOCKS]:
        items = [sent(x) for x in b.items[:MAX_ITEMS] if x.text.strip()]
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
    """작성기 한 번. 쓸 수 없으면 None(부르는 쪽은 무료 답 그대로)."""
    ev = evidence(part, kb, question, trade)
    if not (ev["data"]["카드"] or ev["data"]["근거"] or ev["data"]["계산 결과"]):
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
    calc = [s for s in part.sections if s.source == "calc"]
    new = Part(
        sections=[*calc, *secs], calc=list(part.calc), cards=list(part.cards), ask=part.ask,
        unknown=[] if c.verdict == "answer" else list(part.unknown),
        suggest=_follow(c.follow, ev) or list(part.suggest), used_cards=list(part.used_cards),
        used_chunks=list(part.used_chunks), dropped=list(part.dropped), route=part.route,
        trade=part.trade, scores=dict(part.scores),
    )  # fmt: skip
    return new


def _follow(qs: list[str], ev: dict) -> list[str]:
    """이어 물을 질문: 짧고 숫자 없는 것만 3개까지(숫자는 검사가 볼 근거가 없어요)."""
    out = []
    for q in qs[:3]:
        q = q.strip()
        if 4 <= len(q) <= 30 and not re.search(r"\d", q) and q not in out:
            out.append(q)
    return out
