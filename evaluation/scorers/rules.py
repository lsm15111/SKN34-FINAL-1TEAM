"""채점 규칙의 재료: 규칙 모양(Rule), 글 나누기, 언급 · 위반 찾기, 화면 말에서 키워드 뽑기. 표준 라이브러리만 쓴다.

- 규칙은 '언급'을 키워드(정규식)로 본다. 문장 단위로 보고, must_not 중 negation_ok인 규칙은
  '안 함 · 따로 하는 공사' 같은 말이 같은 문장에 있으면 괜찮다고 본다. 키워드 채점은 거칠다 (뉘앙스는 판정 LLM).
- 공정 스펙에서 규칙을 만들 때는 화면 말(선택지 · 칸 이름 · 견적 줄 이름)에서 키워드를 뽑는다.
  공정마다 더 맞는 키워드는 evaluation/plan/config.py에서 바꾼다.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

ALL = ("summary", "steps", "visit", "cautions")
VC = ("visit", "cautions")


@dataclass(frozen=True)
class Rule:
    desc: str  # 표에 쓰는 말
    where: tuple[str, ...]  # summary · steps · visit · cautions
    any: re.Pattern[str]  # 이 말이 나오면 언급
    near: re.Pattern[str] | None = None  # 같은 문장에 이것도 있어야 언급 (순서 규칙)
    negation_ok: bool = False  # must_not: '안 함' 문장이면 괜찮다
    example: str = ""  # 규칙을 지키는 문장 하나 (모범 답 · 무료 점검용)


def rule(
    desc: str,
    where: tuple[str, ...],
    pattern: str,
    near: str | None = None,
    neg: bool = False,
    example: str = "",
) -> Rule:
    return Rule(desc, where, re.compile(pattern), re.compile(near) if near else None, neg, example)


# ---------------------------------------------------------------- 공통 키워드
JIM = r"(?<![가-힣])짐(?!작)|이삿짐"  # 벌어짐 · 갈라짐의 '짐'은 빼고 본다
OCC_YES = r"사는\s?집|살면서|살고\s?계|거주|" + JIM
OCC_NO = r"빈\s?집|비어\s?있|비워|입주\s?전|이사\s?(전|들어가기)"
PREP = JIM + r"|가구|보양|덮"
EMPTY = JIM + r"|가구"
BASIS = r"공급|전용|분양|평형|실평수"
ORDER = r"먼저|끝난|끝나|끝내|마친|마치|마무리된|뒤|다음|후에|이후|전에"
# 이 말이 같은 문장에 있으면 '안 함 · 범위 밖' 이야기로 본다 (must_not 중 negation_ok 규칙)
NEGATION = re.compile(
    r"않|안\s?(해|하|함|할|합|돼|되)|빼|제외|없이|말고|그대로\s?두|대상이\s?아니|범위\s?밖|항목\s?밖"
    r"|따로\s?(하는|해야|진행)|고르지|선택하지|포함하지|포함되지|하지\s?마|빠져|빠진|빠지|벽만"
)

# 견적 줄 이름에 이 말이 있으면 그 줄은 이 말들로 언급을 본다 ('실측 후' 줄이 왜 실측 뒤인지)
STEMS = {
    "철거": r"철거|제거|떼|뜯|벗겨|없애|걷어",
    "제거": r"철거|제거|떼|뜯|벗겨|없애|걷어",
    "폐기물": r"폐기물|쓰레기|버리|치우",
    "짐": JIM + r"|가구",
    "보수": r"보수|고치|손보|메우",
    "평탄화": r"평탄화|평평|고르",
    "퍼티": r"퍼티|메우|메꾸",
    "곰팡이": r"곰팡이",
}
# 공정 키 → (화면 말, 그 공정 이야기로 보는 말). 등록 전 공정도 둔다 (고르지 않은 공정 언급 검사)
SCOPE = {
    "dobae": ("도배", ("도배", "벽지")),
    "mokgong": ("목공", ("목공", "몰딩", "걸레받이", "평탄화", "문틀", "문짝")),
    "floor": ("바닥재", ("장판", "마루", "바닥재", "포세린")),
    "tile": ("타일", ("타일",)),
    "bath": ("욕실", ("욕실", "화장실", "욕조", "변기", "세면대")),
    "kitchen": ("주방", ("싱크대", r"주방\s?가구", "상판")),
    "electric": ("전기", (r"전기\s?(배선|공사)", "콘센트", "스위치")),
    "window": ("창호", ("창호", "샷시", "새시")),
    "paint": ("도장", ("페인트", "도장")),
    "film": ("필름", ("필름", "시트지")),
}
ETC = ("중문", "가벽", "아트월", "붙박이장", "단열", "방수")  # 믿집 공정 밖 공사

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_BAD_END = re.compile(r"(다|음|함|임|됨)$")
# 낱말 끝 조사. 이 · 가 · 로 · 와 · 과는 명사 끝(걸레받이 · 바닥재로)과 헷갈려 떼지 않는다
_PARTICLE = re.compile(r"(이랑|으로|까지|도|만|은|는|을|를)$")
_STOP = {"기존", "처리", "부분", "필요하면", "자재", "제외", "있으면", "보수할", "곳만", "같이"}


# ---------------------------------------------------------------- 글 꺼내기 · 찾기
def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def texts(plan: dict, where: tuple[str, ...] = ALL) -> list[str]:
    """공정 의견에서 칸별 글을 화면 순서(요약 → 단계 → 실측 질문 → 주의)로 꺼낸다."""
    out: list[str] = []
    if "summary" in where:
        out.append(plan.get("summary") or "")
    if "steps" in where:
        out += [s.get("note") or "" for s in plan.get("steps") or []]
    if "visit" in where:
        out += [v or "" for v in plan.get("visit_checks") or []]
    if "cautions" in where:
        out += [c.get("text") or "" for c in plan.get("cautions") or []]
    return out


def plan_sents(plan: dict, where: tuple[str, ...] = ALL) -> list[str]:
    return [s for t in texts(plan, where) for s in sentences(t)]


def mentions(r: Rule, sents: Iterable[str]) -> bool:
    """규칙의 말이 (순서 규칙이면 같은 문장에 둘 다) 나오나"""
    return any(r.any.search(s) and (r.near is None or r.near.search(s)) for s in sents)


def violations(r: Rule, sents: Iterable[str]) -> list[str]:
    """must_not 규칙에 걸린 문장"""
    return [s for s in sents if r.any.search(s) and not (r.negation_ok and NEGATION.search(s))]


def bad_endings(sents: Iterable[str]) -> list[str]:
    """'-해요'체가 아닌 끝 (…다 · …음 · …함 · …임 · …됨)"""
    return [s for s in sents if _BAD_END.search(s.rstrip(" .!?…~)'\"」』"))]


# ---------------------------------------------------------------- 화면 말 → 키워드
def label_words(label: str, drop: Iterable[str] = ()) -> list[str]:
    """화면 말에서 뜻을 담은 낱말. ' · '로 나눈 덩어리마다 '-요'로 끝나는 말을 빼고 마지막 낱말(머리 명사)을
    조사를 떼어 쓴다. 예: '저가형 · 합지' → 저가형 · 합지, '천장도 해요' → 천장, '천장 몰딩' → 몰딩.
    한 글자 낱말과 drop에 있는 말(공정 이름 등)은 뺀다."""
    out: list[str] = []
    for chunk in re.split(r"\s*[·/,]\s*", re.sub(r"\(.*?\)", " ", label)):
        ws = [w for w in chunk.split() if not w.endswith("요")]
        if not ws:
            continue
        w = _PARTICLE.sub("", ws[-1]) if len(ws[-1]) > 2 else ws[-1]
        if len(w) >= 2 and w not in drop and w not in out:
            out.append(w)
    return out


def all_words(label: str, drop: Iterable[str] = ()) -> list[str]:
    """칸 이름처럼 낱말마다 뜻이 있는 화면 말: 모든 낱말 (조사 · 한 글자 · drop 말 빼고)"""
    out: list[str] = []
    for w in re.sub(r"\(.*?\)", " ", label).replace("·", " ").split():
        w = _PARTICLE.sub("", w) if len(w) > 2 else w
        if len(w) >= 2 and w not in drop and w not in _STOP and w not in out:
            out.append(w)
    return out


def line_pattern(name: str) -> str:
    """'실측 후' 견적 줄 이름 → 언급으로 볼 말. 철거 · 폐기물 · 짐 같은 말이 있으면 그 말의 묶음을 쓴다."""
    stems = [p for k, p in STEMS.items() if k in name]
    if stems:
        return "|".join(dict.fromkeys(stems))
    return alt(all_words(name)) or re.escape(name)


def alt(words: Iterable[str]) -> str:
    """낱말 목록 → 정규식 (띄어 써도 맞게)"""
    return "|".join(re.escape(w).replace(r"\ ", r"\s?") for w in words)
