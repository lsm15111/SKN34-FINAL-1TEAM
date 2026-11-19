"""짧은 답(brief): 질문 꼴에 맞춰 '먼저 보일 문장' 1~3개를 고른다. 나머지는 '자세히'(sections 그대로)에 둔다.

설계: docs/v3/agent-next.md 6장. 무료 · LLM 모드 공통, LLM 0회.
- 새 글을 만들지 않는다. 고르는 것은 출력 검사(check.final)를 통과한 문장(카드 · 조각 요약 · 정해 둔 글)뿐이다.
- 질문 꼴(form) 11가지: 추천 · 하자 · 비용 · 기간 · 순서 · 뜻 · 비교 · 원인 · 방법 · 예아니요 · 그 밖.
  꼴마다 문장 수 · 글자 수 예산(BUDGET)이 있다. 넘치면 문장을 덜 보이고 '자세히'로 넘긴다.
- 문장 점수 = 질문 낱말 덮기(글자 두 개 묶음) + 앞 문장 덤(카드는 결론부터 쓴다) + 꼴에 맞는 끝말 덤.
  정해 둔 정책 글(추천 거절 · 하자 판정 안 함 · 표준견적서 안내)과 순서 문장은 그 꼴이면 맨 앞에 둔다.
- 여러 공종 답은 묶음마다 가장 맞는 문장 하나씩(공종이 빠지지 않게), 못 찾은 공종 한 줄은 늘 보인다.
"""

import re

from app.agent.v3 import policy, templates
from app.agent.v3.schemas import AgentAnswer, Brief, Sentence
from app.knowledge import bm25
from app.knowledge.cards import STOP

Form = str
# 꼴 → (보일 문장 수, 글자 수 상한). 글자 수는 문장 글 합(띄어쓰기 포함). 첫 문장은 넘쳐도 보인다
BUDGET: dict[Form, tuple[int, int]] = {
    "reco": (2, 110),
    "defect": (2, 150),
    "price": (2, 130),
    "period": (2, 130),
    "order": (2, 130),
    "define": (2, 120),
    "compare": (2, 140),
    "cause": (2, 120),
    "howto": (3, 170),
    "yesno": (2, 130),
    "other": (2, 140),
}
FORM_KO = {
    "reco": "추천", "defect": "하자 · 분쟁", "price": "비용", "period": "기간", "order": "순서", "define": "뜻",
    "compare": "비교", "cause": "원인", "howto": "방법", "yesno": "예 · 아니요", "other": "그 밖",
}  # fmt: skip
MULTI_LINES, MULTI_CHARS = 3, 220

ORDER_Q = re.compile(r"순서|먼저|뭐부터|무엇부터|어느\s*(?:것|거|걸|쪽)\s*부터|나서|다음에|끝나고")
DEFINE_Q = re.compile(
    r"뭐예요|뭐에요|뭔가요|뭐죠|무슨\s*뜻|뜻이|이란\s*(?:뭐|무엇)|란\s*게\s*뭐|가\s*뭔지"
)
COMPARE_Q = re.compile(
    r"중에\s*(?:뭐|어느|어떤|뭘)|뭐가\s*(?:더|나|좋|달라)|어느\s*(?:쪽|게|것)|차이(?:가|는|점)?|나아요|낫나요|"
    r"나을까요|좋아요,|vs|"
    r"요\s*[,，]\s*[^?？]{1,30}요\s*[?？]",  # 'A할까요, B할까요?'처럼 둘 중 고르기
    re.IGNORECASE,
)
CAUSE_Q = re.compile(r"왜|원인|이유가")
HOWTO_Q = re.compile(r"어떻게|방법|하는\s*법|요령|뭘\s*(?:봐|확인|준비|챙)|무엇을\s*(?:봐|확인)")
YESNO_Q = re.compile(
    r"(?:돼요|되나요|될까요|되죠|맞죠|맞아요|맞나요|인가요|있어요|있나요|없나요|해야\s*(?:해요|하나요|돼요|할까요)|"
    r"하나요|할까요|괜찮(?:은\s*거예요|아요|나요|을까요|죠)|거예요|건가요|가능해요|가능한가요)\s*[?？]*\s*$"
)
# 의문사. 한국어는 의문사 없이 '…요?'로 끝나면 예 · 아니요 물음이에요('붙을까요?' · '생기나요?' · '내야 해요?')
WH = re.compile(r"뭐|무엇|무슨|어디|언제|누가|누구|왜|어떻게|어떤|얼마|몇|어느|뭘|뭔")
POLAR_END = re.compile(r"요\s*[?？]\s*$")

# 꼴에 맞는 문장 끝말 · 낱말(덤)
DEFINE_S = re.compile(
    r"(?:은|는|이란|란)\s.{2,60}(?:이에요|예요|말해요|뜻해요|가리켜요|불러요)[.]?$"
)
YESNO_S = re.compile(
    r"(?:해도\s*돼요|안\s*돼요|돼요|수\s*있어요|수\s*없어요|해야\s*해요|받아야\s*해요|필요해요|필요\s*없어요|"
    r"좋아요|괜찮아요|아니에요|맞아요|않아요|대상이\s*아니)"
)
CAUSE_S = re.compile(r"때문|생겨요|생기|원인|해서\s")
COMPARE_S = re.compile(r"보다|반면|대신|차이|더\s|쪽이")
HOWTO_S = re.compile(r"먼저|그다음|뒤에|순서로|단계|해요\.$")
LEADS = {templates.EXTRACT_LEAD, templates.EXTRACT_SUMMARY_LEAD}
POLICY_LINES = {
    "reco": (templates.VENDOR_RECO, templates.BRAND_RECO, *templates.RECO_SHORT.values()),
    "defect": (templates.DEFECT, templates.OUT["legal"]),
}
PRIOR = (0.15, 0.07, 0.03)


def form_of(text: str) -> Form:
    """질문 꼴. 정책 표시(추천 · 하자 · 비용 · 기간)가 먼저, 그다음 낱말 · 끝말 규칙."""
    t = (text or "").strip()
    flags = set(policy.policy_of(t))
    if flags & {"vendor_reco", "brand_reco"}:
        return "reco"
    if flags & {"defect_judgement", "legal_case"}:
        return "defect"
    if "price" in flags:
        return "price"
    if "period" in flags:
        return "period"
    for form, pat in (
        ("order", ORDER_Q),
        ("cause", CAUSE_Q),  # '이유가 뭐예요?'는 뜻이 아니라 원인
        ("define", DEFINE_Q),
        ("compare", COMPARE_Q),
        ("howto", HOWTO_Q),
        ("yesno", YESNO_Q),
    ):
        if pat.search(t):
            return form
    if POLAR_END.search(t) and not WH.search(t):
        return "yesno"
    return "other"


def _grams(text: str) -> set[str]:
    return {g for g in bm25.grams(text) if g not in STOP}


def _bonus(form: Form, text: str) -> float:
    pat = {
        "define": DEFINE_S,
        "yesno": YESNO_S,
        "cause": CAUSE_S,
        "compare": COMPARE_S,
        "howto": HOWTO_S,
    }
    p = pat.get(form)
    return 0.08 if p is not None and p.search(text) else 0.0


def _first(form: Form, ans: AgentAnswer) -> list[Sentence]:
    """그 꼴이면 맨 앞에 둘 정해 둔 글(정책 · 순서 · 계산 안내)."""
    out: list[Sentence] = []
    for sec in ans.sections:
        if sec.source != "template":
            continue
        for x in sec.sentences:
            policy_line = form in POLICY_LINES and x.text in POLICY_LINES[form]
            order_line = form == "order" and sec.title == "[순서]"
            # 비용 · 기간: 표준견적서 · 예상 공정표 안내(계산 상자와 같이 보임)
            calc_line = form in ("price", "period") and sec.route != "multi" and x.text not in LEADS
            if policy_line or order_line or calc_line:
                out.append(x)
    return out[:1]


def _fold_lines(ans: AgentAnswer) -> list[Sentence]:
    """여러 공종 답의 '… 쪽 자세한 내용은 확인하지 못했어요' 한 줄(늘 보인다)."""
    tail = templates.PART_FAILED_WHICH.split("{which}")[1]
    return [
        x
        for sec in ans.sections
        if sec.source == "template" and sec.route == "multi" and sec.title != "[순서]"
        for x in sec.sentences
        if x.text.endswith(tail) or x.text == templates.PART_FAILED
    ]


def _pool(ans: AgentAnswer, skip: set[str]) -> list[tuple[int, int, Sentence]]:
    """(묶음 번호, 묶음 안 순서, 문장). 이끄는 말 · 이미 고른 글은 뺀다."""
    out = []
    for i, sec in enumerate(ans.sections):
        k = 0
        for x in sec.sentences:
            if x.text in LEADS or x.text in skip:
                continue
            out.append((i, k, x))
            k += 1
    return out


def make(ans: AgentAnswer, question: str) -> Brief:
    """답 하나의 짧은 답. 답에 문장이 없으면(모름 · 되묻기만) 모름 글을 그대로 쓴다."""
    form = form_of(question)
    every = [x for s in ans.sections for x in s.sentences if x.text not in LEADS]
    extras = sum(1 for s in ans.sections for x in (s.caution, s.tip) if x)
    if not every:
        lines = [Sentence(text=u) for u in ans.unknown[:2]]
        return Brief(form=form, lines=lines, more=0)

    fold = _fold_lines(ans)
    first = _first(form, ans)
    chosen: list[Sentence] = list(first)
    taken = {x.text for x in chosen} | {x.text for x in fold}
    q = _grams(question)
    pool = _pool(ans, taken)
    is_multi = ans.trace.route == "multi"
    n_max, c_max = (MULTI_LINES, MULTI_CHARS) if is_multi else BUDGET[form]

    def score(item: tuple[int, int, Sentence]) -> float:
        _, k, x = item
        cover = len(q & _grams(x.text)) / max(len(q), 1)
        quote = 0.1 if x.text.startswith("“") else 0.0
        return cover + (PRIOR[k] if k < len(PRIOR) else 0.0) + _bonus(form, x.text) - quote

    if is_multi:  # 묶음마다 가장 맞는 문장 하나(공종이 빠지지 않게), 묶음 순서대로
        best: dict[int, tuple[float, tuple[int, int, Sentence]]] = {}
        for it in pool:
            s = score(it)
            if it[0] not in best or s > best[it[0]][0]:
                best[it[0]] = (s, it)
        ranked = [best[i][1] for i in sorted(best)]
    else:
        ranked = sorted(pool, key=lambda it: -score(it))

    used = sum(len(x.text) for x in chosen) + sum(len(x.text) for x in fold)
    picked: list[tuple[int, int, Sentence]] = []
    for it in ranked:
        if len(chosen) + len(picked) >= n_max:
            break
        size = len(it[2].text)
        if (chosen or picked) and used + size > c_max:
            continue  # 예산을 넘는 긴 문장은 건너뛰고 더 짧은 다음 문장을 본다
        picked.append(it)
        used += size
    if not is_multi and picked:  # 가장 맞는 문장을 맨 앞에(결론 먼저), 나머지는 원래 읽는 순서대로
        picked = [picked[0], *sorted(picked[1:], key=lambda it: (it[0], it[1]))]
    chosen += [it[2] for it in picked] + fold
    shown = {x.text for x in chosen}
    more = sum(1 for x in every if x.text not in shown) + extras
    return Brief(form=form, lines=chosen, more=more)
