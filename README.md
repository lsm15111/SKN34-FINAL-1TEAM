# SKN34-FINAL-1TEAM

SK Networks Family AICAMP 34기 1팀 최종 프로젝트 **믿집**: 아파트 도배 · 목공 표준견적과 업체 가견적을 비교하는 서비스입니다.

- 웹 `frontend/`: Next.js · TypeScript
- API `backend/`: FastAPI · PostgreSQL · Redis · arq worker

## 실행

```bash
cp .env.example .env
docker compose up -d --build
```

- 웹 http://localhost:3000 · API 문서 http://localhost:8000/docs
- 관리자 계정: `docker compose exec api python -m app.auth.cli create-admin --email <메일> --name 관리자`

## 개발

1. `main`에서 브랜치를 만듭니다. 예: `feat-login`, `fix-api-error`
2. PR을 올리고, CI 통과와 팀원 1명 승인 뒤 병합합니다.

작업 규칙은 [AGENTS.md](AGENTS.md), 팀 작업 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)에 있습니다.
