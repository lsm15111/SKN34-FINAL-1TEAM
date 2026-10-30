# 팀 개발 가이드

## 브랜치와 Pull Request

- `main`은 공유 기준 브랜치입니다. 기능 개발은 별도 브랜치에서 진행합니다.
- 브랜치 이름: `작업유형-기능이름` (영어 소문자, 하이픈). 예: `feat-login`, `fix-api-error`, `docs-architecture`, `chore-initial-setup`.
- Pull Request에는 변경 목적, 주요 내용, 직접 확인한 테스트를 기록합니다.
- CI가 성공하고 팀원 한 명 이상이 승인한 뒤 병합합니다.
- 프로젝트별 실행 방법과 테스트 명령이 생기면 README와 CI를 함께 갱신합니다.

## 설정 및 비밀정보

- 로컬 API 키, 비밀번호, 접속 정보는 Git에 커밋하지 않습니다.
- 환경변수 예시는 값이 비어 있거나 가짜 값인 `.env.example`에 작성합니다.
- 실제 배포용 값은 배포 환경 확정 후 GitHub Environments의 Secrets/Variables에 보관합니다.
- 대용량 모델 가중치와 데이터셋은 Git 저장소 대신 별도 스토리지 또는 적절한 아티팩트 저장소를 사용합니다.
