"""갈래 C 반셀프 '벽지 직접 구매'(칩 paper_buy, 2026-11-22 리드 결정) · 금액 1원 이상 DB CHECK(0052, NOT VALID).

- 칩을 켜면 표준견적서 도배지 줄이 '안 함'(고객 구매)으로 합계에서 빠지고(계산 엔진 값 그대로) 새 판을 쌓아요.
  끄면 다시 넣은 새 판이에요. 롤 수(계산 엔진)와 가견적 안내 한 줄(틀)이 같이 와요.
- 업체 가견적은 벽지 값이 든 값이라 칩과 상관없이 같아요('시공만' 값은 뒤로). 표준 대비 %도 벽지까지 넣고 견줘요.
- 다른 칩처럼 공정표 '고객이 직접' 줄 · 실측 요청 '업체에 알릴 것' · 업체 브리핑에 들어가요.
유료 호출 0회(무료 모드)."""

from decimal import Decimal

import asyncpg
import pytest

from tests import test_extras as extras
from tests import test_vendor_quote as vendor_quote
from tests.conftest import query
from tests.test_v4_qa_r2_calc import old_zero_quote

D = Decimal
Check = asyncpg.exceptions.CheckViolationError


def _dobae(api, pid: str) -> dict:
    r = api.get(f"/projects/{pid}/standard")
    assert r.status_code == 200, r.text
    return next(t for t in r.json()["trades"] if t["trade"] == "dobae")


def _paper(t: dict) -> dict:
    return next(ln for ln in t["lines"] if ln["key"] == "paper")


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
