#!/usr/bin/env bash
# 비서 QA 명령 도구 입구. 사용: bash evaluation/v4/qa/qa.sh [--api URL] [--tag 이름] <명령> ... (README.md)
# backend 가상환경(httpx)으로 qa.py를 돌려요. 어느 폴더에서 불러도 돼요.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export PYTHONIOENCODING=utf-8
exec uv run --quiet --project "$ROOT/backend" python "$ROOT/evaluation/v4/qa/qa.py" "$@"
