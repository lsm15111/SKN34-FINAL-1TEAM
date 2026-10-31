"""규칙을 모두 지키는 모범 답(가짜 LLM 응답). 표준 라이브러리만 쓴다.

- 무료 점검(T0): 사례마다 이 답을 채점해 모두 통과하면 기대 검사 규칙끼리 모순이 없다는 증거다
- --fake 실행: 유료 호출 없이 실행기 · 채점 · 요약 경로를 돌린다
지식 파일 문장을 쉬운 말로 줄여 쓴 것이라 품질 기준선은 아니다.
"""

import re

_MOK_LABEL = {
    "molding": "천장 몰딩",
    "base": "걸레받이",
    "door": "방문 교체",
    "flatten": "천장 평탄화",
}
_SMP = {
    "text": "공공 기준 단가는 업체 견적과 견주어 보는 기준이고 업체 가격이 아니에요.",
    "source": "smp",
}
_DISPUTE = {"text": "견적서는 항목과 포함 범위를 글로 받아 두세요.", "source": "dispute"}
_BASIS_Q = "적은 면적이 분양 평형(공급면적)인지 전용면적인지 같이 확인해요."
_MOVE_Q = "짐을 누가 옮기고 덮는지 물어봐요. 짐 양을 봐야 정할 수 있어요."


def _eul(word: str) -> str:
    """받침이 있으면 '을', 없으면 '를'"""
    ch = re.sub(r"\(.*\)$", "", word).strip()[-1]
    return "을" if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "를"


def _visit(must: list[str], checks: dict[str, str], extra: list[str]) -> list[str]:
    v = [_MOVE_Q] if "after.moving" in must else []
    v += [q for rid, q in checks.items() if rid in must]
    for q in extra:
        if len(v) >= 6:
            break
        v.append(q)
    return v[:6]


def _cautions(first: dict, order: dict | None, more: list[dict]) -> list[dict]:
    out = [first] + ([order] if order else []) + more + [_SMP, _DISPUTE]
    return out[:4]


def wallpaper(case: dict) -> dict:
    inp, e = case["input"], case["expect"]
    c, t = inp["common"], inp["trades"]["dobae"]
    ceil = t["include_ceiling"]
    grade = "실크(기본형)" if t["grade"] == "basic" else "합지(저가형)"
    where = "벽과 천장을 모두 바르는" if ceil else "벽만 바르고 천장은 하지 않는"
    home = "사는 집" if c["occupied"] else "빈집"
    notes = {
        "prep": "가구를 한쪽으로 옮기고 바닥과 가구를 비닐로 덮어요.",
        "paper": "기존 벽지를 뗄지 정한 뒤 갈라진 곳을 메워 바탕을 고르고, 밑종이와 새 벽지를 "
        + ("벽과 천장에" if ceil else "벽에")
        + " 발라요.",
        "finish": "이음매가 벌어지거나 들뜬 곳이 없는지 같이 보고 청소로 마무리해요.",
    }
    must = e["must"]
    visit = _visit(
        must,
        {
            "check.area_basis": _BASIS_Q,
            "check.grade": "실크와 합지 중 어떤 벽지로 할지 실측 때 정해요.",
            "check.include_ceiling": "천장도 바를지 실측 때 정해요.",
        },
        [
            "기존 벽지가 몇 겹인지 봐 달라고 해요. 그걸 봐야 철거할지 정할 수 있어요.",
            "벽에 갈라진 곳이 있는지 봐 달라고 해요.",
            "관리사무소에 공사 신고를 해야 하는지 확인해요.",
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
        if "order.other" in must
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


def carpentry(case: dict) -> dict:
    inp, e = case["input"], case["expect"]
    c, t = inp["common"], inp["trades"]["mokgong"]
    items, frame = t["items"], t.get("door_frame")
    home = "사는 집" if c["occupied"] else "빈집"
    labels = ", ".join(_MOK_LABEL[i] for i in items)
    if "door" in items:
        tail = "방문은 문틀까지 바꿔요." if frame else "방문은 문틀은 두고 문짝만 바꿔요."
    else:
        tail = "자세한 범위는 실측 때 정해요."
    trims = [n for n, i in (("몰딩", "molding"), ("걸레받이", "base")) if i in items]
    removes = trims + (["튀어나온 조명 상자(등박스)"] if "flatten" in items else [])
    lines = [
        f"{side}과 벽이 만나는 선에 {n}{_eul(n)}"
        for side, n, i in (("천장", "몰딩", "molding"), ("바닥", "걸레받이", "base"))
        if i in items
    ]
    notes = {
        "prep": "가구를 한쪽으로 옮기고 바닥과 가구를 비닐로 덮어요.",
        "remove": f"기존 {' · '.join(removes)}{_eul(removes[-1]) if removes else ''} 뜯고 "
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
        extra.append(f"{'과 '.join(trims)}{_eul(trims[-1])} 붙일 길이를 방마다 재 달라고 해요.")
    if "door" in items:
        extra.append("문 크기와 손잡이 · 경첩이 견적에 들어가는지 물어봐요.")
    if "flatten" in items:
        extra.append("평평하게 만들 천장에 조명 자리를 미리 보강해야 하는지 물어봐요.")
    extra += [
        "관리사무소에 공사 신고를 하고 소음 작업 시간을 확인해요.",
        "공사 순서를 업체와 같이 정해요.",
    ]
    must = e["must"]
    visit = _visit(
        must,
        {
            "check.area_basis": _BASIS_Q,
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
        if "order.other" in must
        else None,
        [],
    )
    return {
        "summary": f"{labels}{_eul(labels)} 하는 {home} 목공이에요. {tail}",
        "steps": [{"key": k, "note": notes[k]} for k in e["step_keys"]],
        "visit_checks": visit,
        "cautions": cautions,
    }


def ideal_plan(agent: str, case: dict) -> dict:
    return {"wallpaper": wallpaper, "carpentry": carpentry}[agent](case)
