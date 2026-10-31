"""규칙을 모두 지키는 모범 공정 의견(가짜 LLM 응답). 표준 라이브러리만 쓴다.

- 무료 점검(T0): 사례마다 이 답을 채점해 모두 통과하면 기대 검사 규칙끼리 모순이 없다는 증거다
- --fake 실행: 유료 호출 없이 실행기 · 채점 · 요약 경로를 돌린다
도배 · 목공은 손으로 쓴 답(지식 파일 문장을 쉬운 말로 줄인 것), 다른 공정은 규칙의 예문으로 만든 답이다.
품질 기준선은 아니다.
"""

import re

from evaluation.scorers.rules import Rule, sentences
from evaluation.scorers.terms import TERMS, unexplained

_SMP = {
    "text": "공공 기준 단가는 업체 견적과 견주어 보는 기준이고 업체 가격이 아니에요.",
    "source": "smp",
}
_DISPUTE = {"text": "견적서는 항목과 포함 범위를 글로 받아 두세요.", "source": "dispute"}
BASIS_Q = "적은 면적이 분양 평형(공급면적)인지 전용면적인지 같이 확인해요."
MOVE_Q = "짐을 누가 옮기고 덮는지 물어봐요. 짐 양을 봐야 정할 수 있어요."
PREP_NOTE = "가구를 한쪽으로 옮기고 바닥과 가구를 비닐로 덮어요."
_PAD = (
    "관리사무소에 공사 신고를 해야 하는지 확인해요.",
    "공사 순서를 업체와 같이 정해요.",
    "견적에 들어간 항목을 글로 받아 둘 수 있는지 물어봐요.",
)


def josa(word: str, pair: str = "을를") -> str:
    """받침이 있으면 pair[0], 없으면 pair[1] (을를 · 은는 · 이가 · 과와)"""
    ch = re.sub(r"\(.*\)$", "", word).strip()[-1]
    has = "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28
    return pair[0] if has else pair[1]


def _visit(must: list[str], checks: dict[str, str], extra: list[str]) -> list[str]:
    v = [MOVE_Q] if "after.moving" in must else []
    v += [q for rid, q in checks.items() if rid in must]
    for q in extra:
        if len(v) >= 6:
            break
        v.append(q)
    return v[:6]


def _cautions(first: dict, order: dict | None, more: list[dict]) -> list[dict]:
    out = [first] + ([order] if order else []) + more + [_SMP, _DISPUTE]
    return out[:4]


def dobae(case: dict) -> dict:
    card, e = case["input"]["card"], case["expect"]
    t = card["values"]["dobae"]
    ceil = t["include_ceiling"] == "yes"
    grade = "실크(기본형)" if t["grade"] == "basic" else "합지(저가형)"
    where = "벽과 천장을 모두 바르는" if ceil else "벽만 바르고 천장은 하지 않는"
    home = "사는 집" if card["occupied"] else "빈집"
    notes = {
        "prep": PREP_NOTE,
        "paper": "기존 벽지를 뗄지 정한 뒤 갈라진 곳을 메워 바탕을 고르고, 밑종이와 새 벽지를 "
        + ("벽과 천장에" if ceil else "벽에")
        + " 발라요.",
        "finish": "이음매가 벌어지거나 들뜬 곳이 없는지 같이 보고 청소로 마무리해요.",
    }
    must = e["must"]
    visit = _visit(
        must,
        {
            "check.area_basis": BASIS_Q,
            "check.grade": "실크와 합지 중 어떤 벽지로 할지 실측 때 정해요.",
            "check.include_ceiling": "천장도 바를지 실측 때 정해요.",
        },
        [
            "기존 벽지가 몇 겹인지 봐 달라고 해요. 그걸 봐야 철거할지 정할 수 있어요.",
            "벽에 갈라진 곳이 있는지 봐 달라고 해요.",
            _PAD[0],
        ],
    )
    more = []
    if "balcony.check" in must:
        more.append(
            {
                "text": "발코니를 넓힌 곳은 결로나 곰팡이가 생기기 쉬워요. 원인부터 고쳐야 다시 생기지 않아요.",
                "source": "field",
            }
        )
    cautions = _cautions(
        {
            "text": "기존 벽지 철거와 폐기물 처리는 실측 뒤에 따로 붙는 경우가 많아요. "
            "가견적에 들어 있는지 물어봐요.",
            "source": "field",
        },
        {"text": "목공을 같이 하면 목공이 끝난 뒤에 도배해요.", "source": "field"}
        if "order.mokgong" in must
        else None,
        more,
    )
    return {
        "summary": f"{grade} 벽지로 {where} {home} 도배예요. "
        "기존 벽지를 뗄지는 실측 때 벽지 상태를 보고 정해요.",
        "steps": [{"key": k, "note": notes[k]} for k in e["step_keys"]],
        "visit_checks": visit,
        "cautions": cautions,
    }


_MOK_LABEL = {
    "molding": "천장 몰딩",
    "base": "걸레받이",
    "door": "방문 교체",
    "flatten": "천장 평탄화",
}


def mokgong(case: dict) -> dict:
    card, e = case["input"]["card"], case["expect"]
    t = card["values"]["mokgong"]
    items, frame = t["items"], t.get("door_frame") != "no"
    home = "사는 집" if card["occupied"] else "빈집"
    labels = ", ".join(_MOK_LABEL[i] for i in items)
    if "door" in items:
        tail = "방문은 문틀까지 바꿔요." if frame else "방문은 문틀은 두고 문짝만 바꿔요."
    else:
        tail = "자세한 범위는 실측 때 정해요."
    trims = [n for n, i in (("몰딩", "molding"), ("걸레받이", "base")) if i in items]
    removes = trims + (["튀어나온 조명 상자(등박스)"] if "flatten" in items else [])
    lines = [
        f"{side}과 벽이 만나는 선에 {n}{josa(n)}"
        for side, n, i in (("천장", "몰딩", "molding"), ("바닥", "걸레받이", "base"))
        if i in items
    ]
    notes = {
        "prep": PREP_NOTE,
        "remove": f"기존 {' · '.join(removes)}{josa(removes[-1]) if removes else ''} 뜯고 "
        "바탕을 정리해요.",
        "ceiling": "천장에 뼈대(천장틀)를 짜고 석고보드를 붙여 평평하게 만들어요.",
        "door": "기존 문을 떼고 문틀까지 새로 세운 뒤 새 문을 달아요."
        if frame
        else "기존 문짝을 떼고 새 문짝을 달아요.",
        "trim": ", ".join(lines) + " 붙여요.",
        "finish": "자투리와 톱밥을 치우고 청소해요.",
    }
    extra = []
    if trims:
        extra.append(f"{'과 '.join(trims)}{josa(trims[-1])} 붙일 길이를 방마다 재 달라고 해요.")
    if "door" in items:
        extra.append("문 크기와 손잡이 · 경첩이 견적에 들어가는지 물어봐요.")
    if "flatten" in items:
        extra.append("평평하게 만들 천장에 조명 자리를 미리 보강해야 하는지 물어봐요.")
    extra += ["관리사무소에 공사 신고를 하고 소음 작업 시간을 확인해요.", _PAD[1]]
    must = e["must"]
    visit = _visit(
        must,
        {
            "check.area_basis": BASIS_Q,
            "check.doors": "바꿀 방문 개수를 실측 때 같이 세어 봐요.",
            "check.door_frame": "문틀까지 바꿀지 문짝만 바꿀지 실측 때 정해요.",
        },
        extra,
    )
    cautions = _cautions(
        {
            "text": "기존 자재 철거와 폐기물 처리는 목공과 따로 붙는 경우가 많아요. "
            "가견적에 들어 있는지 물어봐요.",
            "source": "field",
        },
        {"text": "도배를 같이 하면 목공을 먼저 끝내고 도배해요.", "source": "field"}
        if "order.dobae" in must
        else None,
        [],
    )
    return {
        "summary": f"{labels}{josa(labels)} 하는 {home} 목공이에요. {tail}",
        "steps": [{"key": k, "note": notes[k]} for k in e["step_keys"]],
        "visit_checks": visit,
        "cautions": cautions,
    }


def _pack(items: list[str], n: int) -> list[str]:
    """예문이 n개보다 많으면 가장 짧은 이웃 둘씩 한 줄로 합친다 (칸이 많은 공정)"""
    items = list(items)
    while len(items) > n:
        i = min(range(len(items) - 1), key=lambda k: len(items[k]) + len(items[k + 1]))
        items[i : i + 2] = [f"{items[i]} {items[i + 1]}"]
    return items


def gloss(text: str, trade: str) -> str:
    """풀지 않은 업계 말이 처음 나온 곳 뒤에 쉬운 말을 괄호로 붙인다 (화면 말에서 온 예문용)"""
    for name in unexplained(sentences(text), trade):
        term = TERMS[name]
        text = term.pattern.sub(lambda m, e=term.easy: f"{m.group(0)}({e})", text, count=1)
    return text


def generic(case: dict, label: str, rules: dict[str, Rule], sources: dict[str, str]) -> dict:
    """규칙의 예문으로 만든 모범 답 (설정에 손으로 쓴 답이 없는 공정)"""
    card, e = case["input"]["card"], case["expect"]
    must = e["must"]
    home = "사는 집" if card["occupied"] else "빈집"
    words = [rules[r].example for r in must if r.startswith("sum.") and "occupied" not in r]
    picked = ", ".join(dict.fromkeys(words))
    head = f"{picked}{josa(picked)} 하는 " if picked else ""
    notes = {"prep": PREP_NOTE, "finish": "자투리를 치우고 청소로 마무리해요."}
    placed = [
        rules[r].example
        for r in must
        if not r.startswith("sum.") and r != "prep.mention" and rules[r].example
    ]
    if "prep.mention" in must and "prep" not in e["step_keys"]:
        placed.insert(0, PREP_NOTE)
    placed = _pack(placed, 10)  # 실측 질문 6개 + 주의 4개 안에 넣는다
    visit = (placed[:6] + [p for p in _PAD if p not in placed])[: max(3, min(6, len(placed)))]
    src = "field" if "field" in sources else next(iter(sources))
    cautions = [{"text": t, "source": src} for t in placed[6:10]]
    for c in (_DISPUTE, _SMP):
        if len(cautions) < 2 and c["source"] in sources:
            cautions.append(c)
    while len(cautions) < 2:
        cautions.append({"text": "자세한 범위는 실측 때 업체와 같이 정해요.", "source": src})

    def g(t: str) -> str:  # 화면 말에 든 업계 말(예: 덧방 · 줄퍼티)을 푼다
        return gloss(t, case["trade"])

    return {
        "summary": g(f"{head}{home} {label} 공사예요. 자세한 범위는 실측 때 정해요."),
        "steps": [
            {"key": k, "note": g(notes.get(k, "이 단계 일을 순서대로 해요."))}
            for k in e["step_keys"]
        ],
        "visit_checks": [g(v) for v in visit],
        "cautions": [c | {"text": g(c["text"])} for c in cautions],
    }
