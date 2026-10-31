"""업체 홈페이지 확인기. robots.txt를 지키며 홈페이지 한 장만 읽고 포트폴리오 · 시공사례 · 견적 · 문의 링크만 찾는다.

- 이메일 · 전화번호는 모으지 않는다. mailto · tel 링크와 '@'가 든 주소는 버리고, 페이지 내용은 두지 않는다.
- 긁기 금지 도메인은 robots.txt도 읽지 않는다. 그 주소를 링크로 보여 주는 것은 괜찮다 (읽지 않으므로).
- 내부 주소(사설 · 루프백 IP)와 80 · 443 밖의 포트는 읽지 않는다. 서버 안쪽(클라우드 메타데이터 등)을 찌르지 않게.
- 요청마다 간격을 두고, robots.txt의 Crawl-delay가 더 길면 그것을 따른다. robots.txt를 못 읽으면 읽지 않는다.
"""

import asyncio
import codecs
import ipaddress
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx2

from app.directory.client import BOT

# 약관 · robots가 자동 수집을 막는 곳. 하위 도메인도 모두 막는다
BLOCKED_DOMAINS = (
    "naver.com",  # 네이버 지도 · 플레이스 · 블로그
    "naver.me",
    "blog.me",
    "kakao.com",  # 카카오맵 (카카오는 공식 API로 장소 ID만)
    "kko.to",
    "daum.net",
    "soomgo.com",  # 숨고 · 집닥: 영리 목적 재사용 금지
    "zipdoc.co.kr",
    "ohou.se",  # 오늘의집
    "bucketplace.co.kr",
    "daangn.com",  # 당근: 자동 수집 금지
    "kiscon.net",  # robots.txt가 전체를 막는다 (공시는 공공데이터포털 API로)
    "instagram.com",  # 메타 · 유튜브 약관도 자동 수집을 막는다
    "facebook.com",
    "youtube.com",
)
PAGE_LIMIT = 1_000_000  # 홈페이지 한 장 최대 크기 (바이트)
ROBOTS_LIMIT = 500_000
MAX_HOPS = 3  # 넘겨주기(redirect) 최대 횟수
MAX_PORTFOLIO = 5
MAX_CRAWL_DELAY = 30.0  # robots.txt가 이보다 오래 기다리라고 하면 그 사이트는 건너뛴다
_REDIRECT = {301, 302, 303, 307, 308}
_PORTFOLIO_WORDS = (
    "포트폴리오",
    "시공사례",
    "시공 사례",
    "시공갤러리",
    "작업사례",
    "시공후기",
    "portfolio",
    "gallery",
)
_QUOTE_WORDS = ("견적", "estimate", "quote")  # 이것이 있으면 먼저 고른다
_INQUIRY_WORDS = ("상담신청", "상담 신청", "상담문의", "문의", "inquiry", "contact")

Status = Literal["ok", "robots", "blocked", "unsafe", "not_html", "error"]
Resolve = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True)
class SiteLinks:
    status: Status
    portfolio_urls: list[str] = field(default_factory=list)
    quote_url: str | None = None


def is_blocked(host: str | None) -> bool:
    h = (host or "").lower().rstrip(".")
    return not h or any(h == d or h.endswith("." + d) for d in BLOCKED_DOMAINS)


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def _decode(body: bytes, ctype: str) -> str:
    """Content-Type의 charset → UTF-8 → CP949 순서로 읽는다 (예전 국내 사이트는 EUC-KR이 많다)."""
    m = re.search(r"charset=([\w-]+)", ctype, re.IGNORECASE)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "cp949"]:
        try:  # 크기 한도에서 잘린 마지막 글자는 버린다
            return codecs.getincrementaldecoder(enc)().decode(body, final=False)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


class _Links(HTMLParser):
    """<a href>와 그 글자(안의 그림 alt 포함)만 모은다"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._href, self._text = a.get("href"), []
        elif tag == "img" and self._href is not None:
            self._text.append(a.get("alt") or "")

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None


def find_links(html: str, page_url: str) -> tuple[list[str], str | None]:
    """(포트폴리오 링크 5개까지, 견적 · 문의 링크 하나). 메일 · 전화 링크와 '@'가 든 주소는 버린다."""
    parser = _Links()
    parser.feed(html)
    parser.close()
    here = urlsplit(page_url)._replace(fragment="").geturl()
    portfolio: list[str] = []
    quote: tuple[int, str] | None = None
    for href, text in parser.links:
        url = urljoin(page_url, (href or "").strip())
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or "@" in url or not parts.hostname:
            continue
        url = urlunsplit(parts._replace(fragment=""))
        if url == here or len(url) > 300:
            continue
        hay = (text + " " + parts.path + " " + parts.query).lower()
        if any(w in hay for w in _PORTFOLIO_WORDS) and url not in portfolio:
            portfolio.append(url)
        rank = (
            2
            if any(w in hay for w in _QUOTE_WORDS)
            else 1
            if any(w in hay for w in _INQUIRY_WORDS)
            else 0
        )
        if rank and (quote is None or rank > quote[0]):
            quote = (rank, url)
    return portfolio[:MAX_PORTFOLIO], quote[1] if quote else None


class SiteChecker:
    """홈페이지를 한 곳씩 확인한다. 요청 사이 간격은 interval초(또는 robots의 Crawl-delay)."""

    def __init__(
        self,
        http: httpx2.AsyncClient,
        *,
        interval: float,
        resolve: Resolve = _resolve,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http, self.interval = http, interval
        self._resolve, self._sleep, self._clock = resolve, sleep, clock
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: float | None = None

    async def _pace(self, delay: float) -> None:
        if self._last is not None:
            wait = self._last + delay - self._clock()
            if wait > 0:
                await self._sleep(wait)
        self._last = self._clock()

    async def _safe(self, url: str) -> Status | None:
        """읽으면 안 되는 주소면 그 이유"""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.username or parts.password:
            return "unsafe"
        if is_blocked(parts.hostname):
            return "blocked"
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            return "unsafe"
        if port not in (80, 443):
            return "unsafe"
        try:
            addrs = await self._resolve(parts.hostname or "", port)
        except OSError:
            return "error"
        ok = addrs and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)
        return None if ok else "unsafe"

    async def _get(self, url: str, limit: int, delay: float) -> tuple[int, bytes, str, str]:
        """(상태, 본문 앞부분, Content-Type, Location). 본문은 limit 바이트까지만 읽는다."""
        await self._pace(delay)
        headers = {"Accept": "text/html, */*;q=0.1"}
        async with self.http.stream("GET", url, headers=headers, follow_redirects=False) as r:
            if r.status_code in _REDIRECT:
                return r.status_code, b"", "", r.headers.get("location", "")
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) >= limit:
                    break
            return r.status_code, bytes(body[:limit]), r.headers.get("content-type", ""), ""

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        """그 주소의 robots.txt. 못 읽거나 서버 오류면 None(= 읽지 않는다)."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        rp: RobotFileParser | None = None
        target = origin + "/robots.txt"
        try:
            for _ in range(MAX_HOPS + 1):
                if await self._safe(target) is not None:
                    break
                status, body, _, location = await self._get(target, ROBOTS_LIMIT, self.interval)
                if status in _REDIRECT and location:
                    target = urljoin(target, location)
                    continue
                if status == 200:
                    rp = RobotFileParser()
                    rp.parse(body.decode("utf-8", "replace").splitlines())
                elif status in (401, 403):
                    rp = RobotFileParser()
                    rp.disallow_all = True
                elif 400 <= status < 500:  # robots.txt가 없으면 막지 않은 것으로 본다 (RFC 9309)
                    rp = RobotFileParser()
                    rp.allow_all = True
                break
        except httpx2.HTTPError:
            rp = None
        self._robots[origin] = rp
        return rp

    async def check(self, homepage: str) -> SiteLinks:
        url = homepage
        for _ in range(MAX_HOPS + 1):
            bad = await self._safe(url)
            if bad is not None:
                return SiteLinks(bad)
            rp = await self._robots_for(url)
            if rp is None or not rp.can_fetch(BOT, url):
                return SiteLinks("robots")
            delay = max(self.interval, float(rp.crawl_delay(BOT) or 0))
            if delay > MAX_CRAWL_DELAY:
                return SiteLinks("robots")
            try:
                status, body, ctype, location = await self._get(url, PAGE_LIMIT, delay)
            except httpx2.HTTPError:
                return SiteLinks("error")
            if status in _REDIRECT and location:
                url = urljoin(url, location)
                continue
            if status != 200:
                return SiteLinks("error")
            if "html" not in ctype.lower():
                return SiteLinks("not_html")
            portfolio, quote = find_links(_decode(body, ctype), url)
            return SiteLinks("ok", portfolio, quote)
        return SiteLinks("error")  # 넘겨주기가 너무 많음
