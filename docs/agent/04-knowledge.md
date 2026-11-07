# 04. 지식 구조 — 무엇을 어디에 두고 어떻게 찾나

에이전트가 아는 것은 전부 **출처가 붙은 데이터**에서 온다. LLM의 사전 지식으로 답하지 않는다. 근거: [T5 자재 · 시공](../research/T5_material_method.md), [T6 7장 한국어 검색](../research/T6_agent_tech.md), [T1 · T2 · T3 도메인 조사](../research/README.md).

## 1. 지식 여섯 가지

| 종류 | 예 | 누가 쓰나 | 어디에 | 바뀌는 주기 |
| --- | --- | --- | --- | --- |
| ① 설명 지식(RAG) | "실크는 기존 벽지를 뜯고 띄움 초배를 해요" | 코치 · 서브에이전트 · 견적 설명 | `kb_chunks`(pgvector + pg_bigm) | 수시(적재 명령) |
| ② 선제 안내 카드 | "목공이 끝나야 도배를 해요(몰딩 · 문틀 → 도배)" | 코드(트리거) → 화면 · 코치 | 데이터 파일 → `kb_cards` | 수시 |
| ③ 용어집 | 초배 · 정배 · 덧방 · 띄움 시공 · 걸레받이 · 문선 | 모든 에이전트(정확 조회), 화면 툴팁 | 데이터 파일 → `kb_terms` | 드묾 |
| ④ 정형 시공 지식 | 옵션 코드 → 레시피(이음 · 초배 · 로스 · 추가 줄 · 대기 시간), 공정 선후(DAG), 변경 규칙 | **계산 엔진**(시나리오 견적 · 공정표) | `refprice/options.py` · `refprice/process.py` (버전 상수) | 버전 올릴 때 |
| ⑤ 고객 표현 사전 | "호텔 같은 느낌" → 옵션 후보 + 되물을 것 + 연계 공정 플래그 | 서브에이전트(도구) | 데이터 파일(메모리 적재) | 수시 |
| ⑥ 출처 | 법령 · 시방서 · 제조사 · 기사 · 커뮤니티, 신뢰도 · 이용 조건 | 모든 지식이 참조 | 데이터 파일 → `kb_sources` | 수시 |

- ④를 DB가 아니라 코드 상수로 두는 이유: 계산 엔진은 DB를 모르는 순수 함수다(AGENTS.md §2). 지금 `refprice/book.py`가 단가를 상수로 두는 방식과 같고, 견적에 버전을 고정할 수 있다.
- ②③⑤⑥은 저장소의 데이터 파일(`backend/app/knowledge/data/*.jsonl`)이 원본이다. PR로 고치고 리뷰하고, 적재 명령으로 DB에 올린다. 사람이 읽고 고칠 수 있어야 하기 때문이다.

## 2. 표 설계 (migration 초안)

AGENTS.md §5 규칙(UUID7 · CHECK · JSONB는 통째로 남기는 기록에만)을 따른다. T5의 DDL에서 JSONB 칸은 관계형 칸으로 바꿨다.

### 2.1 `kb_sources`

| 칸 | 타입 | 제약 |
| --- | --- | --- |
| `key` | varchar(16) PK | 예 `S-LX-GUIDE` |
| `title` · `publisher` · `url` | varchar | url 필수 |
| `published_on` · `accessed_on` | date | accessed_on 필수 |
| `reliability` | varchar(10) | CHECK in (official · industry · news · community) |
| `rag_policy` | varchar(10) | CHECK in (full · summary · facts · link · blocked) |
| `license_note` | varchar(200) | |

### 2.2 `kb_chunks` (RAG)

| 칸 | 타입 | 제약 |
| --- | --- | --- |
| `id` | uuid PK | uuid7 |
| `key` | varchar(64) UQ | 예 `dobae.silk.removal`. 같은 키로 다시 적재하면 덮어씀 |
| `kind` | varchar(10) | CHECK in (card · term · recipe · defect · rule · faq · guide · check) |
| `trade` | varchar(10) | CHECK in (common · dobae · mokgong · oos) |
| `stage` | varchar(10) | CHECK in (start · quote · consult · pick · visit · deal · work · after · any) |
| `level` | smallint | 1 기초 · 2 공부한 소비자 · 3 심화 |
| `title` | varchar(80) | |
| `body` | text | **자체 요약만**(원문 전재 금지), 600자 이하 |
| `source_keys` | varchar(16)[] | 1개 이상(CHECK `cardinality ≥ 1`) |
| `conflict` | boolean | 출처끼리 값이 다르면 true → 답에서 '자료마다 달라요'를 밝힘 |
| `valid_to` | date | 가격 · 시세가 든 조각은 6개월 |
| `content_hash` | char(64) | 본문이 같으면 임베딩을 다시 만들지 않음 |
| `embedding` | vector(1536) | text-embedding-3-small 기준. 모델을 바꾸면 차원도 바꾼다 |
| `updated_at` | timestamptz | |

인덱스: `GIN (body gin_bigm_ops)`, `(trade, stage)`. HNSW는 1만 조각을 넘을 때 검토한다(지금 규모는 정확 검색이 충분히 빠르고 재현율이 완벽하다 — pgvector 기본 동작).

### 2.3 `kb_cards` (선제 안내)

| 칸 | 타입 | 제약 |
| --- | --- | --- |
| `key` | varchar(48) PK | 예 `mokgong.before_dobae` |
| `trade` · `stage` · `level` | | 위와 같음 |
| `why` | varchar(10) | CHECK in (money · schedule · defect · safety · legal · paper) — 왜 알아야 하는지 |
| `title` | varchar(40) | 한 줄 |
| `body` | varchar(300) | 2~3문장 '-해요'체 |
| `trigger_key` | varchar(48) | 코드에 있는 트리거 함수 이름(05 문서). 조건을 DB JSON으로 두지 않는다 |
| `priority` | smallint | 같은 때 여러 장이면 높은 것부터 |
| `source_keys` | varchar(16)[] | |

### 2.4 `kb_terms` (용어집)

`term`(PK) · `aliases varchar[]`(현장어: 미쯔바리 · 네바리 · 하구찌 …) · `easy`(쉬운 말 한 줄) · `detail`(2~3문장) · `trade` · `source_keys`. 뜻이 둘 이상인 현장어(예: '네바리')는 `detail`에 둘 다 적고 `conflict=true`.

### 2.5 대화 · 학습 · 브리프 (chat 쪽)

| 표 | 칸(요약) | 누가 씀 |
| --- | --- | --- |
| `chat_threads` | user · project(없을 수 있음) · `locked_until` · created_at | chat.service |
| `chat_messages` | thread · role(user · assistant) · route · agent · body(렌더링 끝난 글) · cards jsonb(**보낸 카드를 통째로 남기는 기록**) · source_keys[] · created_at | chat.service |
| `agent_runs` | message · agent · model · effort · input/output tokens · tool_calls · latency_ms · result(ok · guard_fail · llm_fail · limit) · guard_reason | chat.service |
| `brief_slots` | project · trade · slot_key · value · state(known · after_visit · unknown) · source(user · photo · vendor · default) · confirmed_at · updated_at. UQ(project, trade, slot_key) | chat.service(고객이 고르거나 확인했을 때만) |
| `learner_concepts` | user · concept_key · state(unseen · introduced · checked · mastered) · p_known numeric(3,2) · seen_count · last_seen_at. PK(user, concept_key) | chat.service |

- 에이전트는 이 표를 직접 쓰지 않는다. 출력에 `slot_updates_proposed` · `concepts_introduced`를 담으면 chat.service가 규칙(고객 확인 · 값 검사)을 통과한 것만 쓴다.

## 3. 정형 시공 지식 (`refprice/options.py` · `refprice/process.py`)

T5의 옵션 코드 체계 v0을 쓴다.

| 그룹 | 코드(예) | 계산 엔진이 쓰는 값 |
| --- | --- | --- |
| 도배 등급 | `WP_HAPJI_WIDE` · `WP_SILK_STD` · `WP_SILK_PREMIUM` · `WP_FABRIC_IMPORT` · `WP_MURAL` | 롤 폭 · 길이(실크 1,060mm × 15.6m, 광폭 합지 930mm × 17.75m — LX 공식), 이음(겹침 · 맞댐), 초배(없음 · 밀착 · 띄움), 철거 필요, 퍼티 대기 48시간, 자재 단가 등급 |
| 질감 · 패턴 | `TX_PLAIN` … `TX_PEARL`, `PT_RANDOM` · `PT_STRAIGHT` · `PT_HALF_DROP` | 바탕 민감도(퍼티 범위 가정), 무늬 로스(팀 기준 1개 + 범위) |
| 천장 몰딩 | `CP_MOLD_KEEP` · `CP_MOLD_FLAT_SLIM` · `CP_MOLD_STEP` · `CP_MOLD_MINUS` · `CP_MOLD_NONE` | 철거 줄 · 목공 줄 추가, 석고 덧방 면적, 도배 전 대기, 견적 범위 안 여부 |
| 걸레받이 | `BB_KEEP` · `BB_MDF_WRAP` · `BB_PVC` · `BB_MINUS` · `BB_NONE` | 단가 등급, 벽체 목공 필요(범위 밖 플래그), 바닥 뒤 설치 |
| 방문 · 문선 | `DOOR_LEAF_ABS` · `DOOR_SET_ABS` · `DOOR_FILM` · `DOOR_HIDDEN` · `CASING_SLIM_9` · `CASING_NONE` | 문틀 철거 줄, 도배 전 2일, 필름은 범위 밖 |
| 천장 | `CEIL_KEEP` · `CEIL_FLATTEN` · `CEIL_LIGHTBOX_REMOVE` · `CEIL_INDIRECT_ADD` | 평탄화 면적, 전기 1 · 2차 연계(범위 밖), 띄움 도배 필수 |

- **변경 규칙**(T5 R01~R31)은 `옵션 A → B`일 때 계산 엔진에 주는 효과(줄 추가 · 대기 시간 · 범위 밖 플래그)로 바꿔 둔다. 예: R12 평몰딩 → 무몰딩 = 몰딩 철거 줄 + 평탄화(석고 덧방) 줄 추가, 목공 뒤 1일 이상, 퍼티 +2일, 도배 경계 마감 주의.
- **공정 선후**(T5 3.6 · LX 공정 체크리스트): 철거 → 설비 → (전기 1차 ‖ 목공) → 타일 → 필름 · 도장 → (마루) → 도배 → (장판) → 가구 → 전기 2차 · 조명 → 입주 청소. 마루는 도배 전, 장판은 도배 후, 퍼티 → 도배 48시간. 출처끼리 다른 순서(도배 ↔ 마루, 몰딩 순서)는 `conflict` 표시 + "업체와 최종 확정" 문장을 붙인다.
- 1차 범위(도배 · 목공) 밖 공정은 DAG에 **설명용으로만** 넣고(`in_scope=False`), 금액 · 날짜는 만들지 않는다.

## 4. 데이터 파일 (원본)

```
backend/app/knowledge/data/
  sources.jsonl    {"key":"S-LX-GUIDE","title":"...","url":"...","reliability":"industry","rag_policy":"facts","accessed_on":"2026-11-08"}
  cards.jsonl      {"key":"mokgong.before_dobae","trade":"mokgong","stage":"consult","level":1,"why":"defect","title":"목공이 끝나야 도배해요","body":"...","trigger":"has_both_trades","priority":90,"sources":["S-..."]}
  terms.jsonl      {"term":"띄움 시공","aliases":["공간 초배","갓둘레 붙임"],"easy":"가장자리만 풀을 발라 붙이는 방법","detail":"...","trade":"dobae","sources":["S-..."]}
  chunks.jsonl     {"key":"dobae.silk.removal","kind":"guide","trade":"dobae","stage":"consult","level":2,"title":"...","body":"...","sources":["S-..."],"conflict":false}
  lexicon.jsonl    {"phrase":"호텔 같은 느낌","variants":["호텔식"],"intent":"style","options":["CP_MOLD_NONE","CEIL_INDIRECT_ADD"],"ask":["몰딩 철거까지 원하세요?"],"flags":["needs_carpentry","needs_elec"],"confidence":0.4}
```

- 카드 · 용어 · 표현은 적재할 때 `kb_chunks`에도 한 조각씩 만들어 검색되게 한다.
- 초안은 `feat-agent-knowledge` 브랜치에 T1 · T2 · T3 · T5 · T7에서 뽑아 만든다(사람 검수 필요 표시).

## 5. 적재와 검색

**적재** (`python -m app.knowledge.ingest`, worker로도 돌림)
1. 데이터 파일 검사(키 중복 · 출처 키 존재 · 길이 · 금지 단어) → 실패면 아무것도 바꾸지 않는다(AGENTS.md §3 "수집이 일부라도 실패하면 기존 값 유지"와 같은 원칙).
2. `content_hash`가 바뀐 조각만 임베딩(CI는 스텁) → upsert.
3. 데이터 파일에 없는 키는 지운다(원본은 파일).

**검색** (`knowledge.service.search(query, trade, stage, k=6)`)
1. 질의에서 조사를 떼고 2음절 이상 낱말을 뽑는다.
2. 벡터 top-40 + pg_bigm top-40 → **RRF**(k=60) → (선택) rerank-3 → 상위 6개.
3. 필터: trade(공정 에이전트는 자기 공정 + common), stage(가까운 단계 우선), `valid_to` 지난 조각 제외.
4. 돌려주는 것: key · title · body · source 이름 · 신뢰도 · conflict. 에이전트는 key를 인용한다(출력 검사가 확인).

**DB 준비**
- 로컬: `postgres:17-alpine` → pgvector + pg_bigm이 든 이미지로 바꾼다(`pgvector/pgvector:pg17`에 pg_bigm을 소스 빌드하는 Dockerfile). 
- 운영: RDS 17.6은 `vector` 0.8.0 · `pg_bigm` 1.2_20240606을 지원한다(AWS 표). 17.10 이상이면 0.8.2.
- migration: `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_bigm;` — RDS에서는 `rds.allowed_extensions` 확인.
- 임베딩 모델 결정: RAG 30으로 te3-small vs te3-large vs (로컬) bge-m3 · KURE-v1을 Recall@5 · nDCG@10으로 비교. te3-small은 한국어에서 약한 편(AutoRAG top-1 0.544 vs bge-m3 0.675)이라 **pg_bigm 하이브리드는 필수**다.

## 6. 이용 조건 정책

| 등급 | 대상 | 저장 |
| --- | --- | --- |
| 1 | 법령 · 공공 시방서 · 소비자원 · 공정위 · HB 기준표 | 수치 표 + 출처 표시 요약. 공공누리 유형 확인 뒤 원문 조각 검토 |
| 2 | 제조사(LX · 신한 등) | **규격 · 구조 · 인증 수치만** 구조화 + 링크. 설명은 자체 작성. 원문 문장 · 제품 이미지 전재 금지(신한벽지 약관은 사전승낙 없는 정보 제공을 금지) |
| 3 | 업계 블로그 · 커뮤니티 | 수치는 범위(최소 · 최대 + 날짜), 본문 저장 금지. AI 생성 표기가 있는 글(숨고 블로그 일부)은 신뢰 낮음 |

- 가격 · 시세가 든 조각은 `valid_to`를 6개월로 두고, 지나면 검색에서 빠진다.
- 상용화 전에는 제조사에 데이터 이용을 문의한다.
