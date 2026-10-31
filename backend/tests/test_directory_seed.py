"""개발용 가짜 외부 업체 씨드 (app/directory/seed.py)"""

import asyncio

import pytest

from app.db import SessionLocal
from app.directory import seed
from app.shared.clock import now_utc
from tests.conftest import query
from tests.sourcing_helpers import customer_project


def run_seed() -> int:
    async def go():
        async with SessionLocal() as s:
            return await seed.seed(s, now_utc())

    return asyncio.run(go())


def test_fake_vendors_are_obviously_fake_and_cover_every_route(api):
    assert run_seed() == 5
    assert run_seed() == 5  # 다시 돌려도 늘지 않는다
    rows = query("select * from ext_vendors order by source_id")
    assert len(rows) == 5 and all(r["source"] == "seed" for r in rows)
    assert all(r["name"].startswith("가짜인테리어 ") for r in rows)
    assert all(
        (r["homepage"] or "https://example.com").startswith("https://example.com") for r in rows
    )
    assert query("select count(*) n from ext_vendor_contacts")[0]["n"] == 1
    _, pid = customer_project(api)
    out = api.get(f"/projects/{pid}/sourcing").json()
    routes = {c["name"]: c["route"] for c in out["candidates"]}
    assert routes == {
        "가짜인테리어 1": "reference",  # 대신 요청이 꺼져 있어 정보만 (proxy_off)
        "가짜인테리어 2": "link",
        "가짜인테리어 3": "phone",
        "가짜인테리어 4": "reference",
    }
    costs = {c["name"]: c["cost"]["kind"] for c in out["candidates"]}
    assert costs["가짜인테리어 1"] == "free" and costs["가짜인테리어 3"] == "vendor_fee"


def test_seed_refuses_outside_local(monkeypatch):
    monkeypatch.setattr(seed.settings, "app_env", "production")
    with pytest.raises(SystemExit):
        seed.main([])
    assert query("select count(*) n from ext_vendors")[0]["n"] == 0
