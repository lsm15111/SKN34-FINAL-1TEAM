# dev 통합 · main 배포 전환 (2026년 11월 과거 절차)

> 과거 기본 브랜치와 배포 workflow를 전환하던 때의 작업 기록이다. 일상 개발 절차로 다시 실행하지 않는다. 현재 기준은 [팀 기여 가이드](../../CONTRIBUTING.md)다. 이 아래는 당시 원문을 보존했다.

## 목표와 실제 설정

작업 이슈 → 최신 dev의 작업 브랜치 → dev PR(CI·리뷰) → 로컬·CI 검증 → 공식 dev → main 승격 PR → main Push CI 성공 → AWS 배포.

이 문서와 PR만으로 기본 브랜치·보호 규칙·AWS 설정은 바뀌지 않는다. 기본 브랜치 목표는 dev이고, main/dev의 PR·필수 CI·승인 요구와 강제 push 금지는 유지한다. CI는 기본 브랜치에 의존하지 않고 main push에서만 배포를 호출하며, AWS OIDC는 기존 main 제한을 유지한다.

## 전환 순서 (관리자 실행)

1. 이 PR의 CI·리뷰를 확인한다. 기존 `Deploy staging` 자동배포를 일시 중지하고 진행 중인 배포가 없는지 확인한 뒤 dev에 병합한다. 예전 main의 `workflow_run`은 dev CI 성공을 배포하므로 이 단계 없이 dev에 병합하지 않는다.
2. dev에 새 workflow가 반영된 것을 확인하고 기본 브랜치를 dev로 바꾼다. dev/main 필수 CI·리뷰 설정과 열린 작업 PR의 대상을 확인한다. 이슈·PR 템플릿 개편은 별도 작업이다.
3. 기본 dev의 새 `Deploy staging`이 `workflow_call`·수동 실행만 받는지 확인한 뒤 활성화한다. 중지 기간에 실패한 dev CI가 있으면 재실행하고 dev에서 배포 작업이 건너뛰어지는지 확인한다.
4. dev → main 승격 PR을 만들고 CI·리뷰 후 merge commit으로 병합한다. main에만 있던 README 소개 내용은 보존하고, 개발 규칙 부분만 새 흐름으로 맞춘다. 이 전환 PR에 README 소개 전체를 복사해 다른 작업을 섞지 않는다.
5. main Push CI 성공 뒤 첫 자동배포와 서버 상태를 확인한다. 수동 재배포는 main을 선택한다.

전환 중 workflow를 중지한 상태에서는 호출이 실패할 수 있다. 새 정의 활성화 후 해당 CI를 재실행한다. 기존 기본 main의 옛 정의가 남아 있는 상태에서 다시 활성화하지 않는다. 새 코드 없이 기본 브랜치만 먼저 바꾸거나 AWS 인증 대상을 dev로 넓히지 않는다.

## 확인 항목

- 기능 PR → dev 허용, 기능·외부 fork의 dev → main 차단, 공식 dev → main 허용.
- dev/PR/fork/tag 실행에서는 배포하지 않음.
- main의 필수 CI 실패 시 배포 작업 미실행.
- main push는 검사한 SHA를 배포, 더 최신 main이 있으면 이전 실행 건너뜀.
- 수동 재배포는 최신 main의 성공한 CI 기록을 요구, 수동 복구는 이전 이미지 사용.
- 기본 dev 전환 후에도 main의 OIDC 인증과 웹·API 정상 응답 확인.

로컬 정책 테스트: `python -m unittest discover -s .github/scripts/tests -v`. 실제 AWS 배포와 GitHub 설정 변경은 로컬 테스트로 검증했다고 기록하지 않는다.
