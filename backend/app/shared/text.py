"""글 칸 공용 손질: 보이지 않는 제어 문자 · ANSI 색 코드 · 방향 바꾸기 글자를 지운다(보안 L1 · L2).

- NUL(\\x00)은 PostgreSQL text가 받지 않아 저장에서 500이 났어요. 다른 C0 · C1 제어 문자 · DEL도 화면 · 로그를 어지럽혀요.
  줄바꿈 · 탭 · 캐리지 리턴은 둬요(여러 줄 글). 한 줄 칸은 부르는 쪽이 빈칸을 한 칸으로 줄여요.
- ANSI 색 코드(ESC [ … m)는 통째로 지워요(ESC만 지우면 '[31m'이 남아요).
- 방향 바꾸기 글자(U+202A~202E · U+2066~2069 · U+200E/F · U+061C)는 글을 거꾸로 보이게 해 속일 수 있어요.
- 사람이 쓰는 글 칸은 Tidy를 씌워요(보안 QA r2 N2: 못 받아요 메모 · 벽지 사양 · 추가 금액 칸에 NUL이 남아 500).
- 보이지 않는 글자(폭 없는 빈칸 · 한글 채움 · BOM 등)만 남은 글은 빈 글로 봐요(N4). 글 가운데 것은 지우지 않아요
  (이모지 이음 U+200D · 모양 고르기 U+FE0F가 깨져요).
"""

import re

from pydantic import BeforeValidator

ANSI = re.compile(r"\x1b\[[0-?]{0,32}[ -/]{0,8}[@-~]|\x1b[@-_]")
CONTROL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
# 보이지 않는 글자: 무른 붙임표 · 글자 잇기(U+034F) · 한글 채움(U+115F · 1160 · 3164 · FFA0) · 폭 없는 빈칸 · 이음
# (U+200B~200D · 2060~2064) · 옛 꼴 바꾸기(U+206A~206F) · 점자 빈칸(U+2800) · 모양 고르기(U+FE00~FE0F · E0100~E01EF)
# · BOM(U+FEFF) · 끼움 표시(U+FFF9~FFFB) · 몽골 · 크메르 빈 글자 · 악보 꼴 · 태그(U+E0000~E007F)
INVISIBLE = re.compile(
    "[\u00ad\u034f\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200d\u2060-\u2064\u206a-\u206f"
    "\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff9-\ufffb\U0001d173-\U0001d17a\U000e0000-\U000e007f"
    "\U000e0100-\U000e01ef]"
)


def strip_controls(text: str) -> str:
    """보이지 않는 제어 문자 · ANSI 색 코드 · 방향 바꾸기 글자를 뺀 글(줄바꿈 · 탭은 둔다)."""
    return CONTROL.sub("", ANSI.sub("", text))


def clean_input(v: object) -> object:
    """pydantic before 검사용: 글이면 손질하고, 글이 아니면 그대로 넘겨 형식 검사에 맡긴다."""
    return strip_controls(v) if isinstance(v, str) else v


def visible(text: str) -> str:
    """보이는 글자만 남긴 글(빈칸 · 보이지 않는 글자를 뺌). 비었으면 보낼 말이 없는 글이에요."""
    return INVISIBLE.sub("", text).strip()


def tidy(v: object) -> object:
    """글 칸 손질(pydantic before 검사): 제어 문자를 지우고 앞뒤 빈칸을 뗀다. 보이지 않는 글자만 남으면 빈 글("")로
    바꿔 필수 칸은 길이 검사가 422로, 고를 칸은 칸 검사가 None으로 받게 한다. 글이 아니면 그대로 넘긴다."""
    if not isinstance(v, str):
        return v
    v = strip_controls(v).strip()
    return v if visible(v) else ""


# 사람이 쓰는 글 칸에 씌우는 손질. Annotated 맨 뒤에 둬야 길이 검사보다 먼저 돌고 길이 오류 글도 그대로예요.
#   note: Annotated[str, StringConstraints(max_length=100), Tidy] | None = None
Tidy = BeforeValidator(tidy)
