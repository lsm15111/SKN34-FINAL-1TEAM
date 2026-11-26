"""v3 입구 관문: 12공종 낱말 · 범위 밖 · 복합 · 기다림 · 버튼 · 되묻기 · 정책 표시 (LLM 없음)."""

import pytest

from app.agent.v3.gate import gate, parts_of
from app.agent.v3.policy import policy_of
from app.agent.v3.schemas import Button
from app.agent.v3.trades import BY_CODE, SPECS, chunk_trades, trades_in


@pytest.mark.parametrize(
    ("text", "trade"),
    [
        ("거실 바닥을 강마루로 바꾸려고요", "floor"),
        ("샷시 교체도 해 주나요?", "window"),
        ("누전차단기가 자꾸 툭툭 내려가요", "electric"),
        ("욕실 줄눈이 까맣게 됐어요", "tile"),  # 자리(욕실)보다 하는 일(타일)
        ("싱크대 문짝만 바꿔도 돼요?", "kitchen"),
        ("베란다 탄성코트도 해야 하나요?", "paint"),
        ("방문에 시트지 붙이면 오래 가요?", "film"),  # 물건(방문)보다 하는 일(필름)
        ("보일러 분배기를 바꿔야 할까요?", "plumbing"),
        ("철거하면 폐기물은 누가 치워요?", "demolition"),
        ("실크벽지가 들떴어요", "dobae"),
        ("몰딩을 바꾸고 싶어요", "mokgong"),
        ("포세린 타일이 뭐예요?", "tile"),
        ("필름 시공이 뭐예요?", "film"),
    ],
)
def test_trade_words_pick_first_trade(text, trade):
    assert trades_in(text)[0] == trade


def test_specs_are_12_trades_plus_common_with_two_deep():
    assert len(SPECS) == 13
    assert {s.code for s in SPECS if s.depth == "deep"} == {"dobae", "mokgong"}
    assert all(s.calc == (s.code in ("dobae", "mokgong")) for s in SPECS)
    for s in SPECS:
        for c in (*s.cautions, *s.survey, *s.prep):
            assert not any(ch.isdigit() for ch in c), c  # 정해 둔 글에 숫자 없음


def test_chunk_tags_map_to_v3_codes():
    assert chunk_trades(("바닥재", "공통")) == {"floor"}
    assert chunk_trades(("전체",)) == {"common"}
    assert chunk_trades(()) == {"common"}
    assert chunk_trades(("가구", "중문")) == {"kitchen", "window"}


def test_other_trade_is_answered_not_out_of_scope():
    g = gate("거실 바닥을 강마루로 바꾸려고요")
    assert g.route == "trade"
    assert g.trades[0] == "floor"


@pytest.mark.parametrize(
    "text",
    [
        "인테리어 비용을 대출로 마련하려는데 금리 낮은 상품을 골라 주세요.",
        "이사 업체는 어디가 친절하고 싼지 알려 주세요",
        "로또 번호 알려줘",
        "소송까지 가면 저 대신 대응해 주실 수 있나요?",
    ],
)
def test_service_tasks_are_out_of_scope(text):
    assert gate(text).route == "out_of_scope"


def test_price_calc_for_knowledge_trade_is_out_of_scope_but_deep_trade_is_not():
    assert gate("화장실 두 개 리모델링 견적 금액을 바로 뽑아 주세요.").route == "out_of_scope"
    assert gate("도배 견적 금액을 계산해 주세요").route != "out_of_scope"


def test_two_trades_in_two_parts_go_to_orchestrator():
    g = gate("몰딩을 바꾸려는데 뭘 봐야 해요? 그리고 욕실 줄눈은 어떻게 다시 해요?")
    assert g.route == "multi"
    assert g.trades[:2] == ["mokgong", "bath"]


def test_parts_split_on_questions_and_connectors():
    assert parts_of("도배는 어때요? 그리고 바닥은요?") == ["도배는 어때요?", "바닥은요?"]
    assert len(parts_of("가? 나? 다? 라?")) == 3  # 최대 3조각


def test_button_skips_classifier():
    g = gate("아무 말", button=Button(route="schedule"))
    assert (g.route, g.source, g.confidence) == ("schedule", "button", 1.0)


def test_waiting_agent_keeps_short_answer():
    g = gate("세 놓을 집이에요", waiting="trade")
    assert (g.route, g.source) == ("trade", "waiting")


def test_quote_and_schedule_need_a_project():
    q = "표준견적서에서 철거 줄은 왜 합계에 없어요?"
    assert gate(q).route == "guide"
    assert gate(q, has_project=True).route == "quote_explanation"


def test_knowledge_trade_quote_question_without_project_goes_to_trade():
    # 계산 엔진이 없는 공종의 일반 견적 질문은 그 공종 담당이 지식으로 답한다(바닥 평가 f26 · f27)
    for q in (
        "같은 평수인데 업체마다 마루 견적이 왜 이렇게 달라요?",
        "장판 견적서를 받았는데 뭐가 빠졌는지 어떻게 봐요?",
    ):
        g = gate(q)
        assert (g.route, g.trades[0]) == ("trade", "floor"), q
    assert (
        gate("도배 견적서 합계가 왜 이래요?").route == "guide"
    )  # 계산 엔진 공종 · 믿집 문서는 그대로


def test_floor_words_win_over_place_and_pet_words():
    assert gate("욕실 문 앞 마루가 물 먹어서 검게 변했어요").trades[0] == "floor"
    assert gate("욕실 바닥이 미끄러워요").trades[0] == "bath"  # 그냥 '바닥'은 자리 공종
    assert gate("거실이랑 방 사이 문턱을 없애도 괜찮아요?").trades == ["floor"]
    g = gate("강아지 발톱에 마루가 자꾸 긁히는데 어떻게 관리해요?")
    assert (g.route, g.trades) == ("trade", ["floor"])
    assert gate("강아지 키워도 돼요?").route == "out_of_scope"


def test_low_confidence_asks_back_with_two_or_three_buttons():
    g = gate("음")
    assert g.route == "ask_back"
    assert 2 <= len(g.candidates) <= 3
    assert all(c.route for c in g.candidates)


def test_vendor_name_is_not_read_as_trade_word():
    g = gate("마루와벽은 왜 더 비싸요?", has_project=True, ignore=["마루와벽"])
    assert "floor" not in g.trades


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("도배 평당 얼마예요?", "price"),
        ("샤워수전은 어느 회사 제품이 튼튼해요?", "brand_reco"),
        ("이음매가 보이는데 이 정도면 하자인가요?", "defect_judgement"),
        ("셀프로 콘센트를 바꿔도 돼요?", "diy"),
        ("우리 집 욕실은 덧방으로 해도 되는 상태인지 봐 주세요", "my_house"),
        ("철거 며칠 걸려요?", "period"),
    ],
)
def test_policy_flags(text, flag):
    assert flag in policy_of(text)


@pytest.mark.parametrize(
    "text",
    [
        "도배 기술은 어디서 배울 수 있어요?",
        "에어컨 청소 업체는 어떻게 골라요?",  # 공종 낱말(에어컨)이 있어도 가전 청소는 범위 밖
        "세탁기 들일 때 중문 떼는 건 무료로 해 줘요?",
        "거실에 큰 TV랑 프로젝터 중에 뭘 두는 게 나아요?",
        "집값 언제 오를까요?",
    ],
)
def test_learning_appliance_and_house_price_are_out_of_scope(text):
    assert gate(text).route == "out_of_scope"


def test_house_price_with_trade_words_is_a_construction_question():
    g = gate("집값이 싼 집인데 도배 장판만 할까요?")
    assert g.route != "out_of_scope"
    assert {"dobae", "floor"} <= set(g.trades)


def test_leak_liability_insurance_stays_in_scope():
    # 설비 카드(plumbing.contract.liability-insurance)가 답하는 질문이라 범위 밖으로 막지 않는다
    assert gate("누수 피해를 일상배상책임 보험으로 처리할 수 있어요?").route != "out_of_scope"


@pytest.mark.parametrize(
    "text",
    ["방 불만 켜면 두꺼비집이 내려가요", "멀티탭에서 지직 소리가 나요", "형광등을 LED로 바꿀까요?"],
)
def test_breaker_and_power_strip_are_electric_not_out_of_scope(text):
    g = gate(text)
    assert g.route == "trade"
    assert g.trades[0] == "electric"


def test_opening_windows_is_not_window_work():
    assert "window" not in trades_in("도배하고 창문은 언제부터 열어도 돼요?")
    assert "window" not in trades_in("칠하고 창문 열고 환기해도 돼요?")
    assert trades_in("창문 교체하면 도배도 다시 해요?")[0] == "window"


@pytest.mark.parametrize(
    "text",
    [
        "공사 동의서는 집주인이 받으러 다녀요, 업체가 받아요?",
        "앞집 공사팀이 복도에서 톱질하는데 원래 그래도 돼요?",
        "잔금 치르기 전에 빈집에 들어가 치수를 재도 돼요?",
    ],
)
def test_common_topics_go_to_guide_not_generic_menu(text):
    assert gate(text).route == "guide"


def test_every_trade_name_hits_its_own_words():
    for s in SPECS:
        if s.code != "common":
            assert trades_in(s.ko.split(" · ")[0])[:1] == [s.code], s.code
    assert BY_CODE["electric"].risky_diy and BY_CODE["plumbing"].risky_diy


def test_extra_cost_dispute_is_not_a_price_question():
    from app.agent.v3 import policy

    assert "price" not in policy.policy_of(
        "공사 중에 바닥 상태가 나쁘다고 추가 비용을 달라는데 줘야 해요?"
    )
    assert "price" in policy.policy_of("추가 비용이 얼마나 나와요?")
    assert "price" in policy.policy_of("강마루 시공 비용 알려 주세요")
