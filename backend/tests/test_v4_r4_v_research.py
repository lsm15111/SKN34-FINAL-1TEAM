"""고침 4차 V(QA r4 s3): 조사 칩 · 바꾼 조사 제목. 유료 호출 0회(Claude 대본).

- 자재 조사가 가장 최근이어도 오늘 맡긴 믿집 밖 업체 조사가 있으면 '믿집 밖에서 찾아볼까요?'를 다시 내지 않아요
  (service._looking이 가장 최근 조사의 종류만 봐서 업체 조사를 또 맡기게 함).
- 바꾸기(change_research) 메모에 지역 · 조건이 있으면 제목을 바꿔요: 진행 카드 · 턴 사실 · 끝 줄 · 종 알림이 옛 지역
  ('성남시 …')으로 남던 것. get_research는 바꾸기 메모 낱말로도 찾아요.
"""

import json
import uuid
from datetime import timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import research
from app.assistant.models import RESEARCH_LIVE
from app.db import SessionLocal
from app.shared.clock import now_utc
from tests.conftest import query
from tests.test_v3_visit_kit import customer
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_v4_r3_a1_facts import facts_of
from tests.test_v4_r3_a1_suggest import suggests
from tests.test_v4_research import rows, run, start_turn

SEONGNAM = "성남시 32평 아파트 도배 업체 (실크벽지, 빈 집)"


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def add_research(pid: str, kind: str, title: str, ago_min: int) -> uuid.UUID:
    """끝난 조사 한 줄(ago_min분 전에 맡기고 끝남)."""
    rid = uuid.uuid4()
    owner = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    result = {"summary": None, "links": [], "checks": [], "outside": kind == "outside_vendors",
              "partial": True, "note": None}  # fmt: skip
    query(
        "insert into assistant_research (id, user_id, project_id, kind, title, goal, status, result,"
        " created_at, started_at, ended_at) values ($1, $2, $3, $4, $5, $5, 'done', $6::jsonb,"
        " now() - make_interval(mins => $7), now() - make_interval(mins => $7),"
        " now() - make_interval(mins => $7))",
        rid,
        owner,
        uuid.UUID(pid),
        kind,
        title,
        json.dumps(result, ensure_ascii=False),
        ago_min,
    )
    return rid


# ---- 조사 칩(s3 턴 8) ----


def test_outside_chip_stays_away_after_a_later_materials_research(api, script):
    _, pid = customer(api)  # 업체 0곳 지역: 처음엔 '믿집 밖에서 찾아볼까요?'
    assert "step-outside" in suggests(api, script, pid)
    outside = add_research(pid, "outside_vendors", SEONGNAM, 9)
    add_research(pid, "materials", "곰팡이 덜 생기는 벽지 제품", 1)  # 가장 최근은 자재 조사
    assert "step-outside" not in suggests(api, script, pid, "알겠어요, 고마워요")
    # 업체 조사가 없으면(자재 조사만) 다시 권해요
    query("delete from assistant_research where id = $1", outside)
    assert "step-outside" in suggests(api, script, pid, "그럼 업체는요?")


def test_outside_lately_counts_a_research_made_today(api):
    _, pid = home(api)
    rid = add_research(pid, "outside_vendors", SEONGNAM, 0)
    day = research._day_start(now_utc())
    made = day + timedelta(hours=1)  # 오늘 01:00(서울)에 맡겨 1분 만에 끝남
    query(
        "update assistant_research set created_at = $2, started_at = $2, ended_at = $3 where id = $1",
        rid,
        made,
        made + timedelta(minutes=1),
    )
    owner = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]

    async def lately(now):
        async with SessionLocal() as s:
            return await research.outside_lately(s, owner, uuid.UUID(pid), now)

    assert run(api, lately, made + timedelta(minutes=30)) is True  # 방금 끝남
    # 같은 날 14:30: 끝난 지 12시간이 넘었어도 오늘 맡겼으니 다시 권하지 않아요
    assert run(api, lately, made + timedelta(hours=13, minutes=30)) is True
    assert run(api, lately, day + timedelta(days=1, hours=14)) is False  # 다음 날 · 12시간 넘음


# ---- 바꾼 조사의 제목(s3 턴 3 → 종 알림 · 턴 5 · 7) ----


@pytest.mark.parametrize(
    ("goal", "notes", "kind", "want"),
    [
        (
            SEONGNAM,
            ["성남시 말고 용인시(수지 인근) 32평 실크벽지 조건으로 찾아 줘"],
            "outside_vendors",
            "용인시 32평 아파트 도배 업체 (실크벽지, 빈 집)",
        ),
        (
            "노원구 상계동 32평 아파트 도배 업체",
            ["도봉구로 바꿔서 찾아 줘"],
            "outside_vendors",
            "도봉구 32평 아파트 도배 업체",  # 옛 구의 동은 같이 빠져요
        ),
        (
            "노원구 상계동 32평 아파트 실크벽지 도배 업체",
            ["실크 말고 합지로"],
            "outside_vendors",
            "노원구 상계동 32평 아파트 합지벽지 도배 업체",
        ),
        ("32평 아파트 도배 업체", ["송파구 업체 위주로"], "outside_vendors", "송파구 32평 아파트 도배 업체"),
        (SEONGNAM, ["용인시로 찾아 줘", "실크만 하는 곳"], "outside_vendors", "용인시 32평 아파트 도배 업체 (실크벽지, 빈 집)"),
        ("노원구 상계동 21평 아파트 도배 업체", ["중계동도 봐 줘"], "outside_vendors", "노원구 상계동 21평 아파트 도배 업체"),
        ("곰팡이 덜 생기는 벽지 제품", ["수지 코팅 제품 위주로"], "materials", "곰팡이 덜 생기는 벽지 제품"),
        ("성남시 32평 아파트 도배 업체", ["34평 기준으로"], "outside_vendors", "성남시 34평 아파트 도배 업체"),
        ("성남시 21.4평 아파트 도배 업체", ["21평 실크"], "outside_vendors", "성남시 21.4평 아파트 도배 업체"),
    ],
)  # fmt: skip
def test_steered_title_follows_the_changed_place_and_condition(goal, notes, kind, want):
    assert research.steered_title(goal, notes, kind) == want


def test_change_research_renames_the_title_bell_end_line_and_pick(api, script):
    _, pid = home(api)
    _ev, got, _log = start_turn(api, script, pid, goal=SEONGNAM)
    assert got["state"] == "started"
    (row,) = rows()
    before = row["title"]
    assert before.startswith("성남시 ")
    log = script(
        [
            {
                "tool_calls": [
                    {
                        "id": "c",
                        "name": "change_research",
                        "input": {
                            "action": "steer",
                            "note": "성남시 말고 용인시(수지 인근) 위주로",
                        },
                    }
                ]
            },
            {"text": "돌던 조사를 용인시 업체 위주로 바꿨어요."},
        ]
    )
    ok(ask(api, pid, "아 그거 성남시 말고 용인시로 찾아 줘요"))
    changed = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    want = "용인시" + before[len("성남시") :]
    assert changed["state"] == "steered" and changed["title"] == want
    assert rows()[0]["title"] == want
    # 다음 턴 사실도 바꾼 제목으로
    log = script([{"text": "아직 찾는 중이에요."}])
    ok(ask(api, pid, "조사 어떻게 돼 가요?"))
    assert f"진행 중인 조사: {want}(" in facts_of(log[0])

    async def finish():
        async with SessionLocal() as s:
            await research._end(
                s, row["id"], RESEARCH_LIVE, "done", {"links": [], "partial": True}, None, now_utc()
            )
            await s.commit()

    run(api, finish)
    # 끝 줄(대화)도 바꾼 제목으로. 종 알림은 만들지 않아요(11-24)
    feed = api.get("/assistant/feed", params={"project_id": pid}).json()
    (end,) = [x for x in feed["items"] if x["id"] == f"r-{row['id']}"]
    assert end["parts"][0]["text"].startswith(want) and "성남" not in end["parts"][0]["text"]
    assert query("select * from notifications where kind = 'assistant_research'") == []
    # '수지'(바꾸기 메모에만 있는 낱말)로도 그 조사를 읽어요
    log = script(
        [
            {"tool_calls": [{"id": "g", "name": "get_research", "input": {"about": "수지"}}]},
            {"text": "결과 카드를 보시면 돼요."},
        ]
    )
    ok(ask(api, pid, "아까 수지 쪽 찾은 거 보여 줘"))
    read = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    assert read["title"] == want and read["state"] == "done"
