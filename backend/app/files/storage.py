"""파일 내용을 디스크에 두고 꺼낸다. 운영에서 S3 같은 객체 저장소로 옮기면 이 파일만 바꾼다."""

from pathlib import Path

from app.config import settings
from app.shared.clock import now_utc
from app.shared.ids import uuid7


def _root() -> Path:
    return Path(settings.files_dir).resolve()


def save(data: bytes) -> str:
    """내용을 저장하고 저장 위치(key)를 돌려준다. 원래 파일 이름은 쓰지 않는다."""
    key = f"{now_utc():%Y/%m}/{uuid7().hex}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)  # 다 쓴 뒤에 이름을 바꿔서 반쯤 쓴 파일이 보이지 않게
    return key


def path_of(key: str) -> Path:
    path = (_root() / key).resolve()
    if _root() not in path.parents:
        raise ValueError("storage key outside root")
    return path


def remove(key: str) -> None:
    try:
        path_of(key).unlink(missing_ok=True)
    except ValueError:
        pass
