"""고침 4차 P 갈래 · 가림 빈틈(보안 QA r4 x1 새 문제 1 · 2): 보이지 않는 글자로 끊은 번호, 빈칸으로 끊은 단서 없는
계좌. 날짜 · 전화 · 금액 · 평형은 전처럼, 가린 글에는 보이지 않는 글자가 남지 않음. DB 없음 · 유료 호출 0회.
번호는 모두 지어낸 값이에요."""

import pytest

from app.agent.v3 import check
from app.assistant import policy
from app.shared import pii
from app.shared.text import CONTROL, INVISIBLE

ZW, ZWNJ, ZWJ, WJ, BOM = chr(0x200B), chr(0x200C), chr(0x200D), chr(0x2060), chr(0xFEFF)
# 한글 채움 · 초성 채움 · 중성 채움 · 반각 채움
FILLER, CHO, JUNG, HALF = chr(0x3164), chr(0x115F), chr(0x1160), chr(0xFFA0)
# 보이지 않는 글자 여러 가지: 지시서 꼴 + 무른 붙임표 · 보이지 않는 곱 · 점자 빈칸 · 몽골 모음 가름 · 방향 표시 · 가둠
HIDDEN = [ZW, ZWNJ, ZWJ, WJ, BOM, FILLER, CHO, JUNG, HALF] + [
    chr(c) for c in (0x00AD, 0x2062, 0x2800, 0x180E, 0x200E, 0x2068, 0x2069)
]
VS16 = chr(0xFE0F)
HEART = chr(0x2764) + VS16
FAMILY = ZWJ.join(chr(c) for c in (0x1F468, 0x1F469, 0x1F467))
CODER = chr(0x1F469) + chr(0x1F3FD) + ZWJ + chr(0x1F4BB)  # 피부색 + 이음


def hidden_left(text: str) -> bool:
    return bool(INVISIBLE.search(text) or CONTROL.search(text))


# ---- 1. 보이지 않는 글자로 끊은 번호(새 문제 1) ----

# x1 턴 6 문장 그대로 → 저장 · LLM 입력에 동호수가 남았어요('101동' 뒤 폭 없는 빈칸 '1203')
QA6 = f"연락은 010{ZW}1234{ZW}5678로 주세요. 집은 101동{ZW}1203이에요"


def test_qa_turn6_sentence_masks_both_and_leaves_no_hidden_letters():
    got = policy.mask_in(QA6)
    assert got == "연락은 (번호 가림)로 주세요. 집은 (동호수 가림)이에요"
    assert not hidden_left(got)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        # x1 서버 없는 탐침(out/probe_zw.txt)에서 '같음' · 앞자리가 남던 꼴
        (f"집은 101동{ZW}1203이에요", "집은 (동호수 가림)이에요"),
        (f"집은 101동 {ZW}1203이에요", "집은 (동호수 가림)이에요"),
        (f"집은 101{ZW}동 1203호예요", "집은 (동호수 가림)예요"),
        (f"폰 010{FILLER}1234{FILLER}5678", "폰 (번호 가림)"),
        (f"입금은 3333-01-{ZW}2345678로", "입금은 (계좌 가림)로"),
        (f"주민번호 900101{ZW}1234567", "주민번호 (주민번호 가림)"),
        # 숫자 한 자리마다 끼운 꼴
        (f"1{ZW}0{ZW}1동 1{ZW}2{ZW}0{ZW}3이요", "(동호수 가림)이요"),
        (f"0{ZW}1{ZW}0{ZW}-1234-5678", "(번호 가림)"),
        (FILLER.join("01012345678"), "(번호 가림)"),
        (ZW.join("900101") + "-1234567", "(주민번호 가림)"),
        # 묶음 사이에만 끼운 꼴: 구분자로 본 글이 덜 남겨요
        (f"3333{ZW}01{ZW}2345678로 보내요", "(계좌 가림)로 보내요"),
        (f"카카오뱅크 3333{ZW}01{ZW}2345678", "카카오뱅크 (계좌 가림)"),
        (f"010{WJ}1234{WJ}5678", "(번호 가림)"),
        (f"3층{ZW} 2호", "(동호수 가림)"),
        (f"상계주공 101-{ZW}1203", "상계주공 (동호수 가림)"),
        # 묶음 가운데를 끊은 전화: 지운 글이 덜 남겨요
        (f"0101{ZW}234{ZW}5678", "(번호 가림)"),
        # 이메일 · 아이디 · 줄표 옆
        (f"kim{ZW}.minsu@exam{ZW}ple.com", "(이메일 가림)"),
        (f"카톡 아이디 min{ZW}su88", "카톡 아이디 (아이디 가림)"),
        (f"010{ZW}-{ZW}1234{ZW}-{ZW}5678", "(번호 가림)"),
    ],
)
def test_numbers_split_by_hidden_letters_are_masked(text, want):
    got = check.mask(text)
    assert got == want
    assert not hidden_left(got)


@pytest.mark.parametrize("ch", HIDDEN, ids=[f"U+{ord(c):04X}" for c in HIDDEN])
def test_each_hidden_letter_between_dong_and_ho_or_phone_groups(ch):
    for text, want in [
        (f"집은 101동{ch}1203이에요", "집은 (동호수 가림)이에요"),
        (f"폰 010{ch}1234{ch}5678", "폰 (번호 가림)"),
        (f"주민번호 900101{ch}1234567", "주민번호 (주민번호 가림)"),
        (f"3333{ch}01{ch}2345678", "(계좌 가림)"),
    ]:
        got = check.mask(text)
        assert got == want, (repr(text), got)
        assert not hidden_left(got)


def test_masked_text_drops_hidden_letters_but_keeps_emoji():
    text = f"{ZW}고마워요 {HEART} {FAMILY} {CODER}{FILLER} 집은 101동{ZW}1203이에요{BOM}"
    got = check.mask(text)
    assert got == f"고마워요 {HEART} {FAMILY} {CODER} 집은 (동호수 가림)이에요"
    # 남은 이음 · 모양 고르기는 그림 글자 묶음 안의 것뿐
    plain = chr(0x2764) + " " + FAMILY.replace(ZWJ, "") + " " + CODER.replace(ZWJ, "")
    assert INVISIBLE.sub("", got) == f"고마워요 {plain} 집은 (동호수 가림)이에요"


@pytest.mark.parametrize(
    "text",
    [
        # 가릴 게 없으면 글을 그대로 둔다(조사 · 기억의 '가림 전후가 같은가' 검사가 보이지 않는 글자만으로 걸리지 않게)
        f"도배{ZW} 기간 알려 줘요",
        f"{BOM}실크 벽지로 해 주세요{FILLER}",
        f"12월{ZW} 14일에 3,300,000원{FILLER}, 32평이에요",
        f"2026{ZW}12{ZW}14",  # 지워도 빈칸으로 봐도 8자리 날짜
        f"1588{ZW}1234",
        f"사업자번호 123{ZW}45{ZW}67890",
        f"101동{ZW} 300만 원",
        f"가족 {FAMILY}이 살아요 {HEART}",
    ],
)
def test_text_without_pii_is_returned_as_is(text):
    assert check.mask(text) == text


# ---- 2. 빈칸으로 끊은 단서 없는 계좌(새 문제 2, 리드 결정): 하이픈 규칙과 같은 묶음 수 · 자릿수 ----


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("3333 01 2345678", "(계좌 가림)"),  # x1 탐침 '3333 (번호 가림)'
        ("3333 01 2345678로 보내 주세요", "(계좌 가림)로 보내 주세요"),
        ("입금은 3333 01 2345678, 문의는 010 1234 5678", "입금은 (계좌 가림), 문의는 (번호 가림)"),
        ("110 123 456789", "(계좌 가림)"),  # 3-3-6
        ("1002 123 456789", "(계좌 가림)"),  # 4-3-6
        ("123456 12 123456", "(계좌 가림)"),  # 6-2-6
        ("1000 1234 5678", "(계좌 가림)"),  # 4-4-4
        ("302 1234 5678 91", "(계좌 가림)"),  # 3-4-4-2
        ("3333  01  2345678", "(계좌 가림)"),  # 두 칸
        ("3333 - 01 - 2345678", "(계좌 가림)"),  # 빈칸을 둔 하이픈
        ("3333-01 2345678", "(계좌 가림)"),  # 섞음
        ("3333ㅡ01ㅡ2345678", "(계좌 가림)"),  # 모음 'ㅡ'(전화 N1 꼴)
        ("3333" + chr(0x2014) + "01" + chr(0x2014) + "2345678", "(계좌 가림)"),  # 긴 줄표
        ("- 3333 01 2345678", "- (계좌 가림)"),  # 목록 기호 뒤
        ("(3333 01 2345678)", "((계좌 가림))"),
        (
            "12월 14일에 3,300,000원을 3333 01 2345678로 보낼게요",
            "12월 14일에 3,300,000원을 (계좌 가림)로 보낼게요",
        ),
    ],
)
def test_spaced_account_without_cue_is_masked(text, want):
    assert check.mask(text) == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("2026 12 14", "2026 12 14"),  # 날짜 8자리
        ("2026 12 14에 와 주세요", "2026 12 14에 와 주세요"),
        ("010 1234 5678", "(번호 가림)"),  # 전화(0으로 시작)는 전화 규칙
        ("02 1234 5678", "(번호 가림)"),
        ("0 1 0 7 7 7 7 8 8 8 8", "(번호 가림)"),
        ("82 10 3456 7890", "(번호 가림)"),  # 국제 전화는 먼저 가린다
        ("900101 1234567", "(주민번호 가림)"),  # 주민번호 규칙이 먼저
        ("123 45 67890", "123 45 67890"),  # 사업자번호 10자리
        ("1250 3375 4125원", "1250 3375 4125원"),  # 금액: 12자리라도 단위가 붙으면 둔다
        ("2468 1357 9753mm", "2468 1357 9753mm"),
        ("32 34 40평", "32 34 40평"),  # 평형
        ("100 200 300만 원", "100 200 300만 원"),
        ("3,300,000 3,500,000 3,200,000", "3,300,000 3,500,000 3,200,000"),
        ("12.14 12.15 12.16", "12.14 12.15 12.16"),
    ],
)
def test_spaced_numbers_that_are_not_accounts(text, want):
    assert check.mask(text) == want


@pytest.mark.parametrize(
    "text",
    [
        # 빈칸 계좌 규칙만 본다(뒤 전화 그물 PHONE_ANY가 0이 든 숫자 줄을 가리는 건 출발점부터 같음, 보고서 참고)
        "1000 2000 3000원",
        "1000 2000 3000만 원",
        "2024 2025 2026년",
        "3000 2400 2300mm",
        "3000 2400 2300 mm",
        "3333\n01\n2345678",  # 줄을 넘으면 묶음으로 안 봄(표 · 목록)
        "1200 1500 1800 2100 2400",  # 숫자 15자리 넘는 줄은 통째로 둔다
        "12 3333 01 2345678 9",  # 앞뒤에 묶음이 더 붙은 줄
        "90 100 120 150 180",  # 다섯 묶음(표를 펼친 줄, 셈에서 찾은 오탐)
        "2026 12 14",
        "123 45 67890",
    ],
)
def test_spaced_account_rule_leaves_units_lines_and_long_runs(text):
    assert pii.ACCOUNT_SPACED.sub(pii._bare_account, text) == text
