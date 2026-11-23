"""비서 도구 목록 (계약서 5장). id는 받지 않고 *_ref(v1 · m1 · r1 · s1 · w1 · d1 · p1 · n1)만 받는다.

- 읽기 도구는 기능 service 공개 함수를 부르고, 결과는 runtime이 policy.to_model을 지나 모델에 보낸다.
- 제안 도구는 대기 행동 행만 만든다(actions.propose). 실행은 사람이 승인한 뒤 actions.execute가 한다.
  제안 도구마다 asked_again 칸이 붙는다(ASKED_AGAIN): 고객이 이번 턴 말로 거절 · 거둔 같은 제안을 다시 해 달라고
  했는지는 모델이 정하고, 코드는 이번 턴 고객 말이 있는지와 같은 제안인지만 본다(propose._offer · actions.offer).
- 도구마다 DB 세션을 짧게 열고 닫는다(LLM을 기다리는 동안 세션을 쥐지 않는다).
- 정의는 이름순으로 고정한다(프롬프트 캐시 앞부분이 바뀌지 않게). 입력은 strict 스키마 + pydantic 검사.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

from app.assistant.schemas import ActionOut, CardOut, Surface, TaskOut
from app.auth.models import User

if TYPE_CHECKING:
    from app.assistant.runtime import RefTable


class ToolError(Exception):
    """도구가 돌려줄 오류(is_error). code는 영어 이름, message는 사람에게도 보일 수 있는 한국어 한 줄(이름표 ·
    도구 이름 없이), hint는 모델에만 가는 고칠 방법(이름표 · 도구 이름 · 빠진 칸)."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint


@dataclass
class ToolCtx:
    """서버가 세션으로 정한 값(도구 인자로 바꾸지 않는다)."""

    user: User
    surface: Surface
    turn_id: uuid.UUID
    chat_id: uuid.UUID
    project_id: uuid.UUID | None
    visit_id: uuid.UUID | None
    today: date
    now: datetime
    refs: "RefTable"
    mode: Literal["llm", "free"] = "llm"
    pressed: bool = False  # 사람이 카드 단추로 고른 제안(거절한 제안도 다시 만든다, choices.apply)
    text: str = ""  # 이번 턴 고객 글(가린 것). 고객 말에서만 받는 칸(공사 끝 남은 일)을 견준다
    # 이 턴에 도구가 남긴 표시(턴마다 새 ToolCtx). 같은 고르기 칩을 한 턴에 되풀이하지 않게(QA r4 s1 C1)
    marks: set[str] = field(default_factory=set)
    # 이 제안 도구 부름의 asked_again(모델이 정함: 고객이 이번 턴 말로 거절 · 거둔 같은 제안을 다시 해 달라고 함).
    # 부름마다 run이 넣는다(같은 턴의 다른 부름에 넘어가지 않게)
    asked_again: bool = False


@dataclass
class ToolOut:
    data: dict[str, Any]  # 모델에 갈 값(runtime이 to_model로 거른다)
    cards: list[CardOut] = field(default_factory=list)
    actions: list[ActionOut] = field(default_factory=list)  # commit한 새 제안
    closed: list[ActionOut] = field(default_factory=list)  # 새 제안에 밀려 닫힌 옛 제안
    task: TaskOut | None = None


Runner = Callable[[ToolCtx, Any], Awaitable[ToolOut]]


@dataclass(frozen=True)
class Tool:
    name: str
    surface: Surface
    kind: Literal["read", "propose"]
    description: str
    schema: dict
    model: type[BaseModel]
    status: str  # 도는 동안 '입력 중' 옆에 보일 말
    run: Runner


REGISTRY: dict[str, Tool] = {}

# 제안 도구마다 붙는 칸(QA r6 c1 H2: 거절 직후 '아 그냥 그거 다시 해 줘'를 낱말 규칙이 못 읽어 막음, 카드 단추로는 바로
# 다시 만들어져 말과 어긋남). 다시 해 달라는 뜻인지는 모델이 고객 말로 정하고, 코드는 이번 턴 고객 말이 있는지와 거절한
# 같은 제안인지만 본다(propose.fresh). 켜도 승인 카드를 만들 뿐 실행은 고객이 눌러야 한다(고정 선 1)
ASKED_AGAIN = "asked_again"
ASKED_AGAIN_DEF = {
    "type": "boolean",
    "description": "고객이 이번 턴 말로, 거절했거나 거둔 같은 제안을 다시 해 달라고 했으면 true(예: '아까 그거 다시 해 "
    "줘' · '실수로 거절했어요, 다시요'). 그 밖에는 늘 false예요(비서가 스스로 다시 권할 때도). 켜도 카드는 고객이 눌러야 "
    "실행돼요",
}


def with_again(schema: dict) -> dict:
    """제안 도구 입력 스키마에 asked_again 칸을 꼭 넣는 칸으로 더한다. 선택 칸으로 두면 엄격 도구의 선택 칸 합이 Claude
    한도(24, 넘으면 400)를 넘어요(고객 제안 도구 11개). 모델이 빠뜨려도(대본 · 다른 공급자) run이 false로 본다."""
    return {
        **schema,
        "properties": {**schema.get("properties", {}), ASKED_AGAIN: ASKED_AGAIN_DEF},
        "required": [*schema.get("required", []), ASKED_AGAIN],
    }


def tool(
    name: str,
    *,
    surface: Surface,
    kind: Literal["read", "propose"],
    status: str,
    description: str,
    model: type[BaseModel],
    schema: dict,
) -> Callable[[Runner], Runner]:
    def deco(fn: Runner) -> Runner:
        if name in REGISTRY:
            raise ValueError(f"도구 이름이 겹쳐요: {name}")
        got = with_again(schema) if kind == "propose" else schema
        REGISTRY[name] = Tool(name, surface, kind, description, got, model, status, fn)
        return fn

    return deco


def obj(props: dict[str, dict], required: list[str] | None = None) -> dict:
    """도구 입력 스키마(객체). required를 안 주면 모든 칸이 필수다."""
    return {
        "type": "object",
        "properties": props,
        "required": list(props) if required is None else required,
        "additionalProperties": False,
    }


# Claude는 한 요청에 엄격(strict) 도구를 20개까지 받는다(넘으면 400 'Too many strict tools').
# 승인 카드를 만드는 제안 도구만 엄격으로 두고, 읽기 도구는 엄격을 끈다(입력은 run이 pydantic으로 검사).
STRICT_MAX = 20

# 꺼 둔 도구: 모델에 보이지 않고 불러도 '쓸 수 없는 도구'예요(코드는 다시 켤 때를 위해 둬요).
# - find_floorplan_docs: 도면은 기본 정보 받기에서 뺌(11-22 사용자 '도면은 받는 거에서 빼 줘')
OFF = frozenset({"find_floorplan_docs"})


def defs(surface: Surface) -> list[dict]:
    """그 화면의 도구 정의(이름순). llm.to_claude_tools가 strict(제안 도구만) · cache_control을 붙인다."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.schema,
            "strict": t.kind == "propose",
        }
        for t in sorted(REGISTRY.values(), key=lambda t: t.name)
        if t.surface == surface and t.name not in OFF
    ]


def get(name: str, surface: Surface) -> Tool:
    t = REGISTRY.get(name)
    if t is None or t.surface != surface or name in OFF:
        raise ToolError("unknown_tool", "쓸 수 없는 도구예요.")
    return t


def input_hint(e: ValidationError) -> str:
    """입력 검사 오류 → 모델에 줄 고칠 칸(칸 이름: 까닭, 세 개까지)."""
    got = []
    for x in e.errors()[:3]:
        where = ".".join(str(k) for k in x.get("loc") or ()) or "입력"
        why = str(x.get("msg") or "").removeprefix("Value error, ")
        got.append(f"{where}: {why}")
    return "고칠 칸 - " + " / ".join(got) if got else "입력 칸을 도구 설명과 맞춰 다시 넣어요"


async def run(t: Tool, tc: ToolCtx, args: Any) -> ToolOut:
    """입력을 검사하고(틀리면 bad_input) 도구를 부른다. 제안 도구의 asked_again은 떼어 이 부름의 ToolCtx에 넣는다
    (참일 때만 켠다, 도구 입력 모델은 모른다)."""
    raw = dict(args) if isinstance(args, dict) else {}
    again = raw.pop(ASKED_AGAIN, None) is True and t.kind == "propose"
    try:
        parsed = t.model.model_validate(raw)
    except ValidationError as e:
        raise ToolError("bad_input", "도구 입력이 맞지 않아요.", hint=input_hint(e)) from e
    return await t.run(replace(tc, asked_again=again), parsed)


# 도구 모듈을 불러 REGISTRY를 채운다(정의 순서와 상관없이 defs는 이름순)
import app.assistant.tools.research  # noqa: F401  조사 담당(09-research)
from app.assistant.tools import aftercare, answer, customer, diy, floorplan, propose, vendor  # noqa: F401
