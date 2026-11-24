# 14. 프로젝트 폴더 구조 (feat-v4-secretary)

기준: 통합 브랜치 `feat-v4-secretary` 5591b18(2026-11-24). 파일 수 · 줄 수는 `git ls-files`로 센 값이에요(그림 · 생성 파일 `schema.d.ts` 줄은 빼요). 층 이름은 AGENTS.md 2장 층 규칙이에요.

## 한눈에

| 폴더 | 파일 | 하는 일 |
| --- | --- | --- |
| `backend/` | 686 | FastAPI 앱(`app/` 353파일 · 9.2만 줄) · 마이그레이션(`migrations/` 54) · 시험(`tests/` 274파일 · 5.7만 줄) |
| `frontend/` | 1,361 | Next.js 화면(`app/` 라우트 · `components/` 480 · `lib/` 70 · 흐름 시험 `e2e/` 20 · 그림 `public/` 706) |
| `evaluation/` | 293 | 에이전트 평가(`v4/` 시뮬레이터 · 판정 · 레드팀 · QA 도구, `v3/` 판정 묶음 · 결과, 옛 v2 평가 세트) |
| `docs/` | 268 | 설계 · 결정 · 검증 기록(`v4/` 비서, `v3/` 화면 설계 · ADR · 검증, `v2/` · `api/` · `archive/`) |
| `data/` | 105 | 지식 원자료(`v3/` · `processed/` · `sigong_ilji/` 시공 일지 · `consult/`) |
| `deploy/` · `infra/` | 6 | AWS 배포(Caddy · compose · 배포 스크립트 · 런타임 환경) · CloudFormation(`infra/aws/staging.yaml`) |
| `.github/` | 13 | CI(`ci.yml`) · 보안(`security.yml`) · 배포(`deploy-staging.yml`) · 저장소 점검 스크립트 · 이슈 · PR 틀 |
| `.claude/` | 19 | 로컬 시험 · 실행 스크립트(`run-tests.sh` 역할별 DB · Redis, `env.sh`) |
| 루트 파일 | 10 | `AGENTS.md`(작업 규칙) · `CLAUDE.md` · `CONTRIBUTING.md` · `README.md` · `compose.yaml` · `.env.example` 등 |

## backend/app

```
backend/app/
├── main.py · worker.py · mcp_server.py     조립: 앱(미들웨어 · ROUTERS · health) · arq worker · 일정 MCP 서버
├── config.py · db.py · queue.py            설정 · DB 세션 · 큐 연결
├── demo.py · demo_vendors.py · seed.py     시연 · 목업 업체 · 시드(로컬 · 시험 환경만)
├── data_ingest.py · run_due.py             자료 적재 · 기한 일 돌리기 명령
├── assistant/          62파일 · 27,289줄   v4 비서(고객 · 업체)
│   ├── runtime.py · policy.py              턴 실행(LLM · 도구 상한, 문장 검사 SentenceGate) · 모델 값 거름 · 개인정보 가림
│   ├── actions.py · follow.py              승인 카드 실행(두 트랜잭션) · 이어 하기(카드 뒤 다음 카드)
│   ├── free.py · choices.py · asks.py      무료 모드(LLM 없이 규칙 답) · 카드 단추 고르기 · 요청 점검
│   ├── proactive.py · aftercare.py         먼저 말 걸기 트리거 · 공사 뒤 자동화(추가 금액 · 공사 끝 …)
│   ├── memory.py · research.py · pagecheck.py · weblinks.py · linkimage.py   사용자 기억 · 웹 조사 · 링크 확인
│   ├── service.py · router.py · repository.py · models.py · schemas.py · jobs.py
│   ├── tools/          도구 41개: customer(읽기) · propose(승인 카드) · cards · answer · aftercare · diy · floorplan · research · vendor
│   ├── experts/        공정 전문가 하위 에이전트: pick.py(LLM 없이 공정 고르기) · agent.py(코드 한 벌 + 공정별 설정)
│   └── prompts/        지시문 판(customer_v1~v4 · vendor_v1~v4 · expert_dobae/mokgong_v1~v2 · memory · nudge · researcher · brief)
├── agent/              64파일 · 8,994줄    v2 · v3 에이전트 + LLM 호출 한 곳(llm.py)
│   ├── llm.py · gate.py · intent.py · route.py   LLM SDK 호출 · 입구 관문 · 의도 분류(intent_lr_v1) · 길 고르기
│   ├── v3/             v3 답 · 관문 · 오케스트레이터 · 가이드 · 견적 설명 · 공정표 · composer/planner/general(옛 /ai/turns 전용)
│   ├── trades/         공정별 설정 dobae.py · mokgong.py(증상 낱말 · 주의점 · 실측 변수 · 준비)
│   └── cards/          지식 카드 14개(dobae · mokgong · common · service + 범위 밖 10공정)
├── calc/               33파일 · 6,969줄    계산 엔진(순수 함수): 표준견적서 · 가견적 · 공정표 · 실측 일정 후보(slots) · 기한 · 업체 점수
├── visit/               8파일 · 6,829줄    실측 요청 흐름(요청 → 기간 답 → 날짜 고르기 → 확정 → 실측 → 견적서) · 일정 바꾸기
├── schedule/            8파일 · 5,976줄    공사 날짜 · 확정 공정표 · 연기 · 일정 변경
├── refprice/           15파일 · 7,646줄    기준 단가(공공 단가 · 시장 단가 판 · 공휴일)
├── vendor/              7파일 · 3,369줄    업체 가입 신청 · 관리자 심사 · 업체 정보 · 단가 묶음
├── knowledge/          25파일 · 3,395줄    지식 검색(BM25 · pgvector · RRF) · 공정 지식 조각(expert/) · 적재(ingest · expert_pack)
├── v2/                 22파일 · 3,704줄    v2 상담(/v2/ask) · 공정 지시문 · 숫자 검사(guard, 공정 전문가가 씀)
├── project/             7파일 · 1,812줄    공사 만들기 · 집 정보 · 잠금 · 직접 할 일(diy)
├── chat/                7파일 · 1,593줄    v3 AI 칸 대화(/ai/turns) · 도구
├── quote/               6파일 · 1,375줄    표준견적서 · 실측 견적서 비교
├── thread/              7파일 · 1,220줄    고객-업체 채팅(실측 확정 뒤)
├── report/              6파일 · 1,139줄    신고 · 링크 신고
├── shared/             11파일 · 1,494줄    오류 · 시계 · id · 요청 제한 · 지역 · 요청 검사
├── review/ · files/ · auth/ · account/ · notify/ · realtime/ · usage/ · jobs/ · guest/
│                                           리뷰 · 파일(사진 위치 정보 지우기) · 로그인 · 탈퇴 · 화면 알림 · 실시간 · LLM 비용 장부 · 느린 일 · 손님 계산
└── demo_assets/        시연 사진 · 파일
```

층(AGENTS.md 2장): 조립 `main · worker · mcp_server` → 흐름 `chat → schedule → visit → quote` → 대상 `account | project | vendor` → 기반 `files | refprice | jobs | knowledge | notify → auth` → 도구 `agent → calc` → 공통 `shared → db | queue → config`. v4 비서(`assistant`)는 흐름 층 위에서 기능 service를 도구로 불러요.

## frontend

```
frontend/
├── app/                라우트(76파일)
│   ├── projects/[id]/  고객 공사: 대화(비서) · home(집 정보) · standard · plan · vendors(/[vid] · /reviews) · visits(/new · /[visitId])
│   │                   · quotes(/[visitId]/confirm) · schedule · docs · review
│   ├── vendor/         업체: 작업함 · requests/[visitId](/quote) · jobs/[dealId] · prices/[trade] · profile · reviews
│   ├── admin/ · guide/(백과: 첫 화면 · 글 · 단계 · 용어 사전) · start/(손님 시작) · my/ · notifications/
│   ├── login/ · signup/ · reset-password/ · account/ · faq/ · legal/ · offline/ · icons/
│   └── chat/ · v2/ · demo/ · dev/(부품 갤러리)
├── components/         화면 조각(480파일 · 4만 줄)
│   ├── assistant/      v4 비서 화면: Shell(대화 + 카드 창) · CardWindow · Feed · Message · Board · cards/(카드 19종) · kit/ · hooks/
│   ├── ui/             공용 부품(83): 단추 · 표 · 달력 · 공정표 칸 · 접기 · 시트 …
│   ├── pro/            업체 화면(48) · site/ 머리 · 틀(36) · v2/ v2 앱 화면(57)
│   └── visit · schedule · plan · project · confirm · compare · vendors · review · thread · guide · start · my · auth · admin · ai · home · notify · docs · report
├── lib/
│   ├── api/            서버 쪽 읽기 입구(영역마다 한 파일)
│   ├── backend/        server.ts(서버 → API) · client.ts(브라우저 → /api, SSE) · schema.d.ts(생성, 손으로 안 고침)
│   ├── guide/          백과 데이터(용어 · 글, 5,440줄) · mock/ 예시 데이터 · guest/ 손님 계산 표시 · assistant/ 카드 창 길(trail)
│   └── format.ts · labels.ts · session.ts · types.ts
├── e2e/                흐름 시험(Playwright) 20
└── public/             그림 706(백과 그림 · 아이콘 …)
```

## evaluation · docs · data

```
evaluation/
├── v4/       sim/(시뮬레이터) · sets/(시나리오 · 공정 세트) · intent/(의도 분류) · qa/(QA 도구) · redteam/ · request_check/ · trade_kb/ · tests/
│             + agent_judge.py(판정 에이전트) · grade.py(LLM 판정) · openai_live.py 등 23파일
├── v3/       judge_packs · judge_results · llm_live · llm_sim · results · sets
└── answer/ · ask_back/ · guide/ · intent/ · orchestrator/ · quote_explanation/ · rag/ · schedule/ · trade/   v2 · v3 시절 평가 세트
docs/
├── v4/       00 계획 ~ 14 폴더 구조 · adr/ · eval/(평가 결과) · research/
├── v3/       design/(화면 설계 115) · adr/(39) · verification/(38) · research/ · api.md · data-model.md · copy-guide.md …
└── v2/ · api/ · archive/
data/         v3/(65) · processed/(32) · sigong_ilji/(시공 일지) · consult/
```

## 안 쓰는 코드(코드 점검 2026-11-24 결과)

| 영역 | 크기 | 근거 |
| --- | --- | --- |
| 화면 | 78파일 · 5,043줄 | import 그래프로 아무도 부르지 않음(R7 점검, `d10-/reports/v4 비서 에이전트/audit/R7-frontend.md`) |
| 백엔드 파이썬 | 약 200줄 · 14파일(`agent/trade_agent.py` 통째) | v4가 부르지 않음(R6 점검) |
| 지시문 | 12파일 · 707줄(composer_v3~v8 · v3 옛 역할 4개 · v2 chat_v2 · v3) | 판 이름으로 부르는 곳 없음(R6 점검) |

지우기는 리팩터링 후보로 따로 정해요(점검 합친 보고 참고).
