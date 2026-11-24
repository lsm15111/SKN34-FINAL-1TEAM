"""판정 에이전트가 찾은 비서 문제(2026-11-23) 고침을 지키는 시험.

- F1 · S07: 승인 카드의 판(견적서 n판)이 모델 값 줄에도 간다.
- S10: 업체 체크리스트에 선택 · 실측 후 줄(퍼티 · 철거)도 올라간다.
- S08: 지시문이 '도구 없이 못 한다고 하지 않기' · same은 '만들었어요'가 아님을 말한다.
- S04: 집 정보 도구 설명이 기준을 말하지 않은 계약서 ㎡를 전용으로 카드에 넣고 기준을 밝혀 확인받게 한다.
"""

from app.assistant import prompts
from app.assistant.schemas import ActionSummary, SummaryRow
from app.assistant.tools import REGISTRY, propose
from app.assistant.tools import vendor as vendor_tools
from app.calc.common import COUNTED
from tests.test_v3_visit_kit import requested
from tests.test_visit_inbox import login


def test_summary_rows_carry_version_first():
    sm = ActionSummary(
        title="마루와벽으로 확정",
        amount_won=3650000,
        version="견적서 2판",
        rows=[SummaryRow(label="공사 기간", value="3일")],
        approve_label="마루와벽으로 확정",
    )
    rows = propose.summary_rows(sm)
    assert rows[0] == {"label": "판", "value": "견적서 2판"}
    assert rows[-1] == {"label": "금액", "won": 3650000}


def test_summary_rows_without_version_unchanged():
    sm = ActionSummary(title="t", rows=[SummaryRow(label="a", value="b")], approve_label="ok")
    assert propose.summary_rows(sm) == [{"label": "a", "value": "b"}]


def test_check_hint_covers_counted_optional_after_visit():
    assert set(COUNTED) <= set(vendor_tools.CHECK_HINT)
    assert {"optional", "after_visit"} <= set(vendor_tools.CHECK_HINT)
    assert "excluded" not in vendor_tools.CHECK_HINT and "bundled" not in vendor_tools.CHECK_HINT


def test_vendor_checklist_lists_optional_lines(api):
    """도배만 하는 빈 집: 퍼티 · 경비는 선택 줄이라 합계 밖이어도 체크리스트에 올라간다."""
    f = requested(api)
    login(api, f["email"])
    c = api.get(f"/vendor/assistant/checklists/{f['visit']}").json()
    keys = {x["key"] for x in c["items"]}
    hints = {x["hint"] for x in c["items"]}
    assert "putty" in keys
    assert vendor_tools.CHECK_HINT["optional"] in hints


def test_customer_prompt_retries_tool_before_refusing():
    text = prompts._model_text("customer_v4")
    assert "same에 '만들었어요'라고 하지 마" in text
    assert "도구를 부르지 않고 '다시 만들 수 없어요'" in text


def test_home_info_description_confirms_contract_area_basis():
    text = REGISTRY["propose_home_info"].description
    assert (
        "계약서 ㎡처럼 고객이 기준을 말하지 않은 ㎡는 보통 전용이라 exclusive로 카드를 만들고"
        in text
    )
    assert "공급면적이면 말해 주세요" in text
