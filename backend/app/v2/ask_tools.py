"""v2 AI 도구 정의. 서버가 정하고 브라우저는 고르지 못한다.

- 서버 도구: 서버가 바로 실행한다 (계산 엔진: price_reference · set_schedule_constraints, 지식 검색: search_knowledge).
- 화면 도구: 브라우저가 실행하고 결과만 돌려준다 (고객 상태 저장 · 단계 카드 · 이어 물을 질문).
"""

STYLES = ("modern-white", "natural-wood", "hotel-gray", "midcentury", "french-neutral")
SPACES = ("room", "kitchen", "bath", "entry", "window")
STEPS = (
    "styles", "guide", "info", "scope", "budget", "photo", "plan", "materials", "finish", "quote", "sched",
)  # fmt: skip
TIERS = ("economy", "basic", "premium")
RAG_TRADES = (
    "도배", "바닥재", "타일", "욕실", "가구", "목공", "필름", "도장", "중문", "조명", "창호", "마감",
)  # fmt: skip

_OBJ = {"type": "object", "properties": {}}

DEFS: dict[str, dict] = {
    "price_reference": {
        "description": "지금 고객 집(평형 · 고른 자재)으로 계산한 도배 · 목공 표준견적서(공공 기준, 부가세 포함)와 "
        "시장 기준(업체 견적에 보통 적히는 금액, 부가세 별도) 범위, 그리고 차이 이유를 준다. "
        "공사비 · 평당 가격 · 견적이 비싼지 물으면 반드시 쓴다.",
        "parameters": _OBJ,
    },
    "set_schedule_constraints": {
        "description": "고객이 말한 일정 조건을 공정표 계산 조건으로 바꾼다. 말한 것만 넣는다. "
        "날짜는 YYYY-MM-DD. 날짜 계산은 코드가 한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "weekend_work": {"type": "boolean"},
                "end_by": {"type": "string"},
                "start_after": {"type": "string"},
                "avoid_dates": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            },
        },
    },
    "set_style": {
        "description": "고객이 원하는 스타일을 정한다. 고객이 분위기를 말하거나 스타일을 고르면 쓴다.",
        "parameters": {
            "type": "object",
            "properties": {"style_id": {"type": "string", "enum": list(STYLES)}},
            "required": ["style_id"],
        },
    },
    "set_home_info": {
        "description": "고객이 말한 집 정보를 저장한다. 말한 칸만 넣는다. pyeong은 공급 평형(10~90).",
        "parameters": {
            "type": "object",
            "properties": {
                "pyeong": {"type": "number"},
                "region": {"type": "string"},
                "living": {"type": "string", "enum": ["living", "vacant"]},
                "move": {
                    "type": "string",
                    "description": "입주 날 YYYY-MM-DD(날을 모르면 YYYY-MM)",
                },
            },
        },
    },
    "set_scope": {
        "description": "공사 범위를 정한다. all이면 집 전체, part면 spaces에 공간을 넣는다.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["all", "part"]},
                "spaces": {"type": "array", "items": {"type": "string", "enum": list(SPACES)}},
            },
            "required": ["kind"],
        },
    },
    "set_budget": {
        "description": "고객이 말한 총예산(만 원)이나 원하는 자재 등급을 저장한다. "
        "예산만 주면 등급은 화면 기준으로 정해진다.",
        "parameters": {
            "type": "object",
            "properties": {
                "budget_manwon": {"type": "number"},
                "tier": {"type": "string", "enum": list(TIERS)},
            },
        },
    },
    "pick_material": {
        "description": "믿집 자재 자료의 id로 자재를 고른다. 고객이 고르겠다고 했을 때만 쓴다.",
        "parameters": {
            "type": "object",
            "properties": {"material_id": {"type": "string"}},
            "required": ["material_id"],
        },
    },
    "show_step": {
        "description": "답을 마친 뒤 화면에 띄울 단계 카드를 하나 정한다. "
        "고객이 그 단계로 가자고 하거나 다음으로 넘어갈 때 쓴다.",
        "parameters": {
            "type": "object",
            "properties": {"step": {"type": "string", "enum": list(STEPS)}},
            "required": ["step"],
        },
    },
    "search_knowledge": {
        "description": "믿집 지식 자료(법규 · 표준계약 · 소비자 분쟁 · 표준시방서 · 시공 순서 · 자재 고르는 법 · "
        "비용 구조 · 반셀프 경험담)에서 근거를 찾는다. 같은 뜻을 다른 말로 쓴 검색어 2~3개를 queries에 넣으면 "
        "함께 찾아 합친다. 결과의 source_type이 출처 종류이고, enough=false면 질문과 잘 맞는 자료가 없다는 "
        "뜻이다. 법규 · 기간 · 수치를 말하기 전에는 꼭 쓴다.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "짧은 한국어 검색어(핵심 낱말 2~6개)"},
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                    "description": "같은 뜻을 다른 낱말로 쓴 검색어(선택)",
                },
                "trade": {"type": "string", "enum": list(RAG_TRADES)},
            },
            "required": ["query"],
        },
    },
    "suggest_questions": {
        "description": "답 끝에 고객이 이어서 물어보면 좋을 짧은 질문 2~3개(동사+대상, 20자 안쪽)를 버튼으로 "
        "보여 준다. 매 답마다 한 번 쓴다.",
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {"type": "array", "items": {"type": "string"}, "maxItems": 3}
            },
            "required": ["questions"],
        },
    },
}

# 계산 엔진 결과: 공사 기간 숫자의 근거가 된다 (지식 자료는 근거가 아니다)
CALC_TOOLS = frozenset({"price_reference", "set_schedule_constraints"})
SERVER_TOOLS = CALC_TOOLS | {"search_knowledge"}
CLIENT_TOOLS = frozenset(DEFS) - SERVER_TOOLS

# 대화 종류마다 쓸 수 있는 도구
BY_KIND: dict[str, tuple[str, ...]] = {
    "chat": (
        "price_reference",
        "set_style",
        "set_home_info",
        "set_scope",
        "set_budget",
        "pick_material",
        "show_step",
        "search_knowledge",
        "suggest_questions",
    ),
    "quote_explanation": ("search_knowledge",),
    "schedule": ("set_schedule_constraints", "search_knowledge"),
}


def tools_for(kind: str) -> list[dict]:
    return [{"name": n, **DEFS[n]} for n in BY_KIND[kind]]
