"""v4 조사 담당(09-research): 시작 → 대기 줄 · jobs · arq 큐, 같은 종류 바꾸기 · 다른 종류 거절 · 하루 3번 · 비용 상한,
worker 대본(서버 도구 블록이 섞인 응답 → 결과, 링크는 결과 블록에서만, 막은 곳 · 실행 파일 꼴 · 010 지움, 근거 없는
숫자 문장 빠짐, pause_turn 잇기 · 컨테이너), 바꾸기 메모가 다음 왕복에 들어감, 멈춤 → 부분 결과, 비용 상한에서 끝,
알림 한 번 · 밤에도 바로 대화에, 남의 조사 404 · 업체 403, 턴 사실 한 줄, 실제 SDK 스트림 꼴. 유료 호출 0회."""

import json
import uuid
from datetime import date, datetime, timedelta
from functools import partial

import pytest
import redis
from v3_kb import repo_index

from app.agent import llm
from app.assistant import research, weblinks
from app.assistant.models import AssistantResearch
from app.db import SessionLocal
from app.shared import clock
from app.shared.clock import SEOUL, now_utc
from tests.conftest import REDIS_URL, query
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_vendor_profile import approved_vendor
from tests.test_visit_inbox import login

CODE_CALLER = {"type": "code_execution_20260120", "tool_id": "srvtoolu_code1"}
SITE = "https://dobae-nowon.example.kr/"
SOOMGO = "https://soomgo.com/hire/dobae/nowon"
USAGE = {"input": 10_000, "output": 1_000, "web_searches": 1}  # 40,000 마이크로달러(Sonnet 5.5)


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


def run(api, fn, *args, **kw):
    return api.portal.call(partial(fn, *args, **kw))


def rows() -> list[dict]:
    return [dict(r) for r in query("select * from assistant_research order by created_at, id")]


def notes_of(row: dict) -> list:
    v = row["notes"]
    return json.loads(v) if isinstance(v, str) else v


def result_of(row: dict) -> dict:
    v = row["result"]
    return json.loads(v) if isinstance(v, str) else v


def start_turn(api, script, pid: str, kind: str = "outside_vendors", goal: str | None = None):
    goal = goal or "노원구 상계동 32평 아파트 도배 업체 101동 1203호 010-1111-2222"
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "t1", "name": "start_research", "input": {"kind": kind, "goal": goal}}
                ]
            },
            {"text": "알아볼게요. 몇 분 걸려요. 그동안 다른 얘기 하셔도 돼요."},
        ]
    )
    ev = ok(ask(api, pid, "믿집 밖에서 도배 업체 찾아 줘"))
    tool_result = json.loads(log[1]["messages"][-1]["content"][0]["content"])
    return ev, tool_result, log


def search_blocks() -> list[dict]:
    """동적 거르기: 코드 실행 안에서 부른 검색(caller) · 결과 · 코드 출력. 지도 · 인스타 · 실행 파일 꼴 · 010이 섞임."""
    return [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_code1",
            "name": "code_execution",
            "input": {"code": "r = web_search(query='노원구 도배')"},
        },
        {
            "type": "server_tool_use",
            "id": "srvtoolu_s1",
            "name": "web_search",
            "input": {"query": "노원구 아파트 도배 업체"},
            "caller": CODE_CALLER,
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_s1",
            "caller": CODE_CALLER,
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://map.naver.com/p/entry/place/1",
                    "title": "지도 장소",
                    "encrypted_content": "e1",
                },
                {
                    "type": "web_search_result",
                    "url": "https://soomgo.com/hire/dobae/nowon",
                    "title": "숨고 노원구 도배 고수 010-1234-5678",
                    "encrypted_content": "e2",
                    "page_age": "April 30, 2025",
                },
                {
                    "type": "web_search_result",
                    "url": "http://evil.example/setup.exe",
                    "title": "무료 견적 프로그램",
                    "encrypted_content": "e3",
                },
                {
                    "type": "web_search_result",
                    "url": "https://www.instagram.com/p/abc",
                    "title": "인스타 시공 사진",
                    "encrypted_content": "e4",
                },
                {
                    "type": "web_search_result",
                    "url": SITE,
                    "title": "노원 도배 공방",
                    "encrypted_content": "e5",
                },
            ],
        },
        {
            "type": "code_execution_tool_result",
            "tool_use_id": "srvtoolu_code1",
            "content": {
                "type": "code_execution_result",
                "stdout": "노원 도배 공방 시공 사례 12건",
                "stderr": "",
                "return_code": 0,
                "content": [],
            },
        },
    ]


def fetch_and_summary(text: str | None = None) -> list[dict]:
    return [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_f1",
            "name": "web_fetch",
            "input": {"url": SITE},
        },
        {
            "type": "web_fetch_tool_result",
            "tool_use_id": "srvtoolu_f1",
            "content": {
                "type": "web_fetch_result",
                "url": SITE,
                "retrieved_at": "2026-11-22T01:00:00Z",
                "content": {
                    "type": "document",
                    "source": {
                        "type": "text",
                        "media_type": "text/plain",
                        "data": "노원구 아파트 도배 전문. 실크벽지 시공. 상담 010-9876-5432. 2019년부터 영업.",
                    },
                    "title": "노원 도배 공방 | 소개",
                },
            },
        },
        {
            "type": "text",
            "text": text
            or (
                "요약: 노원구에서 도배를 하는 공개 페이지를 찾았어요. 노원 도배 공방은 2019년부터 영업한다고 "
                "적혀 있어요. 이 업체는 평점 4.9로 1위예요. 시공비는 32평 250만 원이에요. 상담은 "
                "010-9876-5432로 하면 돼요. 이 업체는 2015년에 시작했어요.\n"
                f"- {SITE} : 실크 시공 소개\n- {SOOMGO} : 숨고 노원구 글\n"
                "- https://evil.example/x : 모델이 쓴 주소"
            ),
        },
    ]


def started_research(api, script, pid: str, kind: str = "outside_vendors") -> uuid.UUID:
    _, got, _ = start_turn(api, script, pid, kind)
    assert got["state"] == "started", got
    return rows()[-1]["id"]


# ---- 시작 ----


def test_start_makes_queued_row_job_and_queue_then_steers_and_refuses(api, script):
    _, pid = home(api)
    ev, got, _log = start_turn(api, script, pid)
    assert got["state"] == "started" and got["kind"] == "outside_vendors"
    (card,) = [d for e, d, _ in ev if e == "card" and d["kind"] == "research"]
    (row,) = rows()
    assert card["card_id"] == f"research-{row['id']}" and card["data"]["status"] == "queued"
    assert card["data"]["phase"] == "progress"
    # 목표 · 제목은 가린 글(동호수 · 번호 없음), 시작한 턴이 남는다
    assert "1203" not in row["goal"] and "010" not in row["goal"] and "101동" not in row["goal"]
    assert row["goal"].startswith("노원구 상계동 32평") and row["title"] == research.title_of(
        row["goal"]
    )
    assert row["status"] == "queued" and row["turn_id"] == uuid.UUID(ev[0][1]["turn_id"])
    (job,) = query("select * from jobs where kind = 'assistant_research'")
    assert job["ref_id"] == row["id"] and job["dedup_key"] == f"assistant_research:{row['id']}"
    assert job["run_at"] - row["created_at"] == research.WATCH_AFTER
    r = redis.Redis.from_url(REDIS_URL)
    assert r.exists(f"arq:job:research:{row['id']}") == 1  # arq 큐에 한 번
    # 같은 종류를 또 부탁하면 새 일 대신 바꾸기 메모
    _, again, _ = start_turn(api, script, pid, goal="실크벽지만 하는 곳으로")
    assert again["state"] == "steered" and len(rows()) == 1
    assert [n["text"] for n in notes_of(rows()[0])] == ["실크벽지만 하는 곳으로"]
    # 다른 종류는 도는 조사가 끝나기 전에 시작하지 않는다
    _, busy, _ = start_turn(api, script, pid, kind="materials", goal="실크벽지 인기 라인")
    assert busy["state"] == "busy" and len(rows()) == 1


def test_day_limit_and_budget_refuse_without_new_row(api, script, monkeypatch):
    _, pid = home(api)
    owner = query("select owner_id from projects")[0]["owner_id"]
    for _ in range(research.DAY_MAX):
        query(
            "insert into assistant_research (id, user_id, project_id, kind, title, goal, status,"
            " result, ended_at) values ($1, $2, $3, 'general', '도배 풀', '도배 풀', 'done', '{}',"
            " now())",
            uuid.uuid4(),
            owner,
            uuid.UUID(pid),
        )
    _, got, _ = start_turn(api, script, pid)
    assert got["state"] == "limit" and len(rows()) == research.DAY_MAX
    query("update assistant_research set created_at = now() - interval '2 days'")
    real_ok = llm.budget_ok

    async def over(user_id, label="turn"):  # 조사 몫만 상한에 걸린 것처럼(턴은 LLM 모드)
        return False if label == "research" else await real_ok(user_id, label)

    monkeypatch.setattr(llm, "budget_ok", over)
    _, got, _ = start_turn(api, script, pid)
    assert got["state"] == "budget" and len(rows()) == research.DAY_MAX
    assert query("select count(*) as n from jobs where kind = 'assistant_research'")[0]["n"] == 0


def test_goal_with_only_private_text_is_bad_input(api, script):
    _, pid = home(api)
    log = script(
        [
            {"tool_calls": [{"id": "t1", "name": "start_research",
                             "input": {"kind": "general", "goal": "010-1234-5678"}}]},
            {"text": "무엇을 찾을지 알려 주세요."},
        ]
    )  # fmt: skip
    ok(ask(api, pid, "자료 찾아 줘"))
    err = log[1]["messages"][-1]["content"][0]
    assert err["is_error"] and "bad_input" in err["content"] and rows() == []


# ---- worker ----


def test_worker_keeps_only_tool_result_links_and_gated_summary(api, script):
    _, pid = home(api)
    rid = started_research(api, script, pid)
    other = {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_s3", "content": [
        {"type": "web_search_result", "url": "https://dobae-gwanak.example.kr/",
         "title": "관악구 신림동 도배", "encrypted_content": "e7"}]}  # fmt: skip
    log = script(
        [
            {"blocks": [*search_blocks(), other], "stop": "pause_turn",
             "container": "container_1", "usage": USAGE},
            {"blocks": fetch_and_summary(), "stop": "end_turn", "usage": USAGE},
        ]
    )  # fmt: skip
    assert run(api, research.run, rid) == "done"
    # pause_turn은 새 말 없이 같은 대화를 다시 보내고 컨테이너를 잇는다
    assert len(log) == 2 and log[1]["container"] == "container_1"
    assert log[1]["messages"][-1]["role"] == "assistant"
    assert [m["role"] for m in log[1]["messages"]] == ["user", "assistant"]
    tools = {t["name"]: t for t in log[0]["tools"]}
    assert tools["web_search"]["type"] == "web_search_20260209"
    assert (
        tools["web_search"]["max_uses"] == 4
        and "map.naver.com" in tools["web_search"]["blocked_domains"]
    )
    assert tools["web_fetch"]["type"] == "web_fetch_20260209"
    assert tools["web_fetch"]["max_content_tokens"] == 3000
    assert "soomgo.com" in tools["web_fetch"]["blocked_domains"]
    assert "soomgo.com" not in tools["web_search"]["blocked_domains"]
    first = log[0]["messages"][0]["content"][0]["text"]
    assert "노원구" in first and "1203" not in first and "010" not in first
    (row,) = rows()
    res = result_of(row)
    assert row["status"] == "done" and row["calls"] == 2 and row["cost_micros"] == 80_000
    hrefs = [x["href"] for x in res["links"]]
    # 끝 글이 적은 결과 블록 링크만(고르지 않은 관악구 결과 · 모델 글 속 주소 없음), 검색 결과 순서 그대로
    assert hrefs == [SOOMGO, SITE]
    soomgo = res["links"][0]
    assert "010" not in soomgo["title"] and soomgo["title"] == "숨고 노원구 도배 고수"
    assert soomgo["day"] == "2025-04-30" and soomgo["source"] == "soomgo.com"
    assert all(
        x["memo"] is None for x in res["links"]
    )  # 믿집 밖 업체는 메모 없이(순위 · 평가 없음)
    assert res["summary"] == (
        "노원구에서 도배를 하는 공개 페이지를 찾았어요. 노원 도배 공방은 2019년부터 영업한다고 적혀 있어요."
    )  # 평점 · 순위 · 값 · 번호 · 근거 없는 숫자(2015년) 문장은 빠진다
    assert res["outside"] and res["checks"] and res["note"] and res["partial"] is False
    steps = [s.get("step") or s.get("event") for s in json.loads(row["steps"])]
    assert steps[:2] == ["queued", "running"] and "read" in steps and steps[-1] == "done"
    usage = query("select purpose, model, cost_micros from llm_usage order by created_at")
    assert [u["purpose"] for u in usage] == ["assistant", "assistant", "research", "research"]
    assert {u["model"] for u in usage[2:]} == {"claude-sonnet-5-5"}


def test_materials_memos_come_from_model_lines_but_links_from_blocks(api, script):
    _, pid = home(api)
    rid = started_research(api, script, pid, "materials")
    text = (
        "요약: LX Z:IN 실크벽지 라인을 찾았어요. 롤 폭은 106cm예요. 한 롤에 4만 원이에요.\n"
        f"- {SITE} : 실크 시공 소개\n"
        "- https://www.lxzin.com/wallpaper : 베스띠는 지금 실크벽지 베스트예요"
    )
    blocks = [
        *search_blocks(),
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_s2", "content": [
            {"type": "web_search_result", "url": "https://www.lxzin.com/wallpaper",
             "title": "LX Z:IN 벽지 실크 106cm", "encrypted_content": "e6"}]},
        *fetch_and_summary(text),
    ]  # fmt: skip
    script([{"blocks": blocks, "stop": "end_turn", "usage": USAGE}])
    assert run(api, research.run, rid) == "done"
    res = result_of(rows()[0])
    hrefs = [x["href"] for x in res["links"]]
    assert hrefs[0] == "https://www.lxzin.com/wallpaper"  # 제조사 공식 먼저
    memos = {x["href"]: x["memo"] for x in res["links"]}
    assert memos["https://www.lxzin.com/wallpaper"] == "베스띠는 지금 실크벽지 베스트예요"
    assert memos[SITE] == "실크 시공 소개"
    assert (
        res["summary"] == "LX Z:IN 실크벽지 라인을 찾았어요. 롤 폭은 106cm예요."
    )  # 값은 모으지 않는다
    assert not res["outside"] and res["checks"] == [] and res["note"] is None


def test_steer_note_goes_into_next_round_trip_and_stop_ends_with_partial(api, script, monkeypatch):
    _, pid = home(api)
    rid = started_research(api, script, pid)
    real = research._control
    seen = {"n": 0}

    async def spy(research_id):
        seen["n"] += 1
        if seen["n"] == 2:  # 첫 왕복(pause_turn) 뒤 · 다음 왕복 전
            async with SessionLocal() as s:
                r = await s.get(AssistantResearch, research_id)
                await research._steer(s, r, "상계동 실크 시공하는 곳 위주", now_utc())
                await s.commit()
        return await real(research_id)

    monkeypatch.setattr(research, "_control", spy)
    log = script(
        [
            {"blocks": search_blocks(), "stop": "pause_turn", "container": "container_1",
             "usage": USAGE},
            {"blocks": fetch_and_summary(), "stop": "end_turn", "usage": USAGE},
        ]
    )  # fmt: skip
    assert run(api, research.run, rid) == "done"
    last = log[1]["messages"][-1]  # 멈춘 턴이 도구 결과로 끝나 system 글로 잇는다
    assert last["role"] == "system" and "상계동 실크 시공하는 곳 위주" in last["content"]
    assert rows()[0]["notes_used"] == 1
    # 끝난 턴 뒤 메모는 user 말로 새 왕복
    query("delete from assistant_research")
    rid = started_research(api, script, pid)
    seen["n"] = 0
    log = script(
        [
            {"blocks": fetch_and_summary(), "stop": "end_turn", "usage": USAGE},
            {
                "text": "요약: 바꾼 조건으로 더 찾을 곳이 없어요.",
                "stop": "end_turn",
                "usage": USAGE,
            },
        ]
    )
    assert run(api, research.run, rid) == "done"
    assert len(log) == 2 and log[1]["messages"][-1]["role"] == "user"
    assert "상계동 실크 시공하는 곳 위주" in log[1]["messages"][-1]["content"][0]["text"]
    # 멈춤: 다음 왕복 전에 그때까지 찾은 것으로 끝낸다
    query("delete from assistant_research")
    rid = started_research(api, script, pid)
    seen["n"] = 0

    async def stop_spy(research_id):
        seen["n"] += 1
        if seen["n"] == 2:
            await research._stop(research_id, now_utc())
        return await real(research_id)

    monkeypatch.setattr(research, "_control", stop_spy)
    log = script([{"blocks": search_blocks(), "stop": "pause_turn", "usage": USAGE}])
    assert run(api, research.run, rid) == "stopped"
    (row,) = rows()
    res = result_of(row)
    assert len(log) == 1 and row["status"] == "stopped" and res["partial"] is True
    assert [x["href"] for x in res["links"]] == ["https://soomgo.com/hire/dobae/nowon", SITE]
    assert res["summary"] is None  # 끝 정리 전에 멈춤: 지어내지 않는다
    assert row["stop_at"] is not None and row["ended_at"] is not None


def test_cost_cap_ends_after_first_round_trip(api, script):
    _, pid = home(api)
    rid = started_research(api, script, pid)
    big = {"input": 60_000, "output": 3_000, "web_searches": 4}  # 190,000 마이크로달러 > $0.15
    log = script(
        [
            {"blocks": search_blocks(), "stop": "pause_turn", "usage": big},
            {"blocks": fetch_and_summary(), "stop": "end_turn", "usage": USAGE},
        ]
    )
    assert run(api, research.run, rid) == "done"
    (row,) = rows()
    assert len(log) == 1 and row["calls"] == 1 and row["cost_micros"] == 190_000
    assert result_of(row)["partial"] is True and len(result_of(row)["links"]) == 2


def test_notify_once_feed_at_night_and_watch_closes_stalled(api, script):
    _, pid = home(api)
    rid = started_research(api, script, pid)
    script(
        [{"blocks": [*search_blocks(), *fetch_and_summary()], "stop": "end_turn", "usage": USAGE}]
    )

    async def at_night():
        with clock.moved_to(datetime(2026, 11, 23, 2, 0, tzinfo=SEOUL)):  # 새벽 2시
            return await research.run(rid)

    assert run(api, at_night) == "done"
    assert run(api, research.run, rid) == "skipped"  # 같은 일이 두 번 와도
    job = type("J", (), {"ref_id": rid})()

    async def watch_once():
        async with SessionLocal() as s:
            got = await research.watch(s, job, now_utc())
            await s.commit()
            return got

    assert run(api, watch_once) is False
    (n,) = query("select * from notifications where kind = 'assistant_research'")
    assert n["dedup_key"] == f"research:{rid}" and n["link"] == f"/projects/{pid}"
    assert "조사를 마쳤어요" in n["body"]
    feed = api.get("/assistant/feed", params={"project_id": pid}).json()
    (item,) = [x for x in feed["items"] if x["id"] == f"r-{rid}"]
    assert item["parts"][0]["t"] == "text" and item["parts"][0]["src"] == "guide"
    card = item["parts"][1]["card"]
    assert card["kind"] == "research" and card["card_id"] == f"research-{rid}-result"
    assert card["data"]["phase"] == "result" and card["data"]["summary"]
    # 감시: 6분 지나도 도는 중이면 멈춘 조사로 닫고 알림 · 대화 한 줄
    query("delete from notifications")
    rid2 = uuid.uuid4()
    owner = query("select owner_id from projects")[0]["owner_id"]
    query(
        "insert into assistant_research (id, user_id, project_id, kind, title, goal, status,"
        " started_at) values ($1, $2, $3, 'general', '도배 풀', '도배 풀', 'running', now())",
        rid2,
        owner,
        uuid.UUID(pid),
    )
    job.ref_id = rid2
    assert run(api, watch_once) is True
    row = next(r for r in rows() if r["id"] == rid2)
    assert (row["status"], row["error_code"]) == ("failed", "stalled")
    assert len(query("select * from notifications where kind = 'assistant_research'")) == 1
    feed = api.get("/assistant/feed", params={"project_id": pid}).json()
    (item,) = [x for x in feed["items"] if x["id"] == f"r-{rid2}"]
    assert [p["t"] for p in item["parts"]] == ["text"]  # 찾은 게 없으면 한 줄만


def test_api_owner_only_vendor_forbidden_and_stop(api, script):
    _, pid = home(api)
    rid = started_research(api, script, pid)
    got = api.get(f"/assistant/research/{rid}")
    assert got.status_code == 200 and got.json()["status"] == "queued"
    assert got.json()["phase"] == "progress"
    home(api, "other@mitjip.test")
    assert api.get(f"/assistant/research/{rid}").status_code == 404
    assert api.post(f"/assistant/research/{rid}/stop").status_code == 404
    approved_vendor(api, "v@mitjip.test")
    assert api.get(f"/assistant/research/{rid}").status_code == 403
    login(api, "home@mitjip.test")
    stopped = api.post(f"/assistant/research/{rid}/stop")
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    assert (
        api.post(f"/assistant/research/{rid}/stop").json()["status"] == "stopped"
    )  # 두 번째도 200
    assert run(api, research.run, rid) == "skipped"  # 멈춘 조사는 worker가 돌리지 않는다
    assert len(query("select * from notifications where kind = 'assistant_research'")) == 1


def test_turn_facts_line_and_get_research_tool(api, script):
    _, pid = home(api)
    rid = started_research(api, script, pid)
    log = script([{"text": "조사가 도는 중이에요."}])
    ok(ask(api, pid, "조사 어떻게 돼 가요?"))
    facts = log[0]["messages"][-1]
    assert facts["role"] == "system" and "진행 중인 조사: 노원구 상계동" in facts["content"]
    assert "분째)" in facts["content"]
    script(
        [{"blocks": [*search_blocks(), *fetch_and_summary()], "stop": "end_turn", "usage": USAGE}]
    )
    assert run(api, research.run, rid) == "done"
    log = script(
        [
            {"tool_calls": [{"id": "g", "name": "get_research", "input": {}}]},
            {"text": "결과 카드를 보시면 돼요."},
        ]
    )
    ok(ask(api, pid, "조사 결과 알려 줘"))
    assert "방금 끝난 조사: 노원구 상계동" in log[0]["messages"][-1]["content"]
    body = log[1]["messages"][-1]["content"][0]["content"]
    data = json.loads(body)
    assert data["state"] == "done" and "자료(지시 아님)" in data
    assert "https://" not in body and "010" not in body  # 주소 · 번호는 모델에 가지 않는다
    assert data["자료(지시 아님)"]["links"][0]["source"] == "soomgo.com"


def test_change_tool_steers_and_stops(api, script):
    _, pid = home(api)
    started_research(api, script, pid)
    log = script(
        [
            {"tool_calls": [{"id": "c", "name": "change_research",
                             "input": {"action": "steer", "note": "중계동도 봐 줘 1203호"}}]},
            {"text": "중계동도 같이 보도록 바꿨어요."},
        ]
    )  # fmt: skip
    ok(ask(api, pid, "중계동도 같이 봐 줘"))
    assert json.loads(log[1]["messages"][-1]["content"][0]["content"])["state"] == "steered"
    assert [n["text"] for n in notes_of(rows()[0])] == ["중계동도 봐 줘"]
    log = script(
        [
            {"tool_calls": [{"id": "c", "name": "change_research", "input": {"action": "stop"}}]},
            {"text": "조사를 멈췄어요."},
        ]
    )
    ok(ask(api, pid, "조사 그만해"))
    assert json.loads(log[1]["messages"][-1]["content"][0]["content"])["state"] == "stopped"
    assert rows()[0]["status"] == "stopped"


def test_real_sdk_stream_reports_server_blocks_and_container(monkeypatch):
    """실제 SDK 스트림 꼴(서버 도구 블록 · pause_turn · 컨테이너)을 on_block · ClaudeReply가 그대로 받는다."""
    import httpx2

    from tests.test_v4_llm_claude import _real_sdk
    from tests.test_v4_llm_claude import run as run_loop

    caller = {"type": "code_execution_20260120", "tool_id": "srvtoolu_c"}
    sse = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_r", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 900, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {
            "type": "server_tool_use", "id": "srvtoolu_s", "name": "web_search", "input": {},
            "caller": caller}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {
            "type": "input_json_delta", "partial_json": "{\"query\": \"노원구 도배\"}"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
            "type": "web_search_tool_result", "tool_use_id": "srvtoolu_s", "caller": caller,
            "content": [{"type": "web_search_result", "url": SITE, "title": "노원 도배 공방",
                         "encrypted_content": "e"}]}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta", "delta": {
            "stop_reason": "pause_turn", "stop_sequence": None,
            "container": {"id": "container_9", "expires_at": "2099-01-01T00:00:00Z"}},
            "usage": {"output_tokens": 30,
                      "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}}}),
        ("message_stop", {"type": "message_stop"}),
    ]  # fmt: skip
    sent: list[dict] = []

    def handler(request):
        sent.append(json.loads(request.content))
        body = "".join(f"event: {e}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for e, d in sse)
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )

    install = _real_sdk(monkeypatch, handler)
    seen: list[tuple[str, str | None]] = []

    async def on_block(kind, name):
        seen.append((kind, name))

    async def go():
        install()
        return await llm.claude_stream(
            "s",
            [{"role": "user", "content": "찾아 줘"}],
            tools=research.TOOLS,
            purpose="research",
            container="container_8",
            on_block=on_block,
        )

    reply = run_loop(monkeypatch, go)
    assert seen == [("server_tool_use", "web_search"), ("web_search_tool_result", None)]
    assert reply.stop == "pause_turn" and reply.container == "container_9"
    assert reply.content[1]["type"] == "web_search_tool_result"
    assert reply.content[1]["content"][0]["url"] == SITE
    assert sent[0]["container"] == "container_8" and sent[0]["model"] == "claude-sonnet-5-5"
    assert [t["name"] for t in sent[0]["tools"]] == ["web_fetch", "web_search"]
    (row,) = query("select purpose, web_searches from llm_usage")
    assert (row["purpose"], row["web_searches"]) == ("research", 1)


def test_clean_goal_title_and_links_helpers():
    assert research.clean_goal("노원구 상계2동 32평 101동 1203호 010-1111-2222 https://x.y") == (
        "노원구 상계2동 32평"
    )
    assert research.scrub("숨고 0507-1234-5678 도배 a@b.co") == "숨고 도배"
    assert research.clean_goal("도배 업체 0507-1234-5678 1588-1234") == "도배 업체"
    assert research.title_of("가" * 40) == "가" * 30
    # 제목은 '이름 | 사이트 소개'의 앞 이름만(광고 · 순위 문구 뺌), 앞이 너무 짧으면 그대로
    assert (
        research._title("노원 도배 공방 시공 || 1000만이 고른 No.1 앱", "a.kr")
        == "노원 도배 공방 시공"
    )
    assert research._title("홈 | 노원 도배 공방", "a.kr") == "홈 | 노원 도배 공방"
    # 출처: 한글 도메인은 한글로, 다른 글자 흉내(키릴 а)는 xn-- 그대로
    assert research._source("도배공방.kr".encode("idna").decode("ascii")) == "도배공방.kr"
    assert research._source("аpple.com".encode("idna").decode("ascii")) == "xn--pple-43d.com"
    assert research._source("soomgo.com") == "soomgo.com"
    # 링크 열쇠: %인코딩 · www. · 끝 빗금이 달라도 같은 페이지
    assert weblinks.key("https://www.daangn.com/kr/%EB%8F%84%EB%B0%B0/") == weblinks.key(
        "https://daangn.com/kr/도배"
    )
    # 글 날짜: 날짜 꼴 · 검색한 날 기준 'N days ago'(실제 검색 결과 꼴), 달 · 해 전은 날이 하나로 안 정해져 모름
    today = date(2026, 11, 22)
    assert research._day_of("2025-04-30", today) == date(2025, 4, 30)
    assert research._day_of("569 days ago", today) == date(2025, 5, 2)
    assert research._day_of("2 weeks ago", today) == date(2026, 11, 8)
    assert research._day_of("5 hours ago", today) == today
    assert research._day_of("3 months ago", today) is None
    assert llm.claude_model_for("research")[0] == "claude-sonnet-5-5"
    when = now_utc() - timedelta(minutes=3)
    r = AssistantResearch(
        id=uuid.uuid4(), kind="general", title="도배 풀", status="running", created_at=when,
        started_at=when, step="read",
    )  # fmt: skip
    assert research.model_of(r, now_utc())["when"] == "3분째"
