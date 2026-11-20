"""v3 담기 (api.md 4장 · data-model 4장 shortlists): 업체 목록 v3 카드 · 담기 3칸 · 409 · 빼기 ·
동시 담기 · 권한 · 업체 상세 v3 칸(가견적 v3 · 벽지 차이 · 링크) · 가까운 구 업체."""

import asyncio
import uuid
from decimal import Decimal

from app.calc.quote_diff import percent_vs
from app.shared.errors import AppError
from app.vendor import service as vendor_service
from app.vendor.schemas import EstimateV3LineOut, EstimateV3Out
from app.visit import flow
from app.visit.schemas import ShortlistIn
from tests.conftest import query
from tests.helpers import make_admin, no_surprises, signup, use, vendor_signup
from tests.test_v3_visit_kit import (
    add,
    ask,
    customer,
    quiet,
    run,
    user_id,
    v2_totals,
    vendor,
    with_user,
)
from tests.test_visit_request import listed

V = "/projects/{pid}/vendors"


def cards(api, pid: str) -> dict:
    r = api.get(V.format(pid=pid), params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    return r.json()


def code(r) -> tuple[int, str]:
    return r.status_code, r.json().get("error", {}).get("code", "") if r.content else ""


def fake_v3(monkeypatch, totals: dict[str, dict[str, int]], off: dict[str, str] | None = None):
    """가견적 v3 가짜 (A의 estimate_v3_for · estimates_v3_for 자리): 업체 id → 벽지별 합계.
    off의 벽지는 업체가 '빼기'로 둔 줄(paper_ok False)."""

    def one(vendor_id, project, grade):
        by = totals.get(str(vendor_id))
        if by is None:
            return None
        g = grade or project.trades.dobae.grade
        mode = "excluded" if (off or {}).get(str(vendor_id)) == g else "price"
        line = EstimateV3LineOut(
            code="1204" if g == "basic" else "1203",
            key="paper_silk" if g == "basic" else "paper_hapji",
            name="실크" if g == "basic" else "합지",
            qty=Decimal("63.0"),
            unit="벽지 평",
            unit_price=None if mode == "excluded" else 9_500,
            amount=0 if mode == "excluded" else 598_500,
            mode=mode,
            included_in=None,
        )
        total = by[g]
        return EstimateV3Out(
            rows_ver="dobae_v3",
            set_id=None,
            version=1,
            grade=g,
            tax_kind="general",
            lines=[line],
            supply=total * 10 // 11,
            vat=total - total * 10 // 11,
            total=total,
            vs_standard_pct=Decimal("61.4"),
            paper_ok=mode != "excluded",
        )

    # price_ver: 이 집 저장한 표준견적서 도배 판(ADR 0004). 가짜는 쓰지 않아요
    async def single(s, *, vendor_id, project, trade, grade=None, price_ver=None):
        return one(vendor_id, project, grade)

    async def many(s, *, vendor_ids, project, trade, grade=None, price_ver=None):
        got = {vid: one(vid, project, grade) for vid in vendor_ids}
        return {k: v for k, v in got.items() if v is not None}

    monkeypatch.setattr(vendor_service, "estimate_v3_for", single)
    monkeypatch.setattr(vendor_service, "estimates_v3_for", many)


def test_vendor_cards_states_badge_and_count(api):
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배", wall=7000)
    c = listed(api, "hangyeol@mitjip.test", "한결인테리어")  # 확인한 단가 없음
    x = vendor(api, "stop@mitjip.test", "멈춘도배")
    query(
        "update vendors set suspended_at = now(), suspend_scope = 'new' where user_id = $1",
        uuid.UUID(x),
    )
    query("update vendors set instant_default = true where user_id = $1", uuid.UUID(a))
    _, pid = customer(api)
    got = cards(api, pid)
    v2 = v2_totals(api, pid)
    rows = [(c["name"], c["state"], c["estimate_total"], c["instant_badge"]) for c in got["local"]]
    assert rows == [
        ("마루와벽", "ok", v2[a], True),  # 가견적 낮은 순 · 바로 확정 배지
        ("결도배", "ok", v2[b], False),
        ("한결인테리어", "no_estimate", None, False),  # 가견적 준비 중 (D06 A)
    ]
    assert v2[a] < v2[b]
    first = got["local"][0]
    pct = str(percent_vs(v2[a], got["standard_total"]))
    assert (first["vs_standard_pct"], first["sgg"], first["visit_fee"]) == (pct, "노원구", 0)
    assert x not in {c["vendor_id"] for c in got["local"]}  # 멈춘 업체는 목록에서 뺀다
    assert got["nearby"] == [] and got["nearby_sgg"] == []
    assert got["shortlist"] == {"count": 0, "left": 3}
    assert {"phone", "contact_url"}.isdisjoint(first)

    assert add(api, pid, a).status_code == 201
    got = cards(api, pid)
    assert {c["vendor_id"]: c["shortlisted"] for c in got["local"]} == {a: True, b: False, c: False}
    assert got["shortlist"] == {"count": 1, "left": 2}


def test_shortlist_slots_409s_and_remove(api):
    v = {n: vendor(api, f"{n}@mitjip.test", f"업체{n}") for n in ("a", "b", "c", "e")}
    none = listed(api, "none@mitjip.test", "단가없음")
    _, pid = customer(api)
    r = add(api, pid, v["a"])
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["count"], out["left"]) == (1, 2)
    (item,) = out["items"]
    assert (item["vendor_id"], item["slot"], item["state"], item["visit_id"]) == (
        v["a"],
        1,
        "ok",
        None,
    )
    assert item["name"] == "업체a" and item["estimate_total"] == v2_totals(api, pid)[v["a"]]
    assert code(add(api, pid, v["a"])) == (409, "already")  # 같은 업체 두 번
    assert code(add(api, pid, none)) == (409, "no_estimate")
    assert [add(api, pid, v[n]).json()["count"] for n in ("b", "c")] == [2, 3]
    assert code(add(api, pid, v["e"])) == (409, "slots_full")  # 4번째

    url = f"/projects/{pid}/shortlist"
    assert api.delete(f"{url}/{v['b']}", params={"trade": "dobae"}).status_code == 204
    again = add(api, pid, v["e"]).json()
    assert {x["vendor_id"]: x["slot"] for x in again["items"]}[v["e"]] == 2  # 빈 칸을 다시 쓴다
    assert code(api.delete(f"{url}/{none}", params={"trade": "dobae"})) == (404, "not_found")
    removed = query("select removed_code, removed_at from shortlists where status = 'removed'")
    assert [r["removed_code"] for r in removed] == ["customer"] and removed[0]["removed_at"]

    assert ask(api, pid, [v["a"]]).status_code == 201
    assert code(api.delete(f"{url}/{v['a']}", params={"trade": "dobae"})) == (409, "locked")
    listing = api.get(url, params={"trade": "dobae"}).json()
    mine = {x["vendor_id"]: x for x in listing["items"]}
    assert mine[v["a"]]["visit_status"] == "requested" and mine[v["a"]]["visit_id"]
    assert (listing["count"], listing["left"]) == (3, 0)

    query("update visits set status = 'chosen' where vendor_id = $1", uuid.UUID(v["a"]))
    assert api.delete(f"{url}/{v['c']}", params={"trade": "dobae"}).status_code == 204
    assert code(add(api, pid, v["b"])) == (409, "locked")  # 업체 확정 뒤


def test_paper_unsupported_and_blocked_retry(api, monkeypatch):
    a = vendor(api, "a@mitjip.test", "가")
    b = vendor(api, "b@mitjip.test", "나")
    _, pid = customer(api)
    totals = {a: {"basic": 3_186_150, "economy": 2_874_300}}
    fake_v3(monkeypatch, totals, off={a: "basic"})
    query(
        "insert into visits (id, project_id, trade, vendor_id, vendor_name, slot, attempt,"
        " status, expired_reason) values"
        " (gen_random_uuid(), $1, 'dobae', $2, '나', 1, 1, 'expired', 'reply'),"
        " (gen_random_uuid(), $1, 'dobae', $2, '나', 1, 2, 'expired', 'reply')",
        uuid.UUID(pid),
        uuid.UUID(b),
    )
    got = {c["vendor_id"]: c for c in cards(api, pid)["local"]}
    assert (got[a]["state"], got[a]["estimate_total"]) == ("paper_unsupported", 3_186_150)
    assert got[b]["state"] == "blocked_retry"  # 두 번 요청했지만 끝난 업체 (C18)
    assert code(add(api, pid, a)) == (409, "paper_unsupported")
    assert code(add(api, pid, b)) == (409, "blocked_retry")
    assert query("select count(*) n from shortlists")[0]["n"] == 0


def test_two_at_once_same_vendor_and_last_slot(api, monkeypatch):
    quiet(monkeypatch)
    v = [vendor(api, f"v{i}@mitjip.test", f"업체{i}") for i in range(4)]
    _, pid = customer(api)
    assert api.get(f"/projects/{pid}/standard").status_code == 200  # 표준견적서를 먼저 저장해 둔다
    me = user_id("home@mitjip.test")

    async def put(vid: str):
        data = ShortlistIn(trade="dobae", vendor_id=uuid.UUID(vid))
        return await with_user(me, lambda s, u: flow.add_shortlist(s, u, uuid.UUID(pid), data))

    async def both(x: str, y: str):
        return await asyncio.gather(put(x), put(y), return_exceptions=True)

    errors = [r for r in no_surprises(run(both(v[0], v[0]))) if isinstance(r, AppError)]
    assert [(e.status, e.code) for e in errors] == [(409, "already")]
    assert add(api, pid, v[1]).status_code == 201
    errors = [r for r in no_surprises(run(both(v[2], v[3]))) if isinstance(r, AppError)]
    assert [(e.status, e.code) for e in errors] == [(409, "slots_full")]  # 마지막 칸 하나
    rows = query("select slot from shortlists where status = 'active' order by slot")
    assert [r["slot"] for r in rows] == [1, 2, 3]


def test_shortlist_permissions(api):
    a = vendor(api, "a@mitjip.test", "가")
    token, pid = customer(api)
    url = f"/projects/{pid}/shortlist"
    assert code(add(api, pid, a, trade="mokgong")) == (422, "trade")  # 이 집은 도배만
    assert code(add(api, pid, str(uuid.uuid4()))) == (404, "not_found")  # 고를 수 없는 업체
    assert add(api, pid, a).status_code == 201
    calls = (
        lambda: api.get(url, params={"trade": "dobae"}),
        lambda: add(api, pid, a),
        lambda: api.delete(f"{url}/{a}", params={"trade": "dobae"}),
    )
    signup(api, "other@mitjip.test")
    assert [c().status_code for c in calls] == [404, 404, 404]  # 남의 공사
    assert vendor_signup(api, email="v2@mitjip.test").status_code == 201
    assert [c().status_code for c in calls] == [403, 403, 403]  # 업체
    make_admin(api)
    assert [c().status_code for c in calls] == [403, 403, 403]
    api.cookies.clear()
    assert [c().status_code for c in calls] == [401, 401, 401]
    use(api, token)
    assert api.get(url, params={"trade": "dobae"}).json()["count"] == 1


def test_vendor_detail_v3_and_grade_preview(api, monkeypatch):
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    query("update vendors set instant_default = true where user_id = $1", uuid.UUID(a))
    for sort, status, checked in (
        (0, "shown", "now()"),
        (1, "hidden", "now()"),
        (2, "checking", "null"),
    ):
        query(
            "insert into vendor_review_links (vendor_id, sort, label, url, status, checked_at)"
            f" values ($1, $2, '블로그', 'https://blog.example.com/{sort}', $3, {checked})",
            uuid.UUID(a),
            sort,
            status,
        )
    _, pid = customer(api)
    totals = {a: {"basic": 3_186_150, "economy": 2_874_300}}
    fake_v3(monkeypatch, totals)
    url = f"/projects/{pid}/vendors/{a}"
    d = api.get(url, params={"trade": "dobae"}).json()
    assert d["estimate_v3"]["total"] == 3_186_150 and d["estimate_v3"]["grade"] == "basic"
    assert d["grade_diff"] == -311_850  # C11 '합지 −31만 1,850원' (믿집 계산)
    assert (d["state"], d["instant_badge"], d["shortlisted"]) == ("ok", True, False)
    assert [x["url"] for x in d["review_links"]] == ["https://blog.example.com/0"]  # 보여요만
    assert d["estimate"]["total"] == v2_totals(api, pid)[a]  # 지금 가견적(v2)은 그대로
    preview = api.get(url, params={"trade": "dobae", "grade": "economy"}).json()
    assert preview["estimate_v3"]["grade"] == "economy"
    assert (preview["estimate_v3"]["total"], preview["grade_diff"]) == (
        2_874_300,
        311_850,
    )  # 실크 − 합지
    assert api.get(url, params={"trade": "dobae", "grade": "premium"}).status_code == 422
    assert add(api, pid, a).status_code == 201
    assert api.get(url, params={"trade": "dobae"}).json()["shortlisted"] is True
    # 가견적 v3가 있으면 담기 · 요청 사본도 v3 합계
    assert ask(api, pid, [a]).status_code == 201
    assert query("select estimate_total from visits")[0]["estimate_total"] == 3_186_150


def test_nearby_vendors_when_none_local(api):
    a = vendor(api, "maru@mitjip.test", "마루와벽")  # 노원구 · 도봉구
    _, pid = customer(api, sgg="강북구")  # 강북구 업체 0곳 → 가까운 구
    got = cards(api, pid)
    assert got["local"] == []
    assert [(c["vendor_id"], c["sgg"]) for c in got["nearby"]] == [(a, "도봉구")]
    assert got["nearby_sgg"] == ["도봉구"]
    assert add(api, pid, a).status_code == 201  # 가까운 구 업체도 담을 수 있어요 (C12)
    d = api.get(f"/projects/{pid}/vendors/{a}", params={"trade": "dobae"})
    assert d.status_code == 200 and d.json()["in_area"] is False
