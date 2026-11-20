"""담당들이 같이 쓰는 무료 모드 답 단계 (agents.md 10.2~10.4): 검증된 카드 → 조각 문장 뽑기 → 정직한 모름.

- 받아들이기: 카드 점수 ≥ T_CARD 이고 카드 근거 조각이 같은 질문의 검색 위 8개에 있음(맞물림), 또는 점수 ≥ T_HIGH.
  기준값은 E3 dev에서 골랐다(evaluation/v3/e3_answers.py, docs/v3/verification/b5.md).
- 의미 검색 순위(KB.dense)가 있고 위 규칙으로 못 받았으면: 근거 조각이 의미 순위 위 D_LOCK개에 있는 카드를
  맞물림으로 보고 덤 BD를 더해 한 번 더 본다. 이미 받을 카드가 있으면 순서를 바꾸지 않는다.
  값은 dev로만 골랐다(docs/v3/verification/dense-cards.md).
- 숫자 검사 허용 글: 카드 글 + 인용 조각 원문(카드는 오프라인 검사를 통과한 글), 조각 문장은 그 조각 원문.
- 카드 · 조각 · 계산 결과 밖의 말은 하지 않는다. 못 찾으면 '확인하지 못했어요' + 확인할 곳 + 다음 할 일.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.agent.v3 import check, templates
from app.agent.v3.schemas import (
    AskSlot,
    CalcBox,
    GeneralFacts,
    PolicyFlag,
    ProjectFacts,
    Route,
    Section,
    Sentence,
    TradeCode,
    TurnContext,
    UiCard,
)
from app.agent.v3.trades import BY_CODE, TAG_TO_CODE
from app.knowledge import bm25, cards, extract, search3

T_CARD = 0.55  # 맞물림이 있을 때 받는 점수(열쇠 점수 + 덤). E3 dev 격자에서 고름(b5.md 표)
T_HIGH = 0.62  # 맞물림이 없어도 받는 열쇠 점수
B3, B8 = 0.10, 0.05  # 카드 근거 조각이 검색 위 3개 · 위 8개에 있을 때 덤(E3 dev로 고름)
# 근거 조각이 의미 검색 위 D_LOCK개에 있으면 의미 맞물림 + 덤 BD(dense-cards.md, dev로 고름)
D_LOCK, BD = 3, 0.15
NEAR = 0.05  # 1등과 이만큼 가까운 카드는 '이것도 궁금하세요?'로
DIY_PENALTY = (
    0.10  # 셀프를 묻지 않은 질문에서 셀프 카드 열쇠 점수를 깎는 만큼(T_HIGH 0.62 → 맞물림 필요)
)
T_NEAR_ASK = 0.40  # 모름일 때 이 점수 이상인 카드 열쇠 질문을 '이걸 물으셨나요?' 버튼으로
# 정해 둔 글로 답하는 정책 질문은 조각 문장을 붙이지 않는다(추천 · 금액 · 법률은 원문 한 줄이 오해를 부름)
NO_EXTRACT = frozenset({"price", "vendor_reco", "brand_reco", "legal_case"})
# 믿집이 견적 · 공정표를 만드는 공종. 그 밖은 범위 밖이라 묶음 제목에 '알아 두기'를 붙여요(agent-context.md 4.1)
OWN_TRADES = frozenset({"dobae", "mokgong", "common"})
# 업체에 물을 말을 찾는 질문: 있으면 카드의 '업체에 물을 말' 표를 펼쳐요(없으면 이어 물을 질문으로)
ASK_VENDOR = re.compile(
    r"물어\s{0,2}볼|물어봐|물어\s{0,2}봐야|물을\s{0,2}(?:거|것|게|말)|뭐\s{0,2}물어|질문할|확인할|체크|따져"
)
METHODS_LEAD = "업체가 쓰는 방법은 이래요."
ASK_LEAD = "업체에 이렇게 물어보세요."


def trade_title(code: str | None) -> str:
    """묶음 제목: '[도배]' · 범위 밖은 '[전기 · 알아 두기]'"""
    if not code or code not in BY_CODE:
        return ""
    ko = BY_CODE[code].ko  # type: ignore[index]
    return f"[{ko}]" if code in OWN_TRADES else f"[{ko.split(' · ')[0]} · 알아 두기]"


@dataclass
class KB:
    """한 턴이 쓰는 지식: 검색 색인(DB 적재본) + 카드(정적 파일)."""

    ix: bm25.Index
    cards: cards.CardSet
    tags: Mapping[str, str] = field(default_factory=lambda: TAG_TO_CODE)
    dense: tuple[
        str, ...
    ] = ()  # 이 턴 질문의 의미 검색 순위(rid). chat.service가 임베딩을 만들 수 있을 때 채워요


@dataclass
class Task:
    """오케스트레이터 → 담당 (또는 관문 → 담당). user · project는 ctx에만 있다."""

    text: str
    route: Route
    trades: list[TradeCode]
    policy: list[PolicyFlag]
    ctx: TurnContext
    facts: ProjectFacts | None = None
    slot: str | None = None
    value: str | None = None
    asked: str = ""  # 되물은 담당이 남긴 원래 질문(칸 답일 때)
    general: GeneralFacts | None = (
        None  # 질문의 평수 · 예시 평수로 센 계산 엔진 값(프로젝트와 별개)
    )


@dataclass
class Part:
    """담당 하나가 낸 몫. 오케스트레이터는 sections를 다시 쓰지 않고 이어 붙인다."""

    sections: list[Section] = field(default_factory=list)
    calc: list[CalcBox] = field(default_factory=list)
    cards: list[UiCard] = field(default_factory=list)
    ask: AskSlot | None = None
    unknown: list[str] = field(default_factory=list)
    suggest: list[str] = field(default_factory=list)
    near: list[str] = field(
        default_factory=list
    )  # 모름일 때만 보일 가까운 카드 질문(turn.finish가 고름)
    used_cards: list[str] = field(default_factory=list)
    used_chunks: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    route: Route = "guide"
    trade: TradeCode | None = None
    scores: dict[str, float] = field(
        default_factory=dict
    )  # 받아들인 카드 tag → 점수(LLM 모드 '카드 먼저')

    @property
    def empty(self) -> bool:
        return not (self.sections or self.calc or self.cards or self.unknown)

    def add(self, sec: Section | None, allowed: str, calc_text: str | None = None) -> None:
        if sec is None:
            return
        shown = set(self.used_chunks) | set(self.used_cards)
        kept, dropped = check.section(sec, allowed, calc_text=calc_text, shown=shown or None)
        self.dropped.extend(dropped)
        if kept is not None:
            self.sections.append(kept)


def accept(
    matches: list[cards.Match], top: list[str], near: list[str] | None = None
) -> tuple[cards.Match | None, list[cards.Match]]:
    """(받아들인 카드, 점수 순 후보). 점수 = 열쇠 점수 + 검색 맞물림 덤(인용 조각이 위 3개 B3 · 위 8개 B8).
    맞물림이 없으면 열쇠 점수 ≥ T_HIGH일 때만 받는다.

    near: 의미 검색 순위(조각 ref, 가까운 순). 위 규칙으로 못 받았을 때만 쓴다: 인용 조각이 near 위 D_LOCK개에
    있는 카드에 덤 BD를 더해 다시 줄 세우고, 1등이 그 카드이고 점수 ≥ T_CARD면 받는다."""

    def rank(dlock: set[str]) -> list[tuple[float, cards.Match]]:
        out = []
        for m in matches:
            cites = set(m.card.cites())
            bonus = B3 if cites & set(top[:3]) else (B8 if cites & set(top) else 0.0)
            if cites & dlock:
                bonus = max(bonus, BD)
            out.append((m.score + bonus if bonus else m.score, m))
        return sorted(out, key=lambda p: -p[0])

    ranked = rank(set())
    if not ranked:
        return None, []
    s, m = ranked[0]
    if (set(m.card.cites()) & set(top) and s >= T_CARD) or m.score >= T_HIGH:
        return m, [x for _, x in ranked]
    dlock = set((near or ())[:D_LOCK])
    if dlock:
        again = rank(dlock)
        s, m = again[0]
        if set(m.card.cites()) & dlock and s >= T_CARD:
            return m, [x for _, x in again]
    return None, [x for _, x in ranked]


def card_section(card: cards.AnswerCard, *, route: Route, trade: TradeCode | None) -> Section:
    tag = card.tag

    def sent(x: cards.CardSentence | None) -> Sentence | None:
        return Sentence(text=x.text, cites=[*x.cites, tag]) if x else None

    return Section(
        title=trade_title(card.trade),
        sentences=[sent(x) for x in card.answer],  # type: ignore[misc]
        caution=sent(card.caution),
        tip=sent(card.tip),
        source="card",
        route=route,
        trade=trade or card.trade,  # type: ignore[arg-type]
        sources=[s.model_dump(include={"ref", "title", "kind", "publisher"}) for s in card.sources],
    )


def card_tables(
    part: Part, c: cards.AnswerCard, q: str, allowed: str, *, route: Route, trade: TradeCode | None
) -> None:
    """카드의 방법 표 · 업체에 물을 말 표(agent-context.md 4.2). 물을 말은 질문이 그걸 찾을 때만 펼치고,
    아니면 그 카드의 물을 말 열쇠 질문을 이어 물을 질문 맨 앞에 둬요."""
    srcs = [s.model_dump(include={"ref", "title", "kind", "publisher"}) for s in c.sources]
    if c.methods:
        sec = Section(title="[방법]", sentences=[Sentence(text=METHODS_LEAD)], source="card",
                      route=route, trade=trade, sources=srcs, table=[[m.name, m.when] for m in c.methods])  # fmt: skip
        part.add(sec, allowed)
    if not c.vendor_ask:
        return
    if ASK_VENDOR.search(q or ""):
        sec = Section(title="[업체에 물을 말]", sentences=[Sentence(text=ASK_LEAD)], source="card",
                      route=route, trade=trade, sources=srcs, copyable=True,
                      table=[[a.q, a.why] for a in c.vendor_ask])  # fmt: skip
        part.add(sec, allowed)
    else:
        key = next((k for k in c.keys if ASK_VENDOR.search(k)), None)
        if key:
            part.suggest.insert(0, key)


def card_allowed(kb: KB, card: cards.AnswerCard) -> str:
    texts = [x.text for x in card.answer] + [x.text for x in (card.caution, card.tip) if x]
    texts += [x.text for x in (*card.methods, *card.vendor_ask)]
    texts += [kb.ix.by_ref[r].chunk.text for r in card.cites() if r in kb.ix.by_ref]
    return "\n".join(texts)


def search(kb: KB, q: str, trade: TradeCode | None) -> bm25.Result:
    want = [trade] if trade and trade != "common" else []
    return search3.search(kb.ix, q, trades=want, tags=kb.tags, k=8, dense=kb.dense)


def knowledge(
    part: Part,
    kb: KB,
    q: str,
    *,
    trade: TradeCode | None,
    route: Route,
    intents: tuple[str, ...] | None = None,
    facts: ProjectFacts | None = None,
    allow_extract: bool = True,
    policy: list[PolicyFlag] | tuple = (),
    also: list[TradeCode] | tuple = (),
) -> str:
    """카드 → 조각 문장 → 모름 순서로 part에 담는다. 어느 길로 답했는지 돌려준다(card · extract · unknown).

    also: 관문이 함께 고른 다른 공종. 카드는 trade + also + 공통에서 찾는다(검색 무게는 trade만).
    """
    hits = search(kb, q, trade)
    top = [h.ref for h in hits.hits[:8]]
    by_rid = kb.ix.by_rid
    near = [by_rid[r].chunk.ref for r in kb.dense if r in by_rid] if kb.dense else None
    want = [trade, *(t for t in also if t != trade)] if trade and trade != "common" else None
    matches = cards.find(kb.cards, q, trades=want, intents=intents, k=4)
    # 검색 맞물림 후보: 위 조각을 인용한 카드(열쇠 말이 달라도 근거가 같은 카드)
    seen = {m.card.id for m in matches}
    allow = set(want or ()) | {"common"} if want else None
    extra = [
        i for r in [*top, *(near or ())[:D_LOCK]] for i in kb.cards.by_cite.get(r, [])
        if kb.cards.cards[i].id not in seen and (allow is None or kb.cards.cards[i].trade in allow)
        and (intents is None or kb.cards.cards[i].intent in intents)
    ]  # fmt: skip
    matches += cards.score(kb.cards, q, list(dict.fromkeys(extra)))
    if "diy" not in set(policy):
        # 셀프를 묻지 않았으면 셀프 카드는 점수를 깎아, 검색 맞물림이 있을 때만 받게 해요(r2 점검 C16).
        # 통째로 빼면 '곰팡이 위 덧칠'처럼 셀프 카드가 맞는 답까지 사라져서(1,511개 점검) 깎기만 해요
        matches = [
            cards.Match(m.card, round(m.score - DIY_PENALTY, 4), m.key) if _diy_card(m.card) else m
            for m in matches
        ]
    best, matches = accept(matches, top, near)
    if best is not None:
        c = best.card
        part.used_cards.append(c.tag)
        part.used_chunks.extend(c.cites())
        part.scores[c.tag] = best.score
        # 함께 고른 공종의 카드면 묶음 공종도 그 공종으로
        own = c.trade if c.trade in also and c.trade != trade else trade
        allowed = card_allowed(kb, c)
        part.add(card_section(c, route=route, trade=own), allowed)  # type: ignore[arg-type]
        card_tables(part, c, q, allowed, route=route, trade=own)  # type: ignore[arg-type]
        _card_extras(part, c, facts, q)
        part.suggest.extend(
            m.key for m in matches[1:] if best.score - m.score < NEAR and m.score >= T_CARD
        )
        return "card"
    if allow_extract and hits.enough and not (NO_EXTRACT & set(policy)):
        quotes = extract.pick(kb.ix, q, hits.hits)
        if quotes:
            part.used_chunks.extend(x.ref for x in quotes)
            lead = (
                templates.EXTRACT_SUMMARY_LEAD
                if any(x.summary for x in quotes)
                else templates.EXTRACT_LEAD
            )
            sents = [Sentence(text=lead)]
            for x in quotes:  # 요약이 있으면 해요체 요약(2문장까지), 없으면 원문을 따옴표로
                if x.summary:
                    sents += [Sentence(text=s, cites=[x.ref]) for s in x.summary[:2]]
                else:
                    sents.append(
                        Sentence(text=f"“{x.text}” ({x.kind_ko} · {x.title[:40]})", cites=[x.ref])
                    )
            sec = Section(
                title=trade_title(trade),
                sentences=sents, source="extract", route=route, trade=trade,
                sources=[{"ref": x.ref, "title": x.title, "kind": x.kind, "publisher": x.publisher} for x in quotes],
            )  # fmt: skip
            allowed = "\n".join(
                [lead, *(" ".join([x.text, x.title, *x.summary]) for x in quotes)]
                + [kb.ix.by_ref[x.ref].chunk.text for x in quotes if x.ref in kb.ix.by_ref]
            )
            part.add(sec, allowed)
            if part.sections:
                return "extract"
    where = where_for(q, trade)
    part.unknown.append(templates.UNKNOWN)
    if where:
        part.unknown.append(templates.UNKNOWN_WHERE.format(where=where))
    # 받지 못한 가까운 카드는 '이걸 물으셨나요?' 버튼 후보로(맞은 열쇠 질문 그대로). 답 전체가 모름일 때만 보여요
    part.near.extend(m.key for m in matches[:2] if m.score >= T_NEAR_ASK)
    return "unknown"


def _diy_card(c: cards.AnswerCard) -> bool:
    return "diy" in c.policy or c.kind == "셀프"


# 공통 질문의 '확인할 곳'은 주제로 고른다(늘 '관리사무소 · 1372'면 실측 · 일정 질문에 엉뚱해요)
APT_WORDS = re.compile(
    r"관리사무소|이웃|소음|엘리베이터|승강기|동의서|공사\s{0,2}시간|주차|입주민|게시"
)
DISPUTE_WORDS = re.compile(
    r"하자|분쟁|환불|위약금|피해|소비자|보상|배상|사기|폐업|연락이?\s{0,2}(?:안|끊)|계약\s{0,2}(?:해제|해지|취소)"
    r"|빼고\s{0,2}시공|다른\s{0,2}자재|내용증명"
)
# 확인할 곳을 고르는 말(r2 점검): 업체 고르기 · 견적 비교는 업체에 물으라고 하지 않고, 공사 뒤 · 중은 시공한 업체로
CHOICE_WORDS = re.compile(
    r"업체\s{0,2}(?:고르|선택|비교)|포트폴리오|제일\s{0,2}싼|싼\s{0,2}업체|실측\s{0,2}없이|사진만\s{0,2}보고|견적\s{0,2}(?:차이|비교)"
)
CONTRACT_WORDS = re.compile(r"계약서|특약|계약금|중도금|잔금")
AFTER_WORDS = re.compile(
    r"보수\s{0,2}요청|벌어졌|벌어지|들떴|들뜨|찍혀|파였|얼룩|저절로|하고\s{0,2}나서|끝나고|끝난\s{0,2}뒤|시공한|"
    r"새로\s{0,2}단|생겼|불량"
)
DURING_WORDS = re.compile(r"굳기\s{0,2}전|공사\s{0,2}중|시공\s{0,2}중")


def where_for(q: str, trade: TradeCode | None) -> str | None:
    """'…에 물어보시면 정확해요'의 확인할 곳. None이면 그 줄을 빼요."""
    if CHOICE_WORDS.search(q):
        return None
    if APT_WORDS.search(q):
        return "관리사무소"
    if DISPUTE_WORDS.search(q):
        return "1372 소비자상담센터"
    if CONTRACT_WORDS.search(q):
        return "표준계약서 · 1372 소비자상담센터"
    if AFTER_WORDS.search(q):
        return "시공한 업체"
    if DURING_WORDS.search(q):
        return "시공하는 업체"
    if trade and trade in BY_CODE and trade != "common":
        return BY_CODE[trade].check_where
    return "실측 때 업체"


def drop_promise(part: Part) -> None:
    """추천 거절 글의 '…알려 드릴게요'는 기준 카드가 붙을 때만 둔다. 답이 모름이면 거절 한 문장만 남겨요."""
    for sec in part.sections:
        if sec.source == "template":
            for x in sec.sentences:
                x.text = templates.RECO_SHORT.get(x.text, x.text)


def _card_extras(part: Part, c: cards.AnswerCard, facts: ProjectFacts | None, q: str = "") -> None:
    """카드의 계산 상자 · 되묻기. 숫자는 facts(계산 엔진)에 있을 때만 상자로."""
    for cc in c.calc:
        box = calc_box(cc.ref, facts, label=cc.label)
        if box is not None:
            part.calc.append(box)
    if c.ask and not slot_known(c.ask.slot, facts) and not said_in(c.ask.question, q):
        part.ask = AskSlot(
            trade=c.trade,
            slot=c.ask.slot,
            question=c.ask.question,
            options=c.ask.options,  # type: ignore[arg-type]
        )


# 되묻기 질문에서 뜻 없는 말(질문 꼴 · 흔한 낱말)을 빼고, 남은 낱말이 고객 질문에 이미 있으면 묻지 않아요
_ASK_STOP = frozenset(
    {
        "있나요",
        "있어요",
        "없어요",
        "있으세요",
        "어떤",
        "어느",
        "얼마나",
        "집에",
        "벽에",
        "하세요",
        "해요",
    }
)


def said_in(question: str, q: str) -> bool:
    """되묻기 질문의 핵심 낱말(예: '곰팡이' · '물자국')이 고객 질문에 이미 있나(r2 점검 C23)."""
    for w in re.findall(r"[가-힣]{2,}", question or ""):
        w = re.sub(r"(?:이나|이랑|이|가|나|은|는|을|를|에|도|요)$", "", w)
        if len(w) >= 2 and w not in _ASK_STOP and w in (q or ""):
            return True
    return False


def slot_known(slot: str, facts: ProjectFacts | None) -> bool:
    if facts is None:
        return False
    if slot in facts.brief:
        return True
    spec = BY_CODE.get(slot.split(".")[0])
    for s in spec.slots if spec else ():
        if s.key == slot and s.fact:
            return getattr(facts, s.fact, None) is not None
    return False


def calc_box(ref: str, facts: ProjectFacts | None, label: str = "") -> CalcBox | None:
    """계산 엔진 결과를 상자로 옮긴다(값을 만들지 않음). 없는 값이면 None."""
    if facts is None:
        return None
    if ref == "standard.total" and facts.standard:
        st = facts.standard
        return CalcBox(
            label=label or "표준견적서 합계", ref=ref, amount=st.total, note="부가세 포함"
        )
    if ref.startswith("standard.lines.") and facts.standard:
        key = ref.rsplit(".", 1)[1]
        for ln in facts.standard.lines:
            if ln.key == key:
                return line_box(ln)
        return None
    if ref == "plan.range" and facts.plan:
        p = facts.plan
        return CalcBox(
            label=label or "예상 공정표", ref=ref, qty=p.work_days, unit="일",
            note=f"{templates.md(p.start)} ~ {templates.md(p.end)}",
        )  # fmt: skip
    return None


def line_box(ln) -> CalcBox:
    return CalcBox(
        label=ln.name, ref=f"standard.lines.{ln.key}", qty=ln.qty, unit=ln.unit,
        unit_price=ln.unit_price, amount=ln.amount, in_total=ln.state in ("included", "separate"),
    )  # fmt: skip
