"""답 작성기 (LLM 모드, 지시문 composer_v9). 무료 답을 다시 쓰는 대신 근거 묶음으로 답 한 벌을 블록으로 쓴다.

흐름: 무료 몫(Part) → 근거 묶음(카드 · 조각 · 검색 위 조각 · 계산 결과 · 정해 둔 글, 모두 코드가 고름)
→ LLM 1회(JSON: new · verdict · lead · blocks · follow) → 블록을 Section으로 → 출력 검사(숫자 · 인용 · 금지 표현 · 누출)
→ 고정 몫(source=calc · template, 계산 결과 · 정해 둔 글)은 원래 순서대로 앞에 그대로 두고 작성기 묶음을 붙인다.
  고정 몫은 화면에 먼저 보이고(SSE part), 작성기 묶음은 그 아래에 이어 붙어요. 이미 보인 글은 바꾸지 않아요.
- 계산만 있는 답도 부른다: 검색 위 조각으로 숫자를 읽는 법 · 늘어나는 조건 · 준비를 덧붙인다(숫자 되풀이는 뺌).
- 숫자는 계산 결과 · 근거 글에 있는 것만 통과한다(check.section). 인용은 이번 근거 묶음 ref만 남는다.
- 질문 꼴(explain.kind)이 설명 · 우리 집이면: 공정 정보(코드 데이터)를 근거에 더하고, 근거로 받칠 수 없는 문장은
  일반 설명(source=general, 화면 표시 '일반 설명(믿집 자료 밖)')으로 둬요. 일반 설명은 숫자 · 업체 · 브랜드 · 하자 · 법률 ·
  위험한 작업 말이 없어야 하고, 공종 순서 말은 공종 순서 데이터와 맞아야 해요(explain.general_why).
  설명은 공종마다 블록(trade 칸)으로 길게 써요(MAX_BLOCKS_LONG). 확인할 곳 줄은 우리 집 꼴에만 붙여요.
- verdict가 unknown · none이거나, 고정 몫이 있는데 새 사실 칸(new)이 비거나, 문장이 다 빠지면 None
  → 부르는 쪽은 고정 몫만(고정 몫이 없으면 무료 답). 실패하면 무료 답을 그대로 쓴다.
- 지시문은 고정 글이라 앞쪽이 캐시돼요(OpenAI 자동 캐시는 1,024토큰부터). 질문 꼴 · 근거는 사용자 글에 넣어요.
"""

import json
import math
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.agent import llm
from app.agent.v3 import check, explain, llm_mode, templates
from app.agent.v3.answer import KB, T_HIGH, Part, search, trade_title, where_for
from app.agent.v3.schemas import Section, Sentence, TradeCode
from app.agent.v3.trades import BY_CODE, trades_in
from app.knowledge import bm25, cards

PROMPTS = Path(__file__).with_name("prompts")
VERSION = "composer_v9"  # v9: 퍼티 · 운송비 예시를 판 2026.11b 선택 줄(합계 밖)로 고침. v8: 표준 대비 비율 안 씀
TOP_CHUNKS = 6  # 검색 위 조각을 몇 개 더 넣을지
CHUNK_CHARS = 420  # 조각 글 앞 몇 글자
MAX_BLOCKS = 4
MAX_BLOCKS_LONG = 6  # 설명 질문: 개요 + 공종마다 블록(하는 일 · 순서 · 고를 것) + 주의
MAX_ITEMS = 5
# 질문 꼴: 설명 · 우리 집(explain.kind) · 화면(LLM 모드 데이터 화면에서 질문 분석기를 거친 턴, screen_tools)
Mode = Literal["explain", "house", "screen"]
KIND_KO = {
    None: "자료",
    "explain": "설명",
    "house": "우리 집",
    "screen": "화면",
}  # 지시문에 넘기는 꼴 이름
# 화면 꼴에서 공정 정보도 넣는 조각 꼴(뜻 · 방법 · 고를 것)
FACT_KINDS = frozenset({"what", "how", "choose", "other"})
# 고정 몫: 코드가 만든 글(계산 결과 · 정해 둔 글). 작성기 답에서도 앞에 그대로 남아요
FIXED = ("calc", "template")
# 작성기가 더할 것이 없었던 이유(실패와 달라요). 고정 몫이 있으면 무료 발췌를 붙이지 않아요(turn.py)
QUIET = frozenset(
    {"작성기: 덧붙일 것 없음", "작성기: 새 사실 없음", "작성기: 근거 부족", "작성기: 다 걸러짐"}
)


class CItem(BaseModel):
    text: str
    cites: list[str]


class CBlock(BaseModel):
    kind: Literal["body", "steps", "compare", "caution"]
    # 공종 블록(설명 질문에서 공종마다 하나): 묶음 제목 '[도배]' · '[목공]'이 붙어요. 빈 글이면 제목 없음
    trade: Literal["", "dobae", "mokgong"] = ""
    items: list[CItem]
    rows: list[list[str]]


class Composed(BaseModel):
    # 먼저 쓰는 칸: 근거에 있고 고정 몫에 없는, 질문과 관련 있는 새 사실(한 줄씩). 고정 몫이 있는데 비면 none으로 봐요.
    # 화면에 보이지 않아요. OpenAI 엄격 모드는 모든 칸을 필수로 보내서 기본값은 스텁 · 테스트용이에요
    new: list[str] = Field(default_factory=list)
    # none: 고정 몫(계산 · 정해 둔 글)이 이미 답했고 근거에 덧붙일 새 사실이 없어요(작성기 묶음을 붙이지 않아요)
    verdict: Literal["answer", "partial", "unknown", "none"]
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


_DOT = re.compile(r"\s*·\s*")


def _dots(c: Composed) -> Composed:
    """가운뎃점 앞뒤 띄어쓰기를 화면 글과 같게('문선·몰딩' → '문선 · 몰딩')."""

    def fix(it: CItem) -> CItem:
        return it.model_copy(update={"text": _DOT.sub(" · ", it.text)})

    blocks = [
        b.model_copy(update={"items": [fix(x) for x in b.items],
                             "rows": [[_DOT.sub(" · ", x) for x in r] for r in b.rows]})
        for b in c.blocks
    ]  # fmt: skip
    return c.model_copy(update={"lead": fix(c.lead), "blocks": blocks})


def evidence(
    part: Part,
    kb: KB,
    question: str,
    trade: TradeCode | None,
    mode: Mode | None = None,
    trades: list[str] | None = None,
    screen: dict | None = None,
    asks: list[tuple[str, str]] | None = None,
) -> dict:
    """근거 묶음(코드가 고름). 반환: {kind: [...]} + 'refs'(인용 허용 ref) + 'text'(숫자 허용 글).
    mode(설명 · 우리 집)면 공정 정보(코드 데이터, ref rule:…)를 더해요. 화면 꼴은 보는 화면(screen_tools.screen_text,
    계산 엔진 값) · 분석한 조각을 더하고, 뜻 · 방법 · 고를 것 조각이 있을 때만 공정 정보도 더해요."""
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
    with_facts = mode in ("explain", "house") or (
        mode == "screen" and any(k in FACT_KINDS for k, _ in asks or [])
    )
    rules = explain.facts(trades or ([trade] if trade else [])) if with_facts else []
    shown = [screen] if mode == "screen" and screen else []
    data = {
        "계산 결과": [_clean(x) for x in calc],
        "정해 둔 글": [_clean(x) for x in fixed],
        "카드": [{**c, "글": _clean(c["글"])} for c in cards],
        "근거": [{**c, "글": _clean(c["글"])} for c in chunks.values()],
    }
    if rules:
        data["공정 정보"] = rules
    if shown:
        data["보는 화면"] = [{**x, "글": _clean(x["글"])} for x in shown]
    if mode == "screen" and asks:
        data["질문 분석"] = [f"{k}: {_clean(t)}" for k, t in asks]
    every = [*rules, *shown]
    refs = {c["ref"] for c in cards} | set(chunks) | {r["ref"] for r in every}
    allowed = "\n".join(
        [*calc, *fixed, *(c["글"] for c in cards), *(c["글"] for c in chunks.values()),
         *(r["글"] for r in every), question]
    )  # fmt: skip
    return {
        "data": data, "refs": refs, "allowed": allowed, "calc": " ".join(calc), "fixed": " ".join(fixed),
        "rules": {r["ref"]: r["글"] for r in every}, "rule_src": explain.sources(every),
    }  # fmt: skip


def _sources(kb: KB, refs: set[str], part: Part, rule_src: dict | None = None) -> list[dict]:
    """인용한 조각의 출처 칸(원문 없음). 카드 ref는 그 카드 묶음이 이미 가진 출처를 쓴다.
    rule_src: 공정 정보 ref(rule:…) → 출처 칸(믿집 데이터). 자료 출처 뒤에 둬요(출처 번호가 자료부터 매겨지게)."""
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
    out += [rule_src[r] for r in sorted(refs) if rule_src and r in rule_src and r not in seen]
    return out


def _card_chunks(part: Part, tag: str) -> list[str]:
    """카드 ref를 인용한 문장 → 그 카드가 인용한 조각 ref(출처 번호가 붙게)."""
    for sec in part.sections:
        if any(tag in x.cites for x in sec.sentences):
            return [c for x in sec.sentences for c in x.cites if c.startswith("K")]
    return []


def to_sections(
    c: Composed,
    ev: dict,
    part: Part,
    kb: KB,
    *,
    route,
    trade,
    dropped: list[str],
    mode: Mode | None = None,
) -> list[Section] | None:
    """블록 → 검사를 지난 Section들. lead가 빠지면 None(설명 · 우리 집 꼴은 블록이 남으면 이어 가요).
    mode가 있으면 근거로 받칠 수 없는 문장은 일반 설명(source=general)으로 남겨요(explain.general_why를 지나야 해요)."""
    c = _dots(c)
    refs: set[str] = ev["refs"]
    allowed, calc = ev["allowed"], ev["calc"]
    # 화면 꼴: 보는 화면 글의 숫자. 인용을 비웠어도 숫자가 모두 화면 값이면 화면 인용 문장으로 봐요(3300 '밥값 · 차비')
    screen_nums = (
        check.guard.numbers(ev.get("rules", {}).get(SCREEN_REF, "")) if mode == "screen" else set()
    )

    # 카드 · 공정 정보(rule:…)는 근거 글이 묶음 안에 있어요. 조각(K…)은 색인 글자 묶음과 견줘요
    texts = {c["ref"]: c["글"] for c in ev.get("data", {}).get("카드", [])} | ev.get("rules", {})
    weight = _idf(kb) if kb is not None else None

    def support(text: str, ref: str) -> float:
        """문장과 인용(조각 · 카드 · 공정 정보)의 글자 묶음 겹침을 드문 묶음에 무게를 줘서 잰 값(0~1)."""
        sg = _grams(text)
        if ref.startswith("card:") or ref in texts:
            other = _grams(texts.get(ref, ""))
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

    def item(it: CItem) -> tuple[Sentence, bool] | None:
        """(문장, 일반 설명인가). mode가 있고 작성기가 인용을 비운 문장은 일반 설명이에요: 인용을 대신 붙이지 않고
        (자료에서 온 말처럼 보이지 않게) 일반 설명 규칙으로만 봐요. 인용을 달았으면 지금처럼 인용이 맞아야 해요."""
        if mode and not any(x.strip() for x in it.cites):
            nums = check.guard.numbers(it.text)
            if screen_nums and nums and nums <= screen_nums:
                it = it.model_copy(update={"cites": [SCREEN_REF]})  # 화면 숫자만 쓴 문장: 화면 인용
            else:
                why = explain.general_why(it.text)
                if why:
                    dropped.append(why)
                    return None
                return Sentence(text=it.text.strip()), True
        s = sent(it)
        if s is None:
            return None
        # 공정 정보만 인용한 순서 말도 공종 순서 데이터와 맞아야 해요
        only_rules = not any(x.startswith(("K", "card:")) for x in s.cites)
        if mode and only_rules and not explain.order_ok(s.text):
            dropped.append("순서 틀림")
            return None
        return s, False

    def runs(items: list[CItem]) -> list[tuple[list[Sentence], bool]]:
        """문장들 → (같은 출처끼리 이어진 문장들, 일반 설명인가). 근거 문장과 일반 설명은 묶음을 나눠 표시가 맞게 해요."""
        out: list[tuple[list[Sentence], bool]] = []
        for x in items:
            got = item(x)
            if got is None:
                continue
            s, g = got
            if out and out[-1][1] == g:
                out[-1][0].append(s)
            else:
                out.append(([s], g))
        return out

    calc_nums = check.guard.numbers(calc) if calc else set()
    fixed_texts = [x.text for s in part.sections if s.source in FIXED for x in s.sentences]
    calc_dates = bool(CALC_DATE.search(calc or "")) or any(CALC_DATE.search(t) for t in fixed_texts)
    shown = [_grams(t) for t in fixed_texts]
    fixed_grams: set[str] = set().union(*shown) if shown else set()

    def covered(g: set[str]) -> bool:
        """문장 글자 묶음이 고정 몫(화면에 먼저 보인 글)에 이만큼(COVER, 드문 묶음에 무게) 들어 있으면 말만 바꾼 되풀이."""
        if not (g and fixed_grams and weight is not None):
            return False
        tot = sum(weight(x) for x in g)
        return tot > 0 and sum(weight(x) for x in g if x in fixed_grams) / tot >= COVER

    guide_known = fixed_grams | _grams(GUIDE_WORDS)

    def guide_only(g: set[str]) -> bool:
        """고정 몫 · 안내 낱말로 덮이는 몫(드문 묶음 무게)이 CAN_COVER 이상이면 새 말이 없는 안내 문장."""
        if not g or weight is None:
            return False
        tot = sum(weight(x) for x in g)
        return tot > 0 and sum(weight(x) for x in g if x in guide_known) / tot >= CAN_COVER

    def repeat(text: str) -> str | None:
        n = check.guard.numbers(text)
        g = _grams(text)
        if calc_nums and n and n <= calc_nums:
            return "계산 되풀이"  # 계산 묶음이 이미 보이는 숫자만 든 문장 · 표 줄
        # 화면 꼴의 판단 문장('~보다 높은 편이에요')은 고정 몫과 같은 숫자를 써도 새 말이에요(고정 몫에 판단이 없을 때)
        judged = (
            mode == "screen"
            and JUDGE.search(text)
            and not any(JUDGE.search(t) for t in fixed_texts)
        )
        if not judged and (any(_overlap(g, h) >= SAME for h in shown) or covered(g)):
            return "정해 둔 글 되풀이"
        if order_repeat(text, fixed_texts, weight):
            return "순서 되풀이"  # 고정 몫이 이미 말한 두 공종 순서를 말만 바꿔 다시 쓴 문장
        if calc_dates and (DATE_TALK.search(text) or CALC_TALK.search(text)):
            return "날짜 되풀이"  # 계산 묶음이 보인 날짜 · 요일을 다시 말하거나 조건을 다는 문장
        if fixed_grams and GUIDE_END.search(text.strip()) and guide_only(g):
            return "안내 빈말"  # '~확인할 수 있어요 · 공정표를 참고해요'처럼 새 말 없이 안내만 하는 문장
        # 계산 · 정해 둔 글 아래에 '~에 따라 달라져요 · 정하기 어려워요'만 덧붙이면 새 정보가 없어요.
        # 우리 집 꼴은 대략 답을 하는 자리라 고정 몫이 없어도 이런 흐린 말을 빼요(끝 줄이 실측 확인을 말해요)
        if (fixed_grams or mode == "house") and (
            VAGUE.search(text.strip()) or HEDGE.search(text.strip())
        ):
            return "뻔한 말"
        if mode == "house" and DEFER.search(text.strip()):
            return "미루는 말"  # '~는 상담 때 정해요'만 하는 문장(끝 줄이 이미 확인할 곳을 말해요)
        return None

    def checked(sec: Section) -> Section | None:
        keep = []
        for x in sec.sentences:
            why = repeat(x.text)
            cut = x.text if why else trim_order_head(x.text, fixed_texts, weight)
            if cut != x.text:  # 문장 전체는 지났고 앞 절만 순서 되풀이: 뒤 절만 다시 검사해요
                dropped.append("순서 앞 절 뗌")
                x = x.model_copy(update={"text": cut})
                why = repeat(cut)
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

    def sections(
        items: list[CItem], *, title: str = "", code: TradeCode | None = None, steps: bool = False
    ) -> list[Section]:
        out: list[Section] = []
        for sents, g in runs(items):
            sec = checked(
                Section(sentences=sents, source="general" if g else "llm", route=route,
                        trade=code or trade, title=title, steps=steps and len(sents) >= 2)
            )  # fmt: skip
            if sec is not None:
                out.append(sec)
        return out

    used: set[str] = set()
    head = sections([c.lead])
    lead = head[0] if head else None
    if lead is None and not (calc or ev.get("fixed")) and not mode:
        return None  # 고정 몫(계산 · 정해 둔 글)이 있으면 그 글이 첫 줄 노릇을 해서 lead가 빠져도 이어 간다
    out = [lead] if lead else []
    limit = MAX_BLOCKS_LONG if mode in ("explain", "screen") else MAX_BLOCKS
    for b in c.blocks[:limit]:
        title = trade_title(b.trade) if b.trade else ""
        code = b.trade or None
        items = [x for x in b.items[:MAX_ITEMS] if x.text.strip()]
        if b.kind == "caution":
            if items and out:
                one = sections(items[:1])
                if one:
                    out[-1] = out[-1].model_copy(update={"caution": one[0].sentences[0]})
            continue
        if b.kind == "compare":
            cap = sections(items) if items else []
            general_rows = bool(mode) and not any(s.source == "llm" for s in cap)
            rows = []
            for r in b.rows[:4]:
                if len(r) != 2:
                    continue
                why = repeat(" ".join(r))
                if why:
                    dropped.append(why)  # 계산 상자 · 계산 묶음이 이미 보인 값을 표로 다시 쓴 줄
                    continue
                if general_rows and (why := explain.general_why(" ".join(r))):
                    dropped.append(why)  # 근거 없는 표 줄은 일반 설명 규칙을 지나야 해요
                    continue
                cells = [Sentence(text=x.strip()) for x in r]
                ok = [
                    check.sentence_ok(x, check.guard.numbers(allowed), None, None, rules())[0]
                    for x in cells
                ]
                if all(ok):
                    rows.append([x.text for x in ok])  # type: ignore[union-attr]
            if len(rows) >= 2:
                out.append(
                    Section(
                        sentences=[x for s in cap for x in s.sentences],
                        table=rows,
                        source="general" if general_rows else "llm",
                        route=route,
                        trade=code or trade,
                        title=title,
                    )
                )
            continue
        out += sections(items, title=title, code=code, steps=b.kind == "steps")
    if not out:
        return None
    for sec in out:
        used |= {x for s in sec.sentences for x in s.cites}
        if sec.caution:
            used |= set(sec.caution.cites)
    srcs = _sources(kb, used, part, ev.get("rule_src"))
    if srcs:  # 출처 칸은 근거 문장 묶음에(일반 설명 묶음은 출처가 없어요)
        at = next((i for i, s in enumerate(out) if s.source == "llm"), 0)
        out[at] = out[at].model_copy(update={"sources": srcs})
    return out


async def compose(
    part: Part,
    kb: KB,
    question: str,
    *,
    trade: TradeCode | None,
    mode: Mode | None = None,
    trades: list[str] | None = None,
    screen: dict | None = None,
    asks: list[tuple[str, str]] | None = None,
) -> Part | None:
    """작성기 한 번. 쓸 수 없으면 None(부르는 쪽은 무료 답 그대로).
    계산만 있는 답도 불러요: 숫자는 계산 묶음이 이미 보여서, 작성기는 검색 위 조각으로 덧붙일 것만 써요.
    카드 · 조각 근거가 하나도 없으면 부르지 않아요(덧붙일 것이 없어요). 설명 · 우리 집 꼴(mode)은 공정 정보와
    일반 설명으로, 화면 꼴은 보는 화면(screen) · 분석한 조각(asks: 꼴, 풀어 쓴 질문)으로 쓸 수 있어서 늘 불러요."""
    ev = evidence(part, kb, question, trade, mode, trades, screen, asks)
    if not (ev["data"]["카드"] or ev["data"]["근거"] or mode):
        part.dropped.append("작성기: 근거 없음")
        return None
    messages = [
        ("system", prompt()),
        (
            "user",
            (
                f"<자료>{json.dumps(ev['data'], ensure_ascii=False)}</자료>\n"
                f"질문 꼴: {KIND_KO[mode]}\n고객 질문: {check.mask(question)}"
            ),
        ),
    ]
    try:
        c = await llm.structured("composer", Composed, messages)
    except llm.LLMError:
        part.dropped.append("작성기 실패")
        return None
    if c.verdict in ("unknown", "none"):
        part.dropped.append(
            "작성기: 근거 부족" if c.verdict == "unknown" else "작성기: 덧붙일 것 없음"
        )
        return None
    if (ev["calc"] or ev["fixed"]) and not any(x.strip() for x in c.new):
        part.dropped.append(
            "작성기: 새 사실 없음"
        )  # 고정 몫에 없는 새 사실을 못 적었으면 쓴 글도 되풀이예요
        return None
    dropped: list[str] = []
    secs = to_sections(
        c, ev, part, kb, route=part.route, trade=part.trade, dropped=dropped, mode=mode
    )
    part.dropped.extend(dropped)
    if not secs:
        part.dropped.append("작성기: 다 걸러짐")
        return None
    fixed = [s for s in part.sections if s.source in FIXED]
    # 카드의 방법 · 업체에 물을 말 표는 검증된 카드 글이라 작성기 답 아래에 그대로 붙여요(작성기는 표를 다시 쓰지 않음)
    tables = [s for s in part.sections if s.source == "card" and s.table]
    # 일부만 답했으면 '확인하지 못했어요'는 빼고 확인할 곳 줄만 둬요(답 뒤에 모름이 붙으면 앞뒤가 안 맞아요).
    # 설명 꼴은 확인할 곳 줄도 빼고(집을 볼 일이 아니에요), 우리 집 꼴은 대략 답 끝에 확인할 곳 한 줄을 늘 둬요
    where = [u for u in part.unknown if u != templates.UNKNOWN]
    if mode in ("explain", "screen"):
        where = []
    elif mode == "house":
        where = where or [
            templates.UNKNOWN_WHERE.format(where=where_for(question, trade) or "실측 때 업체")
        ]
    elif c.verdict == "answer":
        where = []
    new = Part(
        sections=[*fixed, *secs, *tables], calc=list(part.calc), cards=list(part.cards), ask=part.ask,
        unknown=where,
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
    r"(?:달라(?:요|져요|질\s{1,2}수\s{1,2}있어요)|차이가\s{1,2}(?:있어요|나요|날\s{1,2}수\s{1,2}있어요))[.!]?$|"
    r"마다\s{0,2}(?:\S+\s{1,2}){0,4}(?:달라요|달라져요|다를\s{1,2}수\s{1,2}있어요|차이가\s{1,2}(?:있어요|나요))[.!]?$"
)
# 고정 몫이 이미 답했는데 '~정하기 어려워요 · ~만으로 정해지지 않아요'로 흐리게 끝내는 문장(composer_v5 두 턴 확인)
HEDGE = re.compile(
    r"(?:정하기|확정하기|단정하기|예상하기)\s{0,2}어려|"
    r"만으로(?:는)?\s{0,2}(?:\S+\s{1,2}){0,2}정해지지\s{0,2}않아요[.!]?$"
)
# 우리 집 꼴에서 기준 없이 '상담 · 실측 때 정해요 · 업체와 정해요'로만 미루는 문장(composer_v6 우리 집 몰딩 질문,
# 3300에서 '믿집 목공 상담에서는 몰딩도 바꿀지 정해요.'도 봤어요)
DEFER = re.compile(
    r"(?:상담|실측)\s{0,2}(?:때|에서는|에서|할\s{0,2}때|하면서)\s{0,2}(?:\S+\s{1,2}){0,3}"
    r"(?:정해요|정하면\s{0,2}돼요|확인해요)[.!]?$|"
    r"업체와\s{0,2}(?:\S+\s{1,2}){0,2}정해요[.!]?$"
)
# 화면 꼴의 판단 말(2026-11-20 사용자: 판단 질문은 LLM이 판단 말로). 고정 몫 숫자를 되풀이해도 새 정보로 봐요
JUDGE = re.compile(
    r"(?:높은|낮은|비싼|싼|많은|적은|무난한|보통인)\s{0,2}편|적당|괜찮|무난|"
    r"보다\s{0,2}(?:높|낮|많|적|비싸|싸)|범위\s{0,2}(?:안|밖|안쪽|바깥)"
)
SCREEN_REF = "rule:screen"  # 보는 화면 근거 ref(screen_tools.SCREEN_REF와 같아요)
# 인용 지지 기준(IDF 무게 겹침). c2 답 인용 154쌍: 맞는 짝 86% 통과 · 섞은 짝 6.5% 통과(support_cal)
SUPPORT = 0.18
# 순서 되풀이: 고정 몫(정해 둔 순서 문장 · 기간 묶음)이 이미 두 공종의 순서를 말했으면, 작성기가 같은 두 공종의
# 순서를 말만 바꿔 다시 쓴 문장('목공과 도배는 순서대로 진행해요')은 빼요. 순서 낱말 · 공종 이름 · 고정 몫 글을
# 빼고 남는 새 말(드문 글자 묶음 무게)이 적으면 되풀이예요. 3300 두 턴 답의 되풀이 문장 4개는 0.64~0.87,
# 새 정보가 든 문장('페인트가 마른 다음에 도배해야 들뜨지 않아요' 등)은 0.09~0.41이라 그 사이 0.55로 둬요
ORDER_CUE = re.compile(
    r"먼저|나중|순서|차례|이어서|다음에|뒤에|동시에|같은\s{0,2}날|겹치지\s{0,2}않|"
    r"(?:끝난|끝나고|끝내고|끝나야|끝나면|마친|마치고|마쳐야|마치면|마무리하고|마무리한)\s{0,2}(?:뒤|다음|후)?"
)
TWO_WORK = re.compile(r"두\s{0,2}(?:공정|공종|작업)")
# 공종 이름 없이 '공정 · 작업'으로 순서를 말하는 문장('공정이 겹치지 않도록 순서대로 잡아요', 3300 평수 2턴)
ANY_WORK = re.compile(r"(?:공정|공종|작업)(?!표)")
# 순서에서 바로 나오는 말('같은 날 안 해요' · '끝나야 할 수 있어요')도 새 정보가 아니라 순서 낱말로 쳐요(3300 날짜 대화 2턴)
ORDER_WORDS = (
    "먼저 나중 순서대로 차례대로 이어서 이어 다음에 끝난 뒤 끝나고 끝내고 끝나야 끝나면 마친 뒤 마치고 마쳐야 "
    "마치면 마무리하고 진행해요 진행하고 진행돼요 진행하진 진행하지 해요 하고 할 수 들어가요 와요 "
    "같은 날 동시에 함께 한꺼번에 겹치지 않고 겹치지 않게 겹치지 않도록 뒤에 이어져요 실제 날짜 공정 공정표 일정 "
    "확인해요 잡아요 정해요 작업 이뤄져요"
)
ORDER_COVER = 0.55
# 계산 묶음이 날짜를 보였으면, 작성기 문장의 날짜 · 요일 · '계산 결과는 ~ 기준' 같은 말은 계산 되풀이나 헛조건이에요
# (계산 엔진이 요일까지 셌어요). 숫자 검사는 같은 날짜라 지나서 따로 빼요(3300 날짜 대화 1턴)
CALC_DATE = re.compile(r"\d{1,2}\.\d{1,2}\s{0,1}\([월화수목금토일]\)")
DATE_TALK = re.compile(
    r"\d{1,2}\.\d{1,2}\s{0,1}\([월화수목금토일]\)|\d{1,2}\s{0,2}월\s{0,2}\d{1,2}\s{0,2}일|요일|"
    r"종료일|완료일|시작일|시작\s{0,2}날짜|끝나는\s{0,2}날|"
    r"(?:주말|공휴일)\S{0,6}\s{0,2}(?:\S+\s{1,2}){0,2}(?:빼|제외|쉬)"
)
CALC_TALK = re.compile(r"계산\s{0,2}(?:결과|값)|기준이며|확정하기\s{0,2}어려")
# 안내성 빈말: '~확인할 수 있어요 · 공정표를 참고해요'로 끝나는데 고정 몫 · 안내 낱말을 빼면 새 말이 거의 없는 문장
GUIDE_END = re.compile(
    r"(?:수\s{0,2}있(?:어요|습니다)|참고해\s{0,2}(?:요|보세요|주세요)|참고하세요|"
    r"확인해\s{0,2}(?:요|보세요|주세요)|확인하세요)[.!]?$"
)
GUIDE_WORDS = (
    "확인할 계산할 볼 알 잡을 드릴 받을 수 있어요 함께 같이 미리 따로 더 자세히 정확한 실제 일정 일정은 날짜 예상 "
    "공정표 공정표를 공정표에서 전체 포함한 포함해 기준 확인되면 넣으면 알려 주시면 계산해 드려요 잡아 드려요 "
    "참고해요 참고하세요 확인해요 확인하세요 확인해 보세요 화면 도 에서 를 을"
)
CAN_COVER = 0.6


def _order_pair(text: str) -> frozenset[str] | None:
    """두 공종(이상)의 순서를 말하는 문장이면 그 공종들. '두 공정'처럼 이름 없이 말하면 {'*'}. 아니면 None."""
    if not ORDER_CUE.search(text or ""):
        return None
    tr = frozenset(t for t in trades_in(text) if t != "common")
    if len(tr) >= 2:
        return tr
    return frozenset({"*"}) if TWO_WORK.search(text) or ANY_WORK.search(text) else None


def order_repeat(text: str, fixed: list[str], weight: Callable[[str], float] | None) -> bool:
    """고정 몫 글(fixed)이 이미 말한 두 공종 순서를, 새 말 없이 되풀이하는 문장인지."""
    pair = _order_pair(text)
    if pair is None or weight is None:
        return False
    said = [p for p in (_order_pair(t) for t in fixed) if p and "*" not in p]
    if not said or ("*" not in pair and not any(pair <= p for p in said)):
        return False
    names = " ".join(BY_CODE[t].ko for p in said for t in p if t in BY_CODE)  # type: ignore[index]
    known = set().union(*(_grams(t) for t in fixed)) | _grams(ORDER_WORDS) | _grams(names)
    g = _grams(text)
    tot = sum(weight(x) for x in g)
    return tot > 0 and sum(weight(x) for x in g if x in known) / tot >= ORDER_COVER


# 앞 절만 고정 몫 순서를 되풀이하는 문장('목공이 끝난 뒤 도배하고, 살면서 하면 더 걸려요')은 앞 절을 떼고
# 뒤 절만 남겨요. 뒤 절이 앞 절에 기대는 말로 시작하거나 문장으로 끝나지 않으면 그대로 둬요(composer_v4 두 턴 확인)
LEANS = re.compile(r"그다음|그\s{0,2}뒤|그\s{0,2}후|그리고|그래서|따라서|이후|이어|이때|다음")
ENDS = re.compile(r"(?:요|다)[.!?]?$")


def trim_order_head(text: str, fixed: list[str], weight: Callable[[str], float] | None) -> str:
    parts = re.split(r",\s*", text.strip(), maxsplit=1)
    if len(parts) < 2:
        return text
    head, tail = parts[0], parts[1].strip()
    if not (tail and ENDS.search(tail)) or LEANS.match(tail):
        return text
    return tail if order_repeat(head, fixed, weight) else text


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
    r"자료(?:로|에서|에는|에|상|만으로)|안내(?:만으로|로는)|확인하지\s{0,2}못했|확인하기\s{0,2}어렵|"
    r"근거(?:가|로|에)"
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
