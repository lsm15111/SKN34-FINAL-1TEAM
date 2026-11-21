import re

_LAST = re.compile(r"([가-힣])[)\]\s]*$")


def i_ga(name: str) -> str:
    """받침이 있으면 '이', 없으면 '가' (마루와벽이 · 결도배가)"""
    last = name[-1:] or " "
    if "가" <= last <= "힣":
        return name + ("이" if (ord(last) - 0xAC00) % 28 else "가")
    return name + "이"


def euro(word: str) -> str:
    """받침이 없거나 ㄹ 받침이면 '로', 그 밖 받침이면 '으로'(결도배로 · 마루와벽으로 · 오전으로). 괄호로 끝나면
    괄호 안 마지막 한글로 본다('11.30(일)로'). 한글로 끝나지 않으면 '(으)로'."""
    m = _LAST.search(word)
    if m is None:
        return word + "(으)로"
    jong = (ord(m[1]) - 0xAC00) % 28
    return word + ("로" if jong in (0, 8) else "으로")
