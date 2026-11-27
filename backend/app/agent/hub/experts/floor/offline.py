"""바닥 전문가 무료 모드(LLM 없음): 질문에서 할 일을 코드로 고르고, 같은 도구 함수로 답을 만든다.

할 일: 자재 비교 · 우리 집 맞춤(조건 되묻기 포함) · 공사 전 할 일 · 공사 뒤 확인 · 업체에 물을 말.
어느 것도 아니면 검증된 답 카드 → 근거 조각 문장 → 정직한 모름(v3 answer.knowledge) 순서로 답한다.
"""

from __future__ import annotations

import re

from app.agent.hub.experts.base import Cited, ExpertRun, add_cited, ask_condition, policy_lines
from app.agent.hub.experts.floor.tools import (
    FIT_ORDER,
    add_checklist,
    add_fit,
    add_vendor,
    compare_card,
    material_keys,
    material_lines,
)
from app.agent.v3 import templates, trades
from app.agent.v3.answer import drop_promise, knowledge

COMPARE = re.compile(
    r"차이|비교|뭐가\s*(?:더\s*)?(?:나아|낫|좋)|어떤\s*(?:게|걸|것이)\s*(?:더\s*)?(?:나아|낫|좋)|"
    r"어느\s*(?:게|쪽|것|걸)|중에(?:서)?|장단점|vs",
    re.IGNORECASE,
)
FIT = re.compile(
    r"추천|골라\s*(?:줘|주|줄)|맞는\s*(?:바닥|게|걸|거)|어울리|(?:뭘로|뭐로)\s*(?:해|깔|할)|정해\s*(?:줘|주)|"
    r"우리\s*집에?\s*(?:맞|좋|어울)"
)
BEFORE = re.compile(
    r"(?:공사|시공|깔기|교체|바꾸기)\s*(?:하기\s*)?전|전에\s*(?:뭘|뭐|무엇|할|준비|확인|챙)|"
    r"준비할|준비해야|미리\s*(?:할|해|챙)|체크\s*리스트|할\s*일|챙길"
)
AFTER = re.compile(
    r"끝나고|끝난\s*(?:뒤|후|다음)|(?:시공|공사)\s*(?:후|뒤|끝나)|다\s*깔고|깔고\s*나서|검수"
)
VENDOR = re.compile(
    r"업체(?:에|한테|에게)\s*(?:뭘|뭐|무엇|뭐라고|어떻게)?\s*(?:물어|말해|요청|확인|여쭤)|"
    r"물어볼|물어봐야|여쭤볼|질문\s*(?:목록|리스트|거리)|견적\s*(?:받을|볼)\s*때"
)
ORDER = re.compile(r"순서|먼저|나중|뭐부터|무엇부터|어느\s*(?:것|거|걸|쪽)\s*부터|부터\s*해")
# 순서 글에서 다른 공종을 찾는 말. 질문에 나온 공종이 든 순서 글만 보여요(타일 순서를 물었는데 도배 이야기 막기)
ORDER_WORDS = {
    "dobae": ("도배",),
    "kitchen": ("싱크대",),
    "window": ("중문",),
    "mokgong": ("걸레받이",),
}
MATERIAL_WORD = re.compile(r"바닥재|마루|장판|타일")
TABLE_LEAD = "바닥재마다 좋은 점과 살필 점을 표로 정리했어요."
VENDOR_LEAD = "바닥 업체와 이야기할 때 아래처럼 물어보면 빠뜨리는 게 적어요."
SUGGEST = {
    "fit": "우리 집에 맞는 바닥재 골라 줘",
    "before": "바닥 공사 전에 할 일 알려 줘",
    "after": "바닥 공사 끝나고 확인할 것 알려 줘",
    "vendor": "바닥 업체에 물어볼 말 만들어 줘",
}


def _vendor_topics(q: str, flags: set[str], before: bool, after: bool) -> list[str]:
    topics: list[str] = []
    if "price" in flags or "견적" in q:
        topics.append("quote")
    if before or "실측" in q:
        topics.append("visit")
    if after:
        topics.append("after")
    return topics or ["quote", "visit"]


def _order_lines(r: ExpertRun, q: str) -> list[Cited]:
    notes = r.x.pack.notes.get("order", [])
    others = [c for c in trades.trades_in(q) if c != "floor"]
    if not others:
        return notes
    words = [w for c in others for w in ORDER_WORDS.get(c, (trades.BY_CODE[c].ko,))]
    return [x for x in notes if any(w in x.text for w in words)]


def run(r: ExpertRun) -> None:
    t = r.t
    q = t.question
    flags = set(t.policy)
    slot_turn = bool(t.slot and t.value)
    pack = r.x.pack

    lines = policy_lines(r.x.spec, flags)
    if lines:
        add_cited(r, [Cited(text=x) for x in lines], title="[바닥]", source="template")

    mats = material_keys(r, q)
    want_order = not slot_turn and bool(ORDER.search(q))
    want_fit = bool(FIT.search(q)) or (slot_turn and t.slot in FIT_ORDER)
    want_compare = (
        not slot_turn
        and not want_fit
        and not want_order  # '도배랑 마루 중에 뭘 먼저 해요?'는 견주기가 아니라 순서
        and bool(COMPARE.search(q))
        and (bool(mats) or bool(MATERIAL_WORD.search(q)))
    )
    want_before = not slot_turn and bool(BEFORE.search(q))
    want_after = not slot_turn and bool(AFTER.search(q))
    asked_vendor = not slot_turn and bool(VENDOR.search(q))
    want_price = not slot_turn and "price" in flags
    did: set[str] = set()

    if want_order and (order := _order_lines(r, t.whole or q)):
        did.add("order")
        add_cited(r, order, title="[바닥] 순서")
    if want_compare:  # 견주기: 나온 자재 설명 + 비교표. 맞춤은 칩으로만 권해요(묻지 않음)
        did.add("compare")
        if mats:
            add_cited(r, material_lines(r, mats), title="[바닥] 자재")
        else:
            add_cited(r, [Cited(text=TABLE_LEAD)], title="[바닥] 자재")
        compare_card(r, mats if len(mats) >= 2 else None)
        add_fit(r)  # 이미 아는 조건이 있으면 맞춤도 같이
    if want_fit:  # 맞춤: 아는 조건으로 고르고, 모자라면 하나만 되물어요
        did.add("fit")
        fitted = add_fit(r)
        if not fitted and not slot_turn:
            if len(mats) == 1:  # '데코타일 추천해 주세요': 그 자재 설명부터
                add_cited(r, material_lines(r, mats), title="[바닥] 자재")
            else:
                add_cited(r, [Cited(text=TABLE_LEAD)], title="[바닥] 자재")
                compare_card(r, mats if len(mats) >= 2 else None)
        missing = [k for k in FIT_ORDER if k not in r.known()]
        if missing:
            if not r.reply.sections:
                add_cited(r, [Cited(text=templates.SLOT_LEAD)], title="[바닥]")
            ask_condition(r, missing[0])
    if want_before:
        did.add("before")
        add_checklist(r, "before")
    if want_after:
        did.add("after")
        add_checklist(r, "after")
    if want_price:  # 바닥 금액은 계산하지 않아요: 견적서에서 볼 것 + 업체에 물을 말
        did.add("price")
        add_cited(r, pack.notes.get("price", []), title="[바닥] 견적서에서 볼 것")
    if asked_vendor or want_price:
        did.add("vendor")
        if asked_vendor and len(did) == 1:
            add_cited(r, [Cited(text=VENDOR_LEAD)], title="[바닥]", source="template")
        add_vendor(r, _vendor_topics(q, flags, want_before, want_after))

    if not did:  # 정해 둔 일이 아니면 검증된 카드 → 근거 조각 → 모름
        how = knowledge(
            r.reply,
            r.kb,
            q,
            trade="floor",
            route="trade",
            facts=t.facts,
            policy=t.policy,  # type: ignore[arg-type]
        )
        if how == "unknown" and lines:
            r.reply.unknown = [u for u in r.reply.unknown if u != templates.UNKNOWN]
            drop_promise(r.reply)

    shown = did | ({"fit"} if r.reply.ask is not None else set())
    r.reply.suggest.extend(text for key, text in SUGGEST.items() if key not in shown)
