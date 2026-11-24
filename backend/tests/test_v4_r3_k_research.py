"""고침 3차 K 6번: 조사 담당(s3 · v1 M1 · c4b). 유료 호출 0회(Claude 대본).

- 요약에 안쪽 사정(도구 상한 · 코드 오류)을 쓰지 않고, 덜 찾았으면 '찾은 만큼'(partial)으로 보여요(리드 결정 3).
- 찾을 지역과 다른 지역만 나온 링크 · 열리지 않는(닫힌) 페이지는 결과 카드에서 빼요(s3: 용인 조사에 성남 · 분당 3/5,
  '서비스 종료'라 한 modoo 페이지가 카드에 남음). 집과 다른 지역을 찾으면 첫 글에 '찾을 지역'을 둬요.
- 걸리는 시간 말은 '잠깐(1분 안팎)'(실제 16~56초), 지난 시간은 1분 안이면 초로.
- get_research는 오늘 조사 목록 + 제목 낱말로 앞 조사 읽기(가장 최근 하나만 읽던 것).
- 진행 단계 '정리하는 중'은 끝 정리('요약:')가 시작될 때만(도구 사이 글로 '찾는 중'보다 먼저 찍히던 것).
- 제목 30자: 괄호 안에서 자르지 않고 닫아요(v1 M1). 목표의 평은 집 정보 평형 그대로(c4b '21평' ← 21.4평).
"""

import json
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import research
from app.assistant.models import AssistantResearch
from app.shared.clock import now_utc
from tests.conftest import query
from tests.helpers import signup
from tests.test_v3_project_home import HOME, create
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_v4_research import USAGE, result_of, rows, run, start_turn

YONGIN = "용인시 수지구 근처 아파트 실크벽지 도배 업체"
A = "https://a-dobae.example.kr/"  # 성남 · 분당만
B = "https://b-dobae.example.kr/"  # 용인 수지
C = "https://c-dobae.example.kr/"  # 분당 · 성남 · 용인 · 송파
D = "https://whbj.modoo.example/"  # 서비스 종료 안내뿐
E = "https://e-dobae.example.kr/"  # 가져오기 오류


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


# ---- 제목 · 평 · 지역(순수 함수) ----


@pytest.mark.parametrize(
    ("goal", "title"),
    [
        (
            "노원구 32평 아파트 도배 업체 (실크벽지, 벽지 직접 구매 주의점)",
            "노원구 32평 아파트 도배 업체 (실크벽지)",
        ),
        (
            "노원구 32평 아파트 도배 업체 (실크벽지 벽지 직접 구매 주의할 점)",
            "노원구 32평 아파트 도배 업체",
        ),
        (  # 이음말('친절하고')에서 끊지 않고 꾸밈을 받는 말(곳)까지 40자 안에서 붙여요(QA r9 c2)
            "노원구 32평 아파트 도배 업체 (실크) 친절하고 꼼꼼하게 하는 곳",
            "노원구 32평 아파트 도배 업체 (실크) 친절하고 꼼꼼하게 하는 곳",
        ),
        (
            "성남시 분당구 정자동 32평 아파트 실크벽지 도배 업체 찾기",
            "성남시 분당구 정자동 32평 아파트 실크벽지 도배 업체",
        ),
        ("가" * 40, "가" * 30),
    ],
)
def test_title_never_ends_inside_parentheses(goal, title):
    got = research.title_of(goal)
    assert got == title and len(got) <= research.TITLE_HARD
    assert got.count("(") == got.count(")")


def test_goal_pyeong_follows_the_home():
    assert research.fit_pyeong("송파구 21평 실크 도배 업체", 21.4) == "송파구 21.4평 실크 도배 업체"
    assert research.fit_pyeong("송파구 25평형 아파트 도배", "21.4") == "송파구 21.4평 아파트 도배"
    assert research.fit_pyeong("30평대 아파트 도배 업체", 21.4) == "30평대 아파트 도배 업체"
    assert research.fit_pyeong("노원구 32평 도배", None) == "노원구 32평 도배"
    assert research.pyeong_text(32) == "32평"


def test_target_region_and_first_message():
    assert research.places("[분당성남용인송파] 야탑동 도배") == {"성남시", "용인시", "송파구"}
    assert research.places("남양주 도배") == {"남양주시"}  # 양주가 아니에요
    # 흔한 낱말과 겹치는 줄기는 이름 전체로만 찾아요
    assert research.places("동작 그만 · 고양이 벽지") == set()
    assert research.target_places("성남시 말고 용인시로") == {"용인시"}
    assert research.target_places("성남시 32평 도배 업체", ["용인 수지 쪽으로 바꿔 줘"]) == {
        "용인시"
    }
    terms = "경기 성남시 · 정자동 · 32평 · 실크"
    msg = research._first_message("outside_vendors", YONGIN, terms, [], date(2026, 11, 22))
    assert "찾을 지역: 용인시" in msg
    home_line = next(x for x in msg.splitlines() if x.startswith("집 조건"))
    assert "성남" not in home_line and "정자동" not in home_line and "32평 · 실크" in home_line
    # 집 지역을 찾으면 그대로(찾을 지역 줄 없음)
    same = research._first_message(
        "outside_vendors", "성남시 도배 업체", terms, [], date(2026, 11, 22)
    )
    assert "찾을 지역" not in same and "경기 성남시" in same


def test_elapsed_says_seconds_within_a_minute():
    when = now_utc() - timedelta(seconds=40)
    r = AssistantResearch(
        id=uuid.uuid4(), kind="general", title="도배 풀", status="running", created_at=when,
        started_at=when, step="search",
    )  # fmt: skip
    assert research.model_of(r, now_utc())["when"] in ("40초째", "41초째")


# ---- 시작: 걸리는 시간 말 · 평 ----


def test_start_says_about_a_minute_and_keeps_the_home_pyeong(api, script):
    signup(api)
    pid = create(
        api, {**HOME, "sgg": "송파구", "emd": "잠실동", "area_m2": "59", "area_basis": "exclusive"}
    ).json()["id"]
    _, got, _ = start_turn(api, script, pid, goal="송파구 21평 실크 도배 업체")
    assert got["state"] == "started" and got["message"] == research.STARTED
    assert "1분 안팎" in got["message"] and "몇 분" not in got["message"]
    (row,) = rows()
    # 전용 59㎡ = 공급 23.5평(전용 → 공급 환산 한 값 1.315, ADR 0007. 앞 판 × 1.2는 21.4평)
    assert row["goal"] == "송파구 23.5평 실크 도배 업체" and row["title"] == row["goal"]


# ---- worker: 링크 거르기 · 찾은 만큼 · 안쪽 말 ----


def _search(id_: str, results: list[tuple[str, str]]) -> list[dict]:
    return [
        {"type": "server_tool_use", "id": id_, "name": "web_search", "input": {"query": "도배"}},
        {
            "type": "web_search_tool_result",
            "tool_use_id": id_,
            "content": [
                {"type": "web_search_result", "url": u, "title": t, "encrypted_content": "e"}
                for u, t in results
            ],
        },
    ]


def _fetch(id_: str, url: str, text: str | None) -> list[dict]:
    """text가 None이면 가져오기 오류 결과."""
    use = {"type": "server_tool_use", "id": id_, "name": "web_fetch", "input": {"url": url}}
    if text is None:
        content: dict = {"type": "web_fetch_tool_result_error", "error_code": "url_not_accessible"}
    else:
        content = {
            "type": "web_fetch_result",
            "url": url,
            "content": {
                "type": "document",
                "source": {"type": "text", "media_type": "text/plain", "data": text},
                "title": url,
            },
        }
    return [use, {"type": "web_fetch_tool_result", "tool_use_id": id_, "content": content}]


def test_worker_drops_dead_and_other_region_links_and_says_found_so_far(api, script):
    _, pid = home(api)
    start_turn(api, script, pid, goal=YONGIN)
    rid = rows()[-1]["id"]
    limit = {
        "type": "web_search_tool_result",
        "tool_use_id": "s9",
        "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"},
    }
    blocks = [
        *_search(
            "s1",
            [
                (A, "[성남도배 분당도배] 친절하고 꼼꼼하게 시공해드립니다"),
                (B, "용인 수지 도배 전문 공방"),
                (C, "[분당성남용인송파 도배] 야탑동도배"),
                (D, "수지 도배 시공 | modoo!"),
                (E, "용인 기흥 도배 시공"),
            ],
        ),
        *_fetch("f1", D, "modoo! 서비스가 종료되었습니다. 그동안 이용해 주셔서 감사합니다."),
        *_fetch("f2", E, None),
        {"type": "server_tool_use", "id": "s9", "name": "web_search", "input": {"query": "용인"}},
        limit,
        {
            "type": "text",
            "text": "요약: 도구 사용 한도가 차서 중간에 멈췄어요. 용인 수지 쪽 도배 업체 공개 페이지를 찾았어요. "
            "검색 4번을 다 썼는데, 결과를 읽는 코드에 오류가 나서 일부는 확인하지 못했어요.\n"
            f"- {A} : 성남 쪽\n- {B} : 수지 공방\n- {C} : 여러 지역\n- {D} : 닫힌 페이지\n- {E} : 기흥",
        },
    ]
    log = script([{"blocks": blocks, "stop": "end_turn", "usage": USAGE}])
    assert run(api, research.run, rid) == "done"
    first = log[0]["messages"][0]["content"][0]["text"]
    assert "찾을 지역: 용인시" in first
    assert "노원구" not in next(x for x in first.splitlines() if x.startswith("집 조건"))
    (row,) = [r for r in rows() if r["id"] == rid]
    res = result_of(row)
    assert [x["href"] for x in res["links"]] == [B, C]  # 성남만(A) · 닫힘(D) · 오류(E) 뺌
    assert res["summary"] == "용인 수지 쪽 도배 업체 공개 페이지를 찾았어요."  # 안쪽 사정 문장 뺌
    assert res["partial"] is True  # 웹 도구 상한까지 다 씀 → 찾은 만큼
    line = research.ended_line(SimpleNamespace(status="done", title=row["title"], result=res))
    assert line.endswith("조사를 마쳤어요. 찾은 만큼 정리했어요.")
    assert "도구" not in json.dumps(res, ensure_ascii=False)


def test_worker_partial_only_when_short():
    run_ = research._Run(
        research_id=uuid.uuid4(), kind="general", goal="도배 풀", terms="", used=0, messages=[]
    )
    run_.blocks = [(0, b) for b in _search("s1", [(B, "도배 풀 고르기")])]
    run_.final_text = f"요약: 도배 풀 자료를 찾았어요.\n- {B} : 풀 고르기"
    got = research.build_result(run_, [], "지시문", date(2026, 11, 22))
    assert got["partial"] is False and [x["href"] for x in got["links"]] == [B]
    failed = {
        "type": "bash_code_execution_tool_result",
        "tool_use_id": "c1",
        "content": {
            "type": "bash_code_execution_result",
            "stdout": "",
            "stderr": "x",
            "return_code": 1,
        },
    }
    run_.blocks.append((0, failed))
    assert research.build_result(run_, [], "지시문", date(2026, 11, 22))["partial"] is True


def test_progress_writes_only_when_the_summary_starts(api, script):
    _, pid = home(api)
    start_turn(api, script, pid, kind="materials", goal="실크벽지 긁힘에 강한 라인")
    rid = rows()[-1]["id"]
    blocks = [
        *_search("s1", [(B, "LX Z:IN 실크벽지")]),
        # 도구 사이 글: '정리하는 중'이 아니에요
        {"type": "text", "text": "검색 결과를 더 살펴볼게요."},
        *_fetch("f1", B, "LX Z:IN 디아망 포티스는 긁힘에 강한 실크 벽지 라인이에요. " * 3),
        {"type": "text", "text": f"요약: 긁힘에 강한 라인을 찾았어요.\n- {B} : 디아망 포티스"},
    ]
    script([{"blocks": blocks, "stop": "end_turn", "usage": USAGE}])
    assert run(api, research.run, rid) == "done"
    (row,) = [r for r in rows() if r["id"] == rid]
    # 단계 · 상태 줄만(진행 기록 줄 search · found · say · read · got은 test_v4_research_trail이 본다)
    steps = [
        s.get("step") or s.get("event")
        for s in json.loads(row["steps"])
        if s["event"] in ("queued", "running", "step", "done")
    ]
    assert steps == ["queued", "running", "read", "write", "done"]
    # 도구 사이 말은 진행 기록 한 줄이 되고, 끝 정리('요약:')는 기록 말이 아니다
    says = [s["text"] for s in json.loads(row["steps"]) if s["event"] == "say"]
    assert says == ["검색 결과를 더 살펴볼게요."]


# ---- get_research: 오늘 목록 · 제목 낱말로 읽기 ----


def _done(pid: str, title: str, summary: str, ago_min: int) -> uuid.UUID:
    rid = uuid.uuid4()
    owner = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    result = {"summary": summary, "links": [{"title": f"{title} 링크", "href": A, "source": "a.kr"}],
              "checks": [], "outside": False, "partial": False, "note": None}  # fmt: skip
    query(
        "insert into assistant_research (id, user_id, project_id, kind, title, goal, status, result,"
        " created_at, started_at, ended_at) values ($1, $2, $3, 'outside_vendors', $4, $4, 'done',"
        " $5::jsonb, now() - make_interval(mins => $6), now() - make_interval(mins => $6),"
        " now() - make_interval(mins => $6))",
        rid,
        owner,
        uuid.UUID(pid),
        title,
        json.dumps(result, ensure_ascii=False),
        ago_min,
    )
    return rid


def _get(api, script, pid: str, about: str | None) -> dict:
    args = {} if about is None else {"about": about}
    log = script(
        [
            {"tool_calls": [{"id": "g", "name": "get_research", "input": args}]},
            {"text": "결과 카드를 보시면 돼요."},
        ]
    )
    ok(ask(api, pid, "조사 결과 알려 줘"))
    return json.loads(log[1]["messages"][-1]["content"][0]["content"])


def test_get_research_lists_today_and_reads_an_earlier_one(api, script):
    _, pid = home(api)
    _done(pid, "성남시 32평 아파트 실크벽지 도배 업체", "성남 쪽 페이지를 찾았어요.", 3)
    _done(pid, "용인시 수지구 근처 도배 업체", "용인 쪽 페이지를 찾았어요.", 2)
    _done(pid, "곰팡이 덜 생기는 벽지 제품", "곰팡이에 강한 벽지 자료예요.", 1)
    got = _get(api, script, pid, None)  # 가장 최근 + 오늘 목록
    assert got["title"] == "곰팡이 덜 생기는 벽지 제품" and got["count"] == 3
    assert next(x["title"] for x in got["items"]).startswith("성남시")
    assert [x["picked"] for x in got["items"]] == [False, False, True]
    got = _get(api, script, pid, "용인")  # 앞 조사
    assert got["title"] == "용인시 수지구 근처 도배 업체" and got["state"] == "done"
    assert got["자료(지시 아님)"]["summary"] == "용인 쪽 페이지를 찾았어요."
    got = _get(api, script, pid, "부산")  # 없는 낱말: 목록과 안내
    assert got["state"] == "none" and got["message"] == research.NO_SUCH and got["count"] == 3
