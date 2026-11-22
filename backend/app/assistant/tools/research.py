"""조사 담당 도구(docs/v4/09-research.md): start_research · change_research · get_research.

- 사용자 · 공사는 세션이 정한다(입력으로 받지 않는다). 목표 · 메모는 가려서(구 · 동 · 평형 · 도배 조건만) 남긴다.
- 시작은 승인 카드가 아니다(바뀌는 업무 상태가 없다). 상한 · 하루 수 · 도는 조사는 도구 결과 state로 알린다.
- 웹에서 온 글(요약 · 링크 제목 · 메모)은 자료 상자로만 모델에 간다. 링크 주소는 모델에 주지 않는다(카드에만).
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.assistant import research
from app.assistant.tools import ToolCtx, ToolError, ToolOut, obj, tool
from app.assistant.tools.customer import pid_of
from app.db import SessionLocal

KINDS = ["outside_vendors", "materials", "general"]
OFF = "지금은 조사를 맡길 수 없어요. 잠시 뒤 다시 해 주세요."


class StartIn(BaseModel):
    kind: Literal["outside_vendors", "materials", "general"]
    goal: str = Field(min_length=1, max_length=300)


class ChangeIn(BaseModel):
    action: Literal["steer", "stop"]
    note: str = Field(default="", max_length=300)


class GetIn(BaseModel):
    about: str = Field(default="", max_length=60)


@tool(
    "start_research",
    surface="customer",
    kind="read",
    status="조사를 맡기고 있어요",
    description="웹 자료가 필요한 부탁을 조사 담당에게 맡겨요(보통 1분 안팎, 승인 카드 아님). "
    "kind: outside_vendors(믿집 승인 업체가 없거나 모자란 지역의 믿집 밖 업체 공개 페이지) · materials(도배 자재 · "
    "제품 라인, 제조사 공식 페이지 먼저) · general(도배 일반 자료). 업체 찾기는 recommend_vendors를 먼저 보고, 믿집 "
    "업체가 없거나 고객이 믿집 밖을 원할 때만 써요. goal에는 '송파구 32평 아파트 도배 업체'처럼 구 · 동 · 평형 · 도배 "
    "조건과 찾을 것만 넣고 동호수 · 이름 · 연락처는 넣지 마. 평은 코드가 집 정보의 평형으로 맞춰요. 공사마다 도는 "
    "조사는 하나라 같은 종류를 또 부탁하면 그 조사의 조건을 바꿔요. 시작하면 진행 카드가 뜨니 message처럼 '잠깐(1분 "
    "안팎) 걸려요'라고만 알려.",
    model=StartIn,
    schema=obj(
        {
            "kind": {"type": "string", "enum": KINDS, "description": "조사 종류"},
            "goal": {"type": "string", "description": "찾을 것(구 · 동 · 평형 · 도배 조건만)"},
        }
    ),
)
async def start_research(tc: ToolCtx, a: StartIn) -> ToolOut:
    if tc.mode != "llm":  # 무료 모드에는 웹 조사가 없다(유료 웹 도구)
        raise ToolError("research_off", OFF)
    goal = research.clean_goal(a.goal)
    if not goal:
        raise ToolError(
            "bad_input",
            "조사할 것을 알려 주세요.",
            hint="goal에 구 · 동 · 평형 · 도배 조건과 찾을 것을 넣어요",
        )
    pid = pid_of(tc)
    async with (
        SessionLocal() as s
    ):  # 평은 집 정보의 공급 평형 그대로(QA r3 c4b: 모델이 21.4평 집을 '21평'으로 적음)
        pyeong = await research.home_pyeong(s, tc.user, pid)
    goal = research.fit_pyeong(goal, pyeong)
    got = await research.start(tc.user, pid, a.kind, goal, tc.turn_id, tc.now)
    data: dict = {"state": got.state, "message": got.message}
    if got.research is not None:
        data.update(title=got.research.title, kind=got.research.kind)
    cards = [research.card_of(got.research)] if got.state == "started" and got.research else []
    return ToolOut(data=data, cards=cards)


@tool(
    "change_research",
    surface="customer",
    kind="read",
    status="조사를 바꾸고 있어요",
    description="도는 조사를 바꾸거나 멈춰요. action=steer면 note(바뀐 조건 한 줄, 구 · 동 · 평형 · 도배 조건만)를 "
    "돌던 조사에 전하고, stop이면 그때까지 찾은 것으로 끝내요. 무엇을 바꿨는지 대화에 한 줄로 말해.",
    model=ChangeIn,
    schema=obj(
        {
            "action": {
                "type": "string",
                "enum": ["steer", "stop"],
                "description": "바꾸기 · 멈추기",
            },
            "note": {"type": "string", "description": "바뀐 조건(steer일 때)"},
        },
        required=["action"],
    ),
)
async def change_research(tc: ToolCtx, a: ChangeIn) -> ToolOut:
    note = research.clean_goal(a.note, research.NOTE_MAX)
    if a.action == "steer" and not note:
        raise ToolError("bad_input", "바꿀 조건을 알려 주세요.", hint="note에 바뀐 조건을 넣어요")
    state, r = await research.change(tc.user, pid_of(tc), a.action, note, tc.now)
    message = {
        "steered": "돌던 조사에 바꾼 조건을 전했어요.",
        "stopping": "다음 단계 전에 멈추고 그때까지 찾은 것으로 정리해요.",
        "stopped": "조사를 멈췄어요.",
        "none": "지금 도는 조사가 없어요.",
    }[state]
    data: dict = {"state": state, "message": message}
    if r is not None:
        data["title"] = r.title
    return ToolOut(data=data)


@tool(
    "get_research",
    surface="customer",
    kind="read",
    status="조사 결과를 보고 있어요",
    description="이 공사의 조사 결과를 읽어요(도는 중이면 단계 · 지난 시간, 끝났으면 요약 · 링크 제목 · 출처). about을 "
    "비우면 가장 최근 조사이고, 오늘 맡긴 조사가 여럿이면 목록(items: 제목 · 종류 · 상태)도 같이 와요. 앞 조사를 "
    "보려면 about에 그 제목 낱말(예: '용인' · '곰팡이')을 넣어 다시 읽어요. 링크 주소는 글에 쓰지 말고 결과 카드를 "
    "가리켜.",
    model=GetIn,
    schema=obj(
        {"about": {"type": "string", "description": "읽을 조사 제목 낱말(비우면 가장 최근)"}},
        required=[],
    ),
)
async def get_research(tc: ToolCtx, a: GetIn) -> ToolOut:
    async with SessionLocal() as s:
        rows = await research.of_today(s, tc.user.id, pid_of(tc), tc.now)
    return ToolOut(data=research.list_model(rows, research.pick(rows, a.about), tc.now))
