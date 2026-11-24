"""조사 결과 항목의 제조사 대표 그림(피클 표본처럼 제품 그림을 같이 보인다, docs/v4/09-research.md).

- 결과 항목 중 제조사 공식 사이트(SITES) 페이지만 우리 서버가 직접 읽는다. robots.txt를 먼저 보고 막혔거나 알 수
  없으면 읽지 않는다. 사이트마다 그림 찾는 법이 달라 표로 둔다(LX Z:IN은 og:image가 제품 그림, 신한벽지는 og:image가
  회사 로고라 본문의 첫 제품 그림). 개나리(https 그림 없음) · 디아이디(화면을 브라우저가 그림)는 넣지 않았다.
- 그림은 저장 · 복사하지 않고 주소만 남긴다. 화면이 그 사이트에서 바로 불러오고(CSP img-src에 같은 곳만 열어 둠,
  frontend/proxy.ts), https이면서 그 사이트(하위 도메인 포함) 주소만 쓴다.
- 일반 이름(link-preview)으로 부르고, 페이지 앞부분(200KB)만 읽고, 모두 합쳐 10초 안에 끝낸다.
- 넘어가기(30x)는 저절로 따라가지 않고 한 번씩(MAX_HOPS번까지) 따라가요. 넘어갈 때마다 새 주소가 https · 바깥 주소
  (public_url)이고 같은 사이트인지와 그 사이트 robots를 다시 봐요(점검 R1b #11: 처음 주소만 보고 끝까지 따라가 내부
  주소 · http로도 요청이 갔고, robots가 막은 같은 사이트 경로도 읽었어요). pagecheck도 같은 도우미(read_page)를 써요.
- 실패(시간 초과 · 막힘 · 그림 없음)는 그림 없이 둔다(지어내지 않음). 로그에는 오류 종류만 남긴다.
"""

import asyncio
import ipaddress
import logging
import re
from collections.abc import Callable
from html import unescape
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

UA = "link-preview/1.0"
MAX_HOPS = 5  # 넘어가기(30x)를 따라가는 횟수(robots.txt도 같아요)
# 안쪽 이름(사설망 · 개발 이름): 이런 곳으로는 요청을 보내지 않아요
_LOCAL_NAME = re.compile(
    r"(?:^|\.)(?:localhost|local|localdomain|internal|intranet|lan|home|corp|home\.arpa)$"
)
# 끝 이름은 글자로 시작해요(한글 도메인 '.한국'도). 숫자뿐이면('127.1' · '0x7f.1') 주소 꼴로 봐요
_TLD = re.compile(r"[^\W\d_][\w-]*")
# 사이트 → 그림 찾는 법: "og"는 og:image, 그 밖의 글은 그 경로가 든 본문 첫 <img>
SITES: dict[str, str] = {
    "lxzin.com": "og",  # og:image = 제품 썸네일(octapi.lxzin.com)
    "shinhanwall.co.kr": "/upload/product/",  # og:image는 회사 로고
}
PAGE_BYTES = 200_000
TIMEOUT = 5.0
TOTAL = 10.0
MAX_PAGES = 6

# 사이트 공용 그림(로고 · 공유용 대표 그림)은 제품 사진이 아니라 버려요(예: www.lxzin.com/images/opengraph_2026.png)
GENERIC = re.compile(r"opengraph|og[_-]?image|logo|favicon|/ci[_./-]", re.IGNORECASE)
_META = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([a-zA-Z_:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")


def public_url(url: str) -> bool:
    """우리 서버가 읽어도 되는 바깥 https 주소인지: https · 기본 포트 · 공인 IP(사설 · 루프백 · 링크 로컬 · 예약 IP가
    아님) · 안쪽 이름(localhost · .local · .internal · 점 없는 이름)이 아님. 이름이 가리키는 IP는 보지 않아요(DNS를
    부르지 않아요)."""
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower().rstrip(".")
        port = u.port
    except ValueError:
        return False
    if u.scheme != "https" or not host or port not in (None, 443):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return (
            "." in host
            and not _LOCAL_NAME.search(host)
            and bool(_TLD.fullmatch(host.rsplit(".", 1)[-1]))
        )
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


async def can_read(
    client: httpx.AsyncClient, url: str, robots: dict[str, RobotFileParser | None]
) -> bool:
    """그 사이트 robots.txt가 이 주소를 읽게 하는지(사이트마다 한 번 읽어 robots에 둬요). 모르면 읽지 않아요."""
    u = urlsplit(url)
    base = f"{u.scheme}://{u.netloc}"
    if base not in robots:
        robots[base] = await _robots(client, base)
    rp = robots[base]
    return rp is not None and rp.can_fetch(UA, url)


async def read_page(
    client: httpx.AsyncClient,
    url: str,
    robots: dict[str, RobotFileParser | None],
    same: Callable[[str], bool],
    *,
    limit: int,
    timeout: float,
) -> tuple[int | None, str | None]:
    """robots를 지키며 페이지 앞부분(limit 바이트)을 읽어요: (상태 코드, html). 넘어가기(30x)는 한 번씩 따라가며 주소마다
    바깥 https 주소(public_url) · 같은 사이트(same) · robots를 다시 봐요. 못 읽은 곳(주소 · 사이트 · robots 막힘 ·
    robots 모름 · 넘어가기가 너무 많음 · 연결 실패)은 (None, None), 200이 아니거나 html이 아니면 (상태, None)."""
    for _ in range(MAX_HOPS + 1):
        if not public_url(url) or not same(url) or not await can_read(client, url, robots):
            return None, None
        try:
            async with client.stream("GET", url, timeout=timeout, follow_redirects=False) as r:
                if r.is_redirect:
                    url = urljoin(str(r.url), r.headers.get("location", ""))
                    continue
                if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                    return r.status_code, None
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) >= limit:
                        break
                return 200, bytes(buf[:limit]).decode(r.encoding or "utf-8", errors="ignore")
        except httpx.HTTPError:
            return None, None
    return None, None  # 넘어가기가 너무 많아요


def site_of(url: str) -> str | None:
    """주소가 그림을 찾는 제조사 사이트(하위 도메인 포함)면 그 사이트 이름, 아니면 None."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    return next((d for d in SITES if host == d or host.endswith("." + d)), None)


def _attrs(tag: str) -> dict[str, str]:
    return {
        m.group(1).lower(): unescape(m.group(2) or m.group(3) or m.group(4) or "")
        for m in _ATTR.finditer(tag)
    }


def _usable(src: str, page_url: str, site: str) -> str | None:
    """그림 주소를 절대 주소로 풀고 https · 같은 사이트일 때만 돌려준다."""
    if not src or src.startswith("data:"):
        return None
    full = urljoin(page_url, src.strip())
    u = urlsplit(full)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not (host == site or host.endswith("." + site)):
        return None
    if GENERIC.search(u.path):
        return None
    return full


def find_image(html: str, page_url: str) -> str | None:
    """페이지 글에서 그 사이트 방법으로 대표 그림 주소를 찾는다(없으면 None)."""
    site = site_of(page_url)
    if site is None:
        return None
    rule = SITES[site]
    if rule == "og":
        for tag in _META.findall(html):
            a = _attrs(tag)
            if (a.get("property") or a.get("name") or "").lower() == "og:image":
                got = _usable(a.get("content", ""), page_url, site)
                if got:
                    return got
        return None
    for tag in _IMG.findall(html):
        src = _attrs(tag).get("src", "")
        if rule in src:
            got = _usable(src, page_url, site)
            if got:
                return got
    return None


async def _robots(client: httpx.AsyncClient, base: str) -> RobotFileParser | None:
    """사이트 robots.txt. 401 · 403은 모두 막음, 다른 4xx(없음)는 모두 허용, 5xx · 연결 실패는 모름(None).
    넘어가기는 MAX_HOPS번까지 한 번씩 따라가고, 바깥 https 주소(public_url)가 아니면 따라가지 않고 모름이에요."""
    rp = RobotFileParser()
    url = f"{base}/robots.txt"
    for _ in range(MAX_HOPS + 1):
        if not public_url(url):
            return None
        try:
            r = await client.get(url, timeout=TIMEOUT, follow_redirects=False)
        except httpx.HTTPError:
            return None
        if not r.is_redirect:
            break
        url = urljoin(str(r.url), r.headers.get("location", ""))
    else:
        return None  # 넘어가기가 너무 많아요
    if r.status_code in (401, 403):
        rp.disallow_all = True
    elif r.status_code >= 500:
        return None
    elif r.status_code >= 400:
        rp.allow_all = True
    else:
        rp.parse(r.text.splitlines())
    return rp


async def image_for(
    client: httpx.AsyncClient, url: str, robots: dict[str, RobotFileParser | None]
) -> str | None:
    """제조사 페이지 하나의 대표 그림 주소(robots를 지킴, 넘어가도 같은 사이트 안에서만). 아니면 None."""
    site = site_of(url)
    if site is None:
        return None
    _, html = await read_page(
        client, url, robots, lambda x: site_of(x) == site, limit=PAGE_BYTES, timeout=TIMEOUT
    )
    return find_image(html, str(url)) if html else None


def _client() -> httpx.AsyncClient:
    """시험이 바꿔 끼우는 자리(MockTransport)."""
    return httpx.AsyncClient(headers={"User-Agent": UA})


async def add_images(items: list[dict]) -> None:
    """결과 항목(dict)의 제조사 페이지에 대표 그림 주소(image)를 채운다. 실패는 그림 없이 둔다."""
    todo = [x for x in items if not x.get("image") and site_of(str(x.get("href") or ""))]
    if not todo:
        return
    todo = todo[:MAX_PAGES]
    robots: dict[str, RobotFileParser | None] = {}

    async def go(client: httpx.AsyncClient) -> None:
        # robots는 사이트마다 한 번만 먼저 읽고, 페이지는 함께 읽는다
        for x in todo:
            u = urlsplit(str(x["href"]))
            base = f"{u.scheme}://{u.netloc}"
            if public_url(str(x["href"])) and base not in robots:
                robots[base] = await _robots(client, base)

        async def one(x: dict) -> None:
            x["image"] = await image_for(client, str(x["href"]), robots)

        await asyncio.gather(*(one(x) for x in todo))

    try:
        async with _client() as client:
            await asyncio.wait_for(go(client), TOTAL)
    except Exception as e:  # noqa: BLE001 - 그림은 없어도 되는 것(시간 초과 포함)
        log.warning("조사 그림 찾기 실패 (%s)", type(e).__name__)
