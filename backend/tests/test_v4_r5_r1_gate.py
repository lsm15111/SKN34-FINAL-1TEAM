"""고침 5차 R1(QA r5 C s5-3 · s5-4): 문장 검사의 숫자 근거 · 되가리키는 문장.

1. 지난 비서 말 두 개(이미 검사를 지나 보낸 글)의 숫자도 근거다: 앞 턴에 '…원부터 …원까지'라고 맞게 말한 뒤 '만 원
   단위로 대충 말하면?'에 도구 없이 '약 305만~340만 원'이 지난다. 지난 비서 말에 없는 숫자 · 반올림 단위의 반을 넘는
   어림 · 셋째 전 비서 말의 숫자는 지금처럼 빠진다.
2. 내용 까닭(숫자 · 한 일처럼 말함 …)으로 뺀 문장 바로 뒤에 '이 값 · 그 금액 · 둘 다 · 이건 · 그중 …'으로 여는 문장도
   뺀다(앞 문장을 가리킴). 그 뒤 남은 글이 없거나 가리키는 말뿐이면 정직한 한 줄(CUT_TEXT · 카드가 있으면 FAIL_TEXT).
DB 없는 문장 검사 + Claude 대본 턴(유료 호출 0회)."""

import json
from types import SimpleNamespace as NS

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import runtime, service
from tests.test_v4_assistant_new_tools import call, results
from tests.test_v4_assistant_offers import tokens
from tests.test_v4_assistant_turns import ask, home, ok, turn_row
from tests.test_v4_r4_g_gate import gate, run
from tests.test_visit_vendors import priced


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def trace(ev) -> dict:
    return json.loads(turn_row(ev[0][1]["turn_id"])["trace"])


# ---- 1. 지난 비서 말 두 개의 숫자 ----

RECOMMEND = ("recommend_vendors", {"trade": "dobae"})


def man(won: int) -> int:
    """만 원 반올림(guard.numbers와 같은 셈)."""
    return round(won / 10_000)


def estimates(api, script) -> tuple[str, int, int]:
    """업체 두 곳(마루와벽 · 결도배)의 가견적이 있는 집. (공사 id, 가장 낮은 값, 가장 높은 값). 고객으로 로그인."""
    priced(api, "maru@mitjip.test", "마루와벽")
    priced(api, "gyeol@mitjip.test", "결도배", wall=7000)
    _, pid = home(api, "r5r1-told@mitjip.test")
    _ev, log = call(script, api, pid, "도배 업체 찾아 줘", RECOMMEND)
    rec = results(log, 1)[0]
    return pid, rec["estimate_low_won"], rec["estimate_high_won"]


def test_numbers_in_the_last_two_answers_are_grounds(api, script):
    """QA r5 C s5-4: 앞 턴에 가견적 범위를 맞게 말한 뒤 '만 원 단위로 대충 말하면?'에 도구 없이 답하자 숫자 검사가 답을
    버리고 '이 값은 …'만 남음. 지난 비서 말에 없는 숫자 · 반올림 단위의 반을 넘는 어림 · 셋째 전 비서 말은 근거가 아니다."""
    pid, lo, hi = estimates(api, script)
    exact = f"가견적은 {lo:,}원부터 {hi:,}원까지예요(부가세 포함)."
    name, args = RECOMMEND
    script([{"tool_calls": [{"id": "t0", "name": name, "input": args}]}, {"text": exact}])
    assert tokens(ok(ask(api, pid, "업체 가견적은 얼마부터 얼마예요?"))) == exact
    rough = f"만 원 단위로는 약 {man(lo)}만~{man(hi)}만 원이에요."
    far = f"낮은 쪽을 줄이면 약 {man(lo) - 2}만 원이에요."  # 반올림 단위의 반(5,000원)을 넘는 어림
    none = "평당으로는 1,234,567원이에요."  # 지난 비서 말에도 없는 숫자
    script([{"text": f"{rough} {far} {none}"}])
    ev = ok(ask(api, pid, "만 원 단위로 대충 말하면 얼마부터 얼마예요?"))
    assert tokens(ev) == rough
    got = trace(ev)
    assert got["tools"] == [] and got["dropped"] == ["계산 결과 · 자료에 없는 숫자"] * 2
    # 숫자 없는 답 두 턴 뒤(가견적을 말한 답은 셋째 · 넷째 전): 그 숫자는 근거가 아니다
    for text, answer in (("고마워요", "네, 또 물어보세요."), ("알겠어요", "좋아요.")):
        script([{"text": answer}])
        ok(ask(api, pid, text))
    script([{"text": rough}])
    assert tokens(ok(ask(api, pid, "만 원 단위로 다시 말해 줘"))) == runtime.CUT_TEXT


def history(*answers: str) -> list[dict]:
    out: list[dict] = []
    for a in answers:
        out += [{"role": "user", "content": "물음"}, {"role": "assistant", "content": a}]
    return out


def test_told_counts_the_last_two_answers():
    """가장 가까운 비서 말 두 개만(카드만 보낸 턴의 기록 글은 세기만 하고 글은 넣지 않는다)."""
    got = runtime.told_before(history("1,111,111원", "2,222,222원", "3,333,333원"))
    assert "2,222,222" in got and "3,333,333" in got and "1,111,111" not in got
    cards_only = f"{runtime.CARDS_ONLY}: 업체 추천)"
    got = runtime.told_before(history("1,111,111원", "2,222,222원", cards_only))
    assert got == "2,222,222원"
    assert runtime.told_before([{"role": "user", "content": "3,333,333원"}]) == ""


def test_the_last_two_answers_are_never_clipped():
    """근거로 쓰는 마지막 비서 말 두 개는 최근 HISTORY_FULL줄 안이라 자르지 않은 글이다(앞부분만 남긴 옛 비서 말은
    근거에 들지 않는다)."""
    long = " ".join(f"{i}번째 업체 가견적은 3,0{i:02d},900원이에요." for i in range(20))
    assert len(long) > service.HISTORY_CUT
    rows = [
        NS(role=role, text=long if role == "assistant" else "물음")
        for _ in range(service.HISTORY // 2)
        for role in ("user", "assistant")
    ]
    said = [m["content"] for m in service._history(rows) if m["role"] == "assistant"]
    # 옛 비서 말은 앞부분만
    assert said[0].endswith("…") and len(said[0]) <= service.HISTORY_CUT + 1
    assert runtime.told_before(service._history(rows)) == f"{long}\n{long}"


# ---- 2. 버린 문장을 되가리키는 문장 ----

# QA r5 C s5-4에 남은 문장
S54 = (
    "이 값은 벽지 값이 들어간 값이라, 벽지를 직접 사시면 실측 때 벽지 값을 빼 달라고 말씀해 주세요."
)
ROUGH = "가견적은 약 305만~340만 원이에요."
TWO = "결도배 3,045,900원 · 마루와벽 3,398,450원"


def test_back_pointer_after_a_dropped_sentence_goes_too():
    """숫자 문장이 빠지면 바로 뒤 '이 값은 …'도 뺀다. 남은 글이 없으면 정직한 한 줄(카드가 있으면 FAIL_TEXT)."""
    g = gate()
    assert run(g, f"{ROUGH} {S54}") == runtime.CUT_TEXT
    assert len(g.dropped) == 2 and g.dropped[-1] == "앞 문장을 가리킴"
    assert run(gate(), f"{ROUGH} {S54}", cards=True) == runtime.FAIL_TEXT
    # 앞 문장이 빠지지 않았으면 그대로 둔다
    assert run(gate(TWO), f"{ROUGH} {S54}") == f"{ROUGH} {S54}"


def test_back_pointer_follows_any_content_drop_and_chains():
    # 한 일처럼 말한 문장 뒤 '그건 …'
    g = gate()
    assert run(g, "실측 요청을 보냈어요. 그건 내일쯤 답이 와요.") == runtime.CUT_TEXT
    assert g.dropped == ["승인 없이 한 일처럼 말함", "앞 문장을 가리킴"]
    # 잇달아 가리키면 잇달아 뺀다 · 첫머리 접속 말은 떼고 본다
    g = gate()
    text = f"{ROUGH} 다만 이 값은 부가세 포함이에요. 그중 결도배가 더 싸요. 실측 때 벽지를 정해요."
    assert run(g, text) == "실측 때 벽지를 정해요."
    assert g.dropped[1:] == ["앞 문장을 가리킴"] * 2


def test_only_the_very_next_sentence_is_checked():
    """빠진 문장 바로 뒤만 본다: 사이에 보낸 문장이 있으면 '이 값은 …'은 그 문장을 가리킨다. 외국어 속말은 사이로 보지
    않는다."""
    text = f"{ROUGH} 표준견적서는 공공 기준이에요. {S54}"
    assert run(gate(), text) == f"표준견적서는 공공 기준이에요. {S54}"
    g = gate()
    assert run(g, f"{ROUGH} Let me check the vendors now. {S54}") == runtime.CUT_TEXT
    assert g.dropped[-1] == "앞 문장을 가리킴"


def test_honest_line_when_only_a_pointer_is_left():
    g = gate()
    got = run(g, f"{ROUGH} {S54} 업체 추천 카드를 눌러 주세요.", opened={"visit_request"})
    assert got == f"업체 추천 카드를 눌러 주세요. {runtime.CUT_TEXT}"


@pytest.mark.parametrize(
    ("text", "back"),
    [
        ("이 값은 부가세 포함이에요.", True),
        ("그 값이면 괜찮아요.", True),
        ("이 금액은 실측 전 값이에요.", True),
        ("그 금액에 벽지 값이 들어 있어요.", True),
        ("이 범위는 업체 두 곳 값이에요.", True),
        ("그 범위 안에서 고르시면 돼요.", True),
        ("둘 다 부가세 포함이에요.", True),
        ("이건 업체가 확인한 단가로 계산한 값이에요.", True),
        ("그건 실측 때 정해요.", True),
        ("이것은 업체마다 달라요.", True),  # '이건 · 그건'을 풀어 쓴 꼴
        ("그것도 실측 때 봐요.", True),
        ("그중 결도배가 더 싸요.", True),
        ("그 중에서 고르시면 돼요.", True),
        ("이 중 한 곳을 고르시면 돼요.", True),
        ("다만 이 값은 실측 전 값이에요.", True),  # 첫머리 접속 말을 떼고 본다
        ("이중 도배는 따로 계산해요.", False),
        ("그 중간에 실측을 해요.", False),
        ("둘 다른 업체예요.", False),
        ("이번 주에 실측해요.", False),
        ("값은 업체마다 달라요.", False),
        ("결도배 값이 이 값보다 낮아요.", False),  # 여는 말만 본다
    ],
)
def test_back_ref_reads_the_opening(text, back):
    assert runtime.back_ref(text) is back


def test_turn_drops_the_back_pointer_and_says_the_honest_line(api, script):
    """턴: s5-4 꼴(근거 없는 어림 + '이 값은 …'). 둘 다 빠지고 정직한 한 줄, 흔적에 까닭."""
    _, pid = home(api, "r5r1-back@mitjip.test")
    script([{"text": f"{ROUGH} {S54}"}])
    ev = ok(ask(api, pid, "만 원 단위로 대충 말하면 얼마부터 얼마예요?"))
    assert tokens(ev) == runtime.CUT_TEXT
    assert trace(ev)["dropped"] == ["계산 결과 · 자료에 없는 숫자", "앞 문장을 가리킴"]
