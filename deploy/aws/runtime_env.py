#!/usr/bin/env python3
"""EC2 배포 시 Secrets Manager 값을 메모리에서만 읽어 Compose 환경 파일을 만든다."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

AI_KEYS = frozenset(
    {
        "LLM_LIVE",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "JEV_ENABLED",
        "JEV_MODEL",
        "OPENAI_AGENT_MODEL",
        "OPENAI_REASONING_EFFORT",
        "OPENAI_LIGHT_MODEL",
        "OPENAI_LIGHT_EFFORT",
        "OPENAI_LIGHT_ROLES",
        "OPENAI_EMBEDDING_MODEL",
    }
)
FLAGS = frozenset({"LLM_LIVE", "JEV_ENABLED"})
MISSING_SECRET = re.compile(
    r"\s*An error occurred \(ResourceNotFoundException\) "
    r"when calling the GetSecretValue operation: [^\r\n]*\s*"
)


class RuntimeConfigError(Exception):
    """호출자에게 원본 비밀값을 노출하지 않는 고정 오류."""


def _valid(value: object) -> str:
    if type(value) is not str or any(c in value for c in "\r\n\x00"):
        raise RuntimeConfigError("Invalid runtime configuration")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise RuntimeConfigError("Invalid runtime configuration") from None
    return value


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeConfigError("Invalid runtime configuration")
        result[key] = value
    return result


def _decode_object(raw: str) -> dict:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError):
        raise RuntimeConfigError("Invalid runtime configuration") from None
    if type(value) is not dict:
        raise RuntimeConfigError("Invalid runtime configuration")
    return value


def _secret(secret_id: str, region: str, *, optional: bool = False) -> dict | None:
    try:
        result = subprocess.run(
            [
                "aws",
                "secretsmanager",
                "get-secret-value",
                "--secret-id",
                secret_id,
                "--region",
                region,
                "--output",
                "json",
                "--no-cli-pager",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeConfigError("Unable to read runtime configuration") from None
    if result.returncode:
        if optional and MISSING_SECRET.fullmatch(result.stderr or ""):
            return None
        raise RuntimeConfigError("Unable to read runtime configuration")
    response = _decode_object(result.stdout)
    secret_string = response.get("SecretString")
    if type(secret_string) is not str:
        raise RuntimeConfigError("Invalid runtime configuration")
    return _decode_object(secret_string)


def _ai_config(secret: dict | None) -> dict[str, str]:
    if secret is None:
        return {"LLM_LIVE": "false"}
    if not set(secret).issubset(AI_KEYS):
        raise RuntimeConfigError("Invalid runtime configuration")
    result = {key: _valid(value) for key, value in secret.items()}
    for key in FLAGS & result.keys():
        if result[key].lower() not in {"true", "false"}:
            raise RuntimeConfigError("Invalid runtime configuration")
        result[key] = result[key].lower()
    result.setdefault("LLM_LIVE", "false")
    if result["LLM_LIVE"] == "true" and not result.get("OPENAI_API_KEY", "").strip():
        raise RuntimeConfigError("Invalid runtime configuration")
    return result


def _compose_value(value: str) -> str:
    """기본은 단일 인용. Compose가 표현 못 하는 역슬래시 조합만 이중 인용한다."""
    value = _valid(value)
    for index, char in enumerate(value):
        if char == "'":
            preceding = len(value[:index]) - len(value[:index].rstrip("\\"))
            if preceding % 2:
                break
    else:
        if (len(value) - len(value.rstrip("\\"))) % 2 == 0:
            return "'" + value.replace("'", "\\'") + "'"
    # Compose dotenv 단일 인용은 '직전 홀수 개 역슬래시'와 끝의 홀수 개 역슬래시를
    # 원문대로 나타내지 못한다. 이때는 이중 인용 + 명시적 escape로 보간을 막는다.
    return (
        '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$") + '"'
    )


def _write_atomic(target: Path, content: str) -> None:
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".env.runtime.", dir=target.parent)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            else:  # Windows 로컬 테스트; 운영 EC2는 Linux fchmod를 사용한다.
                os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    except (OSError, UnicodeError):
        raise RuntimeConfigError("Unable to write runtime configuration") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def render(args: argparse.Namespace) -> None:
    for item in (
        args.region,
        args.stack,
        args.db_secret_id,
        args.db_host,
        args.bucket,
        args.host,
    ):
        if not _valid(item):
            raise RuntimeConfigError("Invalid runtime configuration")
    database = _secret(args.db_secret_id, args.region)
    assert database is not None
    username = _valid(database.get("username"))
    password = _valid(database.get("password"))
    if not username or not password:
        raise RuntimeConfigError("Invalid runtime configuration")
    ai = _ai_config(_secret(f"{args.stack}/ai-runtime", args.region, optional=True))
    values = {
        "APP_ENV": "staging",
        "API_ROOT_PATH": "/api",
        "DATABASE_URL": (
            f"postgresql+asyncpg://{quote(username, safe='')}:{quote(password, safe='')}"
            f"@{args.db_host}:5432/mitjip"
        ),
        "REDIS_URL": "redis://redis:6379/0",
        "FILES_S3_BUCKET": args.bucket,
        "AWS_DEFAULT_REGION": args.region,
        "ALLOWED_ORIGINS": f"https://{args.host}",
        **ai,
    }
    content = "".join(
        f"{key}={_compose_value(value)}\n" for key, value in values.items()
    )
    _write_atomic(Path(args.output), content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the EC2 Compose runtime environment"
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--stack", required=True)
    parser.add_argument("--db-secret-id", required=True)
    parser.add_argument("--db-host", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        render(args)
    except Exception:  # noqa: BLE001 - 실패 원문에 Secret 값이 포함될 수 있다.
        # AWS CLI stderr·JSON·파이썬 예외 문자열에는 비밀값이 들어 있을 수 있다.
        print("Runtime environment configuration failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
