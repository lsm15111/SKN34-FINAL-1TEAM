# 11. 문서 점검 — AGENTS.md · CLAUDE.md · README · .env.example

dev `6507699`(2026-11-06) 기준으로 문서와 코드를 대조했다. AI 코딩 도구는 CLAUDE.md(`@AGENTS.md`)를 읽고 그대로 따르므로, 틀린 문장은 잘못된 코드로 이어진다. **확실한 사실 오류**와 **팀 결정이 필요한 충돌**을 나눠 적는다.

## 1. 확실한 사실 오류 (고쳐도 되는 것)

| # | 문서 · 위치 | 지금 문장 | 실제 | 고칠 문장 |
| --- | --- | --- | --- | --- |
| F1 | AGENTS.md §2 백엔드 구조 | `아직 없음: quote · visit · schedule · refprice · jobs · calc · agent · chat · knowledge · mcp_server.py` | quote · visit · schedule · refprice · calc · notify는 구현됨. agent · chat · knowledge · mcp_server.py는 빈 파일. jobs는 패키지도 표도 없음 | 구현된 패키지를 목록에 넣고, `빈 뼈대: agent · chat · knowledge · mcp_server.py`, `아직 없음: jobs` |
| F2 | AGENTS.md §2 호출 흐름 · 층 규칙 | 느린 일은 `jobs` 행을 남기고 큐에 넣는다, 기반 층에 `jobs` | worker는 `ping` · `demo_reply`뿐. jobs 표 없음 | "jobs는 아직 없다(설계만)"를 붙이거나, 에이전트 작업 이슈에서 jobs 표를 처음 만든다 |
| F3 | README '주요 기능' · '서비스 흐름' | 가견적 요청 → 업체 가견적 제출 | 가견적 = 업체가 확인한 단가 × 표준 수량(계산 엔진). 요청 · 제출 단계 없음(AGENTS.md §1) | 흐름도에서 '가견적 요청 · 제출'을 '업체 고르기(가견적 자동 계산)'로 |
| F4 | README '주요 기능' 업체 | 가견적 · 실측 견적 제출 — 표준 행 양식으로 작성 | 실측 견적서는 업체 양식 파일 + 칸 4개(금액 · 부가세 방식 · 기간 · 유효기간). 줄로 바꾸지 않음 | "가견적 단가는 표준 행에, 실측 견적서는 자기 양식 파일로" |
| F5 | README '주요 기능' 견적 비교 | 표준견적서 ↔ 가견적 ↔ 실측 견적 **항목별** 비교 | 실측 견적은 줄이 없어 항목별 비교가 안 됨(합계 비교만) | "합계 비교 + 차이 설명"으로, 항목별은 견적서 판독(08 문서)이 생긴 뒤 |
| F6 | README '업체 추천' · AI 구조 그림 | 조건 필터 + 점수로 3곳 추천 | 미구현. `calc/vendor_score.py` 빈 파일. 업체 목록은 가견적 낮은 순 정렬뿐 | "예정" 표시 |
| F7 | README 표준견적서 데이터 | 인건비 '2026 상반기 표준일위대가', 도배 벽 1㎡ 노무비 6,656원, 실내건축 일위대가 6,672원 | 코드(`refprice/book.py`)는 **2026 하반기 표준시장단가** 벽 5,993원 · 천장 8,531원 | 코드가 쓰는 출처로 맞추고, 일위대가 값은 '비교용'으로 |
| F8 | README 프로젝트 구조 | 라우트 `request · measure · history` | 실제 라우트는 `standard · plan · vendors · visits · quotes · schedule · docs` | 실제 이름으로 |
| F9 | README 기술 스택 AI | "LLM 공급자 / 프레임워크 확정 후 기입" | `.env.example`은 이미 OpenAI(`gpt-6.1-terra`)로 정함 | 팀이 확정하면 기입(02 · 03 문서 추천: OpenAI Agents SDK 0.24.0) |
| F10 | docs/v2/features.md · structure.md | 상담 챗 보류, chat · knowledge · agent · mcp_server.py는 빈 뼈대 그대로 | README 일정은 11/20 에이전트 1차 | v2 문서가 끝났다고 표시하고 에이전트 문서(docs/agent)로 넘김 |
| F11 | AGENTS.md §2 프런트 구조 | 영역에 `chat` | `components/chat/`은 `.gitkeep`뿐, 상담 창은 `components/site/AskLauncher.tsx`(목업) | 채팅 화면을 만들 때 chat으로 옮긴다고 적음 |
| F13 | README 문제 정의 5. 업체 선정 | "인테리어 업체 **70~80%** 가 실내건축공사업 면허 없음 (서울신문 2026.04.01)" | 기사에 출처 기관 표기가 없고, 같은 수치는 2006년 창원 한 단지 기사에 '알려진 바'로만 나온다. 공식 통계를 찾지 못함(T1 5.7) | 수치를 빼거나 "업계 추정"으로 낮춘다. 소비자원 통계(2023~2026 상반기 피해구제 2,243건, 하자보수 불만 56.9%)로 바꾸는 것을 권장 |
| F14 | README 문제 정의 · 데이터 | "1,500만 원 미만은 건설업 등록 없이 시공 가능" | 맞음(시행령 제8조, 2026-06-23 시행본 원문). 다만 같은 업체 분할 계약은 합산하고(대법원 2018도3821), 고객이 산 자재의 시장가격도 넣는다 | 근거 한 줄을 붙인다 |
| F12 | AGENTS.md §2 · README 아키텍처 | PostgreSQL 17 **+ pgvector** | 로컬 `compose.yaml`은 `postgres:17-alpine`(pgvector 없음), 확장을 만드는 migration도 없음. 스테이징 RDS는 17.6(AWS 표 기준 `vector` 0.8.0 · `pg_bigm` 1.2_20240606 지원) | 지식 검색 이슈에서 로컬 DB 이미지를 pgvector + pg_bigm으로 바꾸고, `CREATE EXTENSION`을 migration으로 더한다(04 문서 5절) |

## 2. 팀 결정이 필요한 충돌

| # | 충돌 | 근거 | 제안 |
| --- | --- | --- | --- |
| D1 | **에이전트 구성이 문서마다 다르다.** AGENTS.md §4 = 오케스트레이터 · 가이드 · 공정 · 견적 설명 · 공정표 다섯. README = 가이드 없음, 오케스트레이터가 시작 순서 · 서류 안내. 파일은 `guide_agent.py` · `consult_agent.py`가 둘 다 있음 | 코드 · 문서 대조 | 02 문서안: 오케스트레이터는 **코드**, LLM 에이전트는 코치(가이드 확장) · 목공 · 도배 · 견적 설명 · 공정표 다섯 |
| D2 | **'공급자 하나'** 규칙인데 `.env.example`은 OpenAI · OpenRouter(Jev) · Voyage 셋 | T6 0-2 | "생성 LLM은 OpenAI 하나. 분류(Jev) · 임베딩 · 재순위 같은 보조 API도 `agent/llm.py`에서만 부르고 CI에서는 모두 스텁" |
| D3 | **'에이전트는 DB에 쓰지 않는다'**가 모호. Agents SDK 세션은 대화 기록을 프레임워크가 DB에 씀 | T6 0-2 | "에이전트 **도구**는 DB 쓰기 금지. 대화 · 사용량 · 학습자 상태 기록은 `chat.service`가 쓴다" |
| D4 | **호출 상한 '도구 4회'** 를 SDK `max_turns`로 착각하기 쉬움 | T6 1.3 | "도구 호출 수는 실행 컨텍스트 카운터 + tool guardrail로 센다. `max_turns=5`는 별도 안전장치" |
| D5 | **범위 밖 요청은 LLM 없이 안내** ↔ 사용자 요구 '최대한 많은 방향 커버' | 사용자 요청, T7 | **결정(2026-11-08, 이성민)**: 범위 밖 **공정**(바닥 · 욕실 · 필름 …)은 코치가 출처 있는 일반 지식만 안내(견적 · 공정표 없음, 범위 밖임을 밝힘). 인테리어와 무관한 요청만 LLM 없이 안내. AGENTS.md §4에 반영, 팀 PR에서 확인 |
| D6 | **가이드는 일반 금액 · 기간을 말하지 않는다** ↔ 지식 카드에는 '퍼티 후 2일', '도배 1~2주 전 예약' 같은 숫자가 있음 | T5 · T7 | 이 집 금액은 계속 금지(견적 설명 · 계산 엔진으로). 기간 · 비율 같은 **지식 숫자는 출처가 붙은 지식 조각에 있는 값만** 허용(숫자 검사기의 허용 집합에 넣음). 법 기준 금액(1,500만 원 · 승강기 사용료 법정 상한 없음 같은 사실)도 인용 조각에 있으면 허용 |
| D7 | **실측 견적서는 줄로 바꾸지 않는다** ↔ 차이 설명 · 누락 항목 검사 | T4 (e), T7 3.7 | 정식 저장은 그대로 두고, 차이가 범위를 넘으면 업체가 **사유 코드**를 고르게 한다. 파일 판독은 '참고'로만(08 문서, 팀 결정) |
| D8 | **PR 400줄 이하** ↔ 사용자 요청 '큰 단위 브랜치' | AGENTS.md §6 | 내 fork 브랜치는 큰 단위로 두고, 팀 PR로 올릴 때 이슈 단위로 쪼갠다(10 문서에 분할안) |
| D9 | **가견적 단가 행에 '실측 후' 줄이 없다**(철거 · 폐기물 · 짐 이동) → 가견적과 실측 간격의 큰 원인 | `calc/estimate.py` `PRICE_ROWS`, T4 추천 2 | 업체가 '실측 후' 줄마다 포함 / 별도 금액 / 실측 후를 고르게 단가 행을 넓힌다(migration 필요) |
| D10 | **표준견적서가 고른 공간을 무시**하고 늘 집 전체 면적으로 계산(문 개수만 '방' 수) | `quote/service.calc_trades` | 공간별 수량(06 문서 3.5) — 가장 큰 간격 원인이라 우선 처리 |
| D11 | **Jev는 LLM이 아니라 결정 모델**이고 한국어 지원이 문서에 없음(alpha API) | 공식 문서 직접 확인 | 의도 200 세트로 재고 채택. 떨어지면 `gpt-6-luna` enum 분류로 대체(공급자 수도 줄어듦) |

## 3. .env.example 검증 (공식 문서 직접 확인, 2026-11-08)

| 값 | 판정 | 메모 |
| --- | --- | --- |
| `OPENAI_AGENT_MODEL=gpt-6.1-terra` | 실재 | $1 / 캐시 $0.05 / 출력 $5 (1M 토큰), 컨텍스트 1.05M, 텍스트 + 이미지 입력. 날짜 스냅샷이 없어 eval 로그에 실행일을 남긴다 |
| `OPENAI_REASONING_EFFORT=low` | 유효 | terra 지원값 none · low · medium(기본) · high · xhigh · max. `minimal`은 없음 |
| `JEV_MODEL=typesafe/jev-1.14` | 실재 | 결정 모델, `POST /api/alpha/decisions`. 한국어 미확인 |
| `OPENAI_EMBEDDING_MODEL=text-embedding-3-small` | 실재 · 폐기 예정 없음 | 한국어 검색은 약함(AutoRAG top-1 0.544, bge-m3 0.675) → pg_bigm 하이브리드 필수, RAG 30으로 A/B |
| `VOYAGE_RERANK_MODEL=rerank-3` | 실재(T6 확인) | 한국어 성능 미확인. 코퍼스가 작아 이득이 작을 수 있음 → '재순위 없음'과 비교 후 결정 |
| `arq` 유지보수 전용 주석 | 맞음(T6 확인) | `arq==0.28.0` 고정 |
| (없음) `OPENAI_AGENTS_DISABLE_TRACING` | 추가 권장 | Agents SDK 트레이싱은 기본 켜짐 · 민감 데이터 포함 기본 True. CI는 1, 운영은 민감 데이터 끔 |
| (없음) 일정 MCP 내부 토큰 키 | 추가 권장 | 03 문서 8절: 백엔드가 5분짜리 내부 JWT 발급 |

## 3.1 이 브랜치에서 고친 것

- AGENTS.md §2 백엔드 구조: 구현된 패키지(notify · quote · visit · schedule · calc · refprice)를 넣고, 빈 뼈대와 '아직 없음(jobs)'을 나눴다(F1 · F2).
- AGENTS.md §2 표: pgvector가 아직 켜지지 않았다고 적었다(F12).
- AGENTS.md §4 끝: 설계 제안 문서를 읽고, 다르면 §4를 따르고 팀에 묻는다는 한 줄.
- README · docs/v2는 팀 소개 보존 원칙이 있어 고치지 않았다. 위 표의 F3~F10 · F13 · F14를 팀이 반영한다.

## 4. CLAUDE.md

- 내용은 `@AGENTS.md` 한 줄이다. Claude Code는 이 import로 AGENTS.md 전체를 읽는다. 구조는 문제없다.
- 위험: AGENTS.md의 사실 오류(F1 · F2)를 AI 도구가 그대로 믿는다. 예를 들어 "quote · visit가 아직 없다"를 보고 새 패키지를 또 만들 수 있다.
- 제안: AGENTS.md §4 끝에 "에이전트 작업 전에 `docs/agent/README.md`를 읽는다" 한 줄을 더한다. 설계가 팀 결정으로 바뀌면 §4를 고친다.

## 5. 확인 못 한 것

- Remote Control의 '인테리어' 세션: 이 PC 세션에서는 Remote Control이 꺼져 있어 다른 기기 세션 목록을 볼 수 없었다.
- README '표준견적서 데이터'의 CSV 12개 · 레코드 55,593개: 저장소에 없다(팀 드라이브로 추정).
- SKN34 강사 요구사항 원문(MCP 필수 · Harness · Verification 루프 · Graph DB 권장은 SKN29 문서 기준 기억).
