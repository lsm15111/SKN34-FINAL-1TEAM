"""공정 의견(TradePlan) 코드 채점. 표준 라이브러리만 쓴다.

plan은 공정 에이전트 출력 모양 그대로의 dict다:
    {"summary": str, "steps": [{"key", "note"}], "visit_checks": [str], "cautions": [{"text", "source"}]}
채점은 모델이 쓴 원문(코드 검사로 버리기 전) 기준이다.

- 형식 검사(CHECKS): 숫자 · 단계 키 · 길이 · 개수 · 출처 · 말투 · 어려운 용어
- 내용 검사: 사례의 기대 검사(expect.must · must_not)에 적힌 규칙 id를 이 파일의 RULES에서 찾는다.
  규칙은 '언급'을 키워드(정규식)로 본다. 문장 단위로 보고, must_not 중 negation_ok인 규칙은
  '안 함 · 따로 하는 공사' 같은 말이 같은 문장에 있으면 괜찮다고 본다.
  키워드 채점은 거칠다. 뉘앙스는 판정 LLM(evaluation/judge)이 본다.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from evaluation.scorers.terms import TERMS

ALL = ("summary", "steps", "visit", "cautions")
VC = ("visit", "cautions")

# 형식 검사 기준 (화면 '한눈에' 카드 기준. 코드 검사 한도는 요약 400 · 단계 · 질문 200 · 주의 300자)
SUMMARY_LEN = (20, 200)
SUMMARY_SENTENCES = (1, 2)  # 프롬프트는 '두 문장'
ITEM_LEN = {"steps": 120, "visit": 120, "cautions": 160}
VISIT_COUNT = (3, 6)
CAUTION_COUNT = (2, 4)

CHECKS = {
    "no_digits": "숫자(0~9) 없음",
    "no_number_words": "말로 쓴 금액 · 기간 · 인원 없음",
    "step_keys": "단계 키가 공정표 안에 있고 겹치지 않음",
    "step_cover": "공정표 단계마다 하나씩",
    "summary_len": f"요약 {SUMMARY_LEN[0]}~{SUMMARY_LEN[1]}자",
    "summary_sent": f"요약 {SUMMARY_SENTENCES[0]}~{SUMMARY_SENTENCES[1]}문장",
    "item_len": "단계 · 실측 질문 {steps}자, 주의 {cautions}자 이하".format(**ITEM_LEN),
    "visit_count": f"실측 질문 {VISIT_COUNT[0]}~{VISIT_COUNT[1]}개",
    "caution_count": f"주의 {CAUTION_COUNT[0]}~{CAUTION_COUNT[1]}개",
    "caution_source": "주의 출처가 지식 파일 목록 안",
    "style": "'-해요'체 (합니다체 · 반말 끝 없음)",
    "terms": "어려운 용어는 처음 나올 때 쉬운 말로 풀이",
    "must": "꼭 언급할 것 모두 언급",
    "must_not": "언급하면 안 되는 것 없음",
}

_DIGIT = re.compile(r"\d")
_NUM_WORD = re.compile(
    r"(십|백|천|만|억)\s?원(?![래목])"
    r"|(하루|이틀|사흘|나흘|일주일|반나절|한\s?달)\s?(정도|만에|이면|가|이|안에|이상)?\s?(걸|소요|끝)"
    r"|(?<![가-힣])(한|두|세|네)\s?명"
)
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_BAD_END = re.compile(r"(다|음|함|임|됨)$")
# 이 말이 같은 문장에 있으면 '안 함 · 범위 밖' 이야기로 본다 (must_not 중 negation_ok 규칙)
NEGATION = re.compile(
    r"않|안\s?(해|하|함|할|합|돼|되)|빼|제외|없이|말고|그대로\s?두|대상이\s?아니|범위\s?밖|항목\s?밖"
    r"|따로\s?(하는|해야|진행)|고르지|선택하지|포함하지|포함되지|하지\s?마|빠져|빠진|빠지|벽만"
)


@dataclass(frozen=True)
class Rule:
    desc: str  # 표에 쓰는 말
    where: tuple[str, ...]  # summary · steps · visit · cautions
    any: re.Pattern[str]  # 이 말이 나오면 언급
    near: re.Pattern[str] | None = None  # 같은 문장에 이것도 있어야 언급 (순서 규칙)
    negation_ok: bool = False  # must_not: '안 함' 문장이면 괜찮다


def _r(desc: str, where: tuple[str, ...], pattern: str, near: str | None = None, neg=False):
    return Rule(desc, where, re.compile(pattern), re.compile(near) if near else None, neg)


_JIM = r"(?<![가-힣])짐(?!작)|이삿짐"  # 벌어짐 · 갈라짐의 '짐'은 빼고 본다
_OCC_YES = r"사는\s?집|살면서|살고\s?계|거주|" + _JIM
_OCC_NO = r"빈\s?집|비어\s?있|비워|입주\s?전|이사\s?(전|들어가기)"
_PREP = _JIM + r"|가구|보양|덮"
_WASTE = r"폐기물|쓰레기|버리|치우"
_MOVE = _JIM + r"|가구"
_BASIS = r"공급|전용|분양|평형|실평수"
_ORDER = r"먼저|끝난|끝나|끝내|마친|마치|마무리된|뒤|다음|후에|이후|전에"
_SCOPE = (
    r"욕실|화장실|타일|장판|마루|바닥재|전기\s?(배선|공사)|콘센트|스위치|창호|샷시|새시|싱크대"
    r"|중문|가벽|아트월"
)
_EMPTY = _JIM + r"|가구"
_DOOR = r"문틀|문짝|문선|경첩|손잡이|방문\s?(교체|개수|크기|을|은|이|도|만|마다)|문\s?(교체|아래)"

_COMMON = {
    "sum.occupied.yes": _r("요약에 사는 집", ("summary",), _OCC_YES),
    "sum.occupied.no": _r("요약에 빈집", ("summary",), _OCC_NO),
    "prep.mention": _r("사는 집: 짐 · 보양 언급", ALL, _PREP),
    "after.waste": _r("폐기물이 왜 실측 뒤인지", VC, _WASTE),
    "after.moving": _r("짐 이동이 왜 실측 뒤인지", VC, _MOVE),
    "check.area_basis": _r("모르는 면적 기준을 실측 때 확인", VC, _BASIS),
    "empty.moving": _r("빈집인데 짐 이야기", ALL, _EMPTY),
}
RULES: dict[str, dict[str, Rule]] = {
    "wallpaper": _COMMON
    | {
        "sum.grade.basic": _r("요약에 기본형(실크)", ("summary",), r"실크|기본형"),
        "sum.grade.economy": _r("요약에 저가형(합지)", ("summary",), r"합지|저가형"),
        "sum.ceiling": _r("요약에 천장 포함 여부", ("summary",), r"천장"),
        "after.removal": _r("벽지 철거가 왜 실측 뒤인지", VC, r"철거|떼|뜯|벗겨"),
        "order.other": _r("목공이 먼저라는 순서", ALL, r"목공", near=_ORDER),
        "check.grade": _r(
            "모르는 등급을 실측 때 정함", VC, r"등급|합지|실크|벽지\s?종류|어떤\s?벽지"
        ),
        "check.include_ceiling": _r("모르는 천장 포함을 실측 때 정함", VC, r"천장"),
        "balcony.check": _r("발코니 확장부 결로 · 곰팡이 확인", ALL, r"발코니|베란다|확장"),
        "not_chosen.ceiling": _r(
            "천장 안 함인데 천장 작업 언급", ALL, r"천장(?!\s?(높이|몰딩|평탄화))", neg=True
        ),
        "other.trade": _r(
            "목공을 안 하는데 목공 언급", ALL, r"목공|몰딩|걸레받이|평탄화|문틀|문짝", neg=True
        ),
        "balcony.none": _r("발코니 확장이 아닌데 발코니 언급", ALL, r"발코니|베란다"),
        "scope": _r("범위 밖 공사 언급", ALL, _SCOPE, neg=True),
    },
    "carpentry": _COMMON
    | {
        "sum.item.molding": _r("요약에 천장 몰딩", ("summary",), r"몰딩"),
        "sum.item.base": _r("요약에 걸레받이", ("summary",), r"걸레받이"),
        "sum.item.door": _r("요약에 방문", ("summary",), r"방문|문짝|문틀|문\s?교체"),
        "sum.item.flatten": _r(
            "요약에 천장 평탄화", ("summary",), r"평탄화|평평|우물\s?천장|등박스"
        ),
        "sum.door_frame.yes": _r("요약에 문틀까지 바꿈", ("summary",), r"문틀"),
        "sum.door_frame.no": _r("요약에 문짝만 바꿈", ("summary",), r"문짝"),
        "after.remove_ceiling": _r("천장 철거가 왜 실측 뒤인지", VC, r"철거|뜯|떼|없애"),
        "after.remove_trim": _r("몰딩 · 걸레받이 철거가 왜 실측 뒤인지", VC, r"철거|뜯|떼"),
        "order.other": _r("도배보다 목공이 먼저라는 순서", ALL, r"도배", near=_ORDER),
        "check.doors": _r("모르는 방문 개수를 실측 때 확인", VC, r"문.{0,8}(개수|몇)|몇\s?(개|짝)"),
        "check.door_frame": _r("모르는 문틀 교체를 실측 때 정함", VC, r"문틀"),
        "not_chosen.molding": _r("고르지 않은 몰딩 언급", ALL, r"몰딩", neg=True),
        "not_chosen.base": _r("고르지 않은 걸레받이 언급", ALL, r"걸레받이", neg=True),
        "not_chosen.door": _r("고르지 않은 방문 언급", ALL, _DOOR, neg=True),
        "not_chosen.flatten": _r(
            "고르지 않은 천장 평탄화 언급",
            ALL,
            r"평탄화|우물\s?천장|등박스|천장틀|석고보드",
            neg=True,
        ),
        "other.trade": _r("도배를 안 하는데 도배 언급", ALL, r"도배|벽지", neg=True),
        "balcony.any": _r("목공 지식에 없는 발코니 언급", ALL, r"발코니|베란다"),
        "scope": _r("범위 밖 공사 언급", ALL, _SCOPE + r"|붙박이장|단열", neg=True),
    },
}


# ---------------------------------------------------------------- 글 꺼내기
def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def texts(plan: dict, where: tuple[str, ...] = ALL) -> list[str]:
    """plan에서 칸별 글을 화면 순서(요약 → 단계 → 실측 질문 → 주의)로 꺼낸다."""
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


def _sents(plan: dict, where: tuple[str, ...]) -> list[str]:
    return [s for t in texts(plan, where) for s in sentences(t)]


def mentions(rule: Rule, plan: dict) -> bool:
    """규칙의 말이 (순서 규칙이면 같은 문장에 둘 다) 나오나"""
    return any(
        rule.any.search(s) and (rule.near is None or rule.near.search(s))
        for s in _sents(plan, rule.where)
    )


def violations(rule: Rule, plan: dict) -> list[str]:
    """must_not 규칙에 걸린 문장"""
    return [
        s
        for s in _sents(plan, rule.where)
        if rule.any.search(s) and not (rule.negation_ok and NEGATION.search(s))
    ]


def unexplained_terms(plan: dict) -> list[str]:
    """처음 나온 문장에서 풀이 없이 쓴 어려운 용어"""
    sents = _sents(plan, ALL)
    out = []
    for name, term in TERMS.items():
        first = next((s for s in sents if term.pattern.search(s)), None)
        if first is not None and not term.gloss.search(first):
            out.append(name)
    return out


def bad_endings(plan: dict) -> list[str]:
    """'-해요'체가 아닌 끝 (…다 · …음 · …함 · …임 · …됨)"""
    return [s for s in _sents(plan, ALL) if _BAD_END.search(s.rstrip(" .!?…~)'\"」』"))]


def skill_sources(agent: str, root: Path | None = None) -> set[str]:
    """지식 파일(SKILL.md) '출처' 목록의 id (app.agent.trade.sources와 같은 규칙)"""
    base = (root or Path(__file__).resolve().parents[2]) / "backend/app/agent/skills"
    names = {"wallpaper": ("wallpaper", "dobae"), "carpentry": ("carpentry", "mokgong")}[agent]
    path = next((base / n / "SKILL.md" for n in names if (base / n / "SKILL.md").exists()), None)
    if path is None:
        raise FileNotFoundError(f"{agent} 지식 파일을 찾지 못했어요")
    return set(re.findall(r"^- \[(\w+)\] .+$", path.read_text(encoding="utf-8"), re.MULTILINE))


# ---------------------------------------------------------------- 채점
def score(agent: str, plan: dict, expect: dict, sources: set[str]) -> dict:
    """{'checks': {검사 id: 통과}, 'rules': {규칙 id: 통과}, 'detail': {검사 id: 실패 이유}}"""
    rules = RULES[agent]
    checks: dict[str, bool] = {}
    detail: dict[str, str] = {}

    def put(cid: str, ok: bool, why: str = "") -> None:
        checks[cid] = ok
        if not ok and why:
            detail[cid] = why

    all_texts = texts(plan, ALL)
    digits = [t for t in all_texts if _DIGIT.search(t)]
    put("no_digits", not digits, f"{len(digits)}곳: {digits[0][:60]}" if digits else "")
    words = [m.group(0) for t in all_texts for m in _NUM_WORD.finditer(t)]
    put("no_number_words", not words, ", ".join(words[:3]))

    keys = [s.get("key") for s in plan.get("steps") or []]
    want = expect["step_keys"]
    bad = [k for k in keys if k not in want]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    put("step_keys", not bad and not dup, f"없는 키 {bad} · 겹친 키 {dup}")
    miss = [k for k in want if k not in keys]
    put("step_cover", not miss, f"빠진 단계 {miss}")

    summary = plan.get("summary") or ""
    lo, hi = SUMMARY_LEN
    put("summary_len", lo <= len(summary) <= hi, f"{len(summary)}자")
    n = len(sentences(summary))
    put("summary_sent", SUMMARY_SENTENCES[0] <= n <= SUMMARY_SENTENCES[1], f"{n}문장")
    long_items = [
        f"{field} {len(t)}자"
        for field, limit in ITEM_LEN.items()
        for t in texts(plan, (field,))
        if len(t) > limit
    ]
    put("item_len", not long_items, ", ".join(long_items[:3]))
    nv, nc = len(plan.get("visit_checks") or []), len(plan.get("cautions") or [])
    put("visit_count", VISIT_COUNT[0] <= nv <= VISIT_COUNT[1], f"{nv}개")
    put("caution_count", CAUTION_COUNT[0] <= nc <= CAUTION_COUNT[1], f"{nc}개")
    bad_src = [
        c.get("source") for c in plan.get("cautions") or [] if c.get("source") not in sources
    ]
    put("caution_source", not bad_src, f"목록 밖 출처 {bad_src}")
    ends = bad_endings(plan)
    put("style", not ends, ends[0][-40:] if ends else "")
    terms = unexplained_terms(plan)
    put("terms", not terms, ", ".join(terms))

    results: dict[str, bool] = {}
    for rid in expect["must"]:
        results[rid] = mentions(rules[rid], plan)
    for rid in expect["must_not"]:
        results[rid] = not violations(rules[rid], plan)
    missed = [r for r in expect["must"] if not results[r]]
    hit = [r for r in expect["must_not"] if not results[r]]
    put("must", not missed, ", ".join(missed))
    put("must_not", not hit, ", ".join(hit))
    return {"checks": checks, "rules": results, "detail": detail}
