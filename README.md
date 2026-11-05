# SKN34-FINAL-1TEAM

SK Networks Family AICAMP 34기 1팀 최종 프로젝트 **믿집**: 반셀프 인테리어 표준견적과 업체 가견적을 비교하는 서비스입니다.

- 웹 `frontend/`: Next.js · TypeScript
- API `backend/`: FastAPI · PostgreSQL · Redis · arq worker

## 실행

```bash
cp .env.example .env   # SEED_PASSWORD에 시험 계정 비밀번호(8자 이상)를 넣는다
docker compose up -d --build
docker compose watch web   # 화면 코드를 고치면 바로 반영한다 (이 창은 켜 둔다)
```

- 웹 http://localhost:3000 · API 문서 http://localhost:8000/docs
- 화면(web)은 폴더를 연결하지 않고, `docker compose watch`가 바뀐 파일만 컨테이너로 복사해요. 고치면 1초 안팎에 반영돼요(Turbopack). watch 없이 `up`만 하면 이미지를 만든 때의 화면 코드로 떠요.
- 컨테이너에서 만든 파일은 PC로 돌아오지 않아요. `pnpm gen:api`처럼 파일을 만드는 명령은 PC의 `frontend`에서 돌립니다.
- 화면을 더 빨리 고치려면 웹만 PC에서 띄워요: `docker compose stop web` 뒤 `cd frontend && pnpm dev --port 3100` (http://localhost:3100)
- `port is already allocated` 오류가 나면 그 포트를 이미 다른 프로그램이 쓰는 거예요. `.env`의 `*_HOST_PORT`를 바꾸고 다시 실행합니다.
- 시험 계정(로컬 전용, 자동 생성): `admin@` · `customer@` · `vendor@` · `vendor-pending@mitjip.local`, 비밀번호는 `.env`의 `SEED_PASSWORD`. 다시 만들 때 `docker compose exec api python -m app.seed`
- 실제 관리자 계정: `docker compose exec api python -m app.auth.cli create-admin --email <메일> --name 관리자`

## 개발

1. 개인 fork의 `main`을 팀 저장소 `main`과 맞춘 뒤 기능 브랜치를 만듭니다. 예: `feat-login`, `fix-api-error`.
2. 팀 `main`으로 PR을 올리고 CI와 리뷰를 통과하면 squash 병합합니다. `main`은 기능을 통합하는 기준 브랜치입니다.
3. 배포할 때 `main`의 CI 성공을 확인하고 팀 저장소에서 `main` → `dev` PR을 만듭니다(base: `dev`, compare: `main`). CI와 리뷰를 통과하면 merge commit으로 병합합니다.
4. `dev`의 Push CI가 성공하면 기존 AWS 개발 서버(스테이징)에 자동배포됩니다. 배포 후 서버에서 통합 테스트합니다.

`main` 병합만으로 `dev` 동기화나 AWS 배포가 시작되지는 않습니다. `dev`에서는 별도 개발을 하지 않으며, 서버에서 찾은 문제도 `main` 대상 PR로 수정한 뒤 다시 `dev`에 반영합니다. `dev` → `main` 승격 단계와 별도 운영 환경(`prod`) 배포는 현재 없습니다.

작업 규칙은 [AGENTS.md](AGENTS.md), 팀 작업 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)에 있습니다.
