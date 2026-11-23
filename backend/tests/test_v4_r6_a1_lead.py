"""v4 고침 갈래 FA1(QA r6 c1 · c2 · c3 · c4 · 화면 걷기): 지금 할 일 줄 · 먼저 말 건 줄 턴 사실 · 고르기 칩 · 다음에 물을
말 되풀이 · 반려동물 기억 · 두 업체 같은 반나절 · 다시 올린 견적서 글 · 리뷰 쓰는 곳 · 담은 업체 이름표 · 화면 요청의
직접 할 일 · 실측 날 전 견적서. 유료 호출 0회(Claude 대본 · 무료 모드)."""

import asyncio
import json
import re
import uuid
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free, memory, proactive
from app.assistant.memory import Item
from app.assistant.runtime import SentenceGate, recent_said
from app.assistant.tools import aftercare as aftercare_tools
from app.assistant.tools import cards
from app.shared.clock import now_utc, today_seoul
from tests.conftest import query
from tests.helpers import use
from tests.test_v3_visit_kit import add, answer, booked, customer, quiet, vendor, visit_of
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v4_assistant_actions import acts
from tests.test_v4_assistant_nudges import offered_nudge
from tests.test_v4_assistant_turns import ask, home, ok
from tests.test_vendor_quote import FULL, doc, url
from tests.test_visit_inbox import login


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


def facts_of(log, call: int = 0) -> str:
    """대본 log의 call번째 LLM 호출이 받은 턴 사실(마지막 system 줄)."""
    return log[call]["messages"][-1]["content"]


def result(log, call: int, block: int = 0) -> dict:
    return json.loads(log[call]["messages"][-1]["content"][block]["content"])


def cards_of(ev, kind: str) -> list[dict]:
    return [d for e, d, _ in ev if e == "card" and d["kind"] == kind]


# ---- 지금 할 일 줄: 정해진 실측 먼저 · 업체 이름(QA r6 c3 M6) ----


def overview(*vendors: tuple[str, str]) -> SimpleNamespace:
    step = SimpleNamespace(key="visit", state="now")
    return SimpleNamespace(
        phase="progress",
        trades=[SimpleNamespace(trade="dobae", steps=[step])],
        vendors=[SimpleNamespace(vendor_name=n, status=st) for n, st in vendors],
    )


def test_now_line_names_the_booked_visit_before_waiting_replies():
    o = overview(("마루와벽", "requested"), ("결도배", "booked"))
    assert free.now_of(o) == "지금은 결도배 실측과 실측 견적서를 기다리는 중이에요."
    o = overview(("마루와벽", "requested"), ("결도배", "booked"), ("한결도배", "offered"))
    assert free.now_of(o) == "지금은 한결도배 실측 시간을 고를 차례예요."  # 고객 차례가 먼저
    o = overview(("마루와벽", "requested"), ("결도배", "requested"), ("닫힌도배", "cancelled"))
    assert free.now_of(o) == "지금은 마루와벽 · 결도배 실측 기간 답을 기다리는 중이에요."


# ---- 되풀이로 빠진 다음 할 일 살리기(QA r6 c3 t19) ----


def gate_run(said_before: list[str], text: str, opened=(), turns=None) -> str:
    async def emit(name: str, data: dict) -> None:
        return None

    g = SentenceGate(emit, "너는 믿집 비서야.", "", said=said_before, turns=turns)
    g.opened |= set(opened)

    async def go():
        await g.feed(text)
        await g.flush()
        await g.settle()

    asyncio.run(go())
    return g.text


def test_chat_pointer_is_kept_when_it_is_the_only_next_step():
    chat = "견적서를 받으신 뒤 메뉴의 [채팅]에서 업체와 직접 이야기해 보세요."
    before = recent_said([{"role": "assistant", "content": f"흥정은 제가 못 해요. {chat}"}])
    text = f"송금은 제가 할 수 없어요. 아직 실측 견적서가 나오기 전이에요. {chat}"
    assert gate_run(before, text).endswith(chat)  # 다음 할 일이 이 문장뿐이라 남겨요
    # 다른 다음 할 일(묻는 말)이 있으면 되풀이는 빼요
    got = gate_run(before, f"송금은 제가 할 수 없어요. {chat} 실측은 언제가 편하세요?")
    assert chat not in got
    # 열린 승인 카드가 있으면 그 카드가 다음 걸음이라 되풀이는 빼요(QA r2 · r4 c5 재촉 되풀이)
    assert chat not in gate_run(before, text, opened={"visit_slot"})
    # 바로 앞 두 답에 다 있었으면(세 번째 연속) 빼요
    assert chat not in gate_run(before, text, turns=[before, before])


# ---- 먼저 말 건 줄을 턴 사실에(QA r6 c1 M11) ----


def test_proactive_line_after_the_last_customer_message_is_in_the_facts(api, script, monkeypatch):
    f, n = offered_nudge(api, monkeypatch)
    query(
        "update assistant_nudges set sent_at = now() - interval '1 minute' where id = $1", n["id"]
    )
    log = script([{"text": "카드를 확인해 주세요."}])
    ok(ask(api, f["pid"], "그거 알아서 해 줘요"))
    facts = facts_of(log)
    (line,) = [x for x in facts.splitlines() if x.startswith("먼저 말 건 줄")]
    assert "마루와벽이 실측 기간을 보냈어요" in line and "카드 실측 시간" in line
    assert "승인 기다림" in line  # 함께 단 승인 카드의 지금 상태
    # 고객이 말한 뒤에는 그 줄이 '마지막으로 말한 뒤'가 아니라 빠져요
    log = script([{"text": "네."}])
    ok(ask(api, f["pid"], "고마워요 하나 더요"))
    assert "먼저 말 건 줄" not in facts_of(log)


# ---- 물은 갈래를 고르기 칩으로(QA r6 c1 M12) ----


def test_offer_choices_shows_chips_and_rejects_numbers(api, script):
    _, pid = home(api)
    ok_args = {
        "title": "무엇부터 볼까요?",
        "options": [
            {"label": "견적 금액", "say": "견적 금액부터 볼래요"},
            {"label": "벽지", "say": "벽지부터 볼래요"},
        ],
    }
    log = script(
        [
            {"tool_calls": [{"id": "c", "name": "offer_choices", "input": ok_args}]},
            {"text": "견적 금액부터 볼까요, 벽지부터 볼까요?"},
        ]
    )
    ev = ok(ask(api, pid, "기다리는 동안 뭐 할 수 있어요?"))
    (card,) = cards_of(ev, "options")
    assert [o["say"] for o in card["data"]["options"]] == [
        "견적 금액부터 볼래요",
        "벽지부터 볼래요",
    ]
    assert result(log, 1)["count"] == 2
    bad = {
        **ok_args,
        "options": [{"label": "3백만 원", "say": "3백만 원으로"}, ok_args["options"][1]],
    }
    log = script(
        [
            {"tool_calls": [{"id": "c", "name": "offer_choices", "input": bad}]},
            {"text": "무엇부터 볼까요?"},
        ]
    )
    ev = ok(ask(api, pid, "뭐부터 봐요?"))
    assert not cards_of(ev, "options")
    err = log[1]["messages"][-1]["content"][0]
    assert err["is_error"] and "bad_input" in err["content"]


# ---- 다음에 물을 말: 열린 승인 카드 · 되풀이(QA r6 c2) ----


def suggest_ids(ev) -> list[str]:
    done = next(d for e, d, _ in ev if e == "done")
    return [x["id"] for x in done["suggest"]]


def test_step_suggestion_rests_after_three_turns_and_with_an_open_card(api, script):
    vendor(api, "maru@mitjip.test", "마루와벽")
    vendor(api, "gyeol@mitjip.test", "결도배")
    _, pid = customer(api)
    got = []
    for i in range(4):
        script([{"text": f"벽지는 바탕이 중요해요{'.' * (i + 1)}"}])
        got.append(suggest_ids(ok(ask(api, pid, f"실크벽지 관리는 어떻게 해요 {i}"))))
    assert [("step-standard" in x) for x in got] == [True, True, True, False]
    # 열린 승인 카드가 있으면 그 카드가 다음 걸음: 단계와 다른 카드(집 정보)여도, 이번 턴에 만든 카드여도 단계 제안을
    # 하지 않아요(QA r6 c2 T2)
    _, pid2 = home(api, "two@mitjip.test")
    script([{"text": "벽지는 바탕이 중요해요."}])
    assert "step-standard" in suggest_ids(ok(ask(api, pid2, "실크벽지 관리는 어떻게 해요")))
    fields = {"occupied": True, "rooms": 3}
    script(
        [
            {"tool_calls": [{"id": "p", "name": "propose_home_info", "input": {"fields": fields}}]},
            {"text": "카드를 확인해 주세요."},
        ]
    )
    ev = ok(ask(api, pid2, "사실 살면서 공사해요"))
    assert [x for x in acts(ev) if x["status"] == "proposed"]
    assert not [x for x in suggest_ids(ev) if x.startswith("step-")]


# ---- 반려동물 기억(QA r6 c3 M9) ----

RANT = "집에 오면 강아지가 벽지를 다 긁어 놔서 거실 벽이 너덜너덜하고 예산은 300만 원 안쪽이면 좋겠어요."


def test_pet_value_keeps_the_grounded_animal_and_reports_why():
    quote = "집에 오면 강아지가 벽지를 다 긁어 놔서"
    why: list[str] = []
    got = memory.validate([Item(key="pet", value="강아지 키움", evidence_quote=quote)], RANT, why)
    assert [(x.key, x.value) for x in got] == [("pet", "강아지")] and why == []
    # 뜻을 뒤집는 말이 있으면 남기지 않아요
    msg = "강아지는 안 키워요."
    got = memory.validate([Item(key="pet", value="강아지 없음", evidence_quote=msg)], msg, why)
    assert got == [] and why == ["pet:value_outside"]
    # 다른 칸은 그대로(인용 밖 낱말이 있으면 빼요) · 까닭 코드만 남아요(값 · 글 없음)
    why = []
    item = Item(key="living", value="살면서 공사", evidence_quote="강아지가 벽지를 다 긁어 놔서")
    assert memory.validate([item], RANT, why) == [] and why == ["living:value_outside"]


# ---- 두 업체 같은 반나절(QA r6 c4 1) ----


def two_offered(api) -> tuple[str, str, dict[str, str]]:
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    token, pid = customer(api)
    for vid in (a, b):
        assert add(api, pid, vid).status_code == 201
    assert ask_visits(api, pid, [a, b]).status_code == 201
    visits = {"마루와벽": visit_of(pid, a), "결도배": visit_of(pid, b)}
    for email, name in (("maru@mitjip.test", "마루와벽"), ("gyeol@mitjip.test", "결도배")):
        login(api, email)
        assert answer(api, visits[name], instant=False).status_code == 200
    use(api, token)
    return token, pid, visits


def slots_call(ref: str) -> dict:
    return {
        "id": f"s-{ref}",
        "name": "vendor_free_slots",
        "input": {"ref": ref, "prefer": "any", "days": "weekend"},
    }


def test_two_vendors_never_get_the_same_half_day(api, script, monkeypatch):
    quiet(monkeypatch)
    _, pid, _visits = two_offered(api)
    log = script([{"text": "두 업체가 기간을 보냈어요."}])
    ok(ask(api, pid, "실측 어떻게 돼요?"))
    refs = dict(re.findall(r"(마루와벽|결도배)\((m\d+)\)", facts_of(log)))
    log = script(
        [
            {"tool_calls": [slots_call(refs["마루와벽"]), slots_call(refs["결도배"])]},
            {"text": "후보를 골라 왔어요."},
        ]
    )
    ok(ask(api, pid, "둘 다 토요일로 잡아 주세요"))
    a, b = result(log, 1, 0), result(log, 1, 1)
    first = a["candidates"][0]
    same = next(
        c for c in b["candidates"] if (c["day"], c["half"]) == (first["day"], first["half"])
    )
    # 마루와벽 카드를 만들면 결도배 후보에서 그 반나절이 빠지고, 그 반나절로는 결도배 카드를 만들지 않아요
    script(
        [
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_visit_slot", "input": {"slot_ref": first["ref"]}}
                ]
            },
            {"text": "카드를 확인해 주세요."},
        ]
    )
    assert [x for x in acts(ok(ask(api, pid, "마루와벽은 그걸로"))) if x["status"] == "proposed"]
    log = script(
        [
            {
                "tool_calls": [
                    {"id": "q", "name": "propose_visit_slot", "input": {"slot_ref": same["ref"]}},
                    slots_call(refs["결도배"]),
                ]
            },
            {"text": "다른 반나절로 볼게요."},
        ]
    )
    ok(ask(api, pid, "결도배도 같은 시간으로"))
    err = log[1]["messages"][-1]["content"][0]
    assert err["is_error"] and "slot_clash" in err["content"]
    again = result(log, 1, 1)
    assert (first["day"], first["half"]) not in {(c["day"], c["half"]) for c in again["candidates"]}
    assert cards.SLOT_SPLIT in again["note"]


# ---- 다시 올린 견적서 글(QA r6 c4 2) ----


def test_resent_quote_line_says_the_version_and_what_changed():
    prev = SimpleNamespace(total=3_300_000, days=3)
    last = SimpleNamespace(total=3_080_000, days=2)
    assert proactive.quote_change(prev, last) == "220,000원 내려감 · 3일 → 2일"
    assert proactive.quote_change(last, last) is None
    f = proactive.Facts("quote_sent", "feed", "customer")
    f.names.update({"vendor": "결도배", "version": "2", "change": "220,000원 내려감 · 3일 → 2일"})
    text = proactive.template(f)
    assert (
        text
        == "결도배가 견적서를 2판으로 다시 올렸어요(220,000원 내려감 · 3일 → 2일). 견줘 볼까요?"
    )
    assert proactive.kept_facts(text, f) and not proactive.kept_facts("결도배 견적서가 왔어요.", f)


# ---- 리뷰 쓰는 곳(QA r6 c4 4) ----


def test_review_card_links_the_review_page_only_when_it_is_open():
    pid = uuid.uuid4()
    card = aftercare_tools.review_card(pid, [SimpleNamespace(review_open=True)])
    assert card is not None and card.kind == "answer"
    (link,) = card.data["links"]
    assert link == {"label": "리뷰 쓰기", "href": f"/projects/{pid}/review"}
    assert aftercare_tools.review_card(pid, [SimpleNamespace(review_open=False)]) is None
    from app.assistant import policy

    assert policy.buttons_of("answer", card.data) == {
        "link"
    }  # '[리뷰 쓰기]를 눌러 주세요'가 맞아요


# ---- 담은 업체 이름표 · 화면 요청의 직접 할 일(QA r6 화면 H3 · M2) ----


def test_shortlisted_vendor_gets_a_ref_and_a_request_card(api, script, monkeypatch):
    quiet(monkeypatch)
    vid = vendor(api, "qa@mitjip.test", "QA벽지공방")
    for i in range(3):  # 점수 높은 다른 업체 셋(추천 3곳에는 안 들 수 있어요)
        vendor(api, f"o{i}@mitjip.test", f"다른도배{i}")
    _, pid = customer(api)
    assert add(api, pid, vid).status_code == 201
    log = script([{"text": "확인했어요."}])
    ok(ask(api, pid, "담아 둔 업체 있어요"))
    m = re.search(r"담은 업체[^\n]*QA벽지공방\((v\d+)\)", facts_of(log))
    assert m is not None, facts_of(log)
    req = {"trade": "dobae", "vendor_refs": [m.group(1)]}
    script(
        [
            {"tool_calls": [{"id": "p", "name": "propose_visit_request", "input": req}]},
            {"text": "카드를 확인해 주세요."},
        ]
    )
    (card,) = [
        x for x in acts(ok(ask(api, pid, "QA벽지공방에 요청해 줘"))) if x["status"] == "proposed"
    ]
    assert "QA벽지공방" in card["summary"]["title"]


def test_screen_request_sends_the_saved_diy_to_the_vendor(api, monkeypatch):
    quiet(monkeypatch)
    vid = vendor(api, "maru@mitjip.test", "마루와벽")
    _, pid = customer(api)
    assert api.put(f"/projects/{pid}/diy", json={"diy": ["paper_buy", "paint"]}).status_code == 200
    assert add(api, pid, vid).status_code == 201
    assert ask_visits(api, pid, [vid]).status_code == 201
    (row,) = query("select diy from visits where project_id = $1", uuid.UUID(pid))
    assert sorted(row["diy"]) == ["paint", "paper_buy"]


# ---- 실측 날 전 견적서(QA r6 c3 · 화면 M1) ----


def test_quote_cannot_be_sent_before_the_booked_visit_day(api, monkeypatch):
    quiet(monkeypatch)
    f = booked(api)  # 오늘 + 6일 오전 실측 확정
    login(api, f["email"])
    body = {**FULL, "measured_on": None, "file_ids": [doc(api)]}
    assert api.put(url(f["visit"]), json=body).status_code == 200  # 임시 저장은 돼요
    r = api.post(f"{url(f['visit'])}/send")
    assert r.status_code == 409 and r.json()["error"]["code"] == "before_visit", r.text
    day = today_seoul()
    query("update visits set booked_day = $1 where id = $2", day, uuid.UUID(f["visit"]))
    r = api.post(f"{url(f['visit'])}/send")  # 실측 날 당일부터는 보내져요
    assert r.status_code == 200, r.text


# ---- 첫 말이 이모지만일 때 이끌 카드(QA r6 c3) ----


def test_emoji_only_first_message_gets_the_today_card(api, script):
    _, pid = home(api)
    script([{"text": "견적이나 공사 준비 중 무엇이 궁금하세요?"}])
    assert cards_of(ok(ask(api, pid, "🏠🔨🤯❓")), "today")
    script([{"text": "무엇이 궁금하세요?"}])
    assert not cards_of(ok(ask(api, pid, "🏠")), "today")  # 첫 답 뒤에는 모델이 정해요


# ---- 끝난 일의 종 알림(QA r6 c1 #11) ----


def bell(pid: str) -> dict[str, bool]:
    """그 공사 고객 종 알림: 글 → 읽음"""
    rows = query(
        "select n.body, n.read_at from notifications n join projects p on p.owner_id = n.user_id"
        " where p.id = $1 and n.project_id = $1",
        uuid.UUID(pid),
    )
    return {r["body"]: r["read_at"] is not None for r in rows}


def test_sweep_reads_the_bell_news_of_finished_work_only(api, monkeypatch):
    quiet(monkeypatch)
    f = booked(api)  # 고객 종: '기간을 보냈어요' · '실측이 … 정해졌어요'
    pid = f["pid"]
    assert asyncio.run(proactive.settle_news(now_utc())) == 0  # 진행 중인 요청의 소식은 그대로
    news = bell(pid)
    assert any("정해졌어요" in b for b in news) and not any(news.values())
    r = api.post(f"/projects/{pid}/visits/{f['visit']}/cancel", json={"code": "changed"})
    assert r.status_code == 200, r.text
    assert asyncio.run(proactive.settle_news(now_utc())) >= 1
    news = bell(pid)
    assert all(read for b, read in news.items() if "정해졌어요" in b)  # 취소한 요청의 소식은 읽음
    vendor_unread = query(
        "select count(*) as n from notifications n join users u on u.id = n.user_id"
        " where u.email = 'maru@mitjip.test' and n.read_at is null"
    )[0]["n"]
    assert vendor_unread >= 1  # 업체 종('취소했어요')은 건드리지 않아요


# ---- '말한 요일이에요'는 이름으로 말한 요일만(QA r6 c3 t12 · FA2 넘김) ----


def test_said_day_reason_only_for_the_weekday_the_customer_named():
    from datetime import date

    sat, sun = date(2026, 11, 28), date(2026, 11, 29)
    named = cards.said_weekdays("결도배 실측 토요일 오전으로 해 주세요")
    assert named == {5}
    assert cards.day_why(("prefer_half", "prefer_day"), sat, named) == ["prefer_half", "prefer_day"]
    assert cards.why_words(cards.day_why(("prefer_day", "earliest"), sun, named)) == [
        "주말이에요",
        "가장 빠른 날이에요",
    ]
    # 요일 이름이 없으면 주말 · 평일 사실로, 안 되는 때로 말한 요일은 세지 않아요
    assert cards.said_weekdays("주말이 편해요") == frozenset()
    assert cards.said_weekdays("토요일이나 일요일은 안 돼요") == frozenset()
    assert cards.said_weekdays("토욜 오전이 좋아요") == {5}
