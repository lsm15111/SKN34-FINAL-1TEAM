import io
import zipfile

import pillow_heif
from PIL import ExifTags, Image, PngImagePlugin

from app.files import images, service
from tests.helpers import JPEG, PDF, signup, upload, vendor_signup
from tests.test_vendor_profile import approved_vendor

pillow_heif.register_heif_opener()


def phone_photo() -> bytes:
    """휴대폰 사진처럼 위치(GPS) · 기기 정보 · 세로 방향(Orientation 6)이 든 JPEG (가로 40 × 세로 20 픽셀로 저장)"""
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "ExamplePhone"
    exif[ExifTags.Base.Orientation] = 6  # 오른쪽으로 90도 돌려서 봐야 하는 사진
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (37.0, 33.0, 30.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E"
    gps[ExifTags.GPS.GPSLongitude] = (126.0, 54.0, 10.0)
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (90, 140, 200)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_customer_uploads_a_photo_and_reads_it_back(api):
    signup(api)
    r = upload(api, name="../../거실 벽.jpg")
    assert r.status_code == 201
    body = r.json()
    assert body["content_type"] == "image/jpeg" and body["filename"] == "거실 벽.jpg"
    got = api.get(f"/files/{body['id']}")
    assert got.status_code == 200 and Image.open(io.BytesIO(got.content)).size == (40, 20)
    assert got.headers["x-content-type-options"] == "nosniff"


def test_location_and_camera_info_are_removed_and_rotation_kept(api):
    signup(api)
    original = phone_photo()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(ExifTags.IFD.GPSInfo)  # 원본에는 있다
    r = upload(api, content=original)
    assert r.status_code == 201
    saved = Image.open(io.BytesIO(api.get(f"/files/{r.json()['id']}").content))
    assert len(saved.getexif()) == 0  # GPS · 기기 · 방향 모두 없음
    assert "exif" not in saved.info
    assert saved.size == (20, 40)  # 방향은 픽셀에 반영됐다 (지운 뒤에도 눕지 않음)


def test_png_text_and_exif_are_removed(api):
    signup(api)
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "GPS 37.55, 126.90")
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), "white").save(buf, "PNG", pnginfo=info)
    r = upload(api, content=buf.getvalue(), name="plan.png")
    saved = Image.open(io.BytesIO(api.get(f"/files/{r.json()['id']}").content))
    assert "Comment" not in saved.info and not saved.getexif()


def test_heic_becomes_jpeg(api):
    signup(api)
    buf = io.BytesIO()
    Image.new("RGB", (32, 16), "green").save(buf, "HEIF")
    r = upload(api, content=buf.getvalue(), name="IMG_0001.HEIC")
    assert r.status_code == 201, r.text
    assert r.json()["content_type"] == "image/jpeg" and r.json()["filename"] == "IMG_0001.jpg"


def test_broken_or_huge_image_is_refused(api, monkeypatch):
    signup(api)
    broken = upload(api, content=JPEG[:20] + b"\x00" * 50)
    assert broken.status_code == 422 and broken.json()["error"]["code"] == "file_broken"
    monkeypatch.setattr(images, "MAX_PIXELS", 100)  # 40 × 20 = 800 > 100: 압축 폭탄 취급
    assert upload(api).json()["error"]["code"] == "file_broken"


def test_type_is_checked_by_content_not_name(api):
    signup(api)
    assert upload(api, content=b"hello, not an image", name="photo.jpg").status_code == 415
    assert upload(api, kind="plan", content=PDF, name="plan.pdf").status_code == 201
    assert (
        upload(api, kind="photo", content=PDF, name="plan.pdf").status_code == 415
    )  # 사진 칸에 PDF 안 됨


def test_empty_big_and_wrong_kind(api, monkeypatch):
    signup(api)
    assert upload(api, content=b"").status_code == 422
    assert upload(api, kind="license").status_code == 403  # 사업자등록증은 업체만
    monkeypatch.setitem(service.RULES, "photo", (service.IMAGES, 10))
    assert upload(api).status_code == 413


def test_vendor_cannot_upload_customer_photos(api):
    vendor_signup(api)
    assert upload(api).status_code == 403


def test_login_needed(api):
    assert upload(api).status_code == 401


XLSX_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
XLSM_MAIN = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"


def zip_bytes(parts: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return buf.getvalue()


def xlsx_bytes(main: str = XLSX_MAIN, **extra: str) -> bytes:
    """엑셀이 만든 것과 같은 뼈대: 목차 · 관계 · 통합 문서 (합성 데이터)"""
    types = (
        '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types"><Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{main}"/></Types>'
    )
    return zip_bytes(
        {
            "[Content_Types].xml": types,
            "_rels/.rels": "<Relationships/>",
            "xl/workbook.xml": "<workbook/>",
            **extra,
        }
    )


def heic_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 16), "green").save(buf, "HEIF")
    return buf.getvalue()


def test_vendor_uploads_price_and_quote_docs(api):
    approved_vendor(api)  # 업체 종류 파일은 승인된 업체만(sec M5)
    sheet = xlsx_bytes()
    x = upload(api, kind="price_doc", content=sheet, name="단가표_2026.xlsx")
    assert x.status_code == 201, x.text
    assert x.json()["content_type"] == service.XLSX and x.json()["filename"] == "단가표_2026.xlsx"
    assert api.get(f"/files/{x.json()['id']}").content == sheet  # 엑셀은 그대로 둔다
    assert upload(api, kind="quote_doc", content=PDF, name="견적서.pdf").status_code == 201
    assert (
        upload(api, kind="quote_doc", content=xlsx_bytes(), name="견적서.xlsx").status_code == 201
    )
    heic = upload(api, kind="price_doc", content=heic_bytes(), name="견적서.HEIC")
    assert heic.json()["content_type"] == "image/jpeg"  # 사진은 위치 정보를 지우고 JPEG로
    assert upload(api, kind="work_photo").status_code == 201
    assert upload(api, kind="work_photo", content=PDF, name="a.pdf").status_code == 415
    assert upload(api, kind="portfolio", content=xlsx_bytes(), name="a.xlsx").status_code == 415


def test_only_real_xlsx_is_accepted(api):
    approved_vendor(api)

    def doc(content: bytes, name: str = "단가표.xlsx") -> int:
        return upload(api, kind="price_doc", content=content, name=name).status_code

    assert doc(zip_bytes({"a.txt": "hello"})) == 415  # 이름만 xlsx인 zip
    assert doc(zip_bytes({"[Content_Types].xml": f"<x>{XLSX_MAIN}</x>"})) == 415  # xl/ 없음
    assert doc(xlsx_bytes(XLSM_MAIN), "매크로.xlsm") == 415
    assert doc(xlsx_bytes(**{"xl/vbaProject.bin": "macro"})) == 415
    assert doc(xlsx_bytes(**{"xl/macrosheets/sheet1.xml": "<x/>"})) == 415
    assert doc(xlsx_bytes(XLSX_MAIN.replace("sheet.main", "template.main")), "서식.xltx") == 415
    assert doc(bytes.fromhex("d0cf11e0a1b11ae1") + b"0" * 64, "예전.xls") == 415
    assert doc(bytes.fromhex("504b0304") + b"0" * 64) == 415  # 깨진 zip
    assert doc(xlsx_bytes()) == 201


def test_vendor_docs_are_vendor_only_and_limited(api, monkeypatch):
    signup(api)
    for kind in ("price_doc", "quote_doc", "work_photo"):
        assert upload(api, kind=kind).status_code == 403
    approved_vendor(api)
    monkeypatch.setitem(service.RULES, "price_doc", (service.DOCS, 10))
    assert upload(api, kind="price_doc", content=PDF, name="a.pdf").status_code == 413
