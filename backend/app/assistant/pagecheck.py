"""조사 결과 링크 · 항목 확인(2026-11-23): 없는 페이지 빼기 + 자재 판매가 · 롤 규격 확인(A안).

- 없는 페이지(사용자 11-23 '링크줬는데 들어가보니 페이지없던데'): 검색 색인에 남은 지운 페이지가 결과에 섞여요(OpenAI 길은
  가져온 글이 없어 아무도 열어 보지 않았어요). 저장하기 전에 링크 · 항목 페이지를 한 번씩 읽어 404 · 410이거나 제목이
  '페이지를 찾을 수 없음' 꼴이면 빼요. 못 읽은 곳(robots · 막은 곳 · 시간 초과 · 다른 사이트로 넘어감)은 그대로 둬요.
- 판매가 · 규격: 조사 담당(LLM)이 적은 값은 그대로 믿지 않아요. 그 항목 페이지에 같은 값이 있을 때만 남기고(판매가
  checked = 오늘), 없거나 못 읽으면 지워요(지어낸 값 없음). 판매가는 태그를 걷은 글의 '32,000원' · '₩32,000'이나 상품
  구조 자료(JSON-LD price · meta product:price:amount · itemprop price), 규격은 '폭 × 길이' 꼴로 같은 값일 때만.
- linkimage와 같은 규칙: robots.txt를 먼저 보고 막혔거나 알 수 없으면 읽지 않아요. 일반 이름(link-preview)으로 부르고,
  https 페이지 앞부분(400KB)만, 모두 합쳐 12초 안에 끝내요. 막은 곳(weblinks.BLOCKED) · 가져오기만 막은 곳
  (research.NO_FETCH)은 읽지 않아요. 넘어가기(30x)는 한 번씩 따라가며 넘어갈 때마다 바깥 https 주소 · 같은 사이트 ·
  robots를 다시 봐요(linkimage.read_page, 점검 R1b #11).
- 페이지 글은 저장하지 않아요. 확인한 값 한 줄(판매가 · 규격)만 조사 결과에 남아요. 로그에는 오류 종류만 남겨요.
"""

import asyncio
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.assistant import linkimage, weblinks

log = logging.getLogger(__name__)

PAGE_BYTES = 400_000
TIMEOUT = 6.0
TOTAL = 12.0
MAX_PAGES = 12  # 한 조사에서 읽는 페이지(링크 6 + 항목 6)
DEAD_STATUS = frozenset({404, 410})
_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# 없는 페이지 제목(소프트 404): 200으로 와도 제목이 이 꼴이면 없는 페이지로 봐요
_DEAD_TITLE = re.compile(
    r"페이지를?\s*찾을\s*수\s*없|존재하지\s*않는\s*(?:페이지|게시물|게시글|글|상품|주소)|"
    r"삭제(?:된|되었)\S*\s*(?:페이지|게시물|게시글|글|상품)|page\s*not\s*found|^\s*404\b|\b404\s*(?:error|not)",
    re.IGNORECASE,
)
_SPACE = re.compile(r"\s+")
# '폭 × 길이' 꼴(조사 담당이 적은 규격 칸 · 페이지 글 둘 다)
SIZE = re.compile(
    r"(\d{1,4}(?:\.\d+)?)\s*(mm|cm|m)?\s*[x×X*]\s*(\d{1,5}(?:\.\d+)?)\s*(mm|cm|m)?(?![a-zA-Z])"
)


def _text(html: str) -> str:
    """태그를 걷은 글(스크립트 안 글도 남아요). 공백은 하나로."""
    return _SPACE.sub(" ", _TAG.sub(" ", unescape(html)))


def price_on(html: str, won: int) -> bool:
    """페이지에 이 값(원)이 판매가 꼴로 있는지."""
    raw = unescape(html)
    text = _text(html)
    comma, plain = f"{won:,}", str(won)
    in_text = (
        rf"(?<![\d,.])(?:{re.escape(comma)}|{plain})\s*원",
        rf"[₩￦]\s*(?:{re.escape(comma)}|{plain})(?![\d,])",
    )
    in_data = (
        rf'"(?:price|lowPrice|salePrice|sale_price|price_amount)"\s*:\s*"?{plain}(?:\.0+)?"?(?![\d])',
        rf"(?:product:price:amount|itemprop=[\"']price[\"'])[^>]{{0,200}}content=[\"']{plain}(?:\.0+)?[\"']",
        rf"content=[\"']{plain}(?:\.0+)?[\"'][^>]{{0,200}}(?:product:price:amount|itemprop=[\"']price[\"'])",
    )
    return any(re.search(p, text) for p in in_text) or any(re.search(p, raw) for p in in_data)


def to_mm(value: str, unit: str | None, *, length: bool) -> int | None:
    """규격 숫자 하나 → mm. 단위가 없으면 크기로 짐작해요(폭 930 = mm · 93 = cm · 0.93 = m, 길이 17750 = mm · 17.75 = m)."""
    try:
        v = Decimal(value)
    except InvalidOperation:
        return None
    if unit is None:
        unit = (
            ("mm" if v >= 1000 else "m")
            if length
            else ("mm" if v >= 300 else ("cm" if v >= 10 else "m"))
        )
    return int((v * {"mm": 1, "cm": 10, "m": 1000}[unit]).to_integral_value())


_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def no_commas(text: str) -> str:
    """천 단위 쉼표를 뗀다(규격 '17,750mm' → '17750mm')."""
    return _THOUSANDS.sub("", text)


def size_on(html: str, width_mm: int, length_mm: int) -> bool:
    """페이지에 '폭 × 길이' 꼴로 같은 규격이 있는지(단위가 달라도 mm로 맞춰 견줘요)."""
    for m in SIZE.finditer(no_commas(_text(html))):
        w = to_mm(m.group(1), m.group(2), length=False)
        ln = to_mm(m.group(3), m.group(4), length=True)
        if w == width_mm and ln == length_mm:
            return True
    return False


def _site(host: str) -> str:
    return host.lower().removeprefix("www.")


def dead_page(status: int | None, html: str | None) -> bool:
    """없는 페이지인지: 404 · 410이거나, 200인데 제목이 '페이지를 찾을 수 없음' 꼴."""
    if status in DEAD_STATUS:
        return True
    if status == 200 and html:
        m = _TITLE.search(html)
        return bool(m and _DEAD_TITLE.search(" ".join(unescape(m.group(1)).split())))
    return False


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    robots: dict[str, RobotFileParser | None],
    skip: tuple[str, ...],
) -> tuple[int | None, str | None]:
    """(상태 코드, html 앞부분). 읽지 않은 곳(바깥 https 주소 아님 · 막은 곳 · robots 막힘 · 모름)이나 연결 실패,
    다른 사이트로 넘어가는 곳(주차 도메인 등: 따라가지 않고 판단하지 않아요)은 (None, None), html이 아니면 (상태, None).
    넘어가기는 한 번씩 따라가며 주소 · 사이트 · robots를 다시 봐요(linkimage.read_page, 점검 R1b #11)."""
    host = (urlsplit(url).hostname or "").lower()
    if not host or weblinks.blocked(host, skip):
        return None, None

    def same(x: str) -> bool:
        h = (urlsplit(x).hostname or "").lower()
        return _site(h) == _site(host) and not weblinks.blocked(h, skip)

    return await linkimage.read_page(client, url, robots, same, limit=PAGE_BYTES, timeout=TIMEOUT)


def _client() -> httpx.AsyncClient:
    """시험이 바꿔 끼우는 자리(MockTransport)."""
    return httpx.AsyncClient(headers={"User-Agent": linkimage.UA})


async def _fetch_all(
    client: httpx.AsyncClient,
    urls: list[str],
    skip: tuple[str, ...],
    pages: dict[str, tuple[int | None, str | None]],
) -> None:
    robots: dict[str, RobotFileParser | None] = {}
    for url in urls:  # robots는 사이트마다 한 번만 먼저 읽고, 페이지는 함께 읽는다
        u = urlsplit(url)
        base = f"{u.scheme}://{u.netloc}"
        if (
            linkimage.public_url(url)
            and base not in robots
            and not weblinks.blocked(u.hostname or "", skip)
        ):
            robots[base] = await linkimage._robots(client, base)

    async def one(url: str) -> None:
        pages[url] = await fetch(client, url, robots, skip)

    await asyncio.gather(*(one(u) for u in urls))


async def check_result(result: dict, today: date, skip: tuple[str, ...]) -> None:
    """조사 결과(dict)의 링크 · 항목 페이지를 한 번씩 읽어 없는 페이지는 빼고, 자재 판매가 · 규격은 같은 값이 페이지에
    있을 때만 남겨요. 못 읽은 곳의 링크는 그대로 두고 판매가 · 규격만 지워요(실패해도)."""
    items = list(result.get("items") or [])
    links = list(result.get("links") or [])
    urls = list(dict.fromkeys(str(x.get("href") or "") for x in [*items, *links] if x.get("href")))
    pages: dict[str, tuple[int | None, str | None]] = {}
    try:
        if urls:
            async with _client() as client:
                await asyncio.wait_for(_fetch_all(client, urls[:MAX_PAGES], skip, pages), TOTAL)
    except Exception as e:  # noqa: BLE001 - 확인은 없어도 되는 것(시간 초과 포함)
        log.warning("조사 링크 확인 실패 (%s)", type(e).__name__)
    finally:
        dead = {u for u, (code, html) in pages.items() if dead_page(code, html)}
        result["items"] = [x for x in items if x.get("href") not in dead]
        result["links"] = [x for x in links if x.get("href") not in dead]
        for x in result["items"]:
            html = pages.get(str(x.get("href")), (None, None))[1]
            price, size = x.get("price"), x.get("size")
            if price:
                if html and price_on(html, int(price["won"])):
                    price["checked"] = today.isoformat()
                else:
                    x["price"] = None
            if size:
                if html and size_on(html, int(size["width_mm"]), int(size["length_mm"])):
                    size["checked"] = True
                else:
                    x["size"] = None
