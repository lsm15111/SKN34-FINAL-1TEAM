"""공공 API 호출 (공공데이터포털 KISCON · 국세청). 키가 없으면 부르지 않는다.

- 응답은 JSON · XML 둘 다 읽는다 (같은 포털이라도 API마다 기본 형식이 다르다).
- 오류 · 로그에 요청 주소를 넣지 않는다. 주소에 서비스 키가 들어 있다.
- KISCON 작업 이름 · 날짜 인자 이름은 활용 문서만 보고 정했다. 키를 받으면 응답으로 한 번 확인한다.
"""

import json
import re
import xml.etree.ElementTree as ET

import httpx2

from app.config import settings

# 믿집 수집기임을 밝힌다 (robots.txt의 User-agent 이름은 MitjipBot)
BOT = "MitjipBot"
API_TIMEOUT_S = 20.0
KISCON_URL = "https://apis.data.go.kr/1613000/ConAdminInfoSvc1"
KISCON_OP = "getConAdminInfoList"  # 확인 필요
KISCON_DATE_PARAMS = ("startDate", "endDate")  # 확인 필요 (공시 기간, YYYYMMDD)
NTS_URL = "https://api.odcloud.kr/api/nts-businessman/v1/status"
NTS_BATCH = 100  # 국세청 API 한 번에 100건
PAGE_ROWS = 100
_OK_CODES = {None, "", "00", "0", "000", "0000", "INFO-000", "NORMAL_SERVICE", "OK"}
_NTS_STATUS = {"01": "active", "02": "suspended", "03": "closed"}


def user_agent() -> str:
    contact = f"; +{settings.bot_contact_url}" if settings.bot_contact_url else ""
    return f"{BOT}/0.1 (Mitjip interior quote app; public data and link check{contact})"


def http_client(
    timeout: float = API_TIMEOUT_S, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """수집 작업이 쓰는 HTTP 클라이언트. 넘겨주기(redirect)는 따라가지 않는다 (홈페이지 확인기가 직접 본다).

    transport는 테스트가 가짜 응답을 넣을 때만 쓴다.
    """
    return httpx2.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": user_agent()},
        follow_redirects=False,
        transport=transport,
    )


class ApiError(Exception):
    """공공 API가 정상 응답을 주지 않음. reason은 로그용 짧은 이름이다 (키 · 주소를 넣지 않는다)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def parse_items(content: bytes) -> tuple[list[dict[str, str]], int]:
    """포털 응답 → (item 목록, 전체 건수). 결과 코드가 정상이 아니면 ApiError."""
    head = content.lstrip()[:1]
    if head == b"{":
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise ApiError("bad_json") from exc
        root = data.get("response", data) if isinstance(data, dict) else {}
        code = _text((root.get("header") or {}).get("resultCode")) or None
        if code not in _OK_CODES:
            raise ApiError(f"result_{code}")
        body = root.get("body") or {}
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        rows = [{k: _text(v) for k, v in it.items()} for it in items if isinstance(it, dict)]
        return rows, int(_text(body.get("totalCount")) or len(rows))
    if head == b"<":
        if re.search(rb"<!(DOCTYPE|ENTITY)", content, re.IGNORECASE):
            raise ApiError("xml_dtd")  # 외부 엔티티 · 부풀리기를 막는다
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ApiError("bad_xml") from exc
        auth = root.findtext(".//returnAuthMsg")
        if auth:
            raise ApiError(auth.strip()[:40])  # 예: SERVICE_KEY_IS_NOT_REGISTERED_ERROR
        code = _text(root.findtext(".//header/resultCode")) or None
        if code not in _OK_CODES:
            raise ApiError(f"result_{code}")
        rows = [{c.tag: _text(c.text) for c in it} for it in root.iter("item")]
        return rows, int(_text(root.findtext(".//totalCount")) or len(rows))
    raise ApiError("unknown_format")


async def _get(http: httpx2.AsyncClient, url: str, params: dict) -> bytes:
    try:
        r = await http.get(url, params=params)
    except httpx2.HTTPError as exc:
        raise ApiError(type(exc).__name__) from None  # 예외 글에 키가 든 주소가 있어 버린다
    if r.status_code != 200:
        raise ApiError(f"http_{r.status_code}")
    return r.content


async def kiscon_items(
    http: httpx2.AsyncClient, key: str, start: str, end: str, *, max_pages: int = 500
) -> list[dict[str, str]]:
    """공시 기간(YYYYMMDD)의 KISCON 공시를 쪽마다 받아 모은다."""
    out: list[dict[str, str]] = []
    for page in range(1, max_pages + 1):
        params = {
            "serviceKey": key,
            "pageNo": page,
            "numOfRows": PAGE_ROWS,
            "type": "json",
            KISCON_DATE_PARAMS[0]: start,
            KISCON_DATE_PARAMS[1]: end,
        }
        rows, total = parse_items(await _get(http, f"{KISCON_URL}/{KISCON_OP}", params))
        out += rows
        if not rows or len(out) >= total:
            break
    return out


async def nts_status(http: httpx2.AsyncClient, key: str, numbers: list[str]) -> dict[str, str]:
    """사업자등록번호(100개까지) → active · suspended · closed · unknown. 검증에만 쓴다."""
    try:
        r = await http.post(NTS_URL, params={"serviceKey": key}, json={"b_no": numbers})
    except httpx2.HTTPError as exc:
        raise ApiError(type(exc).__name__) from None
    if r.status_code != 200:
        raise ApiError(f"http_{r.status_code}")
    try:
        data = r.json()
    except ValueError as exc:
        raise ApiError("bad_json") from exc
    if _text(data.get("status_code")) != "OK":
        raise ApiError(f"status_{_text(data.get('status_code'))[:20]}")
    out: dict[str, str] = {}
    for d in data.get("data") or []:
        no = re.sub(r"\D", "", _text(d.get("b_no")))
        if len(no) == 10:
            out[no] = _NTS_STATUS.get(_text(d.get("b_stt_cd")), "unknown")
    return out
