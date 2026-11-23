"""조사 판매가 A안(2026-11-23 사용자 'A안으로 해보고'): 자재 항목의 판매가 · 규격 칸은 코드가 숫자로 읽고
(price_cell · size_cell · paper_of), 우리 서버가 그 페이지에서 같은 값을 찾았을 때만 남긴다(pagecheck: robots · 막은 곳 ·
글 · 구조 자료). 판매가로 이 집 도배 금액 다시 세기(estimate_product → cards.product_estimate → calc.product_paper ·
rolls.need_size), get_research 모델 값에 확인한 판매가. 유료 호출 0회, 웹은 MockTransport."""

import asyncio
import json
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.agent import llm
from app.assistant import linkimage, pagecheck, policy, research
from app.calc import rolls
from app.calc.common import Money
from app.calc.dobae import PaperSplit
from app.calc.product_paper import product_paper
from app.shared.clock import SEOUL, now_utc
from tests.conftest import query
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_v4_research import USAGE, result_of, rows, run, started_research


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from v3_kb import repo_index

    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


SHOP_A = "https://shop-a.example/p/1"  # 판매가 · 규격이 페이지에 있음
SHOP_C = "https://shop-c.example/p/3"  # 화면을 브라우저가 그려 페이지에 값이 없음
PAGE_A = (
    "<html><body><h1>휘앙세 93 49701-03 코지 린넨</h1><div>판매가 <strong>32,000</strong><span>원</span></div>"
    "<p>규격 930 x 17750 mm</p></body></html>"
)
PAGE_C = "<html><body><div id='app'></div><script src='/app.js'></script></body></html>"


def web(pages: dict[str, str], robots: dict[str, str]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots.get(req.url.host, "User-agent: *\nAllow: /\n"))
        body = pages.get(str(req.url))
        if body is None:
            return httpx.Response(404, text="")
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    return httpx.MockTransport(handler)


@pytest.fixture
def shops(monkeypatch):
    pages = {SHOP_A: PAGE_A, SHOP_C: PAGE_C, "https://shop-b.example/p/2": PAGE_A}
    robots = {"shop-b.example": "User-agent: *\nDisallow: /p/\n"}
    monkeypatch.setattr(
        pagecheck,
        "_client",
        lambda: httpx.AsyncClient(
            transport=web(pages, robots), headers={"User-Agent": linkimage.UA}
        ),
    )


def price(won: int, per_roll: bool = True, checked: str | None = None) -> dict:
    return {
        "text": f"1롤 {won:,}원" if per_roll else f"{won:,}원",
        "won": won,
        "per_roll": per_roll,
        "checked": checked,
    }


# ---- 칸 읽기 · 페이지 확인 ----


def test_price_size_and_paper_cells_are_read_by_code():
    p = research.price_cell("1롤 32,000원")
    assert p is not None and (p.won, p.per_roll, p.text, p.checked) == (
        32000,
        True,
        "1롤 32,000원",
        None,
    )
    assert research.price_cell("판매가 28000원(롤당)").per_roll  # type: ignore[union-attr]
    two = research.price_cell("2롤 묶음 60,000원")
    assert two is not None and two.won == 60000 and not two.per_roll and two.text == "60,000원"
    for bad in ("-", "문의", "3원", "롤당 3,500,000원"):
        assert research.price_cell(bad) is None  # 비운 칸 · 값 없음 · 벽지 값 범위 밖
    s = research.size_cell("930×17750mm")
    assert s is not None and (s.width_mm, s.length_mm, s.text) == (930, 17750, "93cm × 17.75m")
    assert research.size_cell("1.06m x 15.6m").width_mm == 1060  # type: ignore[union-attr]
    assert research.size_cell("106cm × 15.6m").length_mm == 15600  # type: ignore[union-attr]
    assert research.size_cell("930x35500").length_mm == 35500  # type: ignore[union-attr]
    assert research.size_cell("930 × 17,750mm").length_mm == 17750  # type: ignore[union-attr]
    assert research.size_cell("5평") is None and research.size_cell("10 x 20") is None
    assert research.paper_of("휘앙세 93", "합지벽지예요") == "합지"
    assert research.paper_of("실크와 합지 비교") is None and research.paper_of("벽지") is None


def test_pagecheck_finds_price_in_text_or_structured_data_and_size_pairs():
    assert pagecheck.price_on(PAGE_A, 32000) and not pagecheck.price_on(PAGE_A, 3200)
    assert pagecheck.price_on(
        '<script type="application/ld+json">{"offers":{"price":"28000"}}</script>', 28000
    )
    assert pagecheck.price_on('<meta property="product:price:amount" content="28000">', 28000)
    assert pagecheck.price_on("<b>₩28,000</b>", 28000) and not pagecheck.price_on(PAGE_C, 28000)
    assert pagecheck.size_on(PAGE_A, 930, 17750) and not pagecheck.size_on(PAGE_A, 1060, 15600)
    assert pagecheck.size_on("<td>93cm × 17.75m</td>", 930, 17750)
    assert pagecheck.size_on("<td>930 X 17,750 mm</td>", 930, 17750)


def test_check_result_keeps_only_values_found_on_page(shops):
    items = [
        {"href": SHOP_A, "price": price(32000), "size": {"text": "93cm × 17.75m", "width_mm": 930, "length_mm": 17750, "checked": False}},
        {"href": "https://shop-b.example/p/2", "price": price(32000)},  # robots가 막음(링크는 둠)
        {"href": SHOP_C, "price": price(45000)},  # 페이지에 값이 없음
        {"href": "https://blog.naver.com/x/1", "price": price(32000)},  # 가져오기를 막은 곳
        {"href": SHOP_A, "price": price(31000)},  # 페이지 값과 다름
    ]  # fmt: skip
    result = {"items": items, "links": []}
    asyncio.run(pagecheck.check_result(result, date(2026, 11, 23), ("blog.naver.com",)))
    assert len(result["items"]) == 5  # 없는 페이지가 아니면 항목은 그대로
    assert items[0]["price"]["checked"] == "2026-11-23" and items[0]["size"]["checked"] is True
    assert [x["price"] for x in items[1:]] == [None, None, None, None]


def test_failed_check_drops_unchecked_values_but_keeps_links(monkeypatch):
    def broken():
        raise RuntimeError("no network")

    monkeypatch.setattr(pagecheck, "_client", broken)
    items = [{"href": SHOP_A, "price": price(32000), "size": {"text": "x", "width_mm": 930, "length_mm": 17750, "checked": False}}]  # fmt: skip
    result = {"items": items, "links": [{"href": SHOP_A}]}
    asyncio.run(pagecheck.check_result(result, date(2026, 11, 23), ()))
    assert (
        items[0]["price"] is None and items[0]["size"] is None
    )  # 확인하지 못한 값은 남기지 않는다
    assert (
        result["links"] == [{"href": SHOP_A}] and len(result["items"]) == 1
    )  # 못 읽었다고 빼지는 않는다


def test_dead_pages_are_dropped_from_links_and_items(monkeypatch):
    """사용자 11-23 '링크줬는데 들어가보니 페이지없던데': 404 · 410 · '페이지를 찾을 수 없음' 제목은 빼고, 못 읽은 곳은 둔다."""
    ok, soft, gone, closed, naver = (
        "https://a.example/ok", "https://b.example/gone-soft", "https://c.example/gone",
        "https://d.example/private", "https://blog.naver.com/x",
    )  # fmt: skip
    pages = {
        ok: "<html><title>노원 도배 공방</title></html>",
        soft: "<html><title>페이지를 찾을 수 없습니다 | 홈코</title></html>",
    }
    robots = {"d.example": "User-agent: *\nDisallow: /\n"}
    monkeypatch.setattr(
        pagecheck,
        "_client",
        lambda: httpx.AsyncClient(
            transport=web(pages, robots), headers={"User-Agent": linkimage.UA}
        ),
    )
    result = {
        "items": [{"href": gone, "name": "없어진 곳"}, {"href": ok, "name": "노원 도배 공방"}],
        "links": [{"href": u} for u in (ok, soft, gone, closed, naver)],
    }
    asyncio.run(pagecheck.check_result(result, date(2026, 11, 23), ("blog.naver.com",)))
    assert [x["href"] for x in result["items"]] == [ok]
    assert [x["href"] for x in result["links"]] == [ok, closed, naver]
    assert pagecheck.dead_page(410, None) and not pagecheck.dead_page(403, None)
    assert not pagecheck.dead_page(200, "<title>강남 4040 도배</title>")


def test_want_count_and_title_without_ask_tail():
    assert research.want_count("강남구 도배 업체 믿집 밖에서 최대 5곳 조사") == 5
    assert research.want_count("업체 다섯 군데 찾아 줘") == 5
    assert research.want_count("업체 9곳") == research.LINK_MAX
    assert research.want_count("실크벽지 인기 라인") is None
    assert research.want_count("도배 업체", ["3곳만"]) == 3
    assert research.title_of("강남구 20평 빈 집 실크 도배 업체 믿집 밖에서 최대 3곳 조사") == (
        "강남구 20평 빈 집 실크 도배 업체"
    )


# ---- 계산 엔진 ----


def test_rolls_by_product_size_and_product_paper_sum():
    n = rolls.need_size("합지", Decimal("0.93"), Decimal("35.5"), paper_py=Decimal("30.0"))
    # 30평 × 3.3058 = 99.174㎡ ÷ (0.93 × 35.5 = 33.015㎡) = 3.004 → 4롤(올림)
    assert n.count == 4 and n.key == "product" and n.text.startswith("합지(93cm × 35.5m) 약 4롤")
    with pytest.raises(ValueError):
        rolls.need_size("합지", Decimal("0.1"), Decimal(10), paper_py=Decimal(1))
    split = PaperSplit(
        Money(2_000_000, 200_000, 2_200_000), Money(1_500_000, 150_000, 1_650_000), 550_000
    )
    est = product_paper(split, n, 32_000)
    assert (est.paper_won, est.rest_won, est.total_won, est.standard_won) == (
        128_000,
        1_650_000,
        1_778_000,
        2_200_000,
    )
    with pytest.raises(ValueError):
        product_paper(split, n, 0)


# ---- 조사 worker: 판매가 · 규격 칸 ----


def test_worker_reads_price_columns_and_keeps_checked_only(api, script, shops):
    _, pid = home(api)
    rid = started_research(api, script, pid, "materials")
    text = (
        "요약: 고객님이 말한 합지 조건으로 휘앙세 93 제품을 찾았어요. 한 롤에 3만 2천 원이에요.\n"
        "항목:\n"
        f"- 휘앙세 93 코지 린넨 49701-03 | 라떼 베이지 린넨 느낌 합지예요 | - | 1롤 32,000원 | 930×17750mm | {SHOP_A}\n"
        f"- 휘앙세 93 격자 직조 49619-01 | 우유 크림 격자 무늬예요 | - | 1롤 29,000원 | - | {SHOP_C}"
    )
    blocks = [
        {"type": "server_tool_use", "id": "srvtoolu_s1", "name": "web_search", "input": {"query": "휘앙세 93 판매가"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_s1", "content": [
            {"type": "web_search_result", "url": SHOP_A, "title": "휘앙세 93 49701-03 코지 린넨 합지벽지", "encrypted_content": "e1"},
            {"type": "web_search_result", "url": SHOP_C, "title": "휘앙세 93 49619-01 격자 직조", "encrypted_content": "e2"}]},
        {"type": "text", "text": text},
    ]  # fmt: skip
    script([{"blocks": blocks, "stop": "end_turn", "usage": USAGE}])
    assert run(api, research.run, rid) == "done"
    res = result_of(rows()[0])
    a, c = res["items"]
    today = now_utc().astimezone(SEOUL).date().isoformat()
    assert a["paper"] == "합지" and a["price"] == {
        "text": "1롤 32,000원",
        "won": 32000,
        "per_roll": True,
        "checked": today,
    }
    assert a["size"]["text"] == "93cm × 17.75m" and a["size"]["checked"] is True
    assert c["price"] is None and c["size"] is None  # 페이지에 값이 없으면 남기지 않는다
    assert (
        res["summary"] == "고객님이 말한 합지 조건으로 휘앙세 93 제품을 찾았어요."
    )  # 값은 판매가 칸에만


# ---- 판매가로 이 집 금액 다시 세기 ----


def priced_row(pid: str, items: list[dict]) -> None:
    owner = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    result = {
        "summary": "휘앙세 93 제품을 찾았어요.",
        "items": items,
        "links": [],
        "checks": [],
        "outside": False,
        "partial": False,
        "note": None,
    }
    query(
        "insert into assistant_research (id, user_id, project_id, kind, title, goal, status, result, ended_at)"
        " values ($1, $2, $3, 'materials', '휘앙세 93 판매가', '휘앙세 93 판매가', 'done', $4, now())",
        uuid.uuid4(), owner, uuid.UUID(pid), json.dumps(result, ensure_ascii=False),
    )  # fmt: skip


def item(
    won: int = 32000, per_roll: bool = True, size: bool = True, paper: str | None = "합지"
) -> dict:
    out = {
        "name": "휘앙세 93 코지 린넨 49701-03", "feature": None, "caution": None, "href": SHOP_A,
        "source": "shop-a.example", "image": None, "paper": paper,
        "price": price(won, per_roll, "2026-11-23"),
        "size": {"text": "93cm × 35.5m", "width_mm": 930, "length_mm": 35500, "checked": True} if size else None,
    }  # fmt: skip
    return out


def tool_turn(api, script, pid: str, name: str, args: dict) -> tuple[dict, list]:
    log = script(
        [{"tool_calls": [{"id": "t1", "name": name, "input": args}]}, {"text": "계산해 봤어요."}]
    )
    ev = ok(ask(api, pid, "첫 번째 걸로 하면 얼마야?"))
    return json.loads(log[1]["messages"][-1]["content"][0]["content"]), ev


def test_estimate_product_counts_rolls_by_size_and_adds_rest(api, script):
    _, pid = home(api)
    priced_row(pid, [item()])
    got, ev = tool_turn(api, script, pid, "estimate_product", {"name": "코지 린넨"})
    assert got["state"] == "ok" and got["paper"] == "합지" and got["price"] == "1롤 32,000원"
    assert got["rolls"]["text"].startswith("합지(93cm × 35.5m) 약 ")
    assert got["paper_won"] == got["rolls"]["count"] * 32000
    assert (
        got["total_won"] == got["rest_won"] + got["paper_won"]
        and got["rest_won"] < got["standard_won"]
    )
    cards = [d for e, d, _ in ev if e == "card"]
    assert [c["kind"] for c in cards] == ["product_estimate"]
    data = cards[0]["data"]
    assert data["total_won"] == got["total_won"] and data["href"] == SHOP_A
    assert [r["won"] for r in data["rows"]] == [got["paper_won"], got["rest_won"]]
    # 표준 롤로 세면(규격 모름) 롤 수가 늘고 가정 줄이 붙는다
    priced_row(pid, [item(size=False)])
    plain, _ = tool_turn(api, script, pid, "estimate_product", {})
    assert plain["rolls"]["count"] > got["rolls"]["count"]
    assert any("표준 롤" in a for a in plain["assumed"])


def test_estimate_product_without_price_or_per_roll(api, script):
    _, pid = home(api)
    got, ev = tool_turn(api, script, pid, "estimate_product", {})
    assert got["state"] == "no_price" and not [e for e, *_ in ev if e == "card"]
    priced_row(pid, [item(won=60000, per_roll=False)])
    got, _ = tool_turn(api, script, pid, "estimate_product", {})
    assert got["state"] == "not_per_roll" and got["price"] == "60,000원"


def test_get_research_shows_checked_price_to_model(api, script):
    _, pid = home(api)
    priced_row(pid, [item()])
    got, _ = tool_turn(api, script, pid, "get_research", {})
    box = got[policy.DATA_KEY]["items"][0]
    assert (
        box["price"] == "1롤 32,000원" and box["size"] == "93cm × 35.5m" and box["per_roll"] is True
    )
    assert (
        box["price_seen"] == "판매처 표시 값 · 2026-11-23 확인"
        and "estimate_product" in got["message"]
    )


def test_model_item_hides_unchecked_values():
    out = research._item_model(
        {"name": "a", "source": "s", "price": price(32000), "size": {"text": "x", "checked": False}}
    )
    assert "price" not in out and "size" not in out


# ---- 믿집 밖 업체: 부탁한 수 · 업체 이름 · 없는 페이지 ----


def test_outside_vendors_fill_to_count_show_names_and_drop_dead(api, script, monkeypatch):
    """사용자 11-23 '5곳 찾아오라 했더니 하나만': 고른 곳이 모자라면 다른 검색 결과로 채우고(다른 지역은 뺌), 업체 이름
    항목도 보이고, 없는 페이지(404)는 뺀다. 카드 위 안내 한 줄만 두고 '직접 확인하는 곳'은 없다."""
    _, pid = home(api)
    rid = started_research(api, script, pid)  # 믿집 밖 업체, 노원구
    gone = "https://homeco.example/cases/1"
    v0, v1, v2, v3 = (
        "https://nowon-dobae.example/", "https://sanggye-wall.example/",
        "https://bundang-dobae.example/", "https://nowon-silk.example/",
    )  # fmt: skip
    pages = {u: "<html><title>도배 업체</title></html>" for u in (v0, v1, v2, v3)}
    monkeypatch.setattr(
        pagecheck,
        "_client",
        lambda: httpx.AsyncClient(transport=web(pages, {}), headers={"User-Agent": linkimage.UA}),
    )
    text = (
        "요약: 노원구에서 도배를 하는 곳을 찾았어요.\n항목:\n"
        f"- 홈코 | 노원구 실크 도배 사례 | - | - | - | {gone}\n"
        f"- 노원 도배 | 노원구 · 실크 도배 시공 | - | - | - | {v0}"
    )
    found = [
        (gone, "노원구 실크 도배 시공 후기 | 홈코"),
        (v0, "노원 도배 | 노원구 벽지 시공"),
        (v1, "상계 벽지 | 노원구 상계동 도배"),
        (v2, "분당 도배 | 성남시 분당구"),
        (v3, "노원 실크 도배"),
    ]
    blocks = [
        {"type": "server_tool_use", "id": "srvtoolu_s1", "name": "web_search", "input": {"query": "노원구 도배 업체"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_s1", "content": [
            {"type": "web_search_result", "url": u, "title": title, "encrypted_content": f"e{i}"}
            for i, (u, title) in enumerate(found)]},
        {"type": "text", "text": text},
    ]  # fmt: skip
    script([{"blocks": blocks, "stop": "end_turn", "usage": USAGE}])
    assert run(api, research.run, rid) == "done"
    res = result_of(rows()[0])
    assert [x["name"] for x in res["items"]] == ["노원 도배"]  # 없는 페이지(홈코)는 빠짐
    assert res["items"][0]["feature"] == "노원구 · 실크 도배 시공"
    hrefs = [x["href"] for x in res["links"]]
    assert gone not in hrefs and v2 not in hrefs  # 404 · 다른 지역(분당)
    assert set(hrefs) == {v0, v1, v3}  # 고른 곳이 모자라 다른 검색 결과로 채움
    assert res["checks"] == [] and res["note"] == research.OUTSIDE_NOTE
