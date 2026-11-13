"""테스트에서 함께 쓰는 합성 데이터와 동작 (실제 사람 · 업체 정보 아님)."""

import asyncio
import hashlib
import io

from PIL import Image

from app.config import settings

PASSWORD = "test-pass-1234"
PHONE = "01012345678"


def image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (40, 20), **save) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 120, 80)).save(buf, fmt, **save)
    return buf.getvalue()


JPEG = image_bytes("JPEG")
PNG = image_bytes("PNG")
PDF = b"%PDF-1.4\n" + b"0" * 64


def signup(api, email: str = "customer@mitjip.test", name: str = "고객") -> str:
    api.cookies.clear()
    body = {"name": name, "email": email, "password": PASSWORD, "phone": PHONE}
    r = api.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    return api.cookies.get(settings.session_cookie)


def use(api, token: str) -> None:
    api.cookies.clear()
    api.cookies.set(settings.session_cookie, token)


def make_admin(api, email: str = "admin@mitjip.test") -> str:
    from app.auth.cli import create_admin

    asyncio.run(create_admin(email, "관리자", PASSWORD))
    api.cookies.clear()
    r = api.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return api.cookies.get(settings.session_cookie)


def biz_no_for(email: str) -> str:
    """이메일마다 다른 합성 사업자등록번호 10자리 (실제 번호 아님)"""
    return f"{int(hashlib.sha256(email.encode()).hexdigest(), 16) % 10**10:010d}"


def vendor_signup(api, license=("사업자등록증.pdf", PDF), **over):
    """업체 가입 신청: 신청서 + 사업자등록증. license=None이면 파일 없이 보낸다."""
    api.cookies.clear()
    email = over.pop("email", "vendor@mitjip.test")
    data = {
        "name": "예시 담당자",
        "email": email,
        "password": PASSWORD,
        "biz_name": "예시도배",
        "owner_name": "예시 대표",
        "biz_no": biz_no_for(email),
        "phone": PHONE,
        "trades": ["dobae"],
        "areas": ["seoul/노원구", "seoul/도봉구"],
        **over,
    }
    files = (
        {"license_file": (license[0], license[1], "application/octet-stream")} if license else None
    )
    return api.post("/auth/vendor-signup", data=data, files=files)


def upload(api, kind: str = "photo", content: bytes = JPEG, name: str = "living.jpg"):
    return api.post(
        "/files", data={"kind": kind}, files={"file": (name, content, "application/octet-stream")}
    )


def no_surprises(results: list) -> list:
    """동시 시험 결과: AppError가 아닌 예외(교착 · 처리 못 한 오류)는 숨기지 않고 그대로 던진다."""
    from app.shared.errors import AppError

    for r in results:
        if isinstance(r, BaseException) and not isinstance(r, AppError):
            raise r
    return results


def knowledge_version(key: str, status: str = "active"):
    """지식 자료 버전 하나 (합성). 임베딩 없이도 검색 시험이 되게 상태를 바로 넣는다"""
    import uuid

    from conftest import query

    ident = uuid.uuid4()
    query(
        """insert into ref_dataset_versions
        (id,dataset_key,kind,version,source,processed_path,processed_sha256,build_profile,
         historical,current_rule_usable,calculation_usable,reference_usable,
         embedding_model,embedding_dimensions,provenance,status)
        values ($1,$2,'knowledge',1,'synthetic.pdf','synthetic.csv',$3,'test-v1',
                false,false,false,true,'test-model',3,'{}'::jsonb,$4)""",
        ident, key, uuid.uuid4().hex * 2, status,
    )  # fmt: skip
    return ident


def knowledge_chunk(dataset, ref: str, content: str, kind: str = "official") -> None:
    """ref 열이 있는 지식 조각 (합성)"""
    import json

    from conftest import query

    prov = {"id": ref, "ref": ref, "doc": f"d{ref}", "source": "안내", "source_org": "믿집",
            "source_url": "", "source_type": kind, "trades": "도배", "hints": "[]"}  # fmt: skip
    query(
        """insert into rag_chunks
        (dataset_id,dataset_kind,record_key,section,content,page_numbers,content_hash,provenance)
        values ($1,'knowledge',$2,'',$3,'{1}',$4,$5::jsonb)""",
        dataset, ref, content, "a" * 64, json.dumps(prov, ensure_ascii=False),
    )  # fmt: skip
