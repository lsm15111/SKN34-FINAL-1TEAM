"""홈페이지 확인기 · 국세청 상태 확인 (가짜 웹 · 가짜 DNS · 가짜 응답, 실제 호출 없음)."""

import asyncio

import httpx2
import pytest

from app.config import settings
from app.directory import client, tasks
from app.directory.site import SiteChecker, find_links, is_blocked
from tests.conftest import query
from tests.test_directory_models import add

HOME = "https://fake-vendor.test/"
PAGE = """<html><body>
<p>문의 fake@example.com · 010-1234-5678</p>
<a href="/portfolio">포트폴리오</a>
<a href="https://blog.naver.com/fakevendor/1">시공사례 보기</a>
<a href="mailto:fake@example.com">메일 보내기</a>
<a href="tel:0212345678">전화 문의</a>
<a href="/contact">문의하기</a>
<a href="/estimate"><img src="/b.png" alt="견적 신청"></a>
<a href="https://fake@evil.example/x">시공사례</a>
<a href="#top">맨 위로</a>
</body></html>"""
PUBLIC = {"fake-vendor.test", "other-vendor.test", "slow-vendor.test"}


async def fake_dns(host: str, port: int) -> list[str]:
    if host in PUBLIC:
        return ["93.184.216.34"]
    if host == "intranet.test":
        return ["10.0.0.5"]
    if host == "mixed.test":  # 공인 · 사설이 섞인 답
        return ["93.184.216.34", "10.0.0.5"]
    if host == "mapped.test":  # IPv6 꼴로 감싼 루프백
        return ["::ffff:127.0.0.1"]
    if host == "169.254.169.254":
        return [host]
    raise OSError("no such host")


class Web:
    """주소 → (상태, 본문, 머리글). 받은 요청과 실제로 연결한 IP · TLS 이름을 모두 적어 둔다."""

    def __init__(self, pages: dict[str, tuple]):
        self.pages, self.seen, self.peers = pages, [], []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        # 확인기는 IP로 연결하고 이름은 Host 머리글로 보낸다. 원래 주소로 되돌려 찾는다
        url = f"{request.url.scheme}://{request.headers['host']}{request.url.raw_path.decode()}"
        self.seen.append((url, request.headers.get("user-agent", "")))
        self.peers.append(
            (
                request.url.host,
                request.extensions.get("sni_hostname"),
                request.headers.get("connection"),
            )
        )
        status, body, headers = self.pages.get(url, (404, "", {}))
        if isinstance(body, bytes):
            return httpx2.Response(status, content=body, headers=headers)
        return httpx2.Response(status, text=body, headers=headers)

    @property
    def urls(self) -> list[str]:
        return [u for u, _ in self.seen]


HTML = {"content-type": "text/html; charset=utf-8"}


def check(web: Web, url: str = HOME, **kw):
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    async def go():
        async with client.http_client(transport=httpx2.MockTransport(web)) as http:
            site = SiteChecker(
                http,
                interval=kw.pop("interval", 0.0),
                resolve=kw.pop("resolve", fake_dns),
                sleep=fake_sleep,
                clock=lambda: 0.0,
            )
            return await site.check(url)

    return asyncio.run(go()), sleeps


def test_reads_one_page_and_keeps_only_portfolio_and_quote_links():
    web = Web(
        {
            "https://fake-vendor.test/robots.txt": (200, "User-agent: *\nAllow: /\n", {}),
            HOME: (200, PAGE, HTML),
        }
    )
    got, _ = check(web)
    assert got.status == "ok"
    assert got.portfolio_urls == [
        "https://fake-vendor.test/portfolio",
        "https://blog.naver.com/fakevendor/1",  # 링크만 남기고 읽지는 않는다
    ]
    assert got.quote_url == "https://fake-vendor.test/estimate"  # 견적이 문의보다 먼저
    assert web.urls == ["https://fake-vendor.test/robots.txt", HOME]  # 한 장만
    assert all(ua.startswith("MitjipBot/") for _, ua in web.seen)
    kept = " ".join(got.portfolio_urls) + str(got.quote_url)
    assert "@" not in kept and "010" not in kept and "tel:" not in kept


def test_robots_disallow_means_no_page_read():
    web = Web(
        {
            "https://fake-vendor.test/robots.txt": (
                200,
                "User-agent: MitjipBot\nDisallow: /\n",
                {},
            ),
            HOME: (200, PAGE, HTML),
        }
    )
    got, _ = check(web)
    assert got.status == "robots" and web.urls == ["https://fake-vendor.test/robots.txt"]


@pytest.mark.parametrize(
    ("robots", "expected"),
    [((503, "", {}), "robots"), ((403, "", {}), "robots"), ((404, "", {}), "ok")],
)
def test_unreadable_robots_is_a_no(robots, expected):
    web = Web({"https://fake-vendor.test/robots.txt": robots, HOME: (200, PAGE, HTML)})
    assert check(web)[0].status == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://blog.naver.com/fakevendor",
        "https://m.place.naver.com/place/1",
        "https://place.map.kakao.com/1",
        "https://soomgo.com/profile/1",
        "https://zipdoc.co.kr/x",
        "https://ohou.se/experts/1",
    ],
)
def test_blocked_domains_are_never_requested(url):
    web = Web({})
    got, _ = check(web, url)
    assert got.status == "blocked" and web.urls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://intranet.test/",
        "http://169.254.169.254/latest/meta-data/",
        "https://mixed.test/",
        "https://mapped.test/",
        "http://[::1]/",
        "https://fake-vendor.test:8443/",
        "ftp://fake-vendor.test/",
    ],
)
def test_internal_addresses_and_odd_ports_are_never_requested(url):
    web = Web({})
    got, _ = check(web, url)
    assert got.status == "unsafe" and web.urls == []


def test_connects_only_to_the_checked_ip():
    web = Web({"https://fake-vendor.test/robots.txt": (404, "", {}), HOME: (200, PAGE, HTML)})
    assert check(web)[0].status == "ok"
    # 이름은 Host 머리글 · TLS SNI로만 가고, 연결은 확인한 IP로, 연결을 다시 쓰지 않는다
    assert web.peers == [("93.184.216.34", "fake-vendor.test", "close")] * 2


def test_dns_rebinding_cannot_reach_an_internal_address():
    answers = iter([["93.184.216.34"], ["93.184.216.34"]])

    async def rebinding_dns(host: str, port: int) -> list[str]:
        return next(answers, ["127.0.0.1"])  # 두 번 확인한 뒤로는 내부 주소를 준다

    web = Web(
        {
            "https://rebind.test/robots.txt": (404, "", {}),
            "https://rebind.test/": (301, "", {"location": "/next"}),
            "https://rebind.test/next": (200, PAGE, HTML),
        }
    )
    got, _ = check(web, "https://rebind.test/", resolve=rebinding_dns)
    assert got.status == "unsafe"  # 넘겨주기에서 다시 확인하니 내부 주소라 멈춘다
    assert web.urls == ["https://rebind.test/robots.txt", "https://rebind.test/"]
    assert {ip for ip, _, _ in web.peers} == {"93.184.216.34"}  # 확인한 IP에만 닿았다


def test_redirect_to_a_blocked_domain_stops_there():
    web = Web(
        {
            "https://fake-vendor.test/robots.txt": (404, "", {}),
            HOME: (301, "", {"location": "https://m.place.naver.com/place/1"}),
        }
    )
    got, _ = check(web)
    assert got.status == "blocked"
    assert not any("naver" in u for u in web.urls)


def test_requests_are_spaced_and_crawl_delay_is_kept():
    web = Web(
        {
            "https://slow-vendor.test/robots.txt": (200, "User-agent: *\nCrawl-delay: 5\n", {}),
            "https://slow-vendor.test/": (200, PAGE, HTML),
        }
    )
    got, sleeps = check(web, "https://slow-vendor.test/", interval=2.0)
    assert got.status == "ok" and sleeps == [5.0]  # robots 다음 요청은 Crawl-delay만큼 기다린다
    slow = Web(
        {"https://slow-vendor.test/robots.txt": (200, "User-agent: *\nCrawl-delay: 3600\n", {})}
    )
    assert check(slow, "https://slow-vendor.test/")[0].status == "robots"  # 너무 길면 건너뛴다
    assert slow.urls == ["https://slow-vendor.test/robots.txt"]


def test_euc_kr_page_is_read():
    html = '<a href="/works">시공사례</a>'.encode("euc-kr")
    web = Web(
        {
            "https://other-vendor.test/robots.txt": (404, "", {}),
            "https://other-vendor.test/": (
                200,
                html,
                {"content-type": "text/html; charset=euc-kr"},
            ),
        }
    )
    got, _ = check(web, "https://other-vendor.test/")
    assert got.portfolio_urls == ["https://other-vendor.test/works"]
    # charset이 없어도 UTF-8로 안 읽히면 CP949로 읽는다
    web.pages["https://other-vendor.test/"] = (200, html, {"content-type": "text/html"})
    assert check(web, "https://other-vendor.test/")[0].portfolio_urls == [
        "https://other-vendor.test/works"
    ]


def test_find_links_and_blocklist_basics():
    assert is_blocked("BLOG.NAVER.COM.") and is_blocked("naver.com") and is_blocked(None)
    assert not is_blocked("notnaver.com") and not is_blocked("fake-vendor.test")
    p, q = find_links('<a href="/qna">상담 신청</a><a href="javascript:x()">견적</a>', HOME)
    assert p == [] and q == "https://fake-vendor.test/qna"


def test_check_homepages_task_saves_links_only(monkeypatch):
    monkeypatch.setattr(settings, "crawl_interval_s", 0.0)
    add(source_id="site-1", homepage=HOME)
    add(source_id="site-2", homepage="https://blog.naver.com/fakevendor")
    add(source_id="site-3", homepage=HOME, opted_out=True)  # 수신거부 업체는 보지 않는다
    web = Web(
        {
            "https://fake-vendor.test/robots.txt": (404, "", {}),
            HOME: (200, PAGE, HTML),
        }
    )

    async def go():
        async with client.http_client(transport=httpx2.MockTransport(web)) as http:
            return await tasks.check_homepages({"http": http, "site": {"resolve": fake_dns}})

    assert asyncio.run(go()) == {"ok": 1, "blocked": 1}
    rows = {r["source_id"]: r for r in query("select * from ext_vendors")}
    assert rows["site-1"]["quote_url"] == "https://fake-vendor.test/estimate"
    assert rows["site-2"]["site_checked_at"] is not None and rows["site-2"]["portfolio_urls"] == []
    assert rows["site-3"]["site_checked_at"] is None
    stored = " ".join(str(v) for r in rows.values() for v in r.values())
    assert "fake@example.com" not in stored and "01012345678" not in stored
    assert web.urls.count(HOME) == 1


# ── 국세청 ──


def test_nts_status_only_updates_known_numbers(monkeypatch):
    monkeypatch.setattr(settings, "data_go_kr_key", "fake-key")
    add(source_id="b1", reg_kind="business", reg_no="1000000001")
    add(source_id="b2", reg_kind="business", reg_no="1000000002")
    add(source_id="b3", reg_kind="business", reg_no="1000000003")
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        data = [
            {"b_no": "1000000001", "b_stt": "계속사업자", "b_stt_cd": "01"},
            {"b_no": "1000000002", "b_stt": "폐업자", "b_stt_cd": "03"},
            {"b_no": "1000000003", "b_stt_cd": "", "tax_type": "등록되지 않은 번호"},
        ]
        return httpx2.Response(200, json={"status_code": "OK", "data": data})

    async def go():
        async with client.http_client(transport=httpx2.MockTransport(handler)) as http:
            return await tasks.verify_biz_status({"http": http})

    assert asyncio.run(go()) == {"asked": 3, "answered": 3, "changed": 3}
    got = {
        r["reg_no"]: r["biz_status"] for r in query("select reg_no, biz_status from ext_vendors")
    }
    assert got == {"1000000001": "active", "1000000002": "closed", "1000000003": "unknown"}
    assert seen[0].url.params["serviceKey"] == "fake-key"
    assert asyncio.run(go()) == {
        "asked": 0,
        "answered": 0,
        "changed": 0,
    }  # 30일 안에는 다시 안 묻는다


def test_nts_error_keeps_old_values(monkeypatch):
    monkeypatch.setattr(settings, "data_go_kr_key", "fake-key")
    add(source_id="b1", reg_kind="business", reg_no="1000000001")

    async def go():
        tr = httpx2.MockTransport(lambda r: httpx2.Response(200, json={"status_code": "ERR"}))
        async with client.http_client(transport=tr) as http:
            return await tasks.verify_biz_status({"http": http})

    assert asyncio.run(go()) == {"error": "status_ERR"}
    assert query("select biz_status from ext_vendors")[0]["biz_status"] is None
    monkeypatch.setattr(settings, "data_go_kr_key", "")
    assert asyncio.run(tasks.verify_biz_status({})) == {"skipped": "no_key"}
