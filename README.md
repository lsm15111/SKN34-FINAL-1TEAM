# 🏠 믿집 (MitJip)

믿집은 반셀프 인테리어를 위한 견적·공정 관리 서비스입니다.
공공 기준 견적과 업체 견적을 비교하고 공사 일정을 관리합니다.

SK Networks Family AI Camp 34기 · FINAL 1팀

## 주요 기능

- **표준견적서:** 아파트 도배·목공의 수량과 참고 공사비를 계산합니다. 확정 시공 금액은 아닙니다.
- **업체·가견적 비교:** 공정별 승인 업체의 정보와 확인된 단가를 비교하고 실측을 요청합니다.
- **실측 견적 관리:** 업체가 자체 견적서 파일과 금액 요약을 제출하고, 고객이 버전을 확인해 업체를 확정합니다.
- **공사 일정:** 예상 공정표를 확인하고 업체의 날짜 제안·변경 요청·고객 수락과 공사 완료를 관리합니다.
- **AI 상담:** 공정 안내와 시공 기준 검색을 통해 견적 준비를 돕습니다.

기능별 구현·검증 근거와 미완성 범위는 [기능 개발표](docs/feature-roadmap.md)에서 확인할 수 있습니다.

## 서비스 이용 흐름

1. 집 정보와 도배·목공 범위를 선택합니다.
2. 표준견적서와 예상 공정표를 확인합니다.
3. 업체·가견적을 비교하고 실측을 요청합니다(공정당 최대 3곳).
4. 업체가 실측 견적 파일을 제출하면 내용을 확인하고 업체를 확정합니다.
5. 업체의 공사 날짜 제안을 수락하고 일정·추가 금액·완료 여부를 확인합니다.

업체 가입은 사업자등록증 제출과 관리자 심사를 거칩니다. 실측 견적은 업체 자체 양식 파일로 받습니다.

## 팀 소개

| 이름 | 담당 | GitHub |
| :---: | --- | :---: |
| 이성민 | 인프라 · MVP 흐름 UI/UX | [@lsm15111](https://github.com/lsm15111) |
| 이현준 | 백엔드 · 데이터 수집 | [@gksrkd2](https://github.com/gksrkd2) |
| 임형준 | 산출물 · LLM · 에이전트 | [@HyeongJjun](https://github.com/HyeongJjun) |
| 전진환 | ML · DL · 데이터 수집 | [@dfs32dfs](https://github.com/dfs32dfs) |
| 채정석 | 기획 · 데이터 수집 · 프론트엔드 | [@qnfdhk-rgb](https://github.com/qnfdhk-rgb) |

## 기술 구성

| 영역 | 주요 기술 |
| --- | --- |
| 화면 | Next.js 16, React 19, TypeScript |
| API·계산 | FastAPI, Python 3.12, Pydantic, SQLAlchemy |
| 인증·저장소 | 쿠키 세션, PostgreSQL 17, Redis, pgvector |
| AI·검색 | OpenAI SDK, 의도 분류, BM25 + 벡터 검색 |
| 인프라·배포 | Docker Compose, AWS EC2·RDS·S3, Caddy, GitHub Actions |

코드는 `frontend/`(화면), `backend/`(API·계산·마이그레이션), `evaluation/`(평가), `data/`(공유 전처리 데이터), `docs/`(개발 문서)로 나뉩니다. 자세한 구조는 [v2 구조](docs/v2/structure.md)와 [ERD](docs/v2/erd.md)를 참고하세요.

## 로컬 실행

Docker Desktop 및 Docker Compose를 준비한 뒤 저장소 루트에서 실행합니다. 기존 `.env`는 덮어쓰지 않습니다.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# .env에서 POSTGRES_PASSWORD를 설정한 후
docker compose up --build --watch
```

- 웹: http://localhost:3000
- API 문서: http://localhost:8000/docs
- 종료: `docker compose down`

개발 서버 직접 실행, 시험 계정, 환경변수·포트 설명은 [개발 환경](docs/development.md)에 있습니다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [문서 목록](docs/README.md) | 주요 문서 안내 |
| [기능 개발표](docs/feature-roadmap.md) | 구현 범위·검증·이슈·PR 근거 |
| [API 안내](docs/api/README.md) | 인증·오류·호출 순서·API 목록 |
| [기준 데이터](docs/reference-data.md) | CSV 현황, 출처와 적재·활성화 |
| [개발·기여 안내](CONTRIBUTING.md) | 이슈·PR·CI·배포 흐름 |
| [테스트와 QA](docs/testing.md) | 자동 검사와 화면·모델 검증 구분 |
