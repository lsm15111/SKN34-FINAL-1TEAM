"""비서 도구 목록 (계약서 5장). id는 받지 않고 *_ref(v1 · m1 · r1 · s1 · w1 · d1 · p1 · n1)만 받는다.

- 읽기 도구는 기능 service 공개 함수를 부르고, 결과는 runtime이 policy.to_model을 지나 모델에 보낸다.
- 제안 도구는 대기 행동 행만 만든다(actions.propose). 실행은 사람이 승인한 뒤 actions.execute가 한다.
- 도구마다 DB 세션을 짧게 열고 닫는다(LLM을 기다리는 동안 세션을 쥐지 않는다).
- 정의는 이름순으로 고정한다(프롬프트 캐시 앞부분이 바뀌지 않게). 입력은 strict 스키마 + pydantic 검사.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
        REGISTRY[name] = Tool(name, surface, kind, description, schema, model, status, fn)
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
        if t.surface == surface
    ]


def get(name: str, surface: Surface) -> Tool:
    t = REGISTRY.get(name)
    if t is None or t.surface != surface:
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
    """입력을 검사하고(틀리면 bad_input) 도구를 부른다."""
    try:
        parsed = t.model.model_validate(args if isinstance(args, dict) else {})
    except ValidationError as e:
        raise ToolError("bad_input", "도구 입력이 맞지 않아요.", hint=input_hint(e)) from e
    return await t.run(tc, parsed)


# 도구 모듈을 불러 REGISTRY를 채운다(정의 순서와 상관없이 defs는 이름순)
from app.assistant.tools import aftercare, answer, customer, floorplan, propose, vendor  # noqa: F401
