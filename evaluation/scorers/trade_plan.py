"""공정 의견(TradePlan) 코드 채점. 규칙은 공정 스펙 + 공정별 설정(evaluation/plan/config.py)으로 만든다.

plan은 공정 에이전트 출력 모양 그대로의 dict다:
    {"summary": str, "steps": [{"key", "note"}], "visit_checks": [str], "cautions": [{"text", "source"}]}
채점은 모델이 쓴 원문(코드 검사로 버리기 전) 기준이다.

- 형식 검사(CHECKS): 숫자 · 단계 키 · 길이 · 개수 · 출처 · 말투 · 어려운 용어
- 내용 검사: 사례의 기대 검사(expect.must · must_not)에 적힌 규칙 id를 rules(공정)에서 찾는다
  규칙 id: sum.<칸>.<값>(요약에 고른 값) · sum.occupied.* · prep.mention · empty.moving · check.<칸>(모르는 칸)
  · after.<줄 키>('실측 후' 줄) · not_chosen.<칸>.<값>(고르지 않은 항목) · order.<공정>(같이 하는 공정 순서)
  · scope.<공정> · scope.etc(고르지 않은 공정 · 믿집 공정 밖 공사) · 설정에 더한 규칙
"""

import re
from collections import Counter
from functools import cache

from evaluation.common import trades
from evaluation.plan import config
from evaluation.scorers.rules import (
    ALL,
    BASIS,
    EMPTY,
    ETC,
    OCC_NO,
    OCC_YES,
    ORDER,
    PREP,
    SCOPE,
    STEMS,
    VC,
    Rule,
    all_words,
    alt,
    bad_endings,
    label_words,
    line_pattern,
    mentions,
    plan_sents,
    rule,
    sentences,
    texts,
    violations,
)
from evaluation.scorers.terms import unexplained
from evaluation.scorers.witness import BASIS_Q, PREP_NOTE, josa

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
NUM_WORD = re.compile(
    r"(십|백|천|만|억)\s?원(?![래목])"
    r"|(하루|이틀|사흘|나흘|일주일|반나절|한\s?달)\s?(정도|만에|이면|가|이|안에|이상)?\s?(걸|소요|끝)"
    r"|(?<![가-힣])(한|두|세|네)\s?명"
)
_STEM_EXAMPLE = {
    "철거": "기존 자재 철거",
    "제거": "기존 자재 제거",
    "폐기물": "폐기물 처리",
    "짐": "짐 옮기기",
    "보수": "바탕 보수",
    "평탄화": "바닥을 평평하게 고르는 일",
    "퍼티": "갈라진 곳 메우기",
    "곰팡이": "곰팡이 제거",
}


def _literal(words: tuple[str, ...]) -> str:
    return next((w for w in words if re.escape(w) == w), words[0])


def _line_example(name: str) -> str:
    stem = next((k for k in STEMS if k in name), None)
    what = _STEM_EXAMPLE[stem] if stem else " ".join(all_words(name)[:2]) or name
    return f"{what}{josa(what, '은는')} 실측 때 상태를 보고 정해요."


def scope_table() -> dict[str, tuple[str, tuple[str, ...]]]:
    """공정 키 → (화면 말, 그 공정 이야기로 보는 말). SCOPE 표에 없는 등록 공정은 화면 말 하나로 본다"""
    out = dict(SCOPE)
    for k in trades.registered():
        out.setdefault(k, (trades.label(k), (trades.label(k),)))
    return out


@cache
def auto_exempt(trade: str) -> tuple[str, ...]:
    """'고르지 않은 공정' 검사에서 뺄 말: 이 공정 지식 본문에 나오는 다른 공정 말 (예: 필름의 문틀)"""
    body = trades.knowledge_body(trade)
    words = [w for _, ws in scope_table().values() for w in ws] + list(ETC)
    return tuple(w for w in words if re.search(w, body))


def choice_words(f, drop: tuple[str, ...]) -> dict[str, list[str]]:
    """선택지마다 언급으로 볼 낱말. 머리 낱말이 다른 선택지와 겹치면(예: '거실 벽' · '주방 벽') 화면 말을 통째로 쓴다"""
    words = {c.value: label_words(c.label, drop) for c in f.choices}
    seen = Counter(w for ws in words.values() for w in ws)
    out = {}
    for c in f.choices:
        ws = [w for w in words[c.value] if seen[w] == 1]
        if not ws:
            chunks = [
                " ".join(w for w in part.split() if not w.endswith("요"))
                for part in re.split(r"\s*·\s*", re.sub(r"\(.*?\)", " ", c.label))
            ]
            ws = [x for x in chunks if len(x) >= 2]
        out[c.value] = ws or all_words(f.label, drop)
    return out


@cache
def rules(trade: str) -> dict[str, Rule]:
    """이 공정의 규칙 id → 규칙 (공통 규칙 + 스펙 화면 말에서 뽑은 규칙 + 설정)"""
    sp, cfg = trades.spec(trade), config.get(trade)
    drop = (sp.label,)
    out = {
        "sum.occupied.yes": rule("요약에 사는 집", ("summary",), OCC_YES),
        "sum.occupied.no": rule("요약에 빈집", ("summary",), OCC_NO),
        "prep.mention": rule("사는 집: 짐 · 보양 언급", ALL, PREP, example=PREP_NOTE),
        "empty.moving": rule("빈집인데 짐 이야기", ALL, EMPTY),
        "check.area_basis": rule("모르는 면적 기준을 실측 때 확인", VC, BASIS, example=BASIS_Q),
    }
    for f in sp.fields:
        fw = all_words(f.label, drop)
        cws = choice_words(f, drop)
        for c in f.choices:
            w = cws[c.value]
            out[f"sum.{f.key}.{c.value}"] = rule(
                f"요약에 {f.label} '{c.label}'", ("summary",), alt(w), example=w[0]
            )
            if f.kind == "multi":
                out[f"not_chosen.{f.key}.{c.value}"] = rule(
                    f"고르지 않은 {c.label} 언급", ALL, alt(w), neg=True
                )
        if f.unknown is not None:
            cw = fw + [w for ws in cws.values() for w in ws if w not in fw]
            cw = cw or [f.label]
            out[f"check.{f.key}"] = rule(
                f"모르는 {f.label}을 실측 때 확인",
                VC,
                alt(cw),
                example=f"{cw[0]}{josa(cw[0])} 실측 때 같이 확인해요.",
            )
    for key, name in trades.after_lines(trade).items():
        out[f"after.{key}"] = rule(
            f"'{name}' 줄이 왜 실측 뒤인지", VC, line_pattern(name), example=_line_example(name)
        )
    exempt = cfg.scope_exempt if cfg.scope_exempt is not None else auto_exempt(trade)
    for key, (label, words) in scope_table().items():
        if key == trade:
            continue
        ex = _literal(words)
        names = tuple(
            dict.fromkeys(words + ((trades.label(key),) if key in trades.registered() else ()))
        )
        out[f"order.{key}"] = rule(
            f"{label} 공정과의 순서",
            ALL,
            "|".join(names),
            near=ORDER,
            example=f"{ex} 공사와 같이 하면 {ex} 공사가 끝난 뒤에 이어서 해요.",
        )
        if kept := [w for w in words if w not in exempt]:
            out[f"scope.{key}"] = rule(
                f"고르지 않은 공정({label}) 언급", ALL, "|".join(kept), neg=True
            )
    if etc := [w for w in ETC if w not in exempt]:
        out["scope.etc"] = rule("믿집 공정 밖 공사 언급", ALL, "|".join(etc), neg=True)
    out.update(cfg.rules)
    return out


# ---------------------------------------------------------------- 채점
def score(trade: str, plan: dict, expect: dict, sources: set[str]) -> dict:
    """{'checks': {검사 id: 통과}, 'rules': {규칙 id: 통과}, 'detail': {검사 id: 실패 이유}}"""
    table = rules(trade)
    checks: dict[str, bool] = {}
    detail: dict[str, str] = {}

    def put(cid: str, ok: bool, why: str = "") -> None:
        checks[cid] = ok
        if not ok and why:
            detail[cid] = why

    all_texts = texts(plan, ALL)
    digits = [t for t in all_texts if _DIGIT.search(t)]
    put("no_digits", not digits, f"{len(digits)}곳: {digits[0][:60]}" if digits else "")
    words = [m.group(0) for t in all_texts for m in NUM_WORD.finditer(t)]
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
    sents = plan_sents(plan, ALL)
    ends = bad_endings(sents)
    put("style", not ends, ends[0][-40:] if ends else "")
    terms = unexplained(sents, trade)
    put("terms", not terms, ", ".join(terms))

    results: dict[str, bool] = {}
    for rid in expect["must"]:
        results[rid] = mentions(table[rid], plan_sents(plan, table[rid].where))
    for rid in expect["must_not"]:
        results[rid] = not violations(table[rid], plan_sents(plan, table[rid].where))
    missed = [r for r in expect["must"] if not results[r]]
    hit = [r for r in expect["must_not"] if not results[r]]
    put("must", not missed, ", ".join(missed))
    put("must_not", not hit, ", ".join(hit))
    return {"checks": checks, "rules": results, "detail": detail}
