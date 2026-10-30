# syntax=docker/dockerfile:1
# 믿집 API (FastAPI) 이미지. dev는 코드 바인드 마운트 + 자동 재시작, prod는 dev 의존성 없이.
FROM python:3.12.10-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --no-dev
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --system --uid 10001 app
USER app
# 프로세스 2개: 하나가 무거운 일(비밀번호 해시 · 사진 처리)을 할 때 다른 요청을 받는다.
# DB 연결은 프로세스마다 최대 10개(app/db.py). 끌 때는 하던 요청을 20초까지 마친다.
# 연결 유지는 Caddy(60초)보다 길게 둔다. 짧으면 Caddy가 이미 닫힌 연결로 POST를 보내 502가 난다.
# X-Forwarded-For는 Caddy가 덮어써서 믿을 수 있다. api 포트는 운영에서 밖으로 열지 않는다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-graceful-shutdown", "20", "--timeout-keep-alive", "75", "--proxy-headers", "--forwarded-allow-ips", "*"]
