# 믿집 문서

[프로젝트 소개](../README.md) · [기능 개발표](feature-roadmap.md) · [팀 기여 가이드](../CONTRIBUTING.md)

**현행 코드 기준**은 2026-11-19 팀 `dev` `344f6dc`(v3, PR #151 병합)입니다. [기능 개발표](feature-roadmap.md)의 **기존 187행·MVP 분류는 v2 `6d41f94` 당시 기준**으로 보존하고, 현행 v3 구현은 그 문서의 별도 표에서 확인합니다. 기능 담당자·진행 상태의 정본은 GitHub 이슈이며, 코드 반영·CI·AWS 배포는 각각 구분합니다.

## 핵심 문서

| 문서 | 내용 |
| --- | --- |
| [기능 개발표](feature-roadmap.md) | v2 기준 187개 기능의 개발·검증·MVP 기록 + v3 현행 구현 별도 요약 |
| [API 안내](api/README.md) | Swagger·인증·오류·v3 포함 현재 경로·업무 호출 순서 |
| [개발 환경](development.md) | Docker Compose, PC 직접 실행, 로컬 설정 |
| [테스트와 QA](testing.md) | 자동 테스트·화면 검증·실제 모델 평가 구분 |
| [기여 가이드](../CONTRIBUTING.md) | fork·이슈·PR·dev/main 통합·배포 |
| [작업 규칙](../AGENTS.md) | 코드 계층, 구현·검증·에이전트 규칙 |
| [v3 구조](v3/architecture.md) · [데이터 모델](v3/data-model.md) · [API 설계](v3/api.md) | v3 흐름·상태·엔드포인트 설계와 구현 대조 입구(코드가 최종 근거) |
| [v2 구조](v2/structure.md) · [v2 ERD](v2/erd.md) | 이전 v2 기준 화면/API 연결과 DB 관계(현행 v3 스키마라고 해석하지 않음) |
| [AI 상담 협약](agent-contract.md) | 현행 v3 무료/선택 LLM·SSE 흐름과 기존 v2 C안·후속 설계 구분 |
| [기준 데이터](reference-data.md) | 공유 CSV 현황, 적재·활성화·원본 관리 |

## 평가·검증·과거 기록

| 문서 | 내용 |
| --- | --- |
| [코드·PR·CI 근거](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/issues/143) | 당시 실행 기록과 현재 코드 기준을 구분한 문서화 검증 이력 |
| [RAG 평가](../evaluation/rag/README.md) · [답변 평가](../evaluation/answer/README.md) · [공정 평가](../evaluation/trade/README.md) | 질문 세트, 방법과 당시 측정 |
| [시공일지 처리 규칙](../data/sigong_ilji/SPEC.md) · [읽기 안내](../data/sigong_ilji/READER.md) | 로컬 전용 자료의 처리·공유 경계 |
| [초기 v2 구현 계획](v2/features.md) · [과거 dev/main 전환](archive/2026-11-dev-main-transition.md) | 과거 계획·일회성 절차(현행 절차 아님) |
| [v3 설계·검증 기록](v3/README.md) · [v3 AI 설계](v3/agents.md) · [v3 자료 조사](v3/data-sources.md) | 당시 가정·검증 범위가 섞여 있으므로 현행 코드·테스트로 다시 확인 |

과거 평가값과 당시 스키마 설명을 새로운 코드의 완료·품질 근거로 옮기지 않습니다. 현행 `dev` [CI](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/actions/runs/44516531421)·[Security](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/actions/runs/44516531323) 성공은 통합 검사 근거이며, 실제 유료 LLM·운영 AWS·모든 브라우저 시나리오 검증을 뜻하지 않습니다([QA 범위](testing.md#v3-병합-기준-검증-기록)).

## 문서 갱신 규칙

- README는 짧은 소개·실행 입구, 기능표는 상태·근거, API는 호출 계약, 설계 문서는 구조·상태 전이를 맡습니다.
- 구현은 코드와 테스트로, 통합은 CI로, 배포는 서버 상태로 각각 확인합니다. 문서·계획만으로 완료 처리하지 않습니다.
- 이슈에 목적·호출 흐름·검증 결과를 적고 PR에서 영향을 받은 문서를 연결합니다. 빈 문서를 작업마다 만들 필요는 없습니다.

| 변경 대상 | 함께 확인할 정본 |
| --- | --- |
| API·권한·오류 | [API 안내](api/README.md), 자동 OpenAPI, `frontend/`의 `pnpm gen:api` 생성물 `schema.d.ts` |
| DB·마이그레이션 | [v3 데이터 모델](v3/data-model.md), [v2 ERD](v2/erd.md)(이전 구조), [기준 데이터](reference-data.md) |
| 프롬프트·모델 | [AI 협약](agent-contract.md), [테스트·평가](testing.md) |
| CSV·검색 자료 | [기준 데이터](reference-data.md), [RAG 평가](../evaluation/rag/README.md) |
| 기능 상태·검증 | [기능 개발표](feature-roadmap.md), 관련 GitHub 이슈·PR 및 설계 문서 |
| 개발 환경·CI/CD | [개발 환경](development.md), [기여 가이드](../CONTRIBUTING.md), [테스트](testing.md) |
