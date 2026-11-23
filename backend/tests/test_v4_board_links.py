"""보드 칸을 누르면 여는 자세히(2026-11-23 사용자): 낼 금액은 표준견적서(확정 뒤 실측 견적서), 업체 줄은 그 업체 내역.
업체 금액 범위에는 무엇의 범위인지(가견적 · 실측 견적서) 이름을 달아요. 주소는 대화 안 카드 자리 경로예요."""

from tests.helpers import use
from tests.test_deal import confirm, setup
from tests.test_v3_visit_kit import requested
from tests.test_v4_assistant_more import two_requested
from tests.test_v4_assistant_turns import home


def board(api, pid: str) -> dict:
    r = api.get("/assistant/board", params={"project_id": pid})
    assert r.status_code == 200, r.text
    return r.json()


def test_money_opens_the_standard_quote_before_any_vendor(api):
    _, pid = home(api)
    m = board(api, pid)["money"]
    assert m["href"] == f"/projects/{pid}/standard"
    assert (m["range"], m["range_label"], m["range_href"]) == (None, None, None)


def test_requested_rows_open_their_visit_and_range_names_the_fixed_estimates(api):
    pid, visits = two_requested(api)
    b = board(api, pid)
    assert {r["href"] for r in b["vendors"]["rows"]} == {
        f"/projects/{pid}/visits/{v}" for v in visits
    }
    m = b["money"]
    # 범위는 요청 때 고정한 가견적이에요. 그 값을 모아 보이는 화면이 없어 범위는 누르지 않아요(금액은 표준견적서)
    assert m["href"] == f"/projects/{pid}/standard"
    assert (m["range_label"], m["range_href"]) == ("가견적", None)


def test_quotes_range_opens_the_compare_then_deal_money_opens_quotes(api):
    customer, pid, va, _vb, vc = setup(api)  # 마루와벽 · 결도배 견적서 옴, 한결인테리어 답 기다림
    b = board(api, pid)
    rows = {r["name"]: r["href"] for r in b["vendors"]["rows"]}
    assert rows["마루와벽"] == rows["결도배"] == f"/projects/{pid}/quotes"
    assert rows["한결인테리어"] == f"/projects/{pid}/visits/{vc}"
    m = b["money"]
    assert m["href"] == f"/projects/{pid}/standard"
    assert m["range_label"] in ("실측 견적서", "가견적 · 실측 견적서")
    assert m["range_href"] == f"/projects/{pid}/quotes"

    assert confirm(api, pid, va).status_code == 200
    use(api, customer)
    b = board(api, pid)
    m = b["money"]
    assert m["label"].startswith("확정 금액") and m["href"] == f"/projects/{pid}/quotes"
    assert m["range"] is None and m["range_href"] is None
    rows = {r["name"]: r["href"] for r in b["vendors"]["rows"]}
    # 확정한 업체는 공사(날짜 · 추가 금액 · 끝 확인), 고르지 않은 견적서도 견적서 비교에서 봐요
    assert rows["마루와벽"] == f"/projects/{pid}/schedule"
    assert rows["결도배"] == f"/projects/{pid}/quotes"


def test_cancelled_request_opens_the_vendor_detail(api):
    f = requested(api)
    r = api.post(f"/projects/{f['pid']}/visits/{f['visit']}/cancel", json={"code": "changed"})
    assert r.status_code == 200, r.text
    (row,) = board(api, f["pid"])["vendors"]["rows"]
    assert row["href"] == f"/projects/{f['pid']}/vendors/{f['vendor']}"
