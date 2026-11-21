"""QA 2차 고침 G · 파일(sec M5 · L2): 승인 전 업체의 업체 종류 파일 · 사람마다 파일 몫 · 붙이지 않은 파일 정리 ·
파일 이름의 방향 바꾸기 글자."""

import uuid

from app.files import service as files_service
from app.files import storage
from app.shared.clock import now_utc
from app.worker import WorkerSettings
from tests.conftest import query
from tests.helpers import JPEG, PDF, signup, upload, vendor_signup
from tests.test_project import body as project_body
from tests.test_v3_visit_kit import run

# ---- sec M5 붙이지 않은 파일 · 사용자 몫 · 승인 전 업체 ----


def test_m5_vendor_files_need_approval_except_the_license(api):
    assert vendor_signup(api, email="new@mitjip.test").status_code == 201  # 심사 중
    for kind in ("portfolio", "price_doc", "quote_doc", "work_photo", "done_photo", "chat_photo"):
        content, name = (PDF, "a.pdf") if kind.endswith("doc") else (JPEG, "a.jpg")
        r = upload(api, kind=kind, content=content, name=name)
        assert r.status_code == 403 and r.json()["error"]["code"] == "vendor_not_approved", kind
    assert upload(api, kind="license", content=PDF, name="등록증.pdf").status_code == 201
    query("update vendors set status = 'approved', approved_at = now()")
    assert upload(api, kind="portfolio").status_code == 201
    assert query("select count(*) n from files where kind = 'portfolio'")[0]["n"] == 1


def test_m5_files_per_user_have_a_count_and_size_cap(api, monkeypatch):
    signup(api)
    monkeypatch.setattr(files_service, "USER_FILES_MAX", 2)
    assert upload(api).status_code == 201 and upload(api).status_code == 201
    r = upload(api)
    assert r.status_code == 409 and r.json()["error"]["code"] == "file_quota", r.text
    monkeypatch.setattr(files_service, "USER_FILES_MAX", 100)
    used = query("select sum(size) n from files")[0]["n"]
    monkeypatch.setattr(files_service, "USER_BYTES_MAX", used + 10)  # 사진 한 장이 들어갈 자리 없음
    assert upload(api).status_code == 409
    assert query("select count(*) n from files")[0]["n"] == 2
    signup(api, "other@mitjip.test")  # 몫은 사람마다
    assert upload(api).status_code == 201


def test_m5_unattached_files_older_than_a_day_are_cleaned(api):
    signup(api)
    old, fresh, used = (upload(api).json()["id"] for _ in range(3))
    r = api.post("/projects", json=project_body(photo_ids=[used]))
    assert r.status_code == 201, r.text
    query(
        "update files set created_at = now() - interval '25 hours' where id = any($1::uuid[])",
        [uuid.UUID(old), uuid.UUID(used)],
    )
    keys = {r["id"]: r["storage_key"] for r in query("select id, storage_key from files")}
    assert run(files_service.sweep_unattached(now_utc())) == 1
    left = {str(r["id"]) for r in query("select id from files")}
    assert left == {fresh, used}  # 하루 안 된 파일 · 공사에 붙인 파일은 남아요
    assert not storage.path_of(keys[uuid.UUID(old)]).exists()
    assert storage.path_of(keys[uuid.UUID(used)]).exists()
    assert run(files_service.sweep_unattached(now_utc())) == 0
    assert "clean_files" in {c.coroutine.__name__ for c in WorkerSettings.cron_jobs}


# ---- sec L2 파일 이름의 방향 바꾸기 글자 ----


def test_l2_filename_drops_direction_marks():
    from app.files.service import clean_filename

    assert clean_filename("photo\u202egpj.exe") == "photogpj.exe"
    marks = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
    assert clean_filename(f"a{marks}b.jpg") == "ab.jpg"
    assert clean_filename(marks) == "file"
    assert clean_filename("C:\\사진\\집 사진.jpg") == "집 사진.jpg"  # 보통 글자는 그대로
