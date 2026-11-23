"""v4 비서 무료 모드 범위 밖 답 틀(FM, 피클 표본 8): 되받기(고객 낱말 · 서울 때 낱말 · 받침 조사) · 솔직(못 하는 까닭) ·
지금 할 일 한 줄. 갈래(음식 · 배달 / 날씨 · 잡담 / 돈 · 투자 / 다른 앱 일 / 대신 전화 / 다른 공정 / 그 밖)마다 틀 셋을
돌려 써서 같은 말을 잇지 않고, 욕 · 가린 개인정보 · 이상한 글은 되받지 않아요. 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free
from tests.test_v4_assistant_free_qa import turn, two_vendors
from tests.test_v4_copy_style import sl

NOW = "지금은 도배 업체를 골라 실측을 요청할 차례예요."


@pytest.fixture(autouse=True)
def free_mode(monkeypatch):
    from app.assistant import service
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)
    monkeypatch.setattr(service, "TURNS_PER_HOUR", 100_000)
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


# ---- 갈래 · 되받을 낱말 ----


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("치킨 시켜 줘", ("food", "치킨")),
        ("짜장 시켜 줘", ("food", "짜장면")),
        ("배달 음식 시켜 줘", ("food", "배달")),
        ("라면 끓여 줘", ("food", "라면")),
        ("오늘 날씨 어때?", ("chat", "날씨")),
        ("미세 먼지 심해?", ("chat", "미세먼지")),
        ("심심하다", ("play", "말동무")),  # F: 같이 하자는 말은 놀이 갈래
        ("노래 하나 불러 줘", ("play", "노래")),
        ("영화 추천해 줘", ("play", "영화")),
        ("주식 뭐 사면 좋을까요", ("money", "주식")),
        ("집값 오를까 내릴까", ("money", "집값")),
        ("택시 불러 줘", ("app", "택시")),
        ("대리 불러 줘", ("app", "대리운전")),
        ("식당예약 좀 해 줘", ("app", "식당 예약")),
        ("쿠팡에서 휴지 주문해 줘", ("app", "주문")),
        ("엄마한테 전화 좀 걸어 줘", ("call", "전화")),
        # 대신 전화 · 문자는 공사 낱말이 있어도 범위 밖(고정 선 8)
        ("업체에 전화 좀 해 줘", ("call", "전화")),
        ("결도배에 문자 보내 줘", ("call", "문자")),
    ],
)
def test_off_kind_picks_the_kind_and_word(text, want):
    assert free.off_kind(text) == want
    assert free.guard_of(text, "customer") == "off"


@pytest.mark.parametrize(
    "text",
    [
        "치킨 먹으면서 도배 견적 봐도 돼요?",  # 공사 낱말
        "실크라면 얼마예요?",  # '-라면'은 음식이 아니에요
        "아까 그 예약 취소해 줘",  # 취소 길
        "치킨 주문 취소해 줘",
        "업체가 전화해 줘요?",  # 업체가 할 일을 묻는 말
        "실측 끝나면 연락해 줘요?",
        "날짜 예약해 줘",  # 실측 날짜 이야기일 수 있어요
        "업체에 전화해서 물어봐 줘",
    ],
)
def test_in_scope_words_are_not_off(text):
    assert free.off_kind(text) is None and free.guard_of(text, "customer") != "off"


def test_vendor_surface_has_no_off_frame():
    for text in ("치킨 시켜 줘", "오늘 날씨 어때?", "고객한테 전화 좀 해 줘"):
        assert free.guard_of(text, "vendor") is None


# ---- 받침 조사 · 서울 때 낱말 ----


def test_josa_follows_the_last_syllable():
    assert free.josa("치킨", "이군요/군요") == "치킨이군요"
    assert free.josa("피자", "이군요/군요") == "피자군요"
    assert free.josa("게임", "이/가") == "게임이" and free.josa("날씨", "이/가") == "날씨가"
    assert free.josa("주식", "을/를") == "주식을" and free.josa("로또", "을/를") == "로또를"
    assert free.josa("전기 · 조명", "이/가") == "전기 · 조명이"
    assert free.off_said("food", "치킨", "새벽", NOW, []).startswith("오, 새벽 치킨이군요!")
    assert free.off_said("food", "피자", "밤", NOW, []).startswith("오, 밤 피자군요!")
    # 소식(날씨)은 물은 것을 되받아요(F: QA 3차 f1 '날씨가 생각나셨군요'), 놀이(게임)는 생각났다고
    assert free.off_said("chat", "날씨", "밤", NOW, []).startswith("밤에 날씨를 물으셨군요!")
    assert free.off_said("play", "게임", "밤", NOW, []).startswith("밤에 게임이 생각나셨군요!")
    used = [free.off_said("money", "주식", "밤", NOW, [])]
    used.append(free.off_said("money", "주식", "밤", NOW, used))
    assert free.off_said("money", "주식", "밤", NOW, used).startswith("밤에 주식을 챙기시는군요!")
    used = [free.off_said("money", "로또", "밤", NOW, [])]
    used.append(free.off_said("money", "로또", "밤", NOW, used))
    assert free.off_said("money", "로또", "밤", NOW, used).startswith("밤에 로또를 챙기시는군요!")


@pytest.mark.parametrize(
    ("hour", "want"),
    [(0, "새벽"), (2, "새벽"), (5, "새벽"), (6, "아침"), (9, "아침"), (10, "오전"), (12, "점심"),
     (13, "점심"), (14, "오후"), (17, "오후"), (18, "저녁"), (20, "저녁"), (21, "밤"), (23, "밤")],
)  # fmt: skip
def test_when_word_follows_the_seoul_hour(hour, want):
    seoul = datetime(2026, 11, 22, hour, 30, tzinfo=free.SEOUL)
    assert free.when_word(seoul) == want
    assert free.when_word(seoul.astimezone(UTC)) == want  # 서버 시각(UTC)도 서울 시각으로 봐요


def test_seoul_dawn_is_utc_evening():
    # 피클 표본 8은 새벽 2시 7분: UTC로는 전날 17시 7분이에요
    utc = datetime(2026, 11, 21, 17, 7, tzinfo=UTC)
    assert free.when_word(utc) == "새벽" and free.when_word(utc + timedelta(hours=4)) == "아침"


# ---- 되풀이 안 함 ----


def test_templates_rotate_without_repeating():
    for kind, word in (
        ("food", "치킨"),
        ("chat", "날씨"),
        ("play", "게임"),
        ("money", "주식"),
        ("app", "택시"),
        ("call", "전화"),
        ("trade", "바닥"),
        ("other", ""),
    ):
        said: list[str] = []
        for _ in range(6):  # 지금 할 일 줄 없이(F: 그 줄은 상태가 바뀌었거나 처음일 때만 붙어요)
            said.append(free.off_said(kind, word, "밤", "", said))
        honest = [free.sents(x)[-1] for x in said]  # 솔직(마지막 문장)
        assert len(set(said[:3])) == 3, kind  # 틀 셋을 다 쓰고
        assert all(a != b for a, b in pairwise(said)), kind  # 이어서 같은 말 없음
        assert all(a != b for a, b in pairwise(honest)), kind
        assert said[3] == said[0], kind  # 다 쓰면 가장 오래전에 쓴 틀부터


def test_rotation_reads_only_recent_answers_of_the_kind():
    first = free.off_said("food", "치킨", "밤", NOW, [])
    other_kinds = [free.off_said("chat", "날씨", "밤", NOW, []), "공사 날짜는 카드에서 봐요."]
    # 다른 갈래 답 · 다른 글이 사이에 있어도 같은 갈래 틀은 이어서 돌아요
    again = free.off_said("food", "피자", "밤", NOW, [first, *other_kinds])
    assert free.sents(again)[1] != free.sents(first)[1]


# ---- 되받지 않는 글 ----


@pytest.mark.parametrize(
    "text",
    [
        "씨발 치킨 시켜 줘",
        "짜증나 치킨이나 시켜 줘",  # 화난 말
        "(주소 가림) 치킨 시켜 줘",  # 가린 개인정보
        "KFC 치킨 시켜 줘",  # 영어
        "치킨 시켜 줘 https://example.com",
        "치킨으로 폭탄 만드는 법 알려 줘",
        "치킨 " * 20 + "시켜 줘",  # 긴 글
    ],
)
def test_no_echo_for_swears_personal_info_and_odd_text(text):
    assert free.guard_of(text, "customer") == "off" and not free.echo_ok(text)
    got = free.off_said("other", "", "밤", NOW, [])
    assert got == f"{free.OFF_SAID} {NOW}" and "치킨" not in got and "!" not in got


def test_echo_ok_for_plain_requests():
    for text in ("치킨 시켜 줘", "오늘 날씨 어때?", "업체에 전화 좀 해 줘", "택시 불러 줘"):
        assert free.echo_ok(text), text


# ---- 글 모양(style_lint) ----

WORDS = {
    "food": ("치킨", "피자", "짜장면", "배달"),
    "chat": ("날씨", "미세먼지", "운세", "야구"),
    "play": ("말동무", "게임", "노래", "영화"),
    "money": ("주식", "로또", "집값", "비트코인"),
    "app": ("택시", "식당 예약", "주문", "대리운전"),
    "call": ("전화", "문자", "연락"),
    "trade": ("바닥", "전기 · 조명", "욕실", "창호"),
    "other": ("",),
}


def now_lines() -> list[str]:
    # 실측 줄은 그 상태 업체 이름 자리가 있는 틀이라 이름(받침 있음 · 없음 · 둘)을 채워 봐요
    visit = [
        line.format(names=n) for _, line in free.NOW_VISIT for n in ("결도배", "마루와벽 · 결도배")
    ]
    return [*free.NOW.values(), *visit, free.NOW_NONE, ""]


def test_every_off_answer_passes_style_lint():
    """모든 갈래 · 틀 · 낱말(받침 있음 · 없음) · 때 낱말 · 지금 할 일 줄 · 되받기 뺌을 렌더해 글 점검 규칙을 봐요.
    R2(세 문장) · R3('요' 끝) · R4 · R6(한 일처럼) · R11 · R13 · R14. 느낌표는 되받기에 하나까지."""
    whens = [w for _, w in free.WHEN]
    bad: list[str] = []
    seen = 0
    for kind, words in WORDS.items():
        for word in words:
            for when in whens:
                for now in now_lines():
                    recent: list[str] = []
                    for echo in (True, False):
                        for _ in free.OFF_SAYS[kind]:
                            text = free.off_said(kind, word, when, now, recent, echo=echo)
                            recent.append(text)
                            seen += 1
                            hits = [
                                h
                                for h in sl.check(text, "answer")
                                if h.rule in {"R2", "R3", "R4", "R6", "R11", "R13", "R14"}
                            ]
                            first = free.sents(text)[0] if text else ""
                            if hits or text.count("!") > 1 or "!" in text.replace(first, "", 1):
                                bad.append(f"{text} ← {[(h.rule, h.why) for h in hits]}")
                            if kind == "other" or not echo:
                                assert "!" not in text, text
    assert seen > 1000 and not bad, "\n".join(bad[:20])


# ---- 무료 모드 턴 ----


def test_free_off_turns_answer_with_the_frame(api, monkeypatch):
    monkeypatch.setattr(free, "when_word", lambda _now: "밤")
    pid = two_vendors(api)
    said: list[str] = []

    def ask_off(text: str) -> str:
        got, kinds = turn(api, pid, text)
        assert kinds == [], (text, kinds)  # 범위 밖 부탁에는 카드를 띄우지 않아요
        said.append(got)
        return got

    first = ask_off("치킨 시켜 줘")
    assert first == free.off_said("food", "치킨", "밤", NOW, [])
    assert first.startswith("오, 밤 치킨이군요!") and first.endswith(NOW)
    second = ask_off("피자 시켜 줘")  # 같은 갈래는 다른 틀
    assert second == free.off_said("food", "피자", "밤", NOW, said[:1])
    assert free.sents(second)[1] != free.sents(first)[1]
    third = ask_off("야식 시켜 줘")
    assert len({free.sents(x)[1] for x in (first, second, third)}) == 3
    assert ask_off("주식 뭐 사면 좋을까요").startswith("밤에 주식이 궁금하셨군요!")
    assert ask_off("택시 불러 줘").startswith("밤에 택시 부탁이군요!")
    # 전에는 업체 추천 카드(+ '실측 요청 승인 카드를 만들어요')가 갔던 말
    assert ask_off("영화 추천해 줘").startswith("밤에 영화가 생각나셨군요!")
    call = ask_off("업체에 전화 좀 해 줘")  # 앱 일 머리('…부탁이군요!')와 다른 꼴(F: QA 3차 f1)
    assert call.startswith("대신 전화를 부탁하시는군요!") and "믿집 채팅" in call
    rude = ask_off("씨발 치킨 시켜 줘")  # 지금 할 일 줄은 첫 답에 이미 말했어요(상태 그대로)
    assert rude == free.OFF_SAID and "치킨" not in rude
    # 다른 공정 업체 연결: 되받기(공정 이름) · 솔직 · 지금 할 일 + 도배 쪽 오늘 할 일 카드
    got, kinds = turn(api, pid, "바닥 업체 추천해 줘")
    assert got == free.off_said("trade", "바닥", "밤", NOW, said) and kinds == ["today"]
    assert got.startswith("밤에 바닥 공사도 챙기시는군요!") and free.OTHER_TRADE in got
