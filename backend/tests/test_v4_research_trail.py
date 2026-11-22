"""조사 진행 기록 · 결과 항목 · 제조사 그림(피클 표본처럼, docs/v4/09-research.md). 유료 호출 0회(Claude 대본).

- 진행 기록: 블록이 끝날 때 검색어(연락처 뗌) · 결과 수(막은 곳 빼고) · 읽은 곳(도메인 · 제목 · 열었는지) · 결과
  추리기 · 도구 앞 한 줄 말(요약과 같은 검사)을 steps에 남기고, 카드는 그것으로 기록 줄을 만든다. 막은 곳 ·
  가져오기를 막은 곳은 남기지 않고, 끝 정리('요약:')는 기록 말이 아니다.
- 결과 항목: '- 이름 | 특징 | 주의할 점 | 주소' 줄 → 결과 블록 링크와 맞는 것만(지어낸 주소 버림), 칸마다 검사,
  '-'는 빈칸. 믿집 밖 업체는 항목 없이 링크만. 자재 결과 뒤에는 고를 것을 묻는 한 줄.
- 그림: 제조사 공식 페이지만, robots.txt를 지키고(막힘 · 403 · 5xx · 연결 실패면 읽지 않음), 그 사이트 https
  그림만. 실패는 그림 없이.
- 실제 SDK 스트림: 블록이 끝날 때 서버 도구 입력(검색어)이 다 모인 블록이 온다.
"""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import linkimage, research, weblinks
from app.assistant.models import AssistantResearch
from app.db import SessionLocal
from tests.test_v4_assistant_turns import home
from tests.test_v4_research import USAGE, result_of, rows, run, start_turn

LX = "https://www.lxzin.com/zin/product/11441"
SH = "https://www.shinhanwall.co.kr/brands/products-view.html?uid=1761&depth1=3&depth2=10"
MAP = "https://map.naver.com/p/entry/place/1"
SOOMGO = "https://soomgo.com/hire/dobae/nowon"
GUIDE = "https://dobae-guide.example.kr/closed"
LX_IMG = "https://octapi.lxzin.com/upload/product/a_thumb_l.jpg"


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


def _fetched(id_: str, url: str, text: str, title: str) -> list[dict]:
    return [
        {"type": "server_tool_use", "id": id_, "name": "web_fetch", "input": {"url": url}},
        {"type": "web_fetch_tool_result", "tool_use_id": id_, "content": {
            "type": "web_fetch_result", "url": url, "content": {
                "type": "document", "title": title,
                "source": {"type": "text", "media_type": "text/plain", "data": text}}}},
    ]  # fmt: skip


def _failed(id_: str, url: str, code: str) -> list[dict]:
    return [
        {"type": "server_tool_use", "id": id_, "name": "web_fetch", "input": {"url": url}},
        {"type": "web_fetch_tool_result", "tool_use_id": id_,
         "content": {"type": "web_fetch_tool_result_error", "error_code": code}},
    ]  # fmt: skip


def materials_blocks() -> list[dict]:
    final = (
        "요약: 많이 고르는 실크 벽지 두 가지를 찾았어요.\n항목:\n"
        f"- 디아망 회벽/화이트 (PR002-01) | 회벽처럼 요철이 크고 두꺼워요 | 순백보다 살짝 회색이 돌아요 | {LX}\n"
        f"- 조용한 사색 (15053-1) | 요철이 얕고 매트해요 | - | {SH}\n"
        "- 지어낸 제품 | 좋아요 | - | https://made-up.example/x"
    )
    return [
        {"type": "text", "text": "LX Z:IN 공식 페이지에서 인기 실크 제품부터 볼게요."},
        {"type": "server_tool_use", "id": "srvtoolu_s1", "name": "web_search",
         "input": {"query": "LX 실크벽지 인기 제품 010-1234-5678"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_s1", "content": [
            {"type": "web_search_result", "url": MAP, "title": "지도", "encrypted_content": "e1"},
            {"type": "web_search_result", "url": LX, "title": "디아망 / 회벽/화이트 | LX 지인",
             "encrypted_content": "e2"},
            {"type": "web_search_result", "url": SH, "title": "KCC신한벽지 - 조용한 사색",
             "encrypted_content": "e3"}]},
        # 근거 없는 숫자가 든 말은 기록하지 않는다
        {"type": "text", "text": "평점 4.9인 제품부터 볼게요."},
        {"type": "server_tool_use", "id": "srvtoolu_c1", "name": "code_execution",
         "input": {"code": "print(1)"}},
        {"type": "code_execution_tool_result", "tool_use_id": "srvtoolu_c1", "content": {
            "type": "code_execution_result", "stdout": "", "stderr": "", "return_code": 0,
            "content": []}},
        *_fetched("srvtoolu_f1", LX,
                  "디아망 회벽/화이트 PR002-01. 회벽처럼 요철이 크고 두꺼운 실크 벽지예요.",
                  "디아망 / 회벽/화이트 / PR002-01 - 규격/사이즈 | LX 지인 벽지&벽장재"),
        *_failed("srvtoolu_f2", SOOMGO, "url_not_allowed"),  # 가져오기를 막은 곳: 기록 안 함
        *_failed("srvtoolu_f3", GUIDE, "url_not_accessible"),
        {"type": "text", "text": final},
    ]  # fmt: skip


def pages(seen: list[str], robots: dict[str, httpx.Response], page: dict[str, httpx.Response]):
    """linkimage._client 자리: robots · 페이지 응답 표(없는 주소는 404). 부른 주소를 seen에 남긴다."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        assert request.headers["user-agent"] == linkimage.UA
        if url.endswith("/robots.txt"):
            return robots.get(url, httpx.Response(404))
        return page.get(url, httpx.Response(404))

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"User-Agent": linkimage.UA}
    )


def html(body: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=body)


def text(body: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/plain"}, text=body)


def test_trail_items_pictures_and_closing_line(api, script, monkeypatch):
    _, pid = home(api)
    start_turn(api, script, pid, "materials", "실크벽지 질감 인기 제품")
    rid = rows()[-1]["id"]
    seen: list[str] = []
    monkeypatch.setattr(
        linkimage,
        "_client",
        pages(
            seen,
            {
                "https://www.lxzin.com/robots.txt": text("User-agent: *\nDisallow: /mypage*/"),
                "https://www.shinhanwall.co.kr/robots.txt": text("User-agent: *\nDisallow: /brands/"),
            },
            {LX: html(f'<head><meta data-hid="og:image" property="og:image" content="{LX_IMG}"></head>')},
        ),
    )  # fmt: skip
    script([{"blocks": materials_blocks(), "stop": "end_turn", "usage": USAGE}])
    assert run(api, research.run, rid) == "done"
    (row,) = [r for r in rows() if r["id"] == rid]

    async def load():
        async with SessionLocal() as s:
            return await s.get(AssistantResearch, rid)

    r = run(api, load)
    # 진행 기록: 검색어는 연락처를 떼고, 결과 수는 막은 곳(지도)을 빼고, 가져오기를 막은 곳(숨고)은 남기지 않는다
    trail = [(t.kind, t.text, t.title, t.n, t.ok) for t in research.data_of(r).trail]
    assert trail == [
        ("start", None, None, None, None),
        ("say", "LX Z:IN 공식 페이지에서 인기 실크 제품부터 볼게요.", None, None, None),
        ("search", "LX 실크벽지 인기 제품", None, 2, None),
        ("filter", None, None, None, None),
        ("read", "lxzin.com", "디아망 / 회벽/화이트 / PR002-01 - 규격/사이즈", None, True),
        ("read", "dobae-guide.example.kr", None, None, False),
        ("write", None, None, None, None),
        ("end", "done", None, None, None),
    ]
    raw = json.dumps(r.steps, ensure_ascii=False)
    assert "soomgo" not in raw and "1234-5678" not in raw
    # 검색 줄을 펼치면 찾은 페이지(막은 곳 뺌, 제목은 '이름 | 사이트 소개'의 앞 이름), 읽기 줄은 읽은 주소
    lines = research.data_of(r).trail
    assert [(h.title, h.source, h.href) for h in lines[2].hits] == [
        ("디아망 / 회벽/화이트", "lxzin.com", LX),
        ("KCC신한벽지 - 조용한 사색", "shinhanwall.co.kr", SH),
    ]
    assert lines[4].href == LX and lines[5].href == GUIDE

    # 항목: 결과 블록 링크와 맞는 것만(지어낸 주소 버림), '-'는 빈칸, 제조사 그림은 robots가 허락한 곳만
    res = result_of(row)
    assert res["items"] == [
        {"name": "디아망 회벽/화이트 (PR002-01)", "feature": "회벽처럼 요철이 크고 두꺼워요",
         "caution": "순백보다 살짝 회색이 돌아요", "href": LX, "source": "lxzin.com", "image": LX_IMG},
        {"name": "조용한 사색 (15053-1)", "feature": "요철이 얕고 매트해요", "caution": None,
         "href": SH, "source": "shinhanwall.co.kr", "image": None},
    ]  # fmt: skip
    assert res["summary"] == "많이 고르는 실크 벽지 두 가지를 찾았어요."
    assert seen == [
        "https://www.lxzin.com/robots.txt",
        "https://www.shinhanwall.co.kr/robots.txt",
        LX,  # 신한 페이지는 robots가 막아 읽지 않는다
    ]

    # 비서가 읽는 값: 항목(이름 · 특징 · 주의할 점 · 출처)은 자료 상자로만, 주소 · 그림은 없다
    box = research.model_of(r, datetime.now(UTC))[research.policy.DATA_KEY]
    assert [x["name"] for x in box["items"]] == [
        "디아망 회벽/화이트 (PR002-01)",
        "조용한 사색 (15053-1)",
    ]
    assert "href" not in box["items"][0] and "image" not in box["items"][0]

    # 대화: 끝 줄 → 결과 카드 → 고를 것을 묻는 한 줄(자재 · 항목 있음)
    async def feed():
        async with SessionLocal() as s:
            return await research.feed_items(s, row["user_id"], uuid.UUID(pid))

    (item,) = run(api, feed)
    assert [p.t for p in item.parts] == ["text", "card", "text"]
    assert item.parts[2].text == research.ASK_PICK


def test_outside_vendors_keep_links_only_and_trail_pairs_by_ref():
    run_ = research._Run(
        research_id=uuid.uuid4(), kind="outside_vendors", goal="노원구 도배 업체",
        terms="서울 노원구 · 32평", used=0, messages=[],
    )  # fmt: skip
    site = "https://dobae-nowon.example.kr/"
    run_.blocks = [
        (0, {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
            {"type": "web_search_result", "url": site, "title": "노원 도배 공방 | 노원구",
             "encrypted_content": "e"}]}),
    ]  # fmt: skip
    run_.final_text = (
        f"요약: 노원구 도배 페이지를 찾았어요.\n항목:\n- 노원 도배 공방 | 평점 4.9 1위 | - | {site}"
    )
    got = research.build_result(run_, [], "지시문", date(2026, 11, 22))
    assert got["items"] == [] and [x["href"] for x in got["links"]] == [site]
    assert all(x["memo"] is None for x in got["links"])  # 믿집 밖 업체는 평가 없이

    # 함께 부른 검색 둘의 결과가 거꾸로 와도 부름 열쇠로 짝을 맞추고, 이어진 결과 추리기는 한 줄, 40줄만
    t0 = datetime(2026, 11, 22, 1, 0, tzinfo=UTC)

    def at(sec: int) -> str:
        return (t0 + timedelta(seconds=sec)).isoformat()

    steps = [
        {"event": "queued", "at": at(0)},
        {"event": "running", "at": at(1)},
        {"event": "search", "at": at(2), "q": "가", "ref": "a"},
        {"event": "search", "at": at(3), "q": "나", "ref": "b"},
        {"event": "found", "at": at(4), "ref": "b", "n": 5},
        {"event": "found", "at": at(5), "ref": "a", "n": 1},
        {"event": "filter", "at": at(6)},
        {"event": "filter", "at": at(7)},
        {"event": "step", "at": at(8), "step": "read"},
        {"event": "read", "at": at(9), "site": "a.kr", "ref": "c"},
        {"event": "miss", "at": at(10), "ref": "c"},
        {"event": "found", "at": at(11), "ref": "zz", "n": 9},  # 짝 없는 결과는 버린다
        {"event": "steer", "at": at(12)},
        {"event": "stopped", "at": at(13)},
    ]
    rows_ = [(t.kind, t.text, t.n, t.ok) for t in research.trail_of(steps)]
    assert rows_ == [
        ("start", None, None, None),
        ("search", "가", 1, None),
        ("search", "나", 5, None),
        ("filter", None, None, None),
        ("read", "a.kr", None, False),
        ("steer", None, None, None),
        ("end", "stopped", None, None),
    ]
    many = [{"event": "search", "at": at(i), "q": f"q{i}", "ref": str(i)} for i in range(50)]
    kept = research.trail_of(many)
    assert len(kept) == research.TRAIL_MAX and kept[-1].text == "q49"


def test_trail_titles_blocked_pages_and_repeat_reads():
    # 페이지 제목은 낱말 끝에서 자르고, 막힘 안내만 받은 페이지는 '열지 못했어요', 같은 페이지를 다시 읽은 줄은 한 번만
    assert research.clip(
        "실크벽지 베스트(베스띠) / 내추럴 페인팅/화이트 / 82483-01 - 규격/사이즈", 40
    ) == ("실크벽지 베스트(베스띠) / 내추럴 페인팅/화이트 / 82483-01…")
    blocked = {"type": "web_fetch_tool_result", "tool_use_id": "srvtoolu_f9", "content": {
        "type": "web_fetch_result", "url": "https://a.example.kr/", "content": {
            "type": "document", "title": "Block Page",
            "source": {"type": "text", "media_type": "text/plain", "data": "브라우저 설정 안내 " * 30}}}}  # fmt: skip
    assert research.trail_events(blocked) == [("miss", {"ref": "srvtoolu_f9"})]
    t0 = datetime(2026, 11, 22, 1, 0, tzinfo=UTC)
    steps = [
        {"event": "read", "at": t0.isoformat(), "site": "lxzin.com", "u": LX, "ref": "a"},
        {"event": "got", "at": t0.isoformat(), "ref": "a", "title": "디아망"},
        {"event": "read", "at": t0.isoformat(), "site": "lxzin.com", "u": LX, "ref": "b"},
        {"event": "got", "at": t0.isoformat(), "ref": "b", "title": "디아망"},
        {"event": "read", "at": t0.isoformat(), "site": "lxzin.com", "ref": "c"},
        {"event": "miss", "at": t0.isoformat(), "ref": "c"},
    ]
    rows = [(t.kind, t.title, t.ok, t.href) for t in research.trail_of(steps)]
    assert rows == [("read", "디아망", True, LX), ("read", None, False, None)]


def test_partial_only_when_the_last_filter_code_failed():
    """동적 거르기 코드가 중간에 실패해도 다시 짜서 성공했으면 '찾은 만큼'이 아니다(실제 조사 3건이 모두 붙던 것)."""

    def code(id_: str, rc: int) -> dict:
        return {"type": "code_execution_tool_result", "tool_use_id": id_, "content": {
            "type": "code_execution_result", "stdout": "", "stderr": "", "return_code": rc,
            "content": []}}  # fmt: skip

    error = {"type": "bash_code_execution_tool_result", "tool_use_id": "c9",
             "content": {"type": "bash_code_execution_tool_result_error", "error_code": "unavailable"}}  # fmt: skip
    assert weblinks.code_failed([code("c1", 1), code("c2", 0)]) is False
    assert weblinks.code_failed([code("c1", 0), code("c2", 1)]) is True
    assert weblinks.code_failed([code("c1", 0), error]) is True
    assert weblinks.code_failed([]) is False


def test_pictures_follow_robots_and_take_only_same_site_https(monkeypatch):
    sh_page = (
        '<img src="/img/logo.png"><img src="/upload/product/a.jpg" width="700">'
        '<img src="/upload/product/b.jpg">'
    )
    seen: list[str] = []
    monkeypatch.setattr(
        linkimage,
        "_client",
        pages(
            seen,
            {
                "https://www.lxzin.com/robots.txt": httpx.Response(403),
                "https://www.shinhanwall.co.kr/robots.txt": httpx.Response(404),
            },
            {SH: html(sh_page)},
        ),
    )
    items = [
        {"href": LX, "name": "a"},  # robots 403: 읽지 않음
        {"href": SH, "name": "b"},  # robots 없음(404): 읽음 · 본문 첫 제품 그림
        {"href": "https://dobae-nowon.example.kr/", "name": "c"},  # 그림을 찾는 사이트 아님
        {"href": "http://www.lxzin.com/zin/product/1", "name": "d"},  # http 페이지는 읽지 않음
    ]
    asyncio.run(linkimage.add_images(items))
    assert [x.get("image") for x in items] == [
        None,
        "https://www.shinhanwall.co.kr/upload/product/a.jpg",
        None,
        None,
    ]
    assert seen == [
        "https://www.lxzin.com/robots.txt",
        "https://www.shinhanwall.co.kr/robots.txt",
        SH,
    ]

    # og:image: 상대 주소는 풀고, 다른 사이트 · http 그림은 버린다
    assert linkimage.find_image('<meta content="/a.jpg" property="og:image">', LX) == (
        "https://www.lxzin.com/a.jpg"
    )
    assert (
        linkimage.find_image('<meta property="og:image" content="https://evil.example/a.jpg">', LX)
        is None
    )
    assert (
        linkimage.find_image(
            '<meta property="og:image" content="http://octapi.lxzin.com/a.jpg">', LX
        )
        is None
    )
    assert linkimage.find_image("<meta property='og:image' content='https://octapi.lxzin.com/b.jpg'>", LX) == (
        "https://octapi.lxzin.com/b.jpg"
    )  # fmt: skip
    # 사이트 공용 그림(로고 · 공유용 대표 그림)은 제품 사진이 아니라 버린다(실제 조사에서 로고가 붙던 것)
    for generic in ("/images/opengraph_2026.png", "/img/og_image.jpg", "/common/logo.svg"):
        assert linkimage.find_image(f'<meta property="og:image" content="{generic}">', LX) is None

    # 5xx robots · 연결 실패 · 다른 사이트로 넘어가는 페이지는 그림 없이(오류를 내지 않는다)
    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.lxzin.com":
            raise httpx.ConnectTimeout("느림")
        if request.url.host == "evil.example":
            return html('<img src="/upload/product/x.jpg">')
        if str(request.url).endswith("/robots.txt"):
            return text("User-agent: *\nAllow: /")
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    monkeypatch.setattr(
        linkimage, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(broken))
    )
    items = [{"href": LX, "name": "a"}, {"href": SH, "name": "b"}]
    asyncio.run(linkimage.add_images(items))
    assert [x.get("image") for x in items] == [None, None]


def test_real_sdk_stream_reports_finished_blocks_with_tool_input(monkeypatch):
    """실제 SDK 스트림: input_json_delta로 온 검색어가 블록이 끝날 때 다 모인 블록으로 on_block_end에 온다."""
    import httpx2

    from tests.test_v4_llm_claude import _real_sdk
    from tests.test_v4_llm_claude import run as run_loop

    sse = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_r", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 900, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {
            "type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {
            "type": "text_delta", "text": "제조사 페이지부터 볼게요."}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
            "type": "server_tool_use", "id": "srvtoolu_s", "name": "web_search", "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {
            "type": "input_json_delta", "partial_json": "{\"query\": \"LX 실크"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {
            "type": "input_json_delta", "partial_json": "벽지\"}"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta", "delta": {
            "stop_reason": "pause_turn", "stop_sequence": None},
            "usage": {"output_tokens": 30,
                      "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}}}),
        ("message_stop", {"type": "message_stop"}),
    ]  # fmt: skip

    def handler(request):
        body = "".join(f"event: {e}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for e, d in sse)
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )

    install = _real_sdk(monkeypatch, handler)
    done: list[dict] = []

    async def on_block_end(b: dict) -> None:
        done.append(b)

    async def go():
        install()
        return await llm.claude_stream(
            "s",
            [{"role": "user", "content": "찾아 줘"}],
            tools=research.TOOLS,
            purpose="research",
            on_block_end=on_block_end,
        )

    reply = run_loop(monkeypatch, go)
    assert [b["type"] for b in done] == ["text", "server_tool_use"]
    assert done[0]["text"] == "제조사 페이지부터 볼게요."
    assert done[1]["name"] == "web_search" and done[1]["input"] == {"query": "LX 실크벽지"}
    assert reply.stop == "pause_turn"
