"""v4 비서 새 판 갈래 N(런타임 · 숫자 · 사실): 턴 사실 '지금 · 올해 · 미룬 알림' ·날짜 공용 꼴(카피 가이드 F2) · v4 대화 숫자
검사 풀기(어림 · 원대 · 차액 · 합계 · 평당 · 날짜 꼴) · 누출 검사는 규칙 절만 · 이름은 LLM에 보내지 않음 · 지시문 판 고르기
(ASSISTANT_PROMPT_SET) · 시간 제한으로 끊긴 호출의 장부 추정치 · 화면이 끊은 턴의 턴 자리. 유료 호출 0회(Claude 대본)."""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from v3_kb import repo_index

from app.agent import llm
from app.assistant import proactive, prompts, runtime
from app.assistant import service as assistant_service
from app.assistant.runtime import SentenceGate
from app.assistant.tools import cards
from app.assistant.tools import vendor as vendor_tools
from app.config import settings
from app.shared import kdate
from app.shared import request_guards as guards
from tests.conftest import ROOT, query
from tests.helpers import signup
from tests.test_v3_project_home import HOME
from tests.test_v4_assistant_turns import ok, turn_row
from tests.test_v4_llm_claude import _user
from tests.test_v4_llm_claude import run as run_llm
from tests.test_vendor_profile import approved_vendor


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


def home(api, email: str, name: str = "고객") -> str:
    signup(api, email, name=name)
    r = api.post("/projects", json=HOME)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ask(api, pid: str, text: str):
    body = {"project_id": pid, "client_key": uuid.uuid4().hex, "text": text}
    return api.post("/assistant/turns", json=body)


# ---- 1. 날짜 공용 꼴(카피 가이드 F2 · F5) · 때 말 표 ----


def test_dates_follow_copy_guide_f2():
    assert kdate.md_week(date(2026, 12, 7)) == "12.7(월)"  # 0을 붙이지 않는다
    assert kdate.md(date(2026, 12, 7)) == "12.7"
    assert kdate.md_range(date(2026, 12, 7), date(2026, 12, 21)) == "12.7(월)~12.21(월)"
    today = date(2026, 11, 22)
    assert kdate.md_week(date(2026, 12, 15), today) == "12.15(화)"  # 올해면 연도 없이
    assert kdate.md_week(date(2027, 1, 4), today) == "2027.1.4(월)"  # 올해가 아니면 연도
    assert kdate.md(date(2027, 1, 4), today) == "2027.1.4"
    assert kdate.md_long(date(2026, 12, 15)) == "12월 15일(화)"
    assert kdate.md_long(date(2027, 1, 4), today) == "2027년 1월 4일(월)"
    assert kdate.long_range(date(2026, 12, 1), date(2026, 12, 4)) == "12월 1일(화)~4일(금)"
    assert kdate.long_range(date(2026, 12, 29), date(2027, 1, 2)) == "12월 29일(화)~1월 2일(토)"
    assert (
        kdate.long_range(date(2026, 12, 29), date(2027, 1, 2), today)
        == "12월 29일(화)~2027년 1월 2일(토)"
    )
    assert kdate.day_list([date(2026, 12, 24), date(2026, 12, 28)]) == "2일 · 12.24(목) · 12.28(월)"
    # 옮긴 함수는 cards 이름으로도 그대로 쓴다(부르는 곳을 바꾸지 않아도 F2 꼴)
    assert cards.md_week is kdate.md_week and cards.md_long is kdate.md_long


@pytest.mark.parametrize(
    ("hour", "minute", "want"),
    [
        (0, 0, "새벽 0시"),
        (0, 30, "새벽 0시 30분"),
        (2, 5, "새벽 2시 5분"),
        (5, 59, "새벽 5시 59분"),
        (6, 0, "아침 6시"),
        (8, 59, "아침 8시 59분"),
        (9, 0, "아침 9시"),
        (10, 0, "오전 10시"),
        (11, 59, "오전 11시 59분"),
        (12, 0, "낮 12시"),
        (13, 0, "오후 1시"),
        (17, 30, "오후 5시 30분"),
        (18, 0, "저녁 6시"),
        (20, 59, "저녁 8시 59분"),
        (21, 0, "밤 9시"),
        (23, 59, "밤 11시 59분"),
    ],
)
def test_time_words_come_from_one_table(hour, minute, want):
    assert kdate.hour_text(hour, minute) == want


# ---- 2. 턴 사실: 지금 · 올해 · 미룬 알림(고객 · 업체) ----


def test_time_lines_say_seoul_now_and_year():
    at = datetime(2026, 11, 21, 17, 5, tzinfo=UTC)  # 서울 11-22(일) 02:05
    assert assistant_service.time_lines(at) == ["지금: 11월 22일(일) 새벽 2시 5분", "올해: 2026년"]
    lines = assistant_service.time_lines
    assert lines(datetime(2026, 11, 21, 15, tzinfo=UTC))[0] == "지금: 11월 22일(일) 새벽 0시"
    assert lines(datetime(2026, 11, 22, 0, tzinfo=UTC))[0] == "지금: 11월 22일(일) 아침 9시"
    assert lines(datetime(2026, 12, 31, 15, tzinfo=UTC)) == [
        "지금: 1월 1일(금) 새벽 0시",  # 서울은 벌써 새해
        "올해: 2027년",
    ]


def test_deferred_line_only_when_a_nudge_was_put_off():
    """QA r6 c1 M10: 밤 규칙 줄을 늘 넣으면 비서가 '밤 알림은 아침에 가요'를 붙였는데 종 · 대화 줄은 밤에도 바로 갔다.
    실제로 미룬 알림이 있을 때만 수 · 보낼 때를 넣는다(오늘이 아니면 날짜도)."""
    line = assistant_service.deferred_line
    now = datetime(2026, 11, 21, 17, 5, tzinfo=UTC)  # 서울 11-22(일) 02:05
    assert line(0, None, now) is None
    assert (
        line(2, datetime(2026, 11, 22, 0, tzinfo=UTC), now)
        == "알림: 미룬 알림 2개는 아침 9시에 가요"
    )
    late = datetime(2026, 11, 21, 13, tzinfo=UTC)  # 서울 11-21(토) 22:00 → 다음 날 아침
    assert line(1, datetime(2026, 11, 22, 0, tzinfo=UTC), late) == (
        "알림: 미룬 알림 1개는 11월 22일(일) 아침 9시에 가요"
    )


def test_turn_facts_have_now_lines_and_no_name_for_customer_and_vendor(api, script):
    from tests.test_v4_assistant_nudges import add_nudge

    pid = home(api, "jieun@mitjip.test", name="김지은")
    log = script([{"text": "지금은 새벽이 아니어도 바로 볼 수 있어요."}])
    ok(ask(api, pid, "안녕, 너 뭐 해 줄 수 있어?"))
    facts = log[0]["messages"][-1]
    assert facts["role"] == "system"
    assert facts["content"].startswith("지금: ") and "\n올해: 20" in facts["content"]
    assert "\n알림:" not in facts["content"]  # 미룬 알림이 없으면 알림 줄도 없다
    assert "오늘: 20" not in facts["content"] and "부를 이름" not in facts["content"]
    assert "김지은" not in json.dumps(log, ensure_ascii=False)  # 이름은 LLM에 보내지 않는다
    # 밤 · 하루 상한으로 미룬 줄(pending · night)이 있으면 수와 보낼 때를 넣는다
    (me,) = query("select owner_id from projects where id = $1", uuid.UUID(pid))
    due = datetime.now(UTC) + timedelta(hours=5)
    add_nudge(me["owner_id"], project_id=uuid.UUID(pid), reason="night", due_at=due)
    log = script([{"text": "네, 알려 드릴게요."}])
    ok(ask(api, pid, "알림은 언제 와요?"))
    assert "\n알림: 미룬 알림 1개는 " in log[0]["messages"][-1]["content"]
    api.cookies.clear()
    approved_vendor(api, "facts-vendor@mitjip.test")
    log = script([{"text": "오늘 할 일을 정리했어요."}])
    body = {"client_key": uuid.uuid4().hex, "text": "오늘 할 일 알려 주세요"}
    ok(api.post("/vendor/assistant/turns", json=body))
    facts = log[0]["messages"][-1]["content"]
    assert facts.startswith("지금: ") and "\n알림:" not in facts and "\n화면: 업체 비서" in facts


# ---- 3. v4 대화 숫자 검사 풀기(SentenceGate 길만) ----


def gate_said(text: str, allowed: str) -> str:
    """새 문장 검사(빈 지시문)에 allowed를 근거로 text를 흘려 보낸 글."""
    sent: list[str] = []

    async def emit(_name: str, data: dict) -> None:
        sent.append(data["text"])

    g = SentenceGate(emit, "너는 믿집 비서야.", allowed)

    async def go():
        await g.feed(text)
        await g.flush()
        await g.settle()

    asyncio.run(go())
    return "".join(sent).strip()


FACTS = (
    "지금: 11월 22일(일) 새벽 2시 5분\n"
    "올해: 2026년\n"
    "알림: 미룬 알림 1개는 아침 9시에 가요\n"
    "집: 서울 관악구 · 공급 105.8㎡ · 32평 · 빈 집 · 공사 시작 희망 12월 14일(월)"
)
TOOL = json.dumps(
    {
        "standard": {"total": 2952491},
        "grades": [{"grade": "basic", "total": 3016000}, {"grade": "economy", "total": 2474000}],
        "picks": [{"name": "솔빛도배", "won": 3120000}, {"name": "고운도배", "won": 3180000}],
        "windows": [{"start": "2026-12-07", "end": "2026-12-21"}],
        "pyeong": 32,
        "area_m2": 105.8,
    },
    ensure_ascii=False,
)
GROUND = f"{FACTS}\n{TOOL}"

KEEP = [
    "이 집 표준견적서는 약 300만 원이에요.",  # 2,952,491 → 더 둥근 수 · 1.6%
    "이 집 표준견적서는 300만 원 정도예요.",
    "실크는 300만 원대예요.",  # 3,016,000
    "가장 낮은 가견적은 310만 원대예요.",  # 3,120,000 ∈ [310만, 320만)
    "실크가 합지보다 약 54만 원 더 들어요.",  # 차액 542,000
    "실크가 합지보다 542,000원 더 들어요.",
    "두 곳 가견적 차이는 6만 원이에요.",  # 3,180,000 − 3,120,000
    "두 곳을 다 합치면 630만 원이에요.",  # 합 6,300,000
    "실크는 평당 94,250원이에요.",  # 3,016,000 ÷ 32평
    "실크는 평당 약 9.4만 원이에요.",
    "실크는 301만 6,000원이에요.",  # 금액 묶음 3,016,000
    "12월 14일에 시작하길 바라셨죠.",
    "12.14(월)에 시작하길 바라셨죠.",  # 소수 12.14가 아니라 날짜
    "12.14에 시작하길 바라셨죠.",  # 요일 없어도 근거 날짜면
    "12/7부터 볼 수 있어요.",
    "업체는 12.7~12.21 사이에 와요.",
    "12월 7일~21일 사이에 와요.",
    "지금은 새벽 2시라 업체는 아침 9시가 넘어서 볼 거예요.",
    "밤 9시부터 아침 9시까지는 알림을 아침에 보내요.",
]

DROP = [
    "이 집 표준견적서는 300만 원이에요.",  # 어림 낱말 없음
    "예약하면 300만 원이에요.",  # '예약'의 약은 어림 낱말이 아님
    "이 집 표준견적서는 400만 원대예요.",  # 400만 ≤ V인 근거 없음
    "약 90만 원 차이예요.",  # 근거 금액 둘의 차액 어디와도 3% 밖
    "욕실은 보통 500만 원이에요.",  # 근거 없는 돈 숫자(다른 공정)
    "삼백만 원 정도예요.",  # 한글 금액
    "표준견적서보다 3% 비싸요.",  # 표준 대비 %
    "12.16(수)에 시작해요.",  # 근거에 없는 날짜
    "12.15에 시작해요.",  # 근거 날짜가 아니면 소수 12.15
    "공사는 8일 걸려요.",  # 기간은 근거 값 그대로
    "0시가 넘었어요.",  # 지금 줄은 새벽 2시
]


@pytest.mark.parametrize("text", KEEP)
def test_numbers_rebuilt_from_grounds_are_sent(text):
    assert gate_said(text, GROUND) == text


@pytest.mark.parametrize("text", DROP)
def test_numbers_without_grounds_are_dropped(text):
    assert gate_said(text, GROUND) == ""


@pytest.mark.parametrize(
    ("won", "kept"),
    [(2_913_000, True), (2_912_000, False), (3_088_000, True), (3_094_000, False)],
)
def test_round_number_within_three_percent_only(won, kept):
    """'약 300만 원': |300만 − V| ≤ 3% · V(V 하나만 근거)."""
    said = "이 집은 약 300만 원이에요."
    assert (gate_said(said, f"표준견적서 {won:,}원") == said) is kept


def test_band_and_per_pyeong_and_difference_edges():
    one = "표준견적서 2,952,491원"
    assert gate_said("200만 원대예요.", one) == "200만 원대예요."  # 200만 ≤ V < 300만
    assert gate_said("300만 원대예요.", one) == ""  # V < 300만
    assert gate_said("295만 원이에요.", one) == "295만 원이에요."  # 만 원 반올림(옛 검사)
    per = "표준견적서 3,016,000원 · 공급 32평"
    assert gate_said("평당 94,250원이에요.", per) == "평당 94,250원이에요."
    assert gate_said("평당 약 9.4만 원이에요.", per) == "평당 약 9.4만 원이에요."
    assert gate_said("평당 약 9만 원이에요.", per) == ""  # 94,250과 4.5% 차이
    assert gate_said("평당 9만 원이에요.", per) == ""  # 어림 낱말 없음
    two = "실크 3,016,000원 · 합지 2,474,000원"
    assert gate_said("차액은 약 54만 원이에요.", two) == "차액은 약 54만 원이에요."
    assert gate_said("차액은 약 50만 원이에요.", two) == ""  # 542,000과 7.7% 차이
    assert gate_said("둘을 합치면 549만 원이에요.", two) == "둘을 합치면 549만 원이에요."


def test_zero_and_nine_oclock_follow_the_now_line():
    zero = assistant_service.time_lines(datetime(2026, 11, 21, 15, 3, tzinfo=UTC))
    assert gate_said("0시가 넘었어요.", "\n".join(zero)) == "0시가 넘었어요."
    at = datetime(2026, 11, 21, 17, 5, tzinfo=UTC)
    two = "\n".join(assistant_service.time_lines(at))
    assert gate_said("0시가 넘었어요.", two) == ""
    # 아침 9시는 미룬 알림이 있을 때만 근거예요(QA r6 c1 M10: 늘 '밤 알림은 아침에 가요'를 붙임)
    assert gate_said("아침 9시에 알려 드릴게요.", two) == ""
    put_off = assistant_service.deferred_line(1, datetime(2026, 11, 22, 0, tzinfo=UTC), at)
    assert (
        gate_said("아침 9시에 알려 드릴게요.", f"{two}\n{put_off}") == "아침 9시에 알려 드릴게요."
    )


def test_v2_v3_answer_check_is_unchanged():
    """v2 · v3 답 파이프라인 안쪽 검사(guard.check)는 그대로: 어림 · 원대는 지나지 않는다."""
    from app.v2 import guard

    got = guard.check("약 300만 원이에요. 300만 원대예요.", "표준견적서 2,952,491원")
    assert got.text == "" and len(got.dropped) == 2


# ---- 4. 누출 검사는 규칙 절만(예시 절 · 그대로 말해 꼴 문장 · 성격 소개는 뺀다) ----


def leak_said(text: str, prompt: str) -> tuple[str, list[str]]:
    sent: list[str] = []

    async def emit(_name: str, data: dict) -> None:
        sent.append(data["text"])

    g = SentenceGate(emit, prompt, "")

    async def go():
        await g.feed(text)
        await g.flush()
        await g.settle()

    asyncio.run(go())
    return "".join(sent).strip(), g.dropped


def test_v3_memory_place_answer_is_no_longer_dropped_as_a_leak(monkeypatch):
    monkeypatch.setattr(settings, "assistant_prompt_set", "v3")
    said = "내 정보의 '비서가 기억한 것'에서 보고 지울 수 있어요."
    got, dropped = leak_said(said, prompts.system("customer"))  # 지시문 전체와 견주면(고치기 전)
    assert got == "" and dropped == ["지시문 누출"]
    assert leak_said(said, prompts.rules("customer"))[0] == said  # 규칙 절만과 견주면 보낸다
    rule = (
        "가견적은 업체가 확인한 단가에 믿집이 센 수량을 곱한 금액이고, 표준견적서는 공공 기준으로 믿집이 "
        "계산한 참고 금액이야."
    )
    # 규칙을 그대로 옮긴 문장은 그대로 버린다
    assert leak_said(rule, prompts.rules("customer")) == ("", ["지시문 누출"])


def test_v4_examples_and_persona_are_not_leaks_but_rules_are(monkeypatch):
    monkeypatch.setattr(settings, "assistant_prompt_set", "v4")
    rules = prompts.rules("customer")
    # 좋은 예시 · 성격 소개를 닮은 답(고침 3차 A1에서 예시를 두세 문장으로 줄여 지금 예시 글로 바꿈)
    for said in (
        "값을 먼저 보시려면 솔빛도배, 끝낸 공사가 많은 곳을 보시려면 고운도배가 잘 맞아요.",
        (
            "저는 업체 고르기부터 공사 끝까지 할 일을 먼저 챙기는 비서라, 정할 것은 승인 카드로 준비하고"
            " 견적서 · 공사 날짜가 오면 먼저 알려 드려요."
        ),
    ):
        assert leak_said(said, prompts.system("customer"))[1] == ["지시문 누출"]  # 고치기 전
        assert leak_said(said, rules)[0] == said
    rule = "하지 않은 일을 한 것처럼, 없는 카드를 있는 것처럼 말하지 마."
    assert leak_said(rule, rules) == ("", ["지시문 누출"])
    assert "좋은 예시" not in rules and "### 1." not in rules and "너는 믿집 비서야" not in rules
    assert "주말이 편하다고 하셨죠" not in rules and "\u0000" in rules  # 큰따옴표 말은 뺀다
    vendor = prompts.rules("vendor")
    assert "좋은 예시" not in vendor and "고정 선 여덟" in vendor


def test_markers_are_never_sent_and_old_prompts_keep_their_text(monkeypatch):
    for name in ("v3", "v4", "v5"):
        monkeypatch.setattr(settings, "assistant_prompt_set", name)
        for key in ("customer", "vendor", "nudge_write", "nudge_judge", "memory", "brief"):
            assert "<!--" not in prompts.text(key)
    # 표식 줄만 뺀 글이 모델에 가는 글이다(v3 · 업체 v4는 표식을 더했어도 모델 글이 그대로)
    folder = ROOT / "backend" / "app" / "assistant" / "prompts"
    for file in ("customer_v3", "vendor_v3", "vendor_v4", "customer_v4", "customer_v5"):
        raw = (folder / f"{file}.md").read_text(encoding="utf-8")
        assert "<!-- 규칙 -->" in raw
        kept = [ln for ln in raw.splitlines() if ln not in ("<!-- 규칙 -->", "<!-- 예시 -->")]
        assert prompts._model_text(file) == "\n".join(kept).strip()


# ---- 5. 지시문 판 고르기(ASSISTANT_PROMPT_SET) ----

NAMES = ("customer", "vendor", "nudge_write", "nudge_judge", "memory", "brief")


def test_prompt_set_picks_files_and_keeps_text_per_set(monkeypatch):
    # 기본 판은 v4(QA 3 · 4차로 확인, 리드 결정 11-22 오후)
    assert type(settings).model_fields["assistant_prompt_set"].default == "v4"
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "\nASSISTANT_PROMPT_SET=v4\n" in env
    monkeypatch.setattr(settings, "assistant_prompt_set", "v3")
    assert [prompts.version(n) for n in NAMES] == [
        "customer_v3", "vendor_v3", "nudge_write_v2", "nudge_judge_v1", "memory_v4", "brief_v2",
    ]  # fmt: skip
    v3 = prompts.system("customer")
    monkeypatch.setattr(settings, "assistant_prompt_set", "v4")
    assert [prompts.version(n) for n in NAMES] == [
        "customer_v4", "vendor_v4", "nudge_write_v3", "nudge_judge_v1", "memory_v4", "brief_v2",
    ]  # fmt: skip
    v4 = prompts.system("customer")
    assert "판: customer_v3" in v3 and "판: customer_v4" in v4
    # v5는 고객 지시문만 바뀐 판(11-25, 기본은 v4 그대로)
    monkeypatch.setattr(settings, "assistant_prompt_set", "v5")
    assert [prompts.version(n) for n in NAMES] == [
        "customer_v5", "vendor_v4", "nudge_write_v3", "nudge_judge_v1", "memory_v4", "brief_v2",
    ]  # fmt: skip
    assert "판: customer_v5" in prompts.system("customer")
    monkeypatch.setattr(settings, "assistant_prompt_set", "v3")
    assert prompts.system("customer") == v3  # 같은 판이면 같은 글(프롬프트 캐시 앞부분이 맞는다)


def test_each_set_sends_its_own_cached_system_prompt(api, script, monkeypatch):
    pid = home(api, "set@mitjip.test")
    sent = {}
    for name in ("v3", "v4", "v5"):
        monkeypatch.setattr(settings, "assistant_prompt_set", name)
        log = script([{"text": "도와드릴게요."}])
        ok(ask(api, pid, "안녕하세요"))
        (req,) = log
        system = req["system"]
        assert system[-1]["cache_control"] == {"type": "ephemeral"}
        assert "".join(b["text"] for b in system) == prompts.system("customer")
        sent[name] = req
    # 도구 앞부분은 같고 지시문부터 판마다 달라 캐시가 판마다 따로 맞는다
    assert sent["v3"]["tools"] == sent["v4"]["tools"] == sent["v5"]["tools"]
    assert sent["v5"]["system"] != sent["v4"]["system"]
    assert sent["v3"]["system"] != sent["v4"]["system"]


# ---- 6. 시간 제한으로 끊긴 호출의 장부(보수적 추정치) ----


class Said(BaseModel):
    text: str


def usage_rows():
    return query("select * from llm_usage order by created_at, id")


def cut(make, entered: asyncio.Event):
    """공급자 호출이 시작된 뒤(비용 상한 확인을 지나 entered) 부르는 쪽 시간 제한(asyncio.wait_for)으로 끊는다."""

    async def go():
        call = asyncio.ensure_future(make())
        await asyncio.wait_for(entered.wait(), 30)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(call, 0.01)

    return go


def test_haiku_call_cut_by_a_timeout_leaves_an_estimate(monkeypatch, script):
    script([])  # 대본 클라이언트를 쓴다(SDK 대신)
    uid = _user("cut@mitjip.test")
    entered = asyncio.Event()

    async def slow(self, **req):
        entered.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(llm._ScriptMessages, "create", slow)

    async def judge():  # 먼저 말 걸기 판정 · 문장(10초 제한)처럼
        with llm.call_ctx(uid, None, "nudge"):
            return await llm.claude_json("nudge", Said, "지시문", "사실 글", max_tokens=512)

    run_llm(monkeypatch, cut(judge, entered))
    (row,) = usage_rows()
    assert (row["purpose"], row["ok"], row["error"]) == ("nudge", False, llm.ESTIMATED)
    assert row["output_tokens"] == 512 and row["input_tokens"] > len("지시문사실 글")
    assert row["cost_micros"] > 0 and row["user_id"] == uid


def test_stream_cut_before_any_event_leaves_an_input_estimate(monkeypatch, script):
    script([{"text": "안 와요."}])
    uid = _user("cut-stream@mitjip.test")
    entered = asyncio.Event()

    async def slow(self):
        entered.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(llm._ScriptStream, "__aenter__", slow)

    async def turn():
        with llm.call_ctx(uid, None, "assistant"):
            return await llm.claude_stream("지시문", [{"role": "user", "content": "q"}])

    run_llm(monkeypatch, cut(turn, entered))
    (row,) = usage_rows()
    assert (row["error"], row["output_tokens"]) == (llm.ESTIMATED, 0)
    assert row["input_tokens"] > 0 and row["cost_micros"] > 0


# ---- 7. 화면이 스트림을 끊어도 남은 턴 일은 턴 자리에 세고, 저장하면 바로 놓는다 ----


def test_cut_stream_keeps_the_turn_slot_until_saved(api, monkeypatch):
    from sqlalchemy import select

    from app.auth.models import User
    from app.db import SessionLocal

    pid = home(api, "slot@mitjip.test")
    hold = asyncio.Event()
    seen: dict[str, int] = {}
    run_turn, suggest_for = runtime.run_turn, assistant_service.suggest_for

    async def held_run(ctx, emit):
        await hold.wait()
        return await run_turn(ctx, emit)

    async def spy_suggest(*a, **k):
        seen["after_save"] = guards.TURNS.used  # 저장 바로 뒤
        return await suggest_for(*a, **k)

    monkeypatch.setattr(runtime, "run_turn", held_run)
    monkeypatch.setattr(assistant_service, "suggest_for", spy_suggest)

    async def go():
        async with SessionLocal() as s:
            user = await s.scalar(select(User).where(User.email == "slot@mitjip.test"))
        ctx = await assistant_service.start_turn(
            user,
            surface="customer",
            client_key=uuid.uuid4().hex,
            text="오늘 뭐 하면 돼요?",
            project_id=uuid.UUID(pid),
        )
        body = assistant_service.stream(ctx)
        first = await body.__anext__()
        before = guards.TURNS.used
        await body.aclose()  # 화면이 끊었다(턴 일은 run_turn에서 기다리는 중)
        during = guards.TURNS.used
        hold.set()
        await asyncio.gather(*list(assistant_service._BACKGROUND))
        return first, before, during, guards.TURNS.used, ctx.turn_id

    first, before, during, after, turn_id = api.portal.call(go)
    assert "event: ack" in first
    assert during == before + 1  # 남은 일이 자리를 넘겨받았다
    assert seen["after_save"] == before and after == before  # 저장하자마자 놓았다
    assert turn_row(str(turn_id))["status"] == "done"


# ---- 8. 업체 브리핑 한 줄 · 사실의 날짜 꼴 ----


def test_vendor_brief_line_is_f2_and_its_facts_are_long_dates():
    data = SimpleNamespace(
        picked=None,
        fit=[],
        title="관악구 · 도배 실크",
        suggest=SimpleNamespace(start=date(2026, 12, 7), end=date(2026, 12, 21), open_count=5),
        due_at=datetime(2026, 11, 27, 9, tzinfo=UTC),
    )
    assert vendor_tools.brief_template(data) == (
        "12.7(월)~12.21(월)에 빈 반나절 5칸이 있어 답하기 좋아요."
    )
    facts = vendor_tools._brief_facts(data)
    assert (facts["suggest"]["start"], facts["suggest"]["end"]) == ("12월 7일(월)", "12월 21일(월)")
    assert facts["due"] == "11월 27일(금) 오후 6시"
    # 짧은 AI 문장 검사(옛 검사)가 월 · 일을 따로 본다: '12월 7일'이 지난다
    said = "12월 7일~12월 21일에 빈 반나절이 5칸 있어요."
    assert vendor_tools.sentence_ok(said, json.dumps(facts, ensure_ascii=False))


# ---- 9. QA r2 c5: 잠긴 뒤 시작 희망 · 예상 공정표 기간 · 열린 승인 카드가 다음 걸음 ----


def test_locked_home_leaves_the_start_wish_to_the_vendor():
    facts = ["서울 관악구", "공급 105.8㎡", "빈 집", "공사 시작 희망 아직 몰라요", "철거 안 함"]
    locked = {"facts": facts, "locked": True, "start_date": None}
    assert assistant_service.home_facts(locked) == [
        *facts[:3],
        "공사 시작 희망 안 정함(실측 요청 뒤라 업체와 정해요)",
        facts[4],
    ]
    # 잠기기 전(고칠 수 있음) · 희망일이 있으면 그대로
    assert assistant_service.home_facts({**locked, "locked": False}) == facts
    wish = [*facts[:3], "공사 시작 희망 12월 14일(월)"]
    got = {"facts": wish, "locked": True, "start_date": date(2026, 12, 14)}
    assert assistant_service.home_facts(got) == wish


def test_period_line_says_expected_until_dates_are_accepted():
    today = date(2026, 11, 22)
    p = SimpleNamespace(
        kind="expected", start=date(2026, 12, 7), end=date(2026, 12, 11), work_days=4
    )
    # 확정 · 예상 공정표 이름을 밝힌다(QA r3 c2: 확정 뒤에 '지금 예상 공정표 기준'이라고 답함)
    assert assistant_service.period_line(p, today) == (
        "공정표: 예상 공정표 · 예상 공사 12월 7일(월)~11일(금) · 일하는 날 4일"
        "(업체가 공사 날짜를 올리기 전 예상)"
    )
    p.kind = "final"
    assert assistant_service.period_line(p, today) == (
        "공정표: 확정 공정표 · 공사 12월 7일(월)~11일(금) · 일하는 날 4일(수락한 공사 날짜)"
    )
    assert assistant_service.period_line(None, today) is None


def test_turn_facts_carry_the_expected_period_until_it_goes_stale(api, script):
    from app.shared.clock import today_seoul

    pid = home(api, "plan-facts@mitjip.test")
    assert api.get(f"/projects/{pid}/plan").status_code == 200  # 예상 공정표를 만든다
    (plan,) = query(
        "select p.start_date, p.end_date, p.work_days, max(s.end_date) filter (where s.kind = 'work')"
        " as work_end from plans p join plan_steps s on s.plan_id = p.id where p.project_id = $1"
        " and p.kind = 'expected' group by p.id order by p.version desc limit 1",
        uuid.UUID(pid),
    )
    # 공사 기간은 업체 공사 끝날까지예요(공정표 화면 · 보드와 같은 값, 자연 건조 · 입주 청소 빼고, QA r6 화면 M8)
    assert plan["work_end"] < plan["end_date"]
    want = assistant_service.period_line(
        SimpleNamespace(
            kind="expected",
            start=plan["start_date"],
            end=plan["end_date"],
            work_days=plan["work_days"],
            work_end=plan["work_end"],
        ),
        today_seoul(),
    )
    log = script([{"text": "예상 공정표로 보면 그때예요."}])
    ok(ask(api, pid, "도배는 언제 해요?"))
    assert want in log[0]["messages"][-1]["content"]
    # 공사 정보가 바뀌어 예상 공정표가 낡으면 그 기간은 사실에 넣지 않는다(다시 만드는 건 화면 읽기)
    query("update projects set rev = rev + 1 where id = $1", uuid.UUID(pid))
    log = script([{"text": "알겠어요."}])
    ok(ask(api, pid, "도배는 언제 해요?"))
    assert "공정표:" not in log[0]["messages"][-1]["content"]


def test_open_visit_request_card_is_the_next_step_not_picking_vendors(api):
    from tests.test_v4_assistant_actions import acts
    from tests.test_v4_assistant_free import cards_of, two_vendors
    from tests.test_v4_assistant_turns import ask

    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    pid, _ = two_vendors(api)
    ev = ok(ask(api, pid, "업체 추천해 주세요"))
    (picks,) = cards_of(ev, "vendor_picks")
    choice = "visit_request:" + ",".join(p["ref"] for p in picks["data"]["picks"])
    ctx = {"card_id": "picks-dobae", "choice": choice}
    ev = ok(ask(api, pid, "이 두 곳에 요청할래요", context=ctx))
    assert [a for a in acts(ev) if a["status"] == "proposed"]
    steps = {"step-standard", "step-pick"}
    assert not steps & {x["id"] for x in ev[-1][1]["suggest"]}
    # 다음 턴에도(카드가 열려 있는 동안) 업체 고르기 · 실측 시간 제안을 되풀이하지 않는다
    ev = ok(ask(api, pid, "이제 뭐 하면 돼요?"))
    assert not steps & {x["id"] for x in ev[-1][1]["suggest"]}


# ---- 10. QA r2 c3: 도구 앞 영어 속말 · 먼저 말 걸기의 지금 단계 · 알림 목록은 누출이 아님 ----


@pytest.mark.parametrize(
    ("text", "out"),
    [
        ("Direct tasks not saved; make a card.", True),
        ("OK.", True),
        ("确认一下。", True),  # 한글이 없는 다른 글자도
        ("LED 조명은 도배가 끝난 뒤 달아요.", False),  # 제품 이름 · 단위가 섞인 한국어
        ("Z:IN 실크는 닦여요.", False),
        ("3.5m", False),  # 숫자 · 단위만
        ("12.15", False),
        ("~", False),
    ],
)
def test_foreign_sentence_table(text, out):
    assert runtime.foreign(text) is out


def test_gate_drops_a_foreign_monologue_and_keeps_korean_with_product_names():
    said, dropped = leak_said(
        "Direct tasks not saved; make a card. LED 조명은 도배가 끝난 뒤 달아요.",
        "너는 믿집 비서야.",
    )
    assert said == "LED 조명은 도배가 끝난 뒤 달아요." and dropped == ["한글 없는 외국어 글"]


def test_english_monologue_before_a_tool_is_not_sent_saved_or_kept(api, script):
    pid = home(api, "mono@mitjip.test")
    script(
        [
            {
                "text": "Direct tasks not saved; make a card.",
                "tool_calls": [{"id": "t1", "name": "get_home", "input": {}}],
            },
            {"text": "집 정보를 확인했어요. LED 조명은 도배가 끝난 뒤 달아요."},
        ]
    )
    ev = ok(ask(api, pid, "조명은 제가 직접 달래요"))
    text = "".join(d["text"] for e, d, _ in ev if e == "token")
    assert text == "집 정보를 확인했어요. LED 조명은 도배가 끝난 뒤 달아요."
    trace = json.loads(turn_row(ev[0][1]["turn_id"])["trace"])
    assert trace["dropped"] == ["한글 없는 외국어 글"]  # 까닭 종류만(글 없음)
    (saved,) = query("select text from chat_messages where role = 'assistant'")
    assert "Direct" not in saved["text"]


def test_v4_nudge_write_gets_the_step_and_todo(api, monkeypatch, script):
    from functools import partial

    f = proactive.Facts(
        "dates_proposed",
        "notify",
        "customer",
        hours_left=50,
        action_ready=True,
        decision=True,
        names={"vendor": "결도배", "trade": "도배", "area": "마포구"},
    )
    said = "결도배가 공사 날짜를 올렸어요. 날짜를 확인하고 수락 카드를 눌러 주세요."
    sent: dict[str, dict] = {}
    for name in ("v3", "v4"):
        monkeypatch.setattr(settings, "assistant_prompt_set", name)
        log = script([{"json": {"text": said}}])
        assert api.portal.call(partial(proactive.write, f, None)) == (said, "ai")
        sent[name] = json.loads(log[0]["messages"][0]["content"])
    assert (sent["v4"]["step"], sent["v4"]["todo"]) == proactive.STEPS["dates_proposed"]
    assert "업체 확정 끝" in sent["v4"]["step"]
    assert "step" not in sent["v3"] and "todo" not in sent["v3"]  # v2 판 문장 사실은 그대로
    assert "todo" in prompts.text("nudge_write")  # v4 판 지시문이 읽는 법을 안다
    # 업체 쪽은 틀만 쓴다(사실을 보내지 않음) · 판정(judge) 사실도 그대로
    assert "todo" not in proactive.write_facts(
        proactive.Facts("deal_confirmed", "feed", "vendor", names={"area": "마포구"})
    )
    assert "todo" not in f.public()


def test_v4_notify_list_in_the_rules_is_not_a_leak(monkeypatch):
    monkeypatch.setattr(settings, "assistant_prompt_set", "v4")
    rules = prompts.rules("customer")
    said = "업체 답 · 견적서 · 공사 날짜 · 추가 금액 · 공사 끝 · 공사 일주일 전 · 공사 전날에 먼저 알려 드려요."
    assert leak_said(said, rules)[0] == said
    assert "혼잣말" in rules and "저장하면 알려 드릴게요" not in rules  # 큰따옴표 예는 누출 기준 밖


# ---- 11. QA r2 c5: 첫 LLM 턴의 늦은 SDK import를 앱 시작 때 작업 스레드로 ----


def test_llm_sdk_warm_up_only_when_live(monkeypatch):
    import builtins

    real, seen = builtins.__import__, []

    def spy(name, *a, **k):
        if name in ("anthropic", "openai"):
            seen.append(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", spy)
    monkeypatch.setattr(settings, "llm_live", False)
    llm.warm()
    assert seen == []  # LLM이 꺼져 있으면 아무것도 안 부른다(시험 · 무료 모드)
    monkeypatch.setattr(settings, "llm_live", True)
    llm.warm()
    assert seen == ["anthropic", "openai"]
