"""T05 위치 정보 지움 · T06 파일 응답 · W7 새 사진 종류 · T15/W9 사업자등록증 열람 기록 (FI-01~03 · LG-02)."""

import io

import pytest
from PIL import ExifTags, Image

from app.files import service as files_service
from tests.conftest import query
from tests.helpers import PASSWORD, PDF, make_admin, signup, upload, vendor_signup
from tests.security.sec_util import photo_with_gps, prepare
from tests.test_files import xlsx_bytes
from tests.test_vendor_profile import approved_vendor

# (Pillow 형식, 저장 뒤 형식, 원본에 든 EXIF 표시 바이트)
FORMATS = [
    ("JPEG", "image/jpeg", b"Exif\x00\x00"),
    ("PNG", "image/png", b"eXIf"),
    ("WEBP", "image/webp", b"EXIF"),
    ("HEIF", "image/jpeg", b"Exif"),  # 아이폰 사진은 JPEG로 바꾼다
]
PHOTO_KINDS = ["photo", "work_photo", "chat_photo", "review_photo", "done_photo"]


@pytest.mark.parametrize("kind", PHOTO_KINDS)
@pytest.mark.parametrize(("fmt", "saved_as", "marker"), FORMATS)
def test_location_is_removed_for_every_photo_kind(kind, fmt, saved_as, marker):
    original = photo_with_gps(fmt)
    assert marker in original
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(ExifTags.IFD.GPSInfo)
    got = prepare(kind, original, f"a.{fmt.lower()}")
    assert got.content_type == saved_as
    assert marker not in got.data and b"Exif" not in got.data
    saved = Image.open(io.BytesIO(got.data))
    assert len(saved.getexif()) == 0 and "exif" not in saved.info


def test_download_headers_keep_files_from_running(api):
    signup(api)
    r = api.get(f"/files/{upload(api).json()['id']}")
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp and "default-src 'none'" in csp and "frame-ancestors 'self'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-disposition"].startswith("inline; filename*=UTF-8''")


def test_spreadsheets_are_downloaded_not_opened(api):
    approved_vendor(api)  # 업체 종류 파일은 승인된 업체만(sec M5)
    x = upload(api, kind="price_doc", content=xlsx_bytes(), name="단가표 1.xlsx").json()
    r = api.get(f"/files/{x['id']}")
    assert r.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''%EB%8B%A8%EA%B0%80%ED%91%9C%201.xlsx"
    )
    pdf = upload(api, kind="quote_doc", content=PDF, name="견적서.pdf").json()
    assert api.get(f"/files/{pdf['id']}").headers["content-disposition"].startswith("inline;")


NEW_KINDS = [
    ("chat_photo", "customer"),
    ("chat_photo", "vendor"),
    ("review_photo", "customer"),
    ("done_photo", "vendor"),
]


@pytest.mark.parametrize(("kind", "role"), NEW_KINDS)
def test_new_photo_kinds_are_stored_without_location(api, kind, role):
    """W7: 0028 뒤 새 종류가 실제로 올라가고, 저장본에는 위치 정보가 없다."""
    if role == "customer":
        signup(api)
    else:
        approved_vendor(api)  # 업체 종류 파일은 승인된 업체만(sec M5)
    r = upload(api, kind=kind, content=photo_with_gps("JPEG"), name="IMG_0001.jpg")
    assert r.status_code == 201, r.text
    assert (r.json()["kind"], r.json()["content_type"]) == (kind, "image/jpeg")
    saved = api.get(f"/files/{r.json()['id']}")  # 올린 사람은 본다
    assert saved.status_code == 200 and b"Exif" not in saved.content
    assert len(Image.open(io.BytesIO(saved.content)).getexif()) == 0


def test_license_views_go_to_the_access_log_table(api):
    """W9: 업체 본인 · 관리자가 사업자등록증을 열 때마다 file_views 한 줄(누가 · 언제 · 어느 파일)."""
    assert vendor_signup(api, email="lic@mitjip.test").status_code == 201
    (v,) = query("select license_file_id fid, user_id vid from vendors")
    assert api.get(f"/files/{v['fid']}").status_code == 200  # 업체 본인
    make_admin(api)
    assert api.get(f"/files/{v['fid']}").status_code == 200  # 관리자
    (admin,) = query("select id from users where role = 'admin'")
    rows = query(
        "select file_id, owner_id, viewer_id, viewer_role, kind, at from file_views order by at, id"
    )
    assert [tuple(r.values())[:5] for r in rows] == [
        (v["fid"], v["vid"], v["vid"], "vendor", "license"),
        (v["fid"], v["vid"], admin["id"], "admin", "license"),
    ]
    assert all(r["at"] is not None for r in rows)
    cols = query(
        "select column_name from information_schema.columns where table_name = 'file_views'"
    )
    # 이름 · 이메일 · 파일 이름 · 상호 같은 값 칸은 없다
    assert {c["column_name"] for c in cols} == {
        "id", "file_id", "owner_id", "viewer_id", "viewer_role", "kind", "at"
    }  # fmt: skip


def test_access_log_outlives_the_file_and_the_account(api):
    assert vendor_signup(api, email="lic@mitjip.test").status_code == 201
    (v,) = query("select license_file_id fid from vendors")
    assert api.get(f"/files/{v['fid']}").status_code == 200
    gone = api.post("/me/withdraw", json={"password": PASSWORD})
    assert gone.status_code == 204, gone.text
    assert query("select count(*) n from files")[0]["n"] == 0
    assert query("select count(*) n from file_views")[0]["n"] == 1  # 기록은 남는다(고시 제8조)


def test_refused_and_ordinary_views_leave_no_record(api):
    vendor_signup(api, email="lic@mitjip.test")
    (v,) = query("select license_file_id fid from vendors")
    signup(api, "c@mitjip.test")
    photo = upload(api).json()["id"]
    assert api.get(f"/files/{v['fid']}").status_code == 404  # 고객은 못 본다
    assert api.get(f"/files/{photo}").status_code == 200  # 사진은 기록 대상이 아니다
    vendor_signup(api, email="other@mitjip.test")
    assert api.get(f"/files/{v['fid']}").status_code == 404  # 다른 업체도 못 본다
    assert query("select count(*) n from file_views")[0]["n"] == 0
    assert files_service.VIEW_LOGGED == {"license"}
