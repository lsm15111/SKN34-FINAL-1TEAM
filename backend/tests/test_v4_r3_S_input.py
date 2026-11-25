"""고침 3차 S 갈래 · 글 칸 손질(보안 QA r2 x1 N2 · N4): NUL이 남아 저장에서 500 나던 글 칸(못 받아요 메모 · 견적서
벽지 사양 · 추가 금액 한 일 · 이유)과 사람이 쓰는 다른 글 칸, 보이지 않는 글자만 보낸 비서 턴 422.
유료 호출 0회(Claude 대본 · 무료 모드)."""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.quote import schemas as quote_s
from app.schedule import schemas as schedule_s
from app.shared.text import tidy, visible
from app.vendor import schemas as vendor_s
from app.visit import schemas as visit_s
from tests.conftest import query
from tests.helpers import signup
from tests.test_extras import scheduled
from tests.test_v3_visit_kit import booked, requested
from tests.test_vendor_profile import URL, approved_vendor, body
from tests.test_visit_inbox import login

NUL, FILLER, ZW, WJ, BOM = chr(0), chr(0x3164), chr(0x200B), chr(0x2060), chr(0xFEFF)
DIRTY = f" 가{NUL}나{chr(7)} "  # 앞뒤 빈칸 · NUL · 벨 → '가나'
INVISIBLE_ONLY = [ZW + ZW, FILLER, BOM + WJ, f" {ZW} {FILLER} "]


def err(r) -> tuple[int, str, list]:
    e = r.json()["error"]
    return r.status_code, e["code"], e.get("fields", [])


def nul_free(sql: str, *args) -> list[dict]:
    rows = [dict(x) for x in query(sql, *args)]
    assert NUL not in str(rows)
    return rows


# ---- 1. 보고서 세 칸(HTTP · DB): 전에는 500 server_error ----


def test_decline_note_with_nul_is_saved_clean(api):
    f = requested(api)
    login(api, f["email"])
    r = api.post(
        f"/vendor/visits/{f['visit']}/decline",
        json={"code": "full", "note": f"이번 달은{NUL} 꽉 찼어요"},
    )
    assert r.status_code == 200, r.text
    (row,) = nul_free("select decline_note from visits")
    assert row["decline_note"] == "이번 달은 꽉 찼어요"


def test_decline_note_of_invisible_letters_only_is_empty(api):
    f = requested(api)
    login(api, f["email"])
    r = api.post(f"/vendor/visits/{f['visit']}/decline", json={"code": "full", "note": FILLER})
    assert r.status_code == 200, r.text
    assert query("select decline_note from visits")[0]["decline_note"] is None


def test_quote_paper_spec_with_nul_is_saved_clean(api):
    f = booked(api)
    login(api, f["email"])
    r = api.put(f"/vendor/visits/{f['visit']}/quote", json={"paper_spec": f"실크{NUL} 벽지 LX"})
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["paper_spec"] == "실크 벽지 LX"
    (row,) = nul_free("select paper_spec from vendor_quotes")
    assert row["paper_spec"] == "실크 벽지 LX"


def test_extra_title_and_reason_with_nul_are_saved_clean(api):
    _, _, did = scheduled(api)
    url = f"/vendor/jobs/{did}/extras"
    extra = {"entered_amount": 150_000, "vat_mode": "excluded"}
    r = api.post(
        url, json={**extra, "title": f"벽 곰팡이{NUL} 보수", "reason": f"실측 때{NUL} 못 본 곰팡이"}
    )
    assert r.status_code == 201, r.text
    (row,) = nul_free("select title, reason from extra_charges")
    assert (row["title"], row["reason"]) == ("벽 곰팡이 보수", "실측 때 못 본 곰팡이")
    # 손질하고 빈 필수 칸은 다른 빈 입력처럼 422(칸 이름이 붙어요)
    for title in (NUL, FILLER + ZW, "   "):
        bad = api.post(url, json={**extra, "title": title, "reason": "벽 곰팡이"})
        status, code, fields = err(bad)
        assert (status, code) == (422, "invalid") and [f["loc"] for f in fields] == [["title"]]
    assert query("select count(*) as n from extra_charges")[0]["n"] == 1


# ---- 2. 사람이 쓰는 다른 글 칸(HTTP 몇 개) ----


def test_vendor_profile_text_fields_with_nul_are_saved_clean(api):
    approved_vendor(api)
    r = api.put(
        URL,
        json=body(
            address=f"서울특별시 도봉구{NUL} 예시로 1",
            intro=f"도배만{NUL} 12년",
            interior_license=f"제{NUL}2026-1호",
            faqs=[{"key": "process", "answer": f"실측{NUL} 뒤 견적서를 드려요"}],
            links=[{"label": f"블{NUL}로그", "url": "https://blog.example.com"}],
        ),
    )
    assert r.status_code == 200, r.text
    (v,) = nul_free("select address, intro, interior_license from vendors")
    assert (v["address"], v["intro"], v["interior_license"]) == (
        "서울특별시 도봉구 예시로 1", "도배만 12년", "제2026-1호",
    )  # fmt: skip
    assert nul_free("select answer from vendor_faqs")[0]["answer"] == "실측 뒤 견적서를 드려요"
    assert nul_free("select label from vendor_links")[0]["label"] == "블로그"
    bad = api.put(URL, json=body(updated_at=r.json()["updated_at"], site_url=f"www.ex{NUL}.com"))
    assert err(bad)[:2] == (422, "invalid")  # 주소 칸은 지우지 않고 받지 않아요


def test_email_with_nul_is_422_at_signup_and_login_is_not_500(api):
    bad = api.post(
        "/auth/signup",
        json={"name": "널", "email": f"nul{NUL}@mitjip.test", "password": "pass-1234-word"},
    )
    assert err(bad)[:2] == (422, "invalid")
    signup(api, "nul@mitjip.test")
    api.cookies.clear()
    r = api.post(
        "/auth/login", json={"email": f"nul@mitjip{NUL}.test", "password": "pass-1234-word"}
    )
    assert r.status_code in (200, 401), r.text  # 조회에서 500이 나지 않아요


# ---- 3. 글 칸 타입(DB 없음): 칸마다 NUL · 제어 문자를 지우고 앞뒤 빈칸을 뗀다 ----

D = date(2026, 12, 14)
V = str(uuid.uuid4())


@pytest.mark.parametrize(
    ("model", "base", "name"),
    [
        (visit_s.DeclineIn, {"code": "other"}, "note"),
        (quote_s.QuoteDraftIn, {}, "paper_spec"),
        (vendor_s.LinkIn, {"url": "https://blog.example.com"}, "label"),
    ],
)
def test_optional_note_of_invisible_letters_only_is_empty(model, base, name):
    for v in INVISIBLE_ONLY:
        assert not getattr(model.model_validate({**base, name: v}), name), repr(v)  # None · ""


def test_tidy_keeps_lines_emoji_joiners_and_length_messages():
    assert tidy(f" 첫 줄{NUL}\n둘째 줄\t끝 ") == "첫 줄\n둘째 줄\t끝"
    heart, family = chr(0x2764) + chr(0xFE0F), chr(0x1F468) + chr(0x200D) + chr(0x1F469)
    assert tidy(f"고마워요 {heart} {family}") == f"고마워요 {heart} {family}"  # 이모지는 그대로
    assert visible(ZW + FILLER + " ") == "" and tidy(42) == 42
    with pytest.raises(ValidationError) as e:  # 길이 오류 글은 손질 전과 같은 꼴
        schedule_s.ExtraIn.model_validate(
            {"title": "가" * 41, "reason": "곰팡이", "entered_amount": 1}
        )
    assert "at most 40 characters" in str(e.value)
    with pytest.raises(ValidationError) as e:
        visit_s.DeclineIn.model_validate({"code": "other", "note": f"가{NUL}" * 101})
    assert "at most 100 characters" in str(e.value)


# ---- 4. 보이지 않는 글자만 보낸 비서 턴(N4): 다른 빈 입력과 같은 422 ----


def test_turn_text_type_keeps_max_length_and_korean_blank_message():
    from app.assistant.schemas import TurnIn

    pid = str(uuid.uuid4())
    with pytest.raises(ValidationError) as e:
        TurnIn.model_validate({"project_id": pid, "client_key": "k" * 10, "text": FILLER})
    assert "보낼 말을 적어 주세요." in str(e.value)
    t = TurnIn.model_validate(
        {"project_id": pid, "client_key": "k" * 10, "text": f"도배{NUL} 언제요"}
    )
    assert t.text == "도배 언제요"
