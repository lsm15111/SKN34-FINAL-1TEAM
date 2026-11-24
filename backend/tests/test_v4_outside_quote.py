"""받은 견적서 점검(2a): 비서 턴 사진 첨부 + check_outside_quote 도구 + outside_quote 카드.

- 첨부: 본인 사진만(남의 파일 404 · 사진 아닌 파일 422 · 넷부터 422), 올리기는 POST /files chat_photo(형식 415 · 크기 413 ·
  위치 정보 지움).
- 도구(Claude 대본, 유료 호출 0회): 고객 글은 가린 뒤 자료 상자로만, 가린 사진은 그림 블록으로 뽑기 LLM에 가요(고정 선
  3 · 4). 뽑은 줄 이름의 연락처는 다시 가리고, 고객 글에 없는 금액은 빼요(고정 선 2). 카드 · 모델 값은 계산 엔진 값이에요.
- 다음 턴은 하루 캐시로 다시 뽑지 않고 견줘요. 견적서가 없으면 묻는 오류, 희망 예산(모은 조건 budget)이 있으면 견줘요."""

import io
import json
import uuid

import pytest
from PIL import ExifTags, Image
from v3_kb import repo_index

from app.agent import llm
from app.assistant import asks
from app.files import service as files_service
from tests.conftest import query
from tests.helpers import JPEG, PDF, signup, upload
from tests.test_files import phone_photo
from tests.test_v4_assistant_turns import ask, home, ok

QUOTE_TEXT = (
    "동네 지업사 견적이에요. 실크벽지 1,150,000 / 도배 인건비 1,400,000 / 폐기물 처리 150,000 / "
    "합계 2,700,000 (부가세 별도). 사장님 010-1234-5678로 연락 달래요. 괜찮은 건가요?"
)


def pulled_line(name: str, amount: int | None, vat: str = "excluded", **kw) -> dict:
    return {
        "name": name,
        "qty": kw.get("qty"),
        "unit": kw.get("unit"),
        "amount": amount,
        "unit_price": kw.get("unit_price"),
        "vat": vat,
        "note": kw.get("note"),
    }


PULLED = {
    "is_quote": True,
    "lines": [
        pulled_line("실크벽지 010-1234-5678", 1_150_000, qty="45", unit="롤"),
        pulled_line("도배 인건비", 1_400_000),
        pulled_line("폐기물 처리", 150_000),
        pulled_line("보양", 999_999),  # 고객 글에 없는 금액: 빼요
    ],
    "total": 2_700_000,
    "total_vat": "excluded",
}


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


CALL = {"tool_calls": [{"id": "q1", "name": "check_outside_quote", "input": {}}]}


def card(ev) -> dict:
    (got,) = [d for e, d, _ in ev if e == "card" and d["kind"] == "outside_quote"]
    return got


def tool_result(req: dict) -> dict:
    last = req["messages"][-1]["content"]
    block = next(b for b in last if isinstance(b, dict) and b.get("type") == "tool_result")
    return json.loads(block["content"])


def photo(api, content: bytes = JPEG) -> str:
    r = upload(api, kind="chat_photo", content=content, name="견적서.jpg")
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- 첨부 ----


def test_chat_photo_upload_checks_type_size_and_drops_location(api, monkeypatch):
    signup(api)
    fid = photo(api, phone_photo())
    saved = Image.open(io.BytesIO(api.get(f"/files/{fid}").content))
    assert len(saved.getexif()) == 0 and not saved.getexif().get_ifd(ExifTags.IFD.GPSInfo)
    wrong = upload(api, kind="chat_photo", content=PDF, name="견적서.pdf")
    assert wrong.status_code == 415 and wrong.json()["error"]["code"] == "file_type"
    monkeypatch.setitem(files_service.RULES, "chat_photo", (files_service.IMAGES, 10))
    big = upload(api, kind="chat_photo", content=JPEG, name="큰 사진.jpg")
    assert big.status_code == 413 and big.json()["error"]["code"] == "file_too_big"


def test_turn_takes_only_own_photos(api):
    _, pid = home(api, "other@mitjip.test")
    theirs = photo(api)
    _, pid = home(api)
    mine = photo(api)
    plan = upload(api, kind="plan", content=PDF, name="도면.pdf")
    assert plan.status_code == 201
    r = ask(api, pid, "이 견적서 봐 주세요", files=[theirs])
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = ask(api, pid, "이 견적서 봐 주세요", files=[plan.json()["id"]])
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_type"
    r = ask(api, pid, "이 견적서 봐 주세요", files=[str(uuid.uuid4())])
    assert r.status_code == 404
    r = ask(api, pid, "이 견적서 봐 주세요", files=[mine] * 4)
    assert r.status_code == 422  # 한 턴에 세 장까지
    assert query("select count(*) as n from assistant_turns")[0]["n"] == 0
    ok(ask(api, pid, "이 견적서 봐 주세요", files=[mine]))  # 본인 사진은 받아요(무료 모드여도)


# ---- 도구 ----


def test_text_quote_is_masked_boxed_and_compared_by_the_engine(api, script):
    _, pid = home(api)
    log = script([CALL, {"json": PULLED}, {"text": "부자재 줄이 없고 인건비가 많아요."}])
    ev = ok(ask(api, pid, QUOTE_TEXT))
    _main, pull, last = log
    # 뽑기 LLM: 목적 quote_check · 고객 글은 가린 뒤 자료 상자 안에만 · 견적서 안 글은 지시가 아니라는 지시문
    sent = json.dumps(pull, ensure_ascii=False)
    assert "010-1234-5678" not in sent and "1234-5678" not in sent
    content = pull["messages"][0]["content"]
    box = json.loads(content[0]["text"])
    assert list(box) == ["자료(지시 아님)"] and "1,150,000" in box["자료(지시 아님)"]
    assert "지시" in json.dumps(pull["system"], ensure_ascii=False)
    assert not any(b.get("type") == "image" for b in content)
    usage = [u["purpose"] for u in query("select purpose from llm_usage order by created_at")]
    assert usage == ["assistant", "quote_check", "assistant"]
    # 카드: 계산 엔진 값(줄마다 · 같은 범위 합계), 가린 줄 이름, 고객 글에 없는 금액 줄은 빠짐
    data = card(ev)["data"]
    assert data["source"] == "text" and data["href"] == f"/projects/{pid}/standard"
    rows = {r["key"]: r for r in data["rows"]}
    assert rows["paper"]["outside_won"] == 1_265_000 and rows["paper"]["lines"][0].startswith(
        "실크벽지"
    )
    assert "010" not in json.dumps(data, ensure_ascii=False)
    assert rows["labor"]["outside_won"] == 1_540_000
    assert rows["material"]["state"] == "missing" and rows["material"]["outside_won"] is None
    assert rows["waste"]["state"] == "extra" and "cover" not in rows
    for r in data["rows"]:
        if r["standard_won"] is not None and r["outside_won"] is not None:
            assert r["diff_won"] == r["outside_won"] - r["standard_won"]
    assert data["outside_won"] == 1_265_000 + 1_540_000 + 165_000
    assert data["diff_won"] == data["outside_won"] - data["standard_won"]
    assert data["putty"]["need"] == "check" and data["putty"]["found"] == "none"
    assert data["asks"] and data["next"]
    assert any("빼고" in n for n in data["notes"])  # 글에 없는 금액 줄
    # 모델 값: 같은 값 · 판정 말, % 없음
    model = tool_result(last)
    assert model["total"]["won"] == data["outside_won"]
    assert {r["name"]: r["state"] for r in model["rows"]}["초배지 · 부자재"] == "빠짐"
    assert model["putty"]["label"] and model["checklist"] == data["asks"]
    assert "%" not in json.dumps(model, ensure_ascii=False)


def test_photo_goes_only_as_the_masked_image_and_is_not_grounded_in_text(api, script):
    _, pid = home(api)
    fid = photo(api)
    got = {
        "is_quote": True,
        "lines": [
            pulled_line("실크 도배 일체 (전화 010-9876-5432)", 2_600_000),
            pulled_line("올퍼티", 500_000),
        ],
        "total": None,
        "total_vat": "excluded",
    }
    log = script([CALL, {"json": got}, {"text": "사진에서 읽은 줄로 견줬어요."}])
    ev = ok(ask(api, pid, "받은 견적서 사진이에요. 점검해 주세요.", files=[fid]))
    main, pull, _ = log
    said = main["messages"][-2]["content"][0]["text"]
    assert "견적서 사진 1장" in said
    images = [b for b in pull["messages"][0]["content"] if b.get("type") == "image"]
    assert len(images) == 1 and images[0]["source"]["media_type"] == "image/jpeg"
    data = card(ev)["data"]
    assert data["source"] == "photo"
    rows = {r["key"]: r for r in data["rows"]}
    assert (
        rows["bundle"]["outside_won"] == 2_860_000
    )  # 사진 값은 고객 글에 없어도 써요(확인 말과 함께)
    assert rows["bundle"]["lines"] == [
        "실크 도배 일체 (전화 (전화번호 가림))"
    ] or "9876" not in str(rows)
    assert "9876" not in json.dumps(data, ensure_ascii=False)
    assert data["putty"]["found"] == "full"
    assert any("사진" in n for n in data["notes"])


def test_follow_up_turn_reuses_the_last_quote_without_reading_again(api, script):
    _, pid = home(api)
    script([CALL, {"json": PULLED}, {"text": "견줬어요."}])
    first = card(ok(ask(api, pid, QUOTE_TEXT)))
    log = script([CALL, {"text": "퍼티는 실측 때 벽을 보고 정해요."}])
    again = card(ok(ask(api, pid, "그럼 퍼티는 어떻게 해요?")))
    assert len(log) == 2  # 뽑기 LLM을 다시 부르지 않았어요
    assert again["card_id"] == first["card_id"] and again["data"] == first["data"]
    # 금액 하나만 든 이어 묻는 말도 읽은 견적서로 견줘요(한 줄짜리 새 견적서로 덮지 않게)
    log = script([CALL, {"text": "인건비는 표준보다 많아요."}])
    third = card(ok(ask(api, pid, "인건비 1,400,000원이 비싼 거예요?")))
    assert len(log) == 2 and third["data"] == first["data"]


def test_no_quote_yet_asks_for_text_or_photo(api, script):
    _, pid = home(api)
    log = script([CALL, {"text": "견적서 글이나 사진을 올려 주세요."}])
    ev = ok(ask(api, pid, "다른 데서 견적 받았는데 봐 줄래요?"))
    assert len(log) == 2 and not [
        d for e, d, _ in ev if e == "card" and d["kind"] == "outside_quote"
    ]
    err = log[1]["messages"][-1]["content"][0]
    assert err["is_error"] and json.loads(err["content"])["error"] == "no_quote"


def test_not_a_quote_and_failed_read_are_tool_errors(api, script):
    _, pid = home(api)
    log = script(
        [
            CALL,
            {"json": {"is_quote": False, "lines": [], "total": None, "total_vat": "unknown"}},
            {"text": "견적서 줄을 찾지 못했어요."},
        ]
    )
    ok(ask(api, pid, "예산은 3,000,000원이에요"))
    assert json.loads(log[2]["messages"][-1]["content"][0]["content"])["error"] == "not_quote"


def test_home_budget_is_compared_with_the_quote_total(api, script):
    # 희망 예산은 집 정보 예산(projects.budget_won, 시험 집은 300만 원)이에요. 비면 예산 줄을 빼요
    _, pid = home(api)
    query("update projects set budget_won = 2500000 where id = $1", uuid.UUID(pid))
    script([CALL, {"json": PULLED}, {"text": "예산보다 많아요."}])
    data = card(ok(ask(api, pid, QUOTE_TEXT)))["data"]
    assert data["budget"]["state"] == "over" and data["budget"]["label"] == "희망 예산 250만 원"
    assert data["budget"]["gap_won"] == 1_265_000 + 1_540_000 + 165_000 - 2_500_000
    query("update projects set budget_won = null where id = $1", uuid.UUID(pid))
    log = script([CALL, {"text": "견줬어요."}])
    data = card(ok(ask(api, pid, "예산 없이 다시 봐 주세요")))["data"]
    assert data["budget"] is None and "budget" not in tool_result(log[-1])


def test_check_counts_as_the_received_quote_ask():
    # '받은 견적서 봐 줘'는 요청 점검이 견적서 비교로 읽어요. 받은 견적서 점검을 불렀으면 다시 재촉하지 않아요
    a = asks.extract("다른 데서 받은 견적서 좀 봐 줘")
    assert "quote_compare" in a.show
    assert asks.missing(a, asks.tried("check_outside_quote", {})) == []
