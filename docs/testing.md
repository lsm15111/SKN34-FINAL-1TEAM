# 테스트와 QA

[문서 목록](README.md) · [개발 환경](development.md) · [API 계약·오류](api/README.md) · [검증 기록](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/issues/143)

현행 v3 `dev`는 `344f6dc`(PR #151 병합), 기존 v2 기능표·[이슈 #143](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/issues/143)의 검사 기준은 당시 별도 커밋이다. 각 테스트 기록은 **실제로 검사한 SHA·환경·자료**에만 적용한다.

## 무엇을 확인했는지 구분하기

| 구분 | 확인할 수 있는 것 | 이것만으로 판단하지 않을 것 |
| --- | --- | --- |
| 코드 확인 | 구현 위치, 연결, 조건과 상태 전이 | 실제 실행 성공 |
| 자동 테스트 | 합성 입력·실제 테스트 DB로 검사한 계산·API·권한·저장 | 브라우저 조작이나 실제 모델 답변 품질 |
| 화면 QA | 입력·클릭·응답 표시·저장 전후·새로고침·반응형 동작 | 테스트하지 않은 다른 사용자 흐름 |
| 실제 모델 평가 | 해당 모델·프롬프트·자료·질문에서 나온 응답 | 다른 버전의 품질이나 모든 질문의 정확성 |
| AWS 확인 | 배포된 SHA와 실제 서버 동작 | dev의 최신 코드가 모두 배포됐다는 추정 |

HTTP 200, 화면 표시, 테스트 파일 존재, CI 성공은 서로 다른 근거다. 실행하지 않은 항목은 미검증으로 적는다.

## 로컬 자동 검사

저장소 루트:

```powershell
python .github/scripts/check_repo.py
python -m unittest discover -s .github/scripts/tests -v
```

`backend/`에서:

```powershell
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

`tests/conftest.py`는 `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_HOST_PORT`를 환경변수 또는 루트 `.env`에서 읽는다. **pytest 실행당 세션 시작 때 한 번** 기본 `mitjip_test` DB를 재생성하고 마이그레이션 올림·내림·재적용을 확인한다. **각 테스트 전** 전체 업무 표를 비우고 Redis 15번 DB를 초기화한다. 테스트용 인스턴스에만 연결한다. 다른 테스트 DB 이름은 `TEST_DB_NAME`, 호스트·포트는 `TEST_DB_HOST`·`DB_HOST_PORT`, Redis 주소는 `TEST_REDIS_URL`로 지정한다. `LLM_LIVE=false`를 유지한다.

변경 범위가 좁으면 해당 테스트부터 실행한다. 기존 v2 상담은 `tests/test_v2_ask.py tests/test_v2_ask_chat.py`, v3 상담은 `tests/test_v3_ai_api.py tests/test_v3_agent_turn.py tests/test_v3_agent_gate.py`, v3 기한 일·실측·채팅·리뷰·신고는 각각 `test_v3_jobs_sweep.py`·`test_v3_visit_flow.py`·`test_v3_thread_api.py`·`test_v3_review_api.py`·`test_v3_report_api.py`다. 데이터 적재는 `tests/test_data_ingest.py tests/test_reference_schema.py tests/test_knowledge_search.py`를 확인한다.

`frontend/`에서:

```powershell
pnpm install --frozen-lockfile
pnpm typecheck
pnpm lint
pnpm build
```

API를 바꿨으면 로컬 API를 실행한 뒤 `pnpm gen:api`로 생성 타입을 갱신한다. `lib/backend/schema.d.ts`를 손으로 고치지 않는다.

API 계약은 FastAPI `/openapi.json`의 **메서드·경로와 입력/성공 응답 스키마**를 기준으로 검사한다. 실행 시 오류 응답은 [API 안내](api/README.md#오류와-요청-제한)의 `error.code`·`fields` 형태도 별도로 확인해야 한다. 현재 FastAPI 커스텀 422 오류 형식과 자동 OpenAPI의 `HTTPValidationError`(`detail`) 스키마는 완전히 같지 않다. 로그인 쿠키, 역할·업체 승인, 본인 소유권, Origin 검사, 버전 409와 호출 순서는 [단일 API 안내](api/README.md)를 따른다.

## 화면 QA 기록

대상 SHA와 화면 주소, 계정 역할, 사용한 자료, 브라우저·화면 너비를 기록한다. 기대값을 먼저 정하고 입력 → 제안 → 확인 버튼 → 저장된 값 순서로 본다.

- 고객·업체·관리자 권한과 다른 사람의 자료 접근
- 정상 처리와 취소·중복 요청·오류 후 재시도
- 담기·확정 같은 버튼을 누르기 전후의 값, 새로고침 후 유지 여부
- 데스크톱과 360px 화면의 가로 넘침, 입력·버튼 조작
- 개발자 콘솔 오류와 실패한 API 응답

대화 QA에서는 “지금 집에 살아요”와 “공사 기간에도 공사할 집에서 살 예정이에요”를 같은 입력으로 취급하지 않는다. 짧은 “네”는 실제 앞 질문이 예/아니오로 답할 수 있는 경우에만 기대값을 정한다. 모델 해석, 서버 필터, 화면 반영 중 어느 단계에서 문제가 생겼는지 나눠 기록한다.

헤드리스 브라우저, 보이는 브라우저, API 호출만 한 검사를 구분한다. 스크린샷에 계정 정보·키·공유 금지 자료가 포함되지 않도록 확인한다.

## 평가 실행

| 대상 | 실행 위치와 명령 | 제한 |
| --- | --- | --- |
| 의도 분류 기준선 | 루트에서 `python evaluation/run.py intent --split dev --clf all_orchestrator` | 실제 학습 모델 성능과 다름 |
| 의도 분류 모델 | `backend/`에서 `uv run python ../evaluation/run.py intent --split dev --clf intent_lr` | backend 의존성 필요. Jev를 포함한 관문 전체 평가는 아님 |
| 의도 평가 코드 검사 | 루트에서 `python -m unittest discover -s evaluation/tests -v` | 분류 품질을 검증하는 테스트는 아님 |
| 검색 | [RAG 평가 안내](../evaluation/rag/README.md)의 자료 구성과 명령 | 로컬 전용 CSV가 필요한 실험은 자료 없이 재현했다고 적지 않음 |
| 답변 | backend에서 `uv run python ../evaluation/answer/run.py --cap 2.0` | 실제 모델·활성 지식 DB 필요, 유료 |
| 공정 분류·답변 | [공정 평가 안내](../evaluation/trade/README.md) | 코드 분류 검사와 실제 모델 응답을 구분 |

held-out 데이터는 반복 조정에 사용하지 않는다. 의도 평가의 held-out 실행에는 `--final`이 필요하다. 과거 평가 수치를 현재 결과로 옮기지 않는다.

## v3 병합 기준 검증 기록

2026-11-19 PR #151 검수 대상 `1573200`과 병합 `dev` `344f6dc`는 동일 Git tree로 확인됐다. 검증 범위와 실행 기록은 [문서 검증 이슈 #143](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/issues/143)에 구분해 남긴다. 아래는 **선택된 검증 범위**이며 전체 E2E·운영 품질 승인으로 확대하지 않는다.

| 구분 | 실제 확인 결과 | 범위·한계 |
| --- | --- | --- |
| 백엔드 | 선택 테스트 **171개 통과, 실패 0** | 전체 테스트를 모두 실행했다는 뜻은 아님 |
| 원본 headed E2E | **20건 중 9건 통과, 11건 실패** | 변경 전 문구·데스크톱 링크 기대값이 오래되어 실패한 항목 포함. 실패한 후속 단계는 검증되지 않음 |
| 별도 보이는 화면 검증 | **PC 4개 흐름·360px 휴대폰 3개 흐름 통과** | 비회원 견적·가입, 업체 응답·채팅, 견적·공사 일정, 업체 승인 등 선별 흐름. 모든 시나리오 통과 주장은 하지 않음 |
| v3 AI | 전용 QA DB에 저장소 RAG CSV·v3 JSONL 적재 후 **무료 7건·LLM 모드 3건**, 실제 LLM 재작성 **1건** 확인 | **키워드 검색만 사용**, 임베딩 호출 없음. 평가 질문 일부는 자료 부족을 안내했으며 전체 답변 품질 점수 없음 |
| 보안·운영 | 현행 [CI](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/actions/runs/44516531421)·[Security](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/actions/runs/44516531323) 성공 | AWS/운영 환경·전체 파일 보안 감사·모든 실제 모델 질문 검증 없음 |

**확인된 잔여 오류:** v3 `agent/v3/check.py`에서 은행명 뒤 공백 4칸이 있는 합성 계좌번호가 AI 대화 이력에 남는 [이슈 #154](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/issues/154)가 재현됐다. 수정 [PR #155](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/pull/155)는 기준 `dev`에 **미병합**이므로 해결로 기록하지 않는다. 실제 외부 LLM 유출이나 운영 사고가 확인됐다는 뜻도 아니다.

v3 `POST /ai/turns`는 답·저장 완료 후 `token`(완성된 문장)·`card`·`done` 이벤트를 내보낸다([구현](../backend/app/chat/router.py)). 이 SSE를 모델 토큰의 실시간 생성, 완전한 브라우저 E2E 통과 또는 RAG 전체 데이터 적재 검증으로 기록하지 않는다.

## CI와 승인

### 병렬 테스트와 필수 검사

`Backend tests (1/8)`부터 `(8/8)`까지 독립 GitHub 호스팅 VM에서 실행한다. 각 작업은 PostgreSQL·Redis를 따로 가지며 기존 DB 재생성, 마이그레이션 올림·내림, 테스트별 초기화를 유지한다. 같은 DB·Redis에 여러 pytest를 동시에 연결하지 않는다.

[분배 스크립트](../.github/scripts/ci_backend.py)는 전체 pytest collection의 node ID를 정렬해 8개 작업에 번갈아 배정한다. 새 테스트와 파라미터화 사례도 포함된다. UUID처럼 매번 바뀌는 입력은 `pytest.mark.parametrize`의 `ids`를 지정해 수집 ID를 일정하게 유지한다. ruff, migration head 하나 검사, pytest, `alembic check`는 각 작업에서 실행한다.

필수 `Backend`는 항상 실행하여 먼저 8개 작업의 성공을 확인한다. 실패·취소·건너뜀은 실패로 처리한다. 이어 현재 workflow run·커밋의 결과를 검증하여 collection 불일치, 잘못된 분배, 실행 누락·중복, 0개 테스트, skip·xfail을 차단한다. 결과 파일이 없으면 업로드도 실패한다. 실패한 작업만 재실행하면 해당 결과를 교체하며, 작업 상태가 실패하면 이전 결과로 통과할 수 없다.

`Frontend`는 같은 checkout과 `backend/uv.lock`으로 OpenAPI를 직접 생성하고 기존 타입 비교·typecheck·lint·build를 병렬 실행한다. 명세 생성 실패는 필수 Frontend 실패로 이어진다. 기존 필수 검사 이름, 보안 검사와 main 배포 조건을 유지한다. 백엔드와 OpenAPI 생성은 uv `0.13.9`와 전용 캐시 키를 함께 쓴다. 캐시는 의존성 다운로드만 줄이며 `uv sync --locked`와 모든 검사는 항상 실행한다.

로컬 전체 검사 명령은 기존 `uv run pytest -q`다. CI 분배 재현은 격리된 테스트 서비스를 준비한 뒤 backend에서 `uv run python ../.github/scripts/ci_backend.py run --shard 1 --shards 8 --report ../backend-reports/shard-1.json`을 실행한다. shard는 1부터 8까지다. 여덟 결과를 모은 뒤 루트에서 `python3 .github/scripts/ci_backend.py verify --shards 8 --reports backend-reports`로 검증한다. 속도는 가장 느린 작업과 runner 대기 시간에 좌우되므로 실제 CI 시간으로 비교한다.

[CI](../.github/workflows/ci.yml)는 저장소 검사, backend, frontend, 컨테이너 빌드를 실행한다. [Security](../.github/workflows/security.yml)는 CodeQL · Dependency Review · Audit(`pip-audit`·`pnpm audit`·`bandit`·`semgrep`)를 실행한다. 유료 모델 호출은 하지 않는다.

리뷰는 최종 PR head 기준으로 남긴다. 수정이 필요한 재현 오류는 원인 파일·입력·실제 결과·수정 방향을 적고 Request changes로 남긴다. 범위와 검증이 충족되면 승인한다. CI 통과와 업무 동작의 승인 판단은 별개다.
