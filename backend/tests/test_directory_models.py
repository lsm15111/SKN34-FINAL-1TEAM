"""외부 업체 표의 DB 제약과 공정 → 업종 대응표 (합성 데이터, 실제 업체 아님)."""

from decimal import Decimal

import asyncpg
import pytest

from app.directory.industry import (
    TRADE_INDUSTRIES,
    TRADE_LABEL,
    TRADES,
    kiscon_items,
    trades_for_kiscon,
    trades_for_sangga,
)
from tests.conftest import query


def add(**over) -> None:
    row = {"source": "seed", "source_id": "fake-1", "name": "가짜인테리어 1", "trades": ["dobae"]}
    row |= over
    cols = ", ".join(row)
    params = ", ".join(f"${i}" for i in range(1, len(row) + 1))
    query(
        f"insert into ext_vendors (id, fetched_at, optout_token, {cols})"
        f" values (gen_random_uuid(), now(), md5(random()::text), {params})",
        *row.values(),
    )


def bad(**over) -> None:
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        add(source_id=f"bad-{len(over)}-{next(iter(over))}", **over)


def test_one_row_per_source_number():
    add()
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        add(name="가짜인테리어 1 다시")
    add(source="kiscon", source_id="fake-1")  # 출처가 다르면 따로


def test_no_mobile_phone_or_unknown_trade_is_stored():
    add(source_id="tel-1", phone="0212345678")
    add(source_id="tel-2", phone="15880000")
    bad(phone="01012345678")  # 휴대전화는 개인정보일 수 있어 두지 않는다
    bad(phone="02-1234-5678")  # 숫자만
    bad(trades=["roof"])
    bad(trades=[])
    bad(lat=Decimal("37.5"))  # 좌표는 둘 다 있거나 둘 다 없다
    bad(lat=Decimal("10.0"), lng=Decimal("127.0"))
    bad(reg_kind="business")  # 사업자등록만이면 번호가 있어야 한다
    bad(reg_no="12345-6789")  # 숫자 10자리만
    bad(homepage="javascript:alert(1)")
    bad(visit_fee=-1)
    bad(sgg="마포구")  # 시 · 군 · 구만 있고 시 · 도가 없음


def test_only_consented_contacts_with_a_valid_shape():
    add()
    (v,) = query("select id from ext_vendors")
    ins = (
        "insert into ext_vendor_contacts (id, vendor_id, channel, value, consented_at, source)"
        " values (gen_random_uuid(), $1, $2, $3, now(), 'seed')"
    )
    query(ins, v["id"], "sms", "01000000001")
    query(ins, v["id"], "email", "fake@example.com")
    for channel, value in (("sms", "0212345678"), ("email", "not-an-email"), ("form", "http://x")):
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            query(ins, v["id"], channel, value)
    with pytest.raises(asyncpg.exceptions.NotNullViolationError):  # 동의 시각 없이는 못 넣는다
        query(
            "insert into ext_vendor_contacts (id, vendor_id, channel, value, source)"
            " values (gen_random_uuid(), $1, 'sms', '01000000002', 'seed')",
            v["id"],
        )


def test_trade_industry_table_covers_all_ten_trades():
    assert set(TRADE_INDUSTRIES) == set(TRADES) == set(TRADE_LABEL)
    assert kiscon_items()[:3]  # 거를 업종이 있다
    assert trades_for_kiscon("실내건축공사업")[:2] == ["dobae", "mokgong"]
    # 가운뎃점 모양 · 띄어쓰기 · '공사업' 유무가 달라도 같은 업종
    assert trades_for_kiscon("도장ㆍ습식ㆍ방수ㆍ석공사업") == ["paint", "tile", "bath"]
    assert trades_for_kiscon("금속창호 지붕건축물조립") == ["window"]
    assert trades_for_kiscon("토목공사업") == []
    assert trades_for_kiscon("") == []


def test_sangga_codes_and_names():
    assert trades_for_sangga("F42412", None) == ["dobae", "mokgong", "floor", "film"]
    assert trades_for_sangga(None, "벽지·장판·마루 소매업") == ["dobae", "floor"]
    assert trades_for_sangga("M73201", "인테리어 디자인업") == list(TRADES)  # 종합 인테리어
    assert trades_for_sangga("I56111", "한식 일반 음식점업") == []
    assert trades_for_sangga("", "") == []
