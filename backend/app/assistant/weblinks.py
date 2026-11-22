"""웹 도구 결과에서 링크 뽑기 · 막은 곳(도면 찾기 · 조사 담당이 같이 쓴다, 계약서 7장 주입 방어).

- 링크는 서버 도구 결과 블록(web_search_tool_result · web_fetch_tool_result)의 url만 코드가 뽑는다. 모델 글 속 주소는
  쓰지 않는다. 동적 거르기(코드 실행 안에서 부른 검색 · 가져오기)의 결과 블록도 같은 꼴이라 함께 읽는다.
- 막은 곳(BLOCKED)은 검색 · 가져오기 · 보여 주기를 모두 막는다: 도면 찾기 목록(네이버 부동산 · 호갱노노 · 아실) +
  네이버 지도 · 플레이스 · 카카오맵 · 인스타그램. 하위 도메인도 막는다(서버 도구의 blocked_domains와 같은 뜻).
- 실행 파일 꼴 주소(.exe · .apk …)는 버린다. 그림은 저장하지 않는다.
"""

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit

# 도면 찾기(tools/floorplan.py)가 처음부터 막던 곳
LAND = (
    "land.naver.com",
    "new.land.naver.com",
    "m.land.naver.com",
    "fin.land.naver.com",
    "hogangnono.com",
    "asil.kr",
)
# 지도 장소 · 인스타그램: robots가 AI 봇을 막고 약관이 자동 수집을 막는다(조사 06-외부-업체-찾기 2-3 · 6-1)
MAPS = (
    "map.naver.com",
    "m.map.naver.com",
    "place.naver.com",
    "m.place.naver.com",
    "pcmap.place.naver.com",
    "map.kakao.com",
    "place.map.kakao.com",
    "instagram.com",
)
BLOCKED = (*LAND, *MAPS)
BAD_PATH = re.compile(r"\.(?:exe|msi|apk|bat|cmd|scr|js|zip|dmg|pkg)$", re.IGNORECASE)


@dataclass
class Hit:
    """서버 도구 결과 블록에서 뽑은 페이지 하나(나온 순서). 제목 · 글은 원문이라 보여 줄 때 가린다."""

    url: str  # 조각(#…)을 뗀 주소
    host: str  # 소문자, www. 뗌
    title: str
    page_age: str | None = None  # 검색 결과가 알려 준 글 날짜(꼴은 자유)
    fetched: bool = False  # web_fetch로 읽은 페이지
    text: str = ""  # 가져온 글(글 문서만, 숫자 근거)
    # 열리지 않는 페이지: 가져오기가 오류였거나(열 수 없음 · 막힘) 가져온 글이 닫힌 페이지 안내뿐(QA r3 s3: 서비스가
    # 종료된 modoo 페이지가 결과 카드에 남음)
    dead: bool = False


# 닫힌 · 없는 페이지 안내(가져온 글 앞쪽에서만 본다)
_CLOSED = re.compile(
    r"서비스(?:가|를)?\s*(?:종료|중단)|운영(?:이|을)?\s*종료|페이지를\s*찾을\s*수\s*없|존재하지\s*않는\s*페이지|"
    r"삭제된\s*페이지|page\s+not\s+found|404\s*(?:not\s*found|error)",
    re.IGNORECASE,
)
CLOSED_HEAD = 600  # 닫힌 페이지 안내를 찾는 앞 글자 수
CLOSED_MAX = 2000  # 이보다 긴 글은 본문이 있는 페이지로 본다
EMPTY_MAX = 40  # 이보다 짧은 글은 내용이 없는 페이지로 본다


def closed_page(text: str) -> bool:
    """가져온 글이 닫힌 · 없는 페이지 안내뿐인지(아주 짧거나, 짧은 글 앞쪽에 '서비스 종료' 같은 말)."""
    t = " ".join((text or "").split())
    if len(t) < EMPTY_MAX:
        return True
    return len(t) < CLOSED_MAX and bool(_CLOSED.search(t[:CLOSED_HEAD]))


def _error_code(content: object) -> str | None:
    """서버 도구 결과의 오류 코드(오류면 content가 목록이 아니라 error_code가 든 객체예요)."""
    if isinstance(content, dict) and content.get("error_code"):
        return str(content["error_code"])
    return None


def tool_errors(content: list[dict]) -> list[str]:
    """웹 검색 · 가져오기 결과 블록의 오류 코드들(나온 순서). 'max_uses_exceeded'면 도구 상한까지 다 쓴 것."""
    out: list[str] = []
    for b in content:
        if isinstance(b, dict) and b.get("type") in (
            "web_search_tool_result",
            "web_fetch_tool_result",
        ):
            code = _error_code(b.get("content"))
            if code:
                out.append(code)
    return out


def code_failed(content: list[dict]) -> bool:
    """동적 거르기 코드 실행 결과 중 실패(오류 결과 · 0이 아닌 종료 코드)가 있는지."""
    for b in content:
        if not isinstance(b, dict) or b.get("type") not in (
            "code_execution_tool_result",
            "bash_code_execution_tool_result",
        ):
            continue
        c = b.get("content")
        if _error_code(c) or (isinstance(c, dict) and c.get("return_code") not in (None, 0)):
            return True
    return False


def host_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def blocked(host: str, domains: tuple[str, ...] = BLOCKED) -> bool:
    """host가 domains 중 하나이거나 그 하위 도메인인지(www.를 뗀 이름도 본다)."""
    h = host.lower()
    names = {h, h.removeprefix("www.")}
    return any(n == d or n.endswith("." + d) for n in names for d in domains)


def clean_url(url: str, domains: tuple[str, ...] = BLOCKED) -> str | None:
    """보여 줘도 되는 주소(http · https, 막은 곳 · 실행 파일 꼴이 아님)면 조각을 뗀 주소, 아니면 None."""
    try:
        u = urlsplit(str(url or "").strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host or blocked(host, domains):
        return None
    if BAD_PATH.search(u.path):
        return None
    return urlunsplit((u.scheme, u.netloc, u.path, u.query, ""))


def key(url: str) -> str:
    """같은 페이지를 한 번만 셀 열쇠(소문자 host · 끝 빗금 뗌 · %인코딩 풂 · 물음표 뒤 그대로)."""
    u = urlsplit(url)
    path = unquote(u.path).rstrip("/")
    return f"{(u.hostname or '').lower().removeprefix('www.')}{path}?{unquote(u.query)}"


def _fetched_text(doc: dict) -> str | None:
    """가져온 글(글 문서만). PDF(base64) 같은 글이 아닌 문서는 None(읽지 않아 닫힌 페이지인지 모른다)."""
    src = doc.get("source") if isinstance(doc, dict) else None
    if isinstance(src, dict) and src.get("type") == "text":
        return str(src.get("data") or "")
    return None


def _fetch_urls(content: list[dict]) -> dict[str, str]:
    """가져오기 도구 부름 id → 가져오려던 주소(오류 결과에는 주소가 없어 부름 블록에서 찾는다)."""
    out: dict[str, str] = {}
    for b in content:
        if (
            isinstance(b, dict)
            and b.get("type") == "server_tool_use"
            and b.get("name") == "web_fetch"
        ):
            url = (b.get("input") or {}).get("url") if isinstance(b.get("input"), dict) else None
            if url and b.get("id"):
                out[str(b["id"])] = str(url)
    return out


def hits(content: list[dict], domains: tuple[str, ...] = BLOCKED) -> list[Hit]:
    """응답 블록(여러 응답을 이은 것도 됨)에서 서버 도구 결과의 페이지를 나온 순서대로 뽑는다.

    같은 페이지는 한 번만(나중에 가져오기로 읽었으면 fetched · 글을 더한다). 막은 곳 · 실행 파일 꼴은 버린다.
    가져오기가 오류였거나 가져온 글이 닫힌 페이지 안내뿐이면 dead(결과 카드에서 뺀다). 검색 오류 결과는 건너뛴다."""
    out: dict[str, Hit] = {}
    dead: set[str] = set()
    asked = _fetch_urls(content)
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "web_fetch_tool_result" and _error_code(b.get("content")):
            url = clean_url(asked.get(str(b.get("tool_use_id")), ""), domains)
            if url is not None:
                dead.add(key(url))
            continue
        if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
            for r in b["content"]:
                if not isinstance(r, dict) or r.get("type", "web_search_result") != (
                    "web_search_result"
                ):
                    continue
                url = clean_url(str(r.get("url") or ""), domains)
                if url is None or key(url) in out:
                    continue
                host = host_of(url)
                out[key(url)] = Hit(
                    url=url,
                    host=host,
                    title=str(r.get("title") or host),
                    page_age=str(r["page_age"]) if r.get("page_age") else None,
                )
        elif b.get("type") == "web_fetch_tool_result" and isinstance(b.get("content"), dict):
            got = b["content"]
            if got.get("type") != "web_fetch_result":
                continue
            url = clean_url(str(got.get("url") or ""), domains)
            if url is None:
                continue
            doc = got.get("content") if isinstance(got.get("content"), dict) else {}
            text = _fetched_text(doc)
            if text is not None and closed_page(text):
                dead.add(key(url))
            old = out.get(key(url))
            if old is not None:
                old.fetched, old.text = True, old.text or text or ""
                continue
            host = host_of(url)
            out[key(url)] = Hit(
                url=url,
                host=host,
                title=str(doc.get("title") or host),
                fetched=True,
                text=text or "",
            )
    for k in dead & out.keys():
        out[k].dead = True
    return list(out.values())
