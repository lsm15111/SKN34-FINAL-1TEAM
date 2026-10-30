# SKN34-FINAL-1TEAM

SK Networks Family AICAMP 34기 1팀 최종 프로젝트 저장소입니다.

믿집: 아파트 도배 · 목공 표준견적과 업체 가견적을 비교하는 서비스입니다. 지금은 초기 설정(웹 · API · DB · Redis 뼈대)만 있고, 기능은 이슈 단위로 더합니다. 작업 규칙은 [AGENTS.md](AGENTS.md)에 있습니다.

## 기술 스택

| 부분 | 쓰는 것 |
| --- | --- |
| 웹 `frontend/` | Next.js 16 · React 19 · TypeScript, pnpm, Node 24 |
| API `backend/` | FastAPI · SQLAlchemy(async) · Alembic, uv, Python 3.12 |
| 백그라운드 작업 | arq worker (Redis) |
| DB · 캐시 | PostgreSQL 17 · Redis 8 |
| 실행 | Docker Compose |

## 로컬 실행

```bash
cp .env.example .env
docker compose up -d --build
```

- 웹 http://localhost:3000 (첫 화면에서 API · DB · Redis 연결을 보여 줍니다)
- API 문서 http://localhost:8000/docs
- 코드를 고치면 웹 · API · worker가 자동으로 다시 뜹니다. 포트가 겹치면 `.env`의 `*_HOST_PORT`를 바꿉니다.
- 웹만 PC에서 띄울 때: `cd frontend && pnpm install && pnpm dev --port 3100`
- 테스트: `docker compose up -d db redis` 뒤 `cd backend && uv run pytest`

## 개발 흐름

1. `main`에서 작업 브랜치를 만듭니다. 예: `feat-login`, `fix-api-error`, `docs-architecture`
2. 작업 후 Pull Request를 생성합니다.
3. CI 통과 및 팀원 리뷰 후 `main`으로 병합합니다.
4. 배포 설정이 완료되기 전까지 자동 배포는 실행되지 않습니다.

## 현재 CI

Pull Request, `main` 푸시, 수동 실행 시 GitHub Actions에서 다음을 확인합니다.

- 잘못된 JSON 문법
- 남아 있는 Git 충돌 표시
- 텍스트 파일 끝의 불필요한 공백
- 실수로 추적된 `.env` 설정 파일
- backend: ruff, migration head가 하나인지, pytest(실제 PostgreSQL · Redis)
- frontend: API 타입이 명세와 같은지, typecheck, lint, build

로컬에서도 동일한 검사를 실행할 수 있습니다.

```bash
python .github/scripts/check_repo.py
```

> 위 네 가지는 저장소 공통 점검입니다. backend · frontend 검사는 [AGENTS.md](AGENTS.md) 7장에 로컬 명령이 있습니다.

## 추후 연결

- 개발·운영 배포 환경과 GitHub Environments
- 배포용 Secret 및 OIDC 권한 설정
- 운영 DB 마이그레이션 및 배포 후 상태 확인
- 운영 구성(compose.prod.yaml · Caddy · Cloudflare)

팀 작업 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.
