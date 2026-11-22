"""갈래 C 반셀프 '벽지 직접 구매'(칩 paper_buy, 2026-11-22 리드 결정) · 금액 1원 이상 DB CHECK(0052, NOT VALID).

- 칩을 켜면 표준견적서 도배지 줄이 '안 함'(고객 구매)으로 합계에서 빠지고(계산 엔진 값 그대로) 새 판을 쌓아요.
  끄면 다시 넣은 새 판이에요. 롤 수(계산 엔진)와 가견적 안내 한 줄(틀)이 같이 와요.
- 업체 가견적은 벽지 값이 든 값이라 칩과 상관없이 같아요('시공만' 값은 뒤로). 표준 대비 %도 벽지까지 넣고 견줘요.
- 다른 칩처럼 공정표 '고객이 직접' 줄 · 실측 요청 '업체에 알릴 것' · 업체 브리핑에 들어가요.
유료 호출 0회(무료 모드)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import asyncpg
import pytest

from app.assistant import policy
from app.assistant.tools import cards as card_tools
from app.calc import dobae, rolls
from app.calc.common import COUNTED
from app.quote.service import OWN_PAPER_NOTE, standard_v3
from tests import test_extras as extras
from tests import test_vendor_quote as vendor_quote
from tests.conftest import query
from tests.helpers import signup
from tests.test_v3_project_home import HOME, create
from tests.test_v3_visit_kit import v2_totals
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_diy import as_owner, block, chips, plan
from tests.test_v4_assistant_free import cards_of, two_vendors
from tests.test_v4_assistant_turns import ask, ok
from tests.test_v4_qa_r2_calc import old_zero_quote
from tests.test_visit_inbox import login

D = Decimal
Check = asyncpg.exceptions.CheckViolationError


def _dobae(api, pid: str) -> dict:
    r = api.get(f"/projects/{pid}/standard")
    assert r.status_code == 200, r.text
    return next(t for t in r.json()["trades"] if t["trade"] == "dobae")


def _paper(t: dict) -> dict:
    return next(ln for ln in t["lines"] if ln["key"] == "paper")


def test_paper_buy_chip_takes_paper_out_of_the_standard_total(api):
    signup(api)
    pid = create(api, HOME).json()["id"]
    first = _dobae(api, pid)
    assert (first["version"], first["own_paper"], first["paper_note"]) == (1, False, None)
    assert _paper(first)["state"] == "included"
    # 벽지 직접 구매를 켜면 도배지 줄 '안 함'(고객 구매) · 합계에서 빠진 새 판
    assert chips(api, pid, ["paper_buy", "paint"]) == ["paint", "paper_buy"]
    on = _dobae(api, pid)
    paper = _paper(on)
    assert (on["version"], on["own_paper"], on["paper_note"]) == (2, True, OWN_PAPER_NOTE)
    assert paper["state"] == "excluded" and paper["source"].startswith("고객 구매 · ")
    assert paper["amount"] == _paper(first)["amount"]  # 금액은 참고로 남겨요
    # 숫자는 계산 엔진 그대로(같은 집 · 같은 판)
    q = standard_v3(dobae.HomeV3(D("69.4"), "supply", "basic", False), own_paper=True).quote
    assert (on["supply"], on["vat"], on["total"]) == (q.subtotal, q.vat, q.total)
    assert on["supply"] == sum(ln["amount"] for ln in on["lines"] if ln["state"] in COUNTED)
    assert on["supply"] == first["supply"] - paper["amount"]
    assert dobae.OWN_PAPER_ASSUMED in on["notes"]
    # 롤 수(계산 엔진, 보이기용): 실크 롤, 여분은 따로
    need = rolls.need("silk", paper_py=D(paper["qty"]))
    assert on["rolls"] == {
        "key": "silk",
        "name": "실크",
        "size": "106cm × 15.6m",
        "count": need.count,
        "spare_min": 1,
        "spare_max": 2,
        "text": need.text,
    }
    assert _dobae(api, pid)["version"] == 2  # 같은 칩이면 저장본 그대로

    # 비서 표준견적서 카드의 모델 값(허용 칸만 거친 값)에도 롤 수 · 고객 구매 · 가견적 안내가 남아요
    async def std(s, u):
        return (await card_tools.standard(s, u, uuid.UUID(pid)))[1]

    model = policy.to_model(as_owner(api, pid, std))
    # 고침 3차 K 3번: 벽지 줄 금액은 '공급가' 꼬리표, 부가세 포함 몫 · 벽지까지 맡길 때 합계는 계산 엔진 값으로 같이
    assert model["paper"] == {
        "count": need.count,
        "text": need.text,
        "state": "고객 구매(합계 밖)",
        "line": paper["name"],
        "공급가": paper["amount"],
        "rows": [
            {"label": card_tools.PAPER_OWN_ROWS[0], "won": first["total"] - on["total"]},
            {"label": card_tools.PAPER_OWN_ROWS[1], "won": first["total"]},
        ],
        "note": OWN_PAPER_NOTE,
    }
    assert all(ln["name"] != paper["name"] for ln in model["lines"])  # 합계 줄에는 없어요
    # 끄면 다시 벽지를 넣은 새 판(처음과 같은 합계)
    chips(api, pid, ["paint"])
    off = _dobae(api, pid)
    assert (off["version"], off["own_paper"], off["total"]) == (3, False, first["total"])
    rows = query(
        "select version, own_paper from standard_quotes where project_id = $1::uuid"
        " and trade = 'dobae' order by version",
        pid,
    )
    assert [(r["version"], r["own_paper"]) for r in rows] == [(1, False), (2, True), (3, False)]
    # 목공 판에는 고객 구매가 없어요(DB CHECK)
    with pytest.raises(Check):
        query("update standard_quotes set trade = 'mokgong' where own_paper")


def test_estimates_keep_the_paper_and_compare_with_paper(api):
    pid, vids = two_vendors(api)
    before = v2_totals(api, pid)
    r = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    cards = {c["vendor_id"]: c for c in r.json()["local"]}
    assert all(v is not None for v in before.values()) and len(cards) == 2
    chips(api, pid, ["paper_buy"])
    r = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    lst = r.json()
    # 가견적은 벽지 값이 든 값 그대로, 표준 대비 %도 벽지까지 넣은 표준견적서와 견줘요
    assert v2_totals(api, pid) == before
    after = {c["vendor_id"]: c for c in lst["local"]}
    for vid in vids:
        assert after[vid]["estimate_total"] == cards[vid]["estimate_total"]
        assert after[vid]["vs_standard_pct"] == cards[vid]["vs_standard_pct"]
    assert lst["paper_note"] == OWN_PAPER_NOTE
    assert lst["standard_total"] == _dobae(api, pid)["total"]  # 표준견적서는 고객 구매를 뺀 값
    # 비서 업체 고르기 카드에도 안내 한 줄(틀)
    ev = ok(ask(api, pid, "업체 추천해 주세요"))
    (picks,) = cards_of(ev, "vendor_picks")
    assert picks["data"]["basis"][-1] == OWN_PAPER_NOTE


def test_vendor_sees_paper_buy_in_the_request(api):
    pid, _ = two_vendors(api)
    chips(api, pid, ["paper_buy", "paint"])
    ev = ok(ask(api, pid, "업체 추천해 주세요"))
    (picks,) = cards_of(ev, "vendor_picks")
    ref = picks["data"]["picks"][0]["ref"]
    ev = ok(ask(api, pid, "여기에 요청할래요", context={"choice": f"visit_request:{ref}"}))
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    row = a["summary"]["rows"][-1]
    assert (row["label"], row["value"]) == (
        "업체에 알릴 것",
        "고객이 직접 해요 — 페인트(문틀 · 몰딩) · 벽지 직접 구매",
    )
    assert approve(api, a["action_id"]).json()["status"] == "executed"
    (v,) = query("select id, vendor_id, diy from visits")
    assert v["diy"] == ["paint", "paper_buy"]
    with pytest.raises(Check):  # 요청 사본도 칩 키만 받아요(DB CHECK)
        query("update visits set diy = '{floor}'")
    email = query("select email from users where id = $1", v["vendor_id"])[0]["email"]
    login(api, email)
    r = api.get(f"/vendor/assistant/briefs/{v['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["diy"] == ["페인트(문틀 · 몰딩)", "벽지 직접 구매"]


def test_plan_gets_a_paper_buy_row_until_the_day_before_dobae(api):
    pid, _ = two_vendors(api)
    chips(api, pid, ["paper_buy"])
    p = plan(api, pid)
    start = date.fromisoformat(block(p, "work", "dobae")["start"])
    (row,) = [b for b in p["blocks"] if b["kind"] == "diy"]
    assert row["label"] == "벽지 사서 받아 두기"
    assert date.fromisoformat(row["end"]) == start - timedelta(days=1)


def test_unknown_chip_is_still_refused_by_the_db(api):
    pid, _ = two_vendors(api)
    with pytest.raises(Check):
        query(
            "insert into project_conditions (id, project_id, trade, key, value)"
            " values (gen_random_uuid(), $1::uuid, 'diy', 'diy.floor', 'self')",
            pid,
        )


# ---- 8. 실측 견적서 · 추가 금액 1원 이상 DB CHECK(새 행부터, NOT VALID) ----


def _valid(name: str) -> bool:
    return query("select convalidated from pg_constraint where conname = $1", name)[0][
        "convalidated"
    ]


def test_quote_amount_check_refuses_zero_for_new_rows(api):
    _customer, _p, v = vendor_quote.ready(api)
    f = vendor_quote.doc(api)
    url = vendor_quote.url(v)
    assert api.put(url, json={"file_ids": [f], **vendor_quote.FULL}).status_code == 200
    with pytest.raises(Check):
        query("update vendor_quotes set entered_amount = 0, supply = 0, vat = 0, total = 0")
    query("update vendor_quotes set entered_amount = 1, supply = 1, vat = 0, total = 1")
    # NOT VALID: 1원 검사 전에 저장한 0원 행이 있어도 제약은 그대로 살아 있어요(옛 행은 검사하지 않음)
    assert not _valid("ck_vendor_quotes_entered_amount_min")
    old_zero_quote()  # 제약을 잠깐 빼고 0원 행을 만든 뒤 NOT VALID로 되돌려요(운영의 옛 행과 같은 꼴)
    assert [x["entered_amount"] for x in query("select entered_amount from vendor_quotes")] == [0]
    assert not _valid("ck_vendor_quotes_entered_amount_min")
    with pytest.raises(Check) as hit:  # 그 옛 행도 고치면 1원 이상이어야 해요
        query("update vendor_quotes set days = 3")
    assert hit.value.constraint_name == "ck_vendor_quotes_entered_amount_min"


def test_extra_amount_check_refuses_zero_for_new_rows(api):
    _c, _pid, did = extras.scheduled(api)
    assert extras.extra(api, did, 1).status_code == 201
    with pytest.raises(Check):
        query("update extra_charges set entered_amount = 0, supply = 0, vat = 0, total = 0")
    assert not _valid("ck_extra_charges_entered_amount_min")
