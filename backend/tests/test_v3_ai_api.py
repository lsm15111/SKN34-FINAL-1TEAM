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
    rows = query("select role, text from chat_messages order by role desc")
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert "010-1234-5678" not in rows[0]["text"]


def test_account_with_four_spaces_is_masked_in_saved_ai_thread(api):
    use(api, signup(api))
    number = "123456789012"  # 시험용 숫자
    question = f"제 계좌는 국민은행    {number} 입니다. {Q}"
    chat_id = done(ask(api, text=question))["chat_id"]

    saved = api.get(f"/ai/threads/{chat_id}")
    assert saved.status_code == 200, saved.text
    messages = saved.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["text"] == f"제 계좌는 국민은행    (계좌 가림) 입니다. {Q}"
    assert number not in messages[0]["text"]


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
