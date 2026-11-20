# 기준 데이터 사용 안내

전처리 테이블을 사용하는 개발자와 AI 작업 도구가 참고하는 문서다. 테이블 용도와 조회 시 지킬 규칙을 설명한다. 스키마의 기준은 아래 모델과 마이그레이션이며, 구조나 사용 경로를 바꾸면 이 문서도 맞춘다.

## 스키마와 적재

- 스키마: [기준 자료 모델](../backend/app/refprice/models.py), [RAG 모델](../backend/app/knowledge/models.py), [0019 마이그레이션](../backend/migrations/versions/0019_reference_data.py), [0020 마이그레이션](../backend/migrations/versions/0020_ingest_provenance.py), [0023 마이그레이션](../backend/migrations/versions/0023_reference_simplify.py)을 기준으로 6개 테이블이 유지된다. `0020`은 행별 원본 기록과 임베딩 차원 검사를 추가한다.
- `0019`는 확장과 빈 테이블만 만든다. CSV 적재와 임베딩 생성은 수행하지 않는다.
- 전처리 CSV 데이터는 담당자가 DB에 수동으로 적재한다. 마이그레이션만 실행하면 데이터는 적재되지 않는다.

## 테이블별 용도

| 테이블 | 저장하는 내용 | 사용할 곳과 주의점 |
| --- | --- | --- |
| `ref_dataset_versions` | 자료별 버전, 출처, 적용일, 전처리 파일 경로·해시, 가공 프로필, 임베딩 모델·차원, 출처 기록(`provenance`), 활성 여부(`status BOOLEAN`, 기본값 `False`) | 계산·검색 전에 사용할 자료 버전을 선택한다. 데이터 행들이 참조하는 기준이며, 단순 파일 목록이 아니다. |
| `ref_floorplan_rows` | 예시 평면도의 공간별 물량, 요약·상세·합계, 단위와 적용 조건 | 표준 수량 산정의 참고 입력. 예시 평면도를 고객 집의 실제 측정값으로 취급하지 않고, 상세와 합계를 중복 합산하지 않는다. |
| `ref_unit_price_rows` | 일위대가의 작업 코드·규격, 구성 항목의 수치·단위, 기준 단위와 조건 | 공공 기준의 작업별 구성·수량을 해석할 때 쓴다. 모든 수치가 원화 단가인 것은 아니며 업체 확인 단가(`vendor_price`)와도 구분한다. |
| `ref_productivity_rows` | 표준품셈의 작업, 표 셀 수치, 행·열 문맥, 수치 역할, 적용 조건 | 품·소요량 등의 계산 입력 후보를 찾는다. 수치만 뽑지 않고 기준·단위·문맥을 함께 확인한다. |
| `ref_wage_rows` | 직종별 공표 임금, 공표일, 기준 근로시간, 조사 표시와 직종 정의 | 노무비 산정에 필요한 기준 임금을 찾는다. `occupation_wage` 행을 대상으로 직종·공표일·근로시간·조사 표시를 확인한다. |
| `rag_chunks` | 시방서·안내 문서의 본문 조각, 절, 페이지, 본문 해시와 임베딩 | 상담 주의점·설명 근거 검색. 계산용 단가·수량의 확정값을 만드는 테이블이 아니다. 출처는 연결된 버전과 페이지로 확인한다. |

## 전처리 파일과 관계

원본 PDF·엑셀은 프로젝트 폴더 밖에서 별도로 보관하고 저장소에 올리지 않는다. `data/raw/`는 사용하지 않으며 Git 추적에서도 제외한다. 저장소에는 `data/processed/`의 전처리 결과를 두고, 출처 파일명·페이지·해시 등 추적 정보는 유지한다.

`data/processed/`에서 관리하는 공유 자료는 CSV 13개, 55,652행(정형 4개·54,936행, RAG 9개·716행)이다. 가이드북은 59행이며, 시공일지는 포함하지 않는다. `data/consult/consult_knowledge_rag.csv`는 별도 상담 자료로 이 집계에 포함하지 않는다. CSV를 추가하거나 교체하면 **이 문서의 집계·출처 표**와 [검색 평가의 자료 구성](../evaluation/rag/README.md)을 검토한다. 프로젝트 README에는 수치를 중복 기재하지 않는다.

| CSV | 데이터 행 테이블 | 상태 처리 |
| --- | --- | --- |
| `01_floorplan_quantities.csv` | `ref_floorplan_rows` | 적재·활성화 시 `False` 유지 |
| `02_unit_price.csv` | `ref_unit_price_rows` | 적재·활성화 시 `False` 유지 |
| `03_standard_productivity.csv` | `ref_productivity_rows` | 적재·활성화 시 `False` 유지 |
| `06_construction_wages.csv` | `ref_wage_rows` | 적재·활성화 시 `False` 유지 |
| `04`, `05`, `07`~`12`의 `*_rag.csv` 8개 | `rag_chunks` | 새 버전 적재 시 `False`, 검증·활성화 후 `True` |
| `13_interior_guide_book_rag.csv` 59행 | `rag_chunks` | 새 버전 적재 시 `False`, 검증·활성화 후 `True` |

### 기준 자료 출처와 수집 예시

| 자료 종류 | 출처·기존 수집 예시 |
| --- | --- |
| 노무·품 | 2026 건설공사 표준품셈과 2026.9.1 노임 기준. 도배 작업량 예시: 하루 95㎡에 도배공 2명·보통인부 1명 |
| 실내건축 일위대가 | 도배바름 1㎡당 6,672원(당시 전처리 예시이며 현장 견적이나 현재 확정 단가가 아님) |
| 평면도·물량 | AI Hub 평면도 기반 팀 물량 산출서 예시: 59㎡형 벽 도배 126.97㎡, 84㎡형 180.09㎡ |
| 시공·공정 기준 | 건축공사 표준시방서(KCS 41 51 05 등), LH 전문시방서(LHCS 41 51 05 등). 도배 전후 건조·공정 순서의 참고 근거 |

원본 자료와 전처리 예시는 출처·단위·적용 조건을 확인해 사용한다. 위 값은 기존 프로젝트 소개에 기록된 **수집 예시**이며 실제 공사비·기간을 그대로 확정하는 기준이 아니다.

같은 파일 해시·모델·차원·가공 프로필의 RAG 버전이 있으면 검증 후 재사용한다. 이때 기존 활성 여부는 유지되며, 단순 `verify`는 활성 상태를 바꾸지 않는다.

- 현재 미사용 정형 자료 4종은 파일별 `dataset_key`로 구분한다(`app/data_ingest.py`의 `INACTIVE_DATASETS`). `load --execute`와 `verify --require-embeddings --activate`를 실행하면 선택한 해당 자료의 모든 버전을 `False`로 유지하며, 기존 활성 버전도 비활성으로 바꾼다. 테이블과 데이터 행은 삭제하지 않는다. 읽기 전용 명령은 상태를 바꾸지 않는다.
- 이 비활성 유지 규칙은 [PR #106](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/pull/106)의 수정 요청과 승인에 따라 반영됐다. 정형 자료를 계산에 다시 연결할 때는 사용 범위와 활성화 규칙을 별도 작업으로 정한다.
- 데이터 행 5개 테이블은 `(dataset_id, record_key)`가 기본 키다. `record_key`만으로는 버전 간 행을 식별할 수 없다.
- `dataset_id`와 `dataset_kind`는 `ref_dataset_versions`의 `id`와 `kind`를 함께 참조한다. 종류는 각각 `floorplan`, `unit_price`, `productivity`, `wage`, `knowledge`다.
- 계산용 행 4개 테이블의 `parent_key`는 같은 버전·같은 테이블의 상위 행을 참조한다. 표 제목·주석·합계·문맥도 저장하므로 모든 행이 계산 대상은 아니다.

### 상담 지식 자료 (v2)

| CSV | 만드는 법 | 보관 규칙 |
| --- | --- | --- |
| `data/consult/consult_knowledge_rag.csv` | `data/consult/rag5.json` → `python -m app.knowledge.json_csv` | Git에서 관리 |
| `data/processed/13_interior_guide_book_rag.csv` | 안내서 전처리 결과 59행 | 공유 허용, Git에서 관리 |
| `data/local/sigong_ilji_rag.csv` | 시공일지 쪽별 JSON → 쪽 경계 합치기 → CSV 변환, 검토본 1,156행 | 로컬 전용, Git에 올리지 않음 |

- 원본 PDF·엑셀은 저장소 밖에 보관한다([PR #103](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN34-FINAL-1TEAM/pull/103)). 시공일지의 이미지·쪽별 JSON·작업용 CSV는 Git에서 제외한 `data/local/`에 둔다. 전처리 방법은 [시공일지 규칙](../data/sigong_ilji/SPEC.md)과 [읽기 지시](../data/sigong_ilji/READER.md)를 따른다.
- 가이드북 CSV는 공유할 수 있다. 시공일지는 원본 PDF뿐 아니라 본문을 담은 이미지·JSON·CSV도 저장소에 올리지 않는다. 파일명을 바꾸거나 다른 폴더에 옮겨도 같은 규칙을 따른다. 시공일지 자료가 들어 있는 이전 Git 이력도 다시 push하지 않는다.
- 적재 · 활성화는 `app.data_ingest`로 한다. `dataset_key`는 CSV 확장자를 뺀 파일명이다. 안내서는 `13_interior_guide_book_rag`, 로컬 시공일지는 `sigong_ilji_rag`를 사용한다.
- 검색 번호는 파일 위치만으로 정하지 않는다. 행에 `ref`가 있으면 그 번호를 유지하므로 안내서는 K5001~, 시공일지는 K6000~다. `ref`가 없는 팀 자료만 자료명·행 ID 순으로 K2001~를 부여한다(`knowledge/sources.py`).
- 가이드북의 예전 로컬 파일과 현재 `13_interior_guide_book_rag.csv`, 시공일지의 기존 `14_sigong_ilji_rag.csv`와 로컬 `sigong_ilji_rag.csv`는 파일명이 달라 DB에서 각각 다른 자료로 취급된다. 기존 적재본이 있으면 활성 버전을 확인하고 같은 책의 두 자료를 동시에 활성화하지 않는다. 검색 번호가 중복되면 검색 자료 조립이 실패한다.
- 시공일지는 사례 · 후기 · 금액 표 조각을 `source_type` `platform`으로 둔다. 검색이 비용 · 법 · 안전 질문에서 이 종류를 빼므로 책 금액이 상담 금액 근거로 쓰이지 않는다.
- `json_csv`의 새 변환 결과는 공통 9열(`id` · `source` · `source_sha256` · `effective_date` · `content` · `section` · `page` · `category` · `trade`) 뒤에 검색 전용 열을 둔다. 기존 CSV는 열 이름으로 읽으므로 열 순서나 추가 메타데이터 열이 달라도 적재할 수 있다. 아래 형식은 새 변환 결과 기준이다.
  - `page`는 쪽 번호를 `,`로 잇는다. 쪽을 모르면 `1`과 `page_known=false`이고, 쪽을 알면 검색 결과의 절 뒤에 쪽이 붙는다.
  - `effective_date`는 문서 날짜가 `YYYY-MM-DD`일 때만 넣고, 그 밖의 날짜 글은 `doc_date`에만 둔다.
  - `category`는 `topics`에 `table`이 있으면 `table`, 아니면 `text`를 제외한 첫 값이다. 해당 값이 없으면 빈 값이다.
- 검색에만 쓰는 열(`source_org` · `source_url` · `source_type` · `ref` · `doc` · `trades` · `hints` · `rel` · `doc_date` · `page_known`)은 표에 열을 더하지 않고 행의 `provenance`에 남는다. `ref`를 빼면 팀 자료 규칙으로 읽혀 번호가 K2001~로 바뀌고 문서 종류 · 공정 · hints가 사라지므로 빼지 않는다.
- 9열만 있는 CSV도 적재 · 검색된다(출처 기관 · 주소는 빈 값).
- 원본이 파일 하나인 자료(로컬 책 등)는 JSON의 `docs[문서].sha256`에 원본 파일의 SHA-256을, 조각의 `pdf_page`에 원본 파일의 쪽을 담는다. 변환하면 CSV의 `source_sha256` · `page`가 그 값이 된다. 없으면 JSON 파일의 해시와 `page`를 쓴다(웹 자료를 묶은 상담 자료).

### 수동 적재와 검증

아래는 `backend/`에서 공유 가능한 가이드북 한 파일을 처리하는 예다. 로컬 CLI는 `APP_ENV=local` 또는 `test`에서만 실행하며, PostgreSQL에 마이그레이션을 적용하고 터미널의 `DATABASE_URL`을 먼저 설정한다. 이 CLI는 루트 `.env`를 자동으로 읽지 않는다. 시공일지는 `--directory ../data/local --dataset sigong_ilji_rag`를 사용하며 CSV를 저장소에 복사하지 않는다.

```bash
# 계획 확인: DB 변경 및 유료 API 호출 없음
uv run python -m app.data_ingest plan --directory ../data/processed --dataset 13_interior_guide_book_rag
# CSV 적재: 새 버전은 비활성으로 저장, 같은 버전은 재사용
uv run python -m app.data_ingest load --directory ../data/processed --dataset 13_interior_guide_book_rag --execute
# 임베딩: 기존 벡터를 재사용하고, 새 본문은 OpenAI에 전송해 유료 API 호출
uv run python -m app.data_ingest embed --directory ../data/processed --dataset 13_interior_guide_book_rag --execute
# 적재 내용과 임베딩 검증
uv run python -m app.data_ingest verify --directory ../data/processed --dataset 13_interior_guide_book_rag --require-embeddings
# 검증한 버전을 검색에 사용하도록 활성화
uv run python -m app.data_ingest verify --directory ../data/processed --dataset 13_interior_guide_book_rag --require-embeddings --activate
```

- 모델·차원·가공 프로필을 바꾸면 계획부터 같은 옵션으로 진행한다. 임베딩 호출 상한은 `--max-api-calls`로 지정한다.
- 새 임베딩을 만드는 `embed --execute`에는 `OPENAI_API_KEY`가 필요하다. 로컬 보관과 외부 API 전송은 별개이므로, 외부 전송이 금지된 자료에는 이 명령을 사용하지 않는다.
- 파일이 존재하지 않는 것과 정상적인 0행 CSV는 다르다. 없는 `--dataset`이나 CSV 없는 디렉터리의 검증은 오류이며, 삭제를 나타내는 정상 0행 스냅샷은 적재·검증할 수 있다.
- `--json`을 붙이면 결과를 하나의 JSON으로 출력한다. `embed --execute --json` 성공 결과에는 `embedding_usage`도 포함된다. 임베딩 호출·저장 중 실패하면 사용량과 오류는 stderr로 출력한다.
- 검증 완료와 검색 품질 확인은 구분한다. 검색 평가 명령과 자료 구성별 결과는 [RAG 평가 안내](../evaluation/rag/README.md)에 기록한다.

## 조회와 버전 선택 규칙

다음은 기능 연결 시 지켜야 할 규칙이다. DB 제약만으로 행의 계산 적합성이나 검색 품질까지 보장되지는 않는다.

1. 새 계산·검색에 사용할 자료는 `dataset_key`별 `status = True`에서 찾는다. 버전 번호나 생성 시각이 가장 큰 행을 무조건 고르지 않는다. DB는 자료별 활성 버전을 최대 하나로 제한하지만, 활성 버전이 없는 경우도 처리해야 한다.
2. `effective_date`, 출처와 행 문맥을 보고 목적에 맞는 자료인지 판단한다. 활성 여부만으로 계산 적합성이나 현행 기준 여부를 보장하지 않는다.
3. 계산 행은 `record_type`, 단위, 기준 단위, 적용 조건, 상위 문맥을 확인한다. `normalized_value`가 없거나 해석이 불명확한 값을 0이나 임의 단가로 채우지 않는다.
4. RAG 검색은 선택한 버전의 임베딩 모델·차원과 질의 임베딩을 맞추고, 임베딩이 없는 행을 처리한다. 임베딩 저장 여부와 답변 품질 검증은 별개다.
5. 결과에는 사용한 `dataset_id`와 행 키, 출처·적용일·버전 및 가능한 페이지 근거를 추적할 수 있게 한다. 저장된 견적을 재현할 때는 당시 고정한 버전을 사용하고 현재 활성 버전으로 바꾸지 않는다.
6. 기준 데이터 갱신이 일부 실패하면 기존 사용값을 유지한다. 새 자료의 적재·검증과 활성 상태 변경을 구분하고, 활성 전환은 한 트랜잭션으로 처리한다.

## 기능과 에이전트에서 사용하는 경로

아래는 `AGENTS.md`의 층 규칙에 따른 연결 방향이다.

- 계산: 기능 service가 기준 자료를 조회해 입력을 준비하고 `calc`에 전달한다. `calc`는 DB·HTTP·시계를 모르는 순수 함수로 금액·수량·기간·날짜를 계산한다.
- 지식 검색
  - v2 상담의 자료 검색(`search_knowledge`)은 서버 도구다. `v2/ask_tools.py` → `knowledge.service` → `knowledge.repository`(활성 버전만) → PostgreSQL. 키워드(BM25)와 임베딩 가까운 조각을 RRF로 합친다.
  - 지식 자료의 기간 숫자는 공사 기간 근거로 쓰지 않는다. 화면 도구 결과를 숫자 근거에서 빼는 것은 남았다(#124).
  - 시방서 검색용 외부 MCP 서버를 추가하지 않는다.
- 에이전트는 DB나 기능 service를 직접 호출하지 않는다. 프로젝트의 필수 입력은 코드가 먼저 읽어 전달하고, 추가 자료는 도구로 제공한다. 도구가 출처와 버전을 포함한 결과를 반환하도록 구현한다.
- 견적 설명 역할은 저장된 계산 결과를 설명한다. RAG 본문이나 LLM이 만든 숫자로 견적 금액을 대체하지 않는다.

스키마 존재, 데이터 적재, 서비스 연결, 검색·답변 품질 검증은 각각 따로 확인한다.

## 구조 단순화와 호환성

- `0023`은 미사용 정형 자료 4종을 `False`로 바꾸고, 그 외 자료는 `active`만 `True`, `draft`·`approved`·`retired`·`rejected`는 `False`로 바꾼다. 미정의 상태가 있으면 변경 전에 중단한다. `dataset_key`별 활성 버전은 최대 하나다.
- 버전의 `historical`, `current_rule_usable`, `calculation_usable`, `reference_usable`, 품셈의 `semantic_status`, RAG의 `review_reason`과 `ref_dataset_events`를 제거한다. 그 외 데이터 행과 임베딩은 유지한다.
- 삭제 전 이력 건수는 마이그레이션의 NOTICE로 출력한다. PostgreSQL 트랜잭션에서 수행하며 예상하지 못한 의존성이 있으면 실패·롤백한다. 실제 적용 전 이력과 제거 메타데이터를 별도로 백업해야 한다.
- downgrade는 스키마만 복원한다. 비활성은 `draft`, 제거한 불리언은 `False`, 검토 열은 NULL, 이력은 빈 테이블이 되므로 원래 상태·메타데이터·이력은 복구되지 않는다.
- CSV의 기존 메타데이터 열은 필수가 아니며 남아 있어도 행의 `provenance`에 보존한다. `--allow-calculation`은 제거한다. 새 적재는 비활성이고 검증 후 `--activate`로 전환한다. 단, 미사용 정형 자료 4종은 활성화 대상에서 제외한다.
- 현재 지식 검색은 `knowledge.repository.active_versions`에서 `kind = 'knowledge'`와 `status = True`인 버전만 조회한다. 정형 자료 4종은 위 비활성 유지 규칙을 따른다.
