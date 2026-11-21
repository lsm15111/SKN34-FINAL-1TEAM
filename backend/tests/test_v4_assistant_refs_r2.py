"""v4 비서 이름표 번호 고침 2차(QA r2 갈래 E1 · edge P3): Redis 이름표 표 · 번호 기록이 모두 지워져도 지난 카드
단추의 이름표가 다른 대상의 승인 카드를 만들지 않는다(번호는 DB에도 늘기만 하게 두고, 지워진 뒤 다시 쓴 번호는
버려 모르는 이름표 → 카드를 새로 불러옴). 유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

import uuid

import pytest
import redis
from v3_kb import repo_index

from app.agent import llm
from app.assistant.runtime import RefTable
from tests.conftest import REDIS_URL, query
from tests.test_deal import setup as deal_setup
from tests.test_v4_assistant_free import cards_of, said
from tests.test_v4_assistant_refs import RELOADED, col_ref, proposed, visit_of_action
from tests.test_v4_assistant_turns import ask, ok


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture(autouse=True)
def off():
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def wipe(chat_id: str) -> None:
    """Redis 이름표 표와 번호 기록을 모두 지운다(Redis 비우기 · 다른 곳이 같은 Redis 번호를 지움)."""
    redis.Redis.from_url(REDIS_URL).delete(
        f"assistant:refs:{chat_id}", f"assistant:refs:{chat_id}:num"
    )


def test_old_card_button_after_redis_wipe_makes_no_card_for_a_reissued_name(api):
    _token, pid, va, vb, _ = deal_setup(api)
    ev = ok(ask(api, pid, "견적서 비교해 줘"))
    chat = ev[0][1]["chat_id"]
    (old,) = cards_of(ev, "quote_compare")
    old_refs = {col_ref(old, va), col_ref(old, vb)}
    wipe(chat)
    ok(ask(api, pid, "견적서 비교해 줘"))  # 지운 뒤 새 표가 이름표를 다시 매긴다
    for ref in sorted(old_refs):
        press = {"card_id": old["card_id"], "choice": f"vendor_confirm:{ref}"}
        ev = ok(ask(api, pid, "이 업체로 확정할래요", context=press))
        assert proposed(ev) == [] and said(ev) == RELOADED  # 다른 업체 승인 카드를 만들지 않는다
    (new,) = cards_of(ev, "quote_compare")
    new_ref = col_ref(new, va)
    assert new_ref not in old_refs  # 지운 뒤에도 지난 카드의 번호를 다시 쓰지 않는다
    ev = ok(
        ask(
            api,
            pid,
            "이 업체로 확정할래요",
            context={"card_id": new["card_id"], "choice": f"vendor_confirm:{new_ref}"},
        )
    )
    (a,) = proposed(ev)
    assert visit_of_action(a) == va
    tops = {r["prefix"]: r["top"] for r in query("select prefix, top from assistant_ref_tops")}
    assert tops["m"] >= int(new_ref[1:])


def test_fresh_numbers_not_above_the_kept_top_are_dropped():
    t = RefTable(uuid.uuid4())
    ref = t.put("visit", {"id": "x"})  # 지워진 뒤 새로 매긴 번호(m1)
    items, meta = t.merged({}, {}, {"m": 3})
    assert ref not in items and ref in meta["dead"] and meta["top"]["m"] == 3
    # 다른 곳이 같은 번호를 같은 대상으로 이미 저장했으면 그대로 둔다
    items, _ = t.merged({ref: {"kind": "visit", "id": "x"}}, {}, {"m": 3})
    assert items[ref]["id"] == "x"
    # DB 번호보다 큰 새 번호는 그대로 쓴다
    t = RefTable(uuid.uuid4(), top={"m": 3})
    ref = t.put("visit", {"id": "y"})
    items, meta = t.merged({}, {}, {"m": 3})
    assert ref == "m4" and items[ref]["id"] == "y" and meta["top"]["m"] == 4
