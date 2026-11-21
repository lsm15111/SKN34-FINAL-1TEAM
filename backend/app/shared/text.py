"""글 칸 공용 손질: 보이지 않는 제어 문자 · ANSI 색 코드 · 방향 바꾸기 글자를 지운다(보안 L1 · L2).

- NUL(\\x00)은 PostgreSQL text가 받지 않아 저장에서 500이 났어요. 다른 C0 · C1 제어 문자 · DEL도 화면 · 로그를 어지럽혀요.
  줄바꿈 · 탭 · 캐리지 리턴은 둬요(여러 줄 글). 한 줄 칸은 부르는 쪽이 빈칸을 한 칸으로 줄여요.
- ANSI 색 코드(ESC [ … m)는 통째로 지워요(ESC만 지우면 '[31m'이 남아요).
- 방향 바꾸기 글자(U+202A~202E · U+2066~2069 · U+200E/F · U+061C)는 글을 거꾸로 보이게 해 속일 수 있어요.
"""

import re

ANSI = re.compile(r"\x1b\[[0-?]{0,32}[ -/]{0,8}[@-~]|\x1b[@-_]")
CONTROL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)


def strip_controls(text: str) -> str:
    """보이지 않는 제어 문자 · ANSI 색 코드 · 방향 바꾸기 글자를 뺀 글(줄바꿈 · 탭은 둔다)."""
    return CONTROL.sub("", ANSI.sub("", text))


def clean_input(v: object) -> object:
    """pydantic before 검사용: 글이면 손질하고, 글이 아니면 그대로 넘겨 형식 검사에 맡긴다."""
    return strip_controls(v) if isinstance(v, str) else v
