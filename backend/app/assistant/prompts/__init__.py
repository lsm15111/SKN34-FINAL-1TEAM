"""비서 지시문(판 번호 고정). 바꾸면 새 판 파일(customer_v2.md …)을 더하고 VERSION을 올린다(커밋 type prompt).

지시문에는 코드 값 · 규칙만 둔다. 업체 · 웹 · 고객 글은 넣지 않는다(턴 사실도 role:system 메시지로 따로 보낸다).
"""

from functools import cache
from pathlib import Path

VERSION = {"customer": "customer_v1", "vendor": "vendor_v1"}
_DIR = Path(__file__).resolve().parent


@cache
def system(surface: str) -> str:
    """화면(customer · vendor)의 지시문. 판 번호가 같으면 글이 같다(프롬프트 캐시)."""
    return (_DIR / f"{VERSION[surface]}.md").read_text(encoding="utf-8").strip()
