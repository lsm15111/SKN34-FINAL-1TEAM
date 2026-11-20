"""대화 상태(맥락 L1, agent-context.md 3절): 이어 묻기 풀기 · 주제 바뀜 · 되묻기 칸 턴 · 범위 밖 턴.
무료 모드(LLM_LIVE=false), 유료 호출 0회, DB 없음."""

import asyncio
import uuid
from datetime import date

from v3_kb import repo_kb

from app.agent.v3 import context
from app.agent.v3.schemas import Button, TurnContext
from app.agent.v3.turn import run_turn

KB = repo_kb()
CTX = TurnContext(user_id=uuid.uuid4(), today=date(2026, 11, 20))


def st(**k) -> dict:
    return context.ChatState(turn=1, **k).model_dump()


def turn(text, *, state=None, waiting=None, button=None):
    return asyncio.run(run_turn(text, CTX, kb=KB, state=state, waiting=waiting, button=button))


def test_short_follow_up_takes_form_from_previous_turn():
    q, took = context.resolve(
        "합지는요?", context.ChatState(trades=["dobae"], form="price", q="실크 평당 얼마예요")
    )
    assert took and q == "합지는요 비용은 얼마예요"


def test_added_trade_joins_previous_trade_and_form():
    prev = context.ChatState(trades=["dobae"], form="period", q="도배 며칠 걸려요")
    q, took = context.resolve("목공도 같이 하면요?", prev)
    # '랑'으로 이어야 관문이 두 공종 질문(multi)으로 읽어요
    assert took and q == "도배랑 목공도 같이 하면요 기간은 며칠 걸려요"
    both = context.ChatState(trades=["dobae", "mokgong"], form="price", q="도배 목공 얼마예요")
    assert context.resolve("그럼 할인은요?", both)[0].startswith("도배랑 목공 그럼 할인은요")


def test_new_topic_or_own_form_is_not_inherited():
    prev = context.ChatState(trades=["dobae"], form="price", q="실크 평당 얼마예요")
    assert context.resolve("욕실 타일 줄눈은 뭐예요?", prev) == ("욕실 타일 줄눈은 뭐예요?", False)
    q, _ = context.resolve("그럼 셀프로 해도 돼요?", prev)
    assert "얼마" not in q  # 제 꼴(예 · 아니요)이 있으면 꼴은 물려받지 않아요
    assert context.resolve("합지는요?", None) == ("합지는요?", False)  # 첫 턴


def test_follow_up_turn_answers_with_inherited_price_policy():
    r = turn("합지는요?", state=st(trades=["dobae"], form="price", q="실크벽지 평당 얼마예요"))
    t = r.answer.trace
    assert t.inherited and "price" in t.policy and "dobae" in t.trades
    assert r.state and r.state["form"] == "price" and r.state["trades"] == ["dobae"]


def test_follow_up_adds_trade_and_keeps_period():
    r = turn("목공도 같이 하면요?", state=st(trades=["dobae"], form="period", q="도배 며칠 걸려요"))
    t = r.answer.trace
    assert t.inherited and "period" in t.policy and t.route == "multi"
    assert {"dobae", "mokgong"} <= set(t.trades) | set(
        t.parts
    )  # 공사 화면 답은 test_v3_ai_api에서 봐요


def test_first_turn_and_topic_change_do_not_inherit():
    assert not turn("합지는요?").answer.trace.inherited
    r = turn(
        "욕실 타일 줄눈은 뭐예요?", state=st(trades=["dobae"], form="price", q="실크 평당 얼마")
    )
    assert not r.answer.trace.inherited and r.state and "dobae" not in r.state["trades"]


def test_slot_answer_turn_keeps_state_and_reports_filled_value():
    first = turn("합지랑 실크 중에 뭐로 해야 해요?")
    assert first.state and first.state["trades"] == ["dobae"]
    r = turn(
        "세 놓을 집", state=first.state, waiting=first.waiting,
        button=Button(route="trade", trade="dobae", slot="dobae.grade", value="세 놓을 집"),
    )  # fmt: skip
    assert not r.answer.trace.inherited
    assert r.state and r.state["q"] == first.state["q"]  # 짧은 칸 답이 앞 질문 맥락을 지우지 않아요
    assert r.filled == ("dobae", "dobae.grade", "세 놓을 집")


def test_out_of_scope_turn_keeps_previous_state():
    prev = st(trades=["dobae"], form="price", q="실크 평당 얼마예요")
    r = turn("오늘 점심 뭐 먹을까요?", state=prev)
    assert r.answer.trace.route == "out_of_scope" and r.state == prev


def test_broken_saved_state_is_ignored():
    r = turn("합지는요?", state={"trades": "도배", "turn": "x"})
    assert not r.answer.trace.inherited
