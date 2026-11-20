"""AI 칸 API (`/ai/*`): 로그인 · 역할 · 남의 것 404 · SSE · 저장 · 같은 키 · 동시 저장 409 · 되묻기 칸 ·
로그인 전 자주 묻는 질문 · 입력 한도. LLM_LIVE=false(무료 모드), 유료 호출 0회.
"""

import json
import uuid

import asyncpg
import pytest
from conftest import TEST_DSN, query
from helpers import make_admin, signup, upload, use
from v3_kb import repo_index

from tests.test_project import body as project_body

Q = "합지랑 실크 중에 뭐로 해야 해요?"


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    """시험 DB에는 지식 자료를 넣지 않으니, 운영과 같은 CSV로 만든 색인을 넘긴다(DB 적재본과 같은 규칙)."""
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def ask(api, text=Q, key=None, **over):
    body = {"client_key": key or uuid.uuid4().hex, "text": text, **over}
    return api.post("/ai/turns", json=body)


def done(r) -> dict:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    ev = events(r.text)
    assert ev[-1][0] == "done"
    return ev[-1][1]


def test_login_and_customer_role_are_required(api):
    assert ask(api).status_code == 401
    use(api, make_admin(api))
    assert ask(api).status_code == 403


def test_turn_streams_sentences_then_done_and_saves_masked_question(api):
    use(api, signup(api))
    r = ask(api, text="제 번호 010-1234-5678이에요. " + Q)
    ev = events(r.text)
    names = [e for e, _ in ev]
    assert names[0] == "token" and names[-1] == "done"
    out = ev[-1][1]
    assert out["mode"] == "free" and out["route"] == "trade"
    assert out["rev"] == 2 and out["chat_id"]
    sec = out["answer"]["sections"]
    assert sec and sec[0]["source"] == "card"
    assert all("url" not in s for x in sec for s in x["sources"])  # 출처는 이름 · 종류만
    assert "trace" not in out["answer"]
    # 짧은 답: 먼저 보일 문장은 sections에서 고른 그대로(새 글 없음)
    brief = out["answer"]["brief"]
    assert brief["lines"] and set(brief["lines"]) <= {t for x in sec for t in x["sentences"]}
    rows = query("select role, text from chat_messages order by role desc")
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert "010-1234-5678" not in rows[0]["text"]


def test_same_client_key_returns_first_answer_without_saving_twice(api):
    use(api, signup(api))
    a = done(ask(api, key="same-key-123"))
    b = done(ask(api, key="same-key-123"))
    assert a == b
    assert query("select count(*) as n from chat_messages")[0]["n"] == 2


def test_follow_up_and_slot_answer_clear_waiting(api):
    use(api, signup(api))
    first = done(ask(api))
    assert first["answer"]["ask"]["slot"] == "dobae.grade"
    cid = first["chat_id"]
    assert query("select waiting from chats where id = $1", uuid.UUID(cid))[0]["waiting"] == "trade"
    btn = {"route": "trade", "trade": "dobae", "slot": "dobae.grade", "value": "세 놓을 집"}
    second = done(ask(api, text="세 놓을 집", chat_id=cid, button=btn))
    assert second["rev"] == 3 and second["answer"]["ask"] is None
    assert query("select waiting from chats where id = $1", uuid.UUID(cid))[0]["waiting"] is None


def test_chat_state_is_saved_and_follow_up_inherits_it(api):
    """이어 묻기(agent-context.md 3절): 앞 턴의 공종 · 꼴을 chats.state에 두고 다음 턴이 물려받아요."""
    use(api, signup(api))
    first = done(ask(api, text="도배 며칠 걸려요?"))
    cid = uuid.UUID(first["chat_id"])
    st = json.loads(query("select state from chats where id = $1", cid)[0]["state"])
    assert st["trades"] == ["dobae"] and st["form"] == "period" and st["turn"] == 1
    done(ask(api, text="목공도 같이 하면요?", chat_id=str(cid)))
    st = json.loads(query("select state from chats where id = $1", cid)[0]["state"])
    assert {"dobae", "mokgong"} <= set(st["trades"]) and st["form"] == "period" and st["turn"] == 2
    # 저장한 고객 글은 독립 질문이 아니라 고객이 쓴 글 그대로(가림만)예요
    rows = query(
        "select text from chat_messages where chat_id = $1 and role = 'user' order by turn", cid
    )
    assert [r["text"] for r in rows] == ["도배 며칠 걸려요?", "목공도 같이 하면요?"]


def test_someone_elses_chat_and_missing_project_are_404(api):
    use(api, signup(api, "a@mitjip.test"))
    cid = done(ask(api))["chat_id"]
    use(api, signup(api, "b@mitjip.test"))
    assert ask(api, chat_id=cid).status_code == 404
    assert api.get(f"/ai/threads/{cid}").status_code == 404
    r = ask(api, context={"screen": "standard", "project_id": str(uuid.uuid4())})
    assert r.status_code == 404


def test_stale_rev_is_409_and_saves_nothing(api, monkeypatch):
    use(api, signup(api))
    cid = done(ask(api))["chat_id"]
    from app.agent.v3 import turn as turn_mod

    real = turn_mod.run_turn

    async def racing(*a, **k):
        out = await real(*a, **k)
        conn = await asyncpg.connect(TEST_DSN)  # 다른 질문이 먼저 저장됨
        try:
            await conn.execute("update chats set rev = rev + 1 where id = $1", uuid.UUID(cid))
        finally:
            await conn.close()
        return out

    monkeypatch.setattr(turn_mod, "run_turn", racing)
    r = ask(api, text="도배 곰팡이는 왜 생겨요?", chat_id=cid)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"
    assert query("select count(*) as n from chat_messages")[0]["n"] == 2


@pytest.mark.parametrize("text", ["", "가" * 1001])
def test_text_length_is_limited(api, text):
    use(api, signup(api))
    assert ask(api, text=text).status_code == 422


def test_threads_list_and_detail(api):
    use(api, signup(api))
    cid = done(ask(api))["chat_id"]
    rows = api.get("/ai/threads").json()
    assert rows[0]["chat_id"] == cid and rows[0]["preview"].startswith("합지랑")
    d = api.get(f"/ai/threads/{cid}").json()
    assert [m["role"] for m in d["messages"]] == ["user", "assistant"] and d["rev"] == 2
    assert api.get(f"/ai/threads?project_id={uuid.uuid4()}").status_code == 404


def test_guest_faq_needs_no_login_and_reads_cards_only(api):
    api.cookies.clear()
    r = api.get("/ai/faq")
    assert r.status_code == 200
    chips = r.json()
    assert len(chips) >= 3 and all(c["sentences"] for c in chips)
    assert "표준견적서는 업체 견적이에요?" in [c["question"] for c in chips]


def _project(api) -> str:
    photo = upload(api).json()["id"]
    r = api.post("/projects", json=project_body([photo]))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_project_screen_chat_is_tied_to_that_project(api):
    use(api, signup(api, "p@mitjip.test"))
    pid = _project(api)
    cid = done(ask(api, context={"screen": "standard", "project_id": pid}))["chat_id"]
    assert (
        str(query("select project_id from chats where id = $1", uuid.UUID(cid))[0]["project_id"])
        == pid
    )
    other = done(ask(api))["chat_id"]  # 공사 밖에서 연 대화는 공사 칸이 비어요
    assert (
        query("select project_id from chats where id = $1", uuid.UUID(other))[0]["project_id"]
        is None
    )
    assert [r["chat_id"] for r in api.get(f"/ai/threads?project_id={pid}").json()] == [cid]
    assert {r["chat_id"] for r in api.get("/ai/threads").json()} == {cid, other}
    # 공사 없이 시작한 대화를 공사 화면에서 이어 물으면 그 공사가 적혀요
    done(
        ask(
            api,
            text="도배 곰팡이는 왜 생겨요?",
            chat_id=other,
            context={"screen": "standard", "project_id": pid},
        )
    )
    assert len(api.get(f"/ai/threads?project_id={pid}").json()) == 2


def test_someone_elses_project_is_404_and_writes_no_chat(api):
    use(api, signup(api, "owner@mitjip.test"))
    pid = _project(api)
    use(api, signup(api, "other@mitjip.test"))
    before = query("select count(*) as n from chats")[0]["n"]
    assert ask(api, context={"screen": "standard", "project_id": pid}).status_code == 404
    assert query("select count(*) as n from chats")[0]["n"] == before
    assert api.get(f"/ai/threads?project_id={pid}").status_code == 404


def test_project_slot_answer_becomes_condition_and_is_not_asked_again(api):
    """모은 조건(맥락 L3): 공사 화면에서 되묻기에 답한 칸은 저장하고, 다음 대화에서도 다시 묻지 않아요."""
    use(api, signup(api, "cond@mitjip.test"))
    pid = _project(api)
    ctx = {"screen": "standard", "project_id": pid}
    q = "문 교체 견적에 손잡이랑 경첩도 포함돼요?"
    first = done(ask(api, text=q, context=ctx))
    assert first["answer"]["ask"]["slot"] == "mokgong.doors" and first["conditions"] == []
    btn = {"route": "trade", "trade": "mokgong", "slot": "mokgong.doors", "value": "문짝만"}
    second = done(ask(api, text="문짝만", chat_id=first["chat_id"], context=ctx, button=btn))
    want = {"trade": "mokgong", "key": "mokgong.doors", "label": "방문", "value": "문짝만"}
    assert second["conditions"] == [want]
    assert done(ask(api, text=q, context=ctx))["answer"]["ask"] is None  # 새 대화에서도 안 물어요
    assert api.get(f"/projects/{pid}/conditions").json() == [want]
    assert (
        api.delete(f"/projects/{pid}/conditions/mokgong.doors").json() == []
    )  # 지우면 다시 물어요
    assert done(ask(api, text=q, context=ctx))["answer"]["ask"]["slot"] == "mokgong.doors"
    # 공사 밖 대화의 칸 답은 저장하지 않아요
    out = done(ask(api, text=q))
    done(ask(api, text="문짝만", chat_id=out["chat_id"], button=btn))
    assert api.get(f"/projects/{pid}/conditions").json() == []
    use(api, signup(api, "cond2@mitjip.test"))
    assert api.get(f"/projects/{pid}/conditions").status_code == 404
    assert api.delete(f"/projects/{pid}/conditions/mokgong.doors").status_code == 404


def test_latest_thread_continues_within_24h_in_the_same_scope(api):
    """이어 보기(맥락 L2): 같은 공사(없으면 공사 밖) 대화만, 마지막 턴 뒤 24시간 안이면 이어 가요."""
    use(api, signup(api, "latest@mitjip.test"))
    assert api.get("/ai/threads/latest").json() is None
    pid = _project(api)
    cid = done(ask(api, context={"screen": "standard", "project_id": pid}))["chat_id"]
    assert api.get("/ai/threads/latest").json() is None  # 공사 대화는 공사 밖에서 잇지 않아요
    d = api.get(f"/ai/threads/latest?project_id={pid}").json()
    assert d["chat_id"] == cid and [m["role"] for m in d["messages"]] == ["user", "assistant"]
    free = done(ask(api))["chat_id"]
    assert api.get("/ai/threads/latest").json()["chat_id"] == free
    query(
        "update chats set updated_at = now() - interval '25 hours' where id = $1", uuid.UUID(free)
    )
    assert api.get("/ai/threads/latest").json() is None  # 24시간이 지나면 새 대화
    assert api.get(f"/ai/threads/latest?project_id={pid}").json()["chat_id"] == cid
    use(api, signup(api, "latest2@mitjip.test"))
    assert api.get(f"/ai/threads/latest?project_id={pid}").status_code == 404
    assert api.get("/ai/threads/latest").json() is None  # 남의 대화는 보이지 않아요


def test_llm_mode_sends_fixed_part_first_then_done(api, monkeypatch):
    """LLM 모드: 답 작성기를 기다리기 전에 고정 몫을 part로 먼저 보내고, 저장 뒤 done으로 끝낸다.
    done의 앞 묶음은 part와 같아서 화면에 이미 보인 글은 바뀌지 않는다."""
    from app.agent import llm
    from app.agent.v3.llm_mode import LlmSection
    from app.chat import service

    monkeypatch.setattr(service, "mode", lambda: "llm")
    monkeypatch.setattr(llm, "_stubs", {})  # 이 시험의 스텁은 끝나면 되돌려요
    llm.set_stub("trade", LlmSection(sentences=[]))  # 다시 쓰기 실패 → 무료 묶음 그대로
    use(api, signup(api))
    ev = events(ask(api).text)
    names = [e for e, _ in ev]
    assert names[0] == "part" and names[-1] == "done" and names.count("part") == 1
    first, out = ev[0][1], ev[-1][1]
    assert out["mode"] == "llm" and "notice" not in out["answer"]
    n = len(first["sections"])
    assert out["answer"]["sections"][:n] == first["sections"]  # 먼저 보인 글은 그대로 앞에
    assert first["fixed"] == out["answer"]["fixed"] == n
    assert not first["cards"] and out["answer"]["cards"]  # 다음 단추는 마지막 답에만
    assert len(query("select 1 from chat_messages")) == 2  # 저장은 한 번(part는 저장하지 않음)


def test_free_mode_sends_no_part(api):
    use(api, signup(api))
    assert "part" not in [e for e, _ in events(ask(api).text)]


def test_llm_daily_cap_falls_back_to_free_mode(api, monkeypatch):
    """LLM 모드 하루 상한을 넘으면 막지 않고 무료 모드로 답해요(비용 상한)."""
    from app.agent import llm
    from app.agent.v3.llm_mode import LlmSection
    from app.chat import service

    monkeypatch.setattr(service, "mode", lambda: "llm")
    monkeypatch.setattr(service, "AI_LLM_PER_DAY", 1)
    monkeypatch.setattr(llm, "_stubs", {})
    llm.set_stub("trade", LlmSection(sentences=[]))
    use(api, signup(api))
    assert done(ask(api))["mode"] == "llm"
    second = ask(api)
    assert done(second)["mode"] == "free"
    assert "part" not in [e for e, _ in events(second.text)]
