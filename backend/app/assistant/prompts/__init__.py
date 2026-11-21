"""비서 지시문(판 번호 고정). 바꾸면 새 판 파일(customer_v2.md …)을 더하고 VERSION을 올린다(커밋 type prompt).

지시문에는 코드 값 · 규칙만 둔다. 업체 · 웹 · 고객 글은 넣지 않는다(턴 사실도 role:system 메시지로 따로 보낸다).
짧은 일(먼저 말 걸기 판정 · 문장, 기억 뽑기, 업체 브리핑 한 문장)은 Haiku 지시문을 따로 둔다.
"""

from functools import cache
from pathlib import Path

VERSION = {
    "customer": "customer_v2",
    "vendor": "vendor_v2",
    "nudge_judge": "nudge_judge_v1",
    "nudge_write": "nudge_write_v1",
    "memory": "memory_v2",
    "brief": "brief_v1",
}
_DIR = Path(__file__).resolve().parent


@cache
def system(surface: str) -> str:
    """화면(customer · vendor)의 지시문. 판 번호가 같으면 글이 같다(프롬프트 캐시)."""
    return text(surface)


@cache
def text(name: str) -> str:
    """이름(VERSION 키)의 지시문 글."""
    return (_DIR / f"{VERSION[name]}.md").read_text(encoding="utf-8").strip()
