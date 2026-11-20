# 팀 기여 가이드

[문서 목록](docs/README.md) · [개발 환경](docs/development.md) · [테스트와 QA](docs/testing.md) · [기능 개발표](docs/feature-roadmap.md)

팀 저장소는 `SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM`입니다. 개인 fork를 `origin`, 팀 저장소를 `upstream`으로 두고 작업합니다. GitHub 기본 브랜치는 `dev`(2026-11-18 확인)이며 **`dev`는 기능 통합·검증, `main`은 검증한 배포 버전**입니다.

## 작업 순서

1. **이슈:** 목적·범위·완료 조건을 정하고 [기능 ID](docs/feature-roadmap.md)와 필요한 문서를 연결합니다.
2. **브랜치:** 팀의 최신 `upstream/dev`를 기준으로 개인 fork에서 `feat-…`, `fix-…`, `docs-…` 등 `type-기능이름` 브랜치를 만듭니다.
3. **구현·검증:** 작업 범위의 테스트를 실행하고 API·상태·권한 등이 달라지면 관련 문서와 기능표도 확인합니다.
4. **기능 PR:** 작업 브랜치 → 팀 `dev`로 PR을 엽니다. 이슈·문서 링크를 남기고, 작성자 본인이 최신 `dev`로 rebase합니다. **CI 통과와 팀원 1명 이상의 승인 후 squash 병합**합니다.
5. **통합 검증:** 공식 `dev`의 통합 결과를 확인합니다. PR 병합·이슈 종료는 배포나 실제 브라우저 QA의 증거가 아닙니다.
6. **승격 PR:** 공식 저장소의 `dev` → `main`으로 PR을 올립니다. 포함 작업·검증·배포 영향을 적고 리뷰 후 **merge commit**으로 병합합니다.
7. **스테이징:** 공식 `main` push의 필수 CI가 모두 성공하면 해당 SHA의 [Deploy staging](.github/workflows/deploy-staging.yml)을 호출하고 실제 웹·API 상태를 확인합니다. `dev` 병합만으로는 배포하지 않습니다.

브랜치 이름은 영어 소문자·하이픈을 사용하고 커밋 제목은 `type: 한국어 요약`으로 씁니다. type: `feat`·`fix`·`docs`·`test`·`chore`·`refactor`·`prompt`·`eval`. 다른 사람의 PR에 임의 동기화 merge 커밋을 넣지 않습니다.

## fork 최신화 예시

아래는 **팀원이 직접 실행하는 일반 개발 예시**입니다. 로컬 미반영 변경이 있으면 먼저 확인합니다.

```bash
git fetch upstream
git switch dev
git merge --ff-only upstream/dev
git push origin dev
git switch <작업브랜치>
git rebase dev
git push --force-with-lease origin <작업브랜치>
```

로컬 `dev`가 없다면 `git switch --create dev --track upstream/dev`로 만듭니다. 동기화는 작성자 본인이 수행하고 공유 중인 브랜치에 대한 강제 갱신은 사전에 조율합니다. 이전 기본 브랜치 전환은 [과거 기록](docs/archive/2026-11-dev-main-transition.md)에만 보관합니다.

## CI·배포 기준

| 이벤트 | 검사·결과 |
| --- | --- |
| `dev` 대상 기능 PR, `dev` push | 저장소 검사·backend·frontend·이미지와 Security 검사, **배포 없음** |
| 공식 `dev` → `main` 승격 PR | 공식 dev에서 온 PR만 허용, CI·리뷰 후 병합 |
| 공식 `main` push | 필수 CI 성공한 **정확한 SHA**만 AWS 스테이징 배포 시도 |
| `Deploy staging` 수동 실행 | 일반 재배포는 `main` 선택과 최신 main의 성공한 CI 확인 후 수행. **이전 이미지 롤백은 현재 CI 성공 여부와 무관** |

배포는 [CI](.github/workflows/ci.yml) · [경로·SHA 검사](.github/scripts/development_flow.py) · [배포 workflow](.github/workflows/deploy-staging.yml)를 따릅니다. AWS OIDC의 `main` 제한을 유지하며 별도 `prod` 환경은 아직 없습니다. 더 최신 main push가 생겼으면 오래된 실행은 배포하지 않습니다. 최초 배포 실패로 CI가 실패했다면 해당 CI 작업을 재실행하거나 main의 CI를 수동 실행해 **성공 확인 뒤 일반 재배포**합니다. 롤백은 이전 이미지를 복원하지만 **DB 마이그레이션은 되돌리지 않습니다**. 서버의 실제 배포 SHA와 활성 데이터를 확인해야 배포를 완료로 기록합니다.

## 이슈·PR·문서

- [이슈 템플릿](.github/ISSUE_TEMPLATE/task.md): 목적, 범위, 완료 조건, 바뀐 호출 흐름, 직접 실행한 검증 명령·결과, 미완을 기록합니다. 담당자·상태의 정본은 GitHub 이슈입니다.
- [PR 템플릿](.github/pull_request_template.md): 바뀐 것, 관련 이슈, 영향 받은 문서를 간단히 연결합니다.
- 설계·API·DB 계약을 바꿀 때는 [문서 목차의 갱신 규칙](docs/README.md#문서-갱신-규칙)을 확인합니다. **이슈만으로 충분한 작업에 빈 작업 문서를 새로 만들지 않습니다.** 여러 기능의 공통 계약이 달라질 때만 해당 기존 기준 문서에 근거를 보충합니다.
- 공통 파일 충돌은 [AGENTS.md](AGENTS.md)의 호출/수정 규칙을 따릅니다. `uv.lock`·`pnpm-lock.yaml`·생성된 `schema.d.ts`는 임의로 병합하지 말고 각 도구로 재생성합니다. 이슈·PR·커밋은 한국어로 짧게 기록합니다.

## 비밀정보

실제 키·비밀번호·세션·개인정보는 Git·이슈·PR·문서에 넣지 않습니다. `.env`는 Git에서 제외하고 `.env.example`에는 가짜 값과 설명만 둡니다. 모델 가중치·대용량 자료·공유 금지 원본은 별도 보관하며, 배포 비밀 값은 환경별 권한에 맞게 관리합니다.
