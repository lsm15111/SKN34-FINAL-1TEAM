"""관리자 계정을 만든다. 관리자는 가입 화면이 없다 (FBF-02).

docker compose exec api python -m app.auth.cli create-admin --email admin@example.com --name 관리자
비밀번호는 화면에 보이지 않게 입력받거나, MJ_ADMIN_PASSWORD 환경변수로 넘긴다.
"""

import argparse
import asyncio
import getpass
import os

from app.auth import service
from app.auth.schemas import clean_name, normalize_email
from app.db import SessionLocal


async def create_admin(email: str, name: str, password: str) -> None:
    async with SessionLocal() as s:
        await service.create_user(
            s, email=normalize_email(email), name=clean_name(name), password=password, role="admin"
        )
        await s.commit()


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.auth.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    args = p.parse_args()
    password = os.environ.get("MJ_ADMIN_PASSWORD") or getpass.getpass("비밀번호 (8자 이상): ")
    if len(password) < 8:
        raise SystemExit("비밀번호는 8자 이상이어야 해요.")
    asyncio.run(create_admin(args.email, args.name, password))
    print("관리자 계정을 만들었어요.")


if __name__ == "__main__":
    main()
