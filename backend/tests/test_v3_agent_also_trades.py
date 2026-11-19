"""v3 공종 담당: 관문이 함께 고른 공종(trades[1:])의 카드도 찾는다. 다른 공종은 여전히 거른다. DB · 유료 호출 없음."""

import time
import uuid
from datetime import date

from v3_kb import repo_kb

from app.agent.v3 import trade_agent
from app.agent.v3.answer import Task
from app.agent.v3.schemas import TurnContext

KB = repo_kb()
CTX = TurnContext(user_id=uuid.uuid4(), today=date(2026, 11, 19))
PAINTED = "card:dobae.method.painted-wall@"


def _run(text: str, trades: list[str]):
    task = Task(text=text, route="trade", trades=trades, policy=[], ctx=CTX)  # type: ignore[arg-type]
    return trade_agent.run(task, KB)


def test_v3_agent_card_from_trade_the_gate_also_picked():
    part = _run("페인트 칠한 벽 위에도 도배할 수 있나요?", ["paint", "dobae"])
    assert any(t.startswith(PAINTED) for t in part.used_cards)
    sec = next(s for s in part.sections if s.source == "card")
    assert sec.trade == "dobae" and sec.title == "[도배]"
    assert all(x.cites for x in sec.sentences)


def test_v3_agent_card_of_trade_the_gate_did_not_pick_stays_out():
    part = _run("페인트 칠한 벽 위에도 도배할 수 있나요?", ["paint"])
    assert not any(t.startswith(PAINTED) for t in part.used_cards)
    assert all(not t.startswith("card:dobae.") for t in part.used_cards)


def test_v3_agent_also_trades_keep_other_trades_filtered():
    # 필름 카드 열쇠('필름 들뜸은 왜 생겨요?')와 글자가 거의 같지만 관문이 고르지 않은 공종이다
    part = _run("벽지 들뜸은 왜 생겨요?", ["dobae"])
    assert all(not t.startswith("card:film.") for t in part.used_cards)


def test_v3_agent_also_trades_long_input_is_fast():
    text = ("페인트 칠한 벽 위에 도배 " * 400)[:5000]
    t0 = time.perf_counter()
    part = _run(text, ["paint", "dobae", "mokgong"])
    assert time.perf_counter() - t0 < 5
    assert part.sections or part.unknown
