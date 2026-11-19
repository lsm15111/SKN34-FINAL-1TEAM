# 에이전트 설계 웹 조사 (2026-11-19)

- 누가: 리드가 하위 에이전트 다섯에게 갈래를 나눠 맡겼어요(웹 검색 · 페이지 열기). 리드가 숫자 · 주장을 다시 읽고 이 문서로 묶었어요. 유료 API 0회.
- 갈래: A 구조 · 라우팅 · 협업 / B 한국어 검색 · 질문-카드 맞추기 / C 비용 · 지연 / D 짧은 답 · 쉬운 말 / E 다양한 질문 · 평가 · 개선 루프
- 읽는 법
  - 숫자는 출처가 잰 값이에요. 평가 세트 · 지표가 출처마다 달라서 출처끼리 바로 견주면 안 돼요.
  - 회사 발표 숫자는 '회사 발표'라고 적었어요. 찾지 못한 것은 '확인 못 함'이에요.
  - 세션 전체 웹 검색 한도(200회)가 차서 일부 주제는 덜 봤어요(각 갈래 끝에 적음).
- 설계에 쓴 방식: [../agent-next.md](../agent-next.md)

## A. 구조 · 라우팅 · 여러 에이전트 협업

한 줄: 지침과 실측 모두 지금 뼈대(코드 관문 → 좁은 담당 → 깊이 1 오케스트레이터)를 지지해요. 측정값(근거 답 16%, 조각 덮기 0.26)을 보면 병목은 에이전트 수가 아니라 ① 글자 맞추기 검색 ② 기준 하나(0.7) ③ 여러 공종 검색 몫을 나누지 않음이에요(가설).

| # | 발견 | 출처 |
| --- | --- | --- |
| A1 | 단순한 것부터가 공통 지침. 라우팅은 입력 종류가 뚜렷하고 분류가 정확할 때 쓰는 고정 흐름. 여럿으로 나누는 건 조건 분기가 지나치거나 도구가 겹칠 때뿐 | A[1][4][6] |
| A2 | 여러 에이전트 이득은 병렬로 나눌 수 있는 일에 한정. Anthropic 조사 시스템 +90.2%지만 토큰은 대화의 약 15배. Google 180개 구성: 병렬형 +80.9%, 순서형 −39~70% | A[2][7] |
| A3 | 중앙 조정이 오류 번짐을 줄임: 소통 없는 병렬형 최대 17.2배, 중앙형 4.4배. 하위 에이전트끼리 암묵 결정이 엇갈려 결과가 어긋남(Cognition) | A[7][9] |
| A4 | 다중 에이전트 실패 분석(실행 기록 1,600+): 같은 단계 되풀이 17.1%, 되물어야 할 때 안 물음 11.7% | A[10] |
| A5 | 감독자가 담당 답을 '옮겨 말하면' 손실. 그대로 전달하게 고치자 감독자형 약 50% 향상(LangChain). 라우터형 호출 5회 · 약 9천 토큰 vs 넘김형 7회+ · 1만 4천 토큰+ | A[8] |
| A6 | 의도 분류 계단(EMNLP 2024): 작은 분류기 F1 0.60~0.66, 최고 LLM 0.74, 분류기가 약 56배 빠름. 불확실한 것만 LLM에 보내면 정확도 차 약 2%, 지연 약 절반. 범위 밖 재현율은 LLM도 0.60~0.64 | A[11] |
| A7 | 되묻기는 규칙이 정하는 편이 안전. Rasa: 기준 미만이면 '이 뜻 맞나요?' → 다시 말해 달라 → 사람. LLM은 모호함 알아채기가 약함(CLAMBER) | A[12][13] |
| A8 | 고객 응대는 '매번 성공'으로 재요. τ-bench: GPT-4o 소매 61%, 8번 모두 성공은 25% 미만 | A[3][14] |
| A9 | 선두 회사는 '작은 전용 모델 여럿 + 감독'(회사 발표). Intercom Fin: 전용 모델 9개, 넘김 판단 98%+, 자체 재순위로 비용 80%↓ · 중간 지연 150ms. 검증된 맞춤 답을 생성 답보다 먼저 씀 | A[15][16] |
| A10 | 처리율 ≠ 만족: Klarna 첫 달 2/3 처리 → 2025 사람 상담 다시 늘림(보도). 토스뱅크 AI 처리 70% vs 챗봇 만족 36%(보도). 서울시 조사(1,000명) 챗봇 불만 1위 '질문과 무관한 획일적 답' 39.4% | A[17][18][21][22] |
| A11 | 근거 없는 답은 비쌈: Air Canada 챗봇 잘못된 안내에 회사 책임 인정(2024-02). DoorDash 보내기 전 2단 검사로 환각 90%↓(대가는 지연) | A[19][23] |
| A12 | 도구 · 지시가 늘면 쪼개기보다 '그때 필요한 지시만'(Shopify). LLM 판정자는 사람과 kappa 0.02 → 0.61로 맞춘 뒤 씀 | A[20] |

우리 구조에 맞춘 제안(A): ① 카드 찾기를 뜻 검색으로(무료 모드 LLM 0회 유지) ② 열쇠를 초보 말투로 넓히기(한 번 생성 + 검수) ③ 관문 기준을 둘로(높음 바로 · 중간 버튼 확인 · 낮음 범위 밖) ④ 오케스트레이터: 나누기는 코드, 찾기는 공종별, 붙이기는 손대지 않음, 순서 · 기간은 나누지 않음 ⑤ 답 모양 '한 줄 답 → 이유 하나 → 다음 행동' ⑥ 모를 때 가까운 카드 2~3개 '이걸 물으셨나요?' ⑦ LLM은 애매할 때 질문 다시 쓰기 · 조각 엮기 두 곳만 ⑧ 층별 지표 + 'k번 모두 성공'.
피할 것(A): 담당 늘리기 · 담당끼리 직접 넘기기, 관문을 LLM 분류로 통째 바꾸기, 오케스트레이터가 담당 답 다시 쓰기, 처리율만 성공으로 보기, 근거 없을 때 그럴듯하게 채우기.
확인 못 함(A): OpenAI 가이드 PDF 본문(요약본으로 확인), Google 에이전트 백서 원문, DoorDash 원문(403), 답 길이와 만족의 관계, 한국 인테리어 플랫폼 상담 AI 구조.

A 출처
- [1] Building effective agents · Anthropic · 2024-12-19 · https://www.anthropic.com/engineering/building-effective-agents
- [2] How we built our multi-agent research system · Anthropic · 2025-06-13 · https://www.anthropic.com/engineering/multi-agent-research-system
- [3] Demystifying evals for AI agents · Anthropic · 2026-01-09 · https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- [4] A practical guide to building agents · OpenAI · 2025(요약본으로 확인) · https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- [5] Handoffs(Agents SDK) · OpenAI · https://openai.github.io/openai-agents-python/handoffs/
- [6] Choose a design pattern for your agentic AI system · Google Cloud · https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system
- [7] Towards a science of scaling agent systems · Google Research · 2026-01-28 · https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/
- [8] Benchmarking Multi-Agent Architectures · LangChain · 2025-06-10 · https://www.langchain.com/blog/benchmarking-multi-agent-architectures
- [9] Don't Build Multi-Agents · Cognition · 2025-06-12 · https://cognition.com/blog/dont-build-multi-agents
- [10] Why Do Multi-Agent LLM Systems Fail? · Cemri 외 · 2025-03 · https://arxiv.org/abs/2503.13657
- [11] Intent Detection in the Age of LLMs · Arora 외 · EMNLP 2024 Industry · https://arxiv.org/abs/2410.01627
- [12] Fallback and Human Handoff · Rasa(구판 문서) · https://legacy-docs-oss.rasa.com/docs/rasa/fallback-handoff
- [13] CLAMBER · Zhang 외 · ACL 2024 · https://arxiv.org/abs/2405.12063
- [14] τ-bench · Yao 외(Sierra) · 2024-06 · https://arxiv.org/abs/2406.12045
- [15] Constellation of models · Sierra · 2025-12-03 · https://sierra.ai/blog/constellation-of-models
- [16] Fin CX 모델 · 재순위 모델 개발기(2025-09-11) · Intercom · https://fin.ai/cx-models , https://fin.ai/research/how-we-built-a-world-class-reranker-for-fin/
- [17] Klarna AI assistant handles two-thirds of customer service chats · Klarna · 2024-02-27 · https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/
- [18] Klarna CEO reverses course by hiring more humans · Entrepreneur · 2025-05 · https://www.entrepreneur.com/business-news/klarna-ceo-reverses-course-by-hiring-more-humans-not-ai/491396
- [19] Path to high-quality LLM-based Dasher support automation · DoorDash · 2024-09-17(요약본) · https://careersatdoordash.com/?p=12568
- [20] Lessons from Shopify Sidekick · Shopify · 2025-08-26 · https://shopify.engineering/building-production-ready-agentic-systems
- [21] AI 챗봇 한계 보도 · 머니투데이 · 2026-05-05 · https://www.mt.co.kr/future/2026/05/05/2026042117032871034
- [22] 온라인쇼핑 소비자 조사 · 서울시 미디어허브 · 2026-02-27 · https://mediahub.seoul.go.kr/archives/2017269
- [23] Moffatt v. Air Canada, 2024 BCCRT 149 · 2024-02-14 · https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do

## B. 한국어 검색 · 질문-카드 맞추기 · 근거 답 성능

| # | 발견 | 출처 |
| --- | --- | --- |
| B1 | 0.6B 이하에서는 bge-m3를 한국어로 더 학습한 모델이 앞섬. MTEB(kor) 검색 9과제 nDCG@10: snowflake-arctic-l-v2.0-ko 0.765 · KURE-v1 0.762 · bge-m3 0.751 · KoE5 0.734. 셋 다 568M · 1024차원 · 8,192토큰. KURE-v1 MIT, 2.27GB | B[1][2][3][7] |
| B2 | FAQ에 가까운 과제(WebFAQ)도 순서 같음: snowflake-ko 85.98 · KURE-v1 85.05 · bge-m3 84.14 | B[3] |
| B3 | 작은 모델은 3~5점 손해: mE5-small 0.671 · e5-small-ko 0.689 · mE5-large 0.722 · bge-m3 0.724(7과제) | B[6] |
| B4 | 상용 API가 한국어에서 앞서지 않음: OpenAI text-embedding-3-large 0.685 vs KURE-v1 0.764(6과제). 값: 3-large $0.13 · 3-small $0.02(100만 토큰). CLOVA 임베딩 v2는 bge-m3 밀집 출력 | B[1][5][10][11] |
| B5 | 작으면서 1위인 예외: 후기 상호작용 KURE-v2(154M) 0.816(저자 측정). pgvector 단일 벡터에 바로 안 맞음 | B[2] |
| B6 | 한국어는 키워드와 의미 검색 차이가 큼: MIRACL-ko BM25 37.1 · bge-m3 밀집 69.9 · 셋 섞기 72.1. 우리 조각 실험(held-out hit@5 0.697 → 0.758)과 같은 방향 | B[5][9] |
| B7 | CPU 실측(arm64 4스레드, 8비트): bge-m3 질문 1개 12.6ms(p95 17.7). pgvector 1.2만 개 정확 검색 14.8ms ≈ HNSW 14.9ms. 재순위 문단 10개 1.45초 · 메모리 2.99GiB | B[13] |
| B8 | 한국어 재순위: bge-reranker-v2-m3-ko top-1 F1 0.912 vs 원본 0.877(자체 보고) | B[12] |
| B9 | 모델을 바꾸면 점수 기준을 새로 정해야 함. 의미 캐시 실험에서 맞는 적중 · 틀린 적중 평균 유사도 0.84 vs 0.85로 거의 같음 | B[8][24] |
| B10 | 답할지 판단은 여러 신호를 묶은 보정기가 점수 하나보다 나음: 정확도 80% 유지 때 답한 비율 48% → 56%. 검색 점수 분포 24개 특징으로 '근거 충분' AUROC 0.856(2ms) vs 로컬 LLM 판정 0.649 | B[22][23] |
| B11 | 섞기: 정규화 가중합이 RRF보다 나았다는 분석(RRF는 k에 민감) | B[15] |
| B12 | 합성 질문으로 열쇠를 늘릴 땐 거르기가 핵심: 품질 낮은 것을 거르면 효과 최대 +16%, 색인 −33% | B[18][20][21] |
| B13 | HyDE는 약한 검색기 보완용: Mr.TyDi-ko MRR@100 BM25 28.5 → HyDE 30.6, 미세조정 밀집 34.2. 질문마다 LLM 1회 | B[19] |
| B14 | 의미 캐시는 오답 위험: 고정 기준 0.97에서 적중 67% · 오답 5.2%. GPTCache(0.7)는 1,000질문 중 틀린 적중 233건 | B[24][25] |
| B15 | 형태소: Nori가 공백 분리보다 MRR@100 0.221 → 0.285. 글자 n-gram이 형태소보다 나았다는 1999년 보고(초록). 어느 쪽도 '두꺼비집 → 분전반' 같은 말 차이는 못 메움 | B[16][17] |

우리 구조에 맞춘 제안(B, 순서대로): 0) 평가 틀 고정(held-out을 열쇠에 안 넣기, 200개+로 늘리기, '답 없음' 라벨) 1) 카드 열쇠 · 본문 · 조각을 KURE-v1(또는 snowflake-ko, 기준선 bge-m3)로 임베딩해 pgvector `vector(1024)` 정확 검색 2) 바이그램 · 밀집 점수 가중합(가중치 하나를 dev로) 3) 기준값 대신 '맞을 확률' 보정기(1위 점수 · 1·2위 차이 · 두 점수 1위 일치 · 맞물림 · 주제) 4) 애매한 구간만 재순위 5) 열쇠 늘리기는 생성 → 거르기 → held-out 확인 + '초보 말 → 업계 말' 사전 6) 의미 캐시는 '검토 뒤 카드로 올리기'만.
피할 것(B): 바이그램 기준(0.55/0.62)을 새 점수에 그대로 쓰기, 평가 질문을 열쇠로 넣기, 무료 모드에 HyDE, 생성 답 자동 캐시, 수천 개 규모에 HNSW · 별도 벡터 DB · 유료 임베딩부터.
확인 못 함(B): KorSTS 최신 표, Kiwi BM25 수치, Cohere · Upstage · CLOVA 가격, EC2 CPU 실측.

B 출처
- [1] KURE-v1 · 고려대 NLP&AI · https://huggingface.co/nlpai-lab/KURE-v1
- [2] KURE-v2 · nlpai-lab · https://huggingface.co/nlpai-lab/KURE-v2
- [3] ko-embedding-leaderboard · OnAnd0n(2026-07) · https://github.com/OnAnd0n/ko-embedding-leaderboard
- [4] comsat-embed-ko-8b-preview · Sionic AI · https://huggingface.co/sionic-ai/comsat-embed-ko-8b-preview
- [5] PIXIE-Splade-Preview · TelePIX · https://huggingface.co/telepix/PIXIE-Splade-Preview
- [6] multilingual-e5-small-ko(사본) · https://huggingface.co/exp-models/dragonkue-KoEn-E5-Tiny-ONNX
- [7] snowflake-arctic-embed-l-v2.0-ko · https://huggingface.co/dragonkue/snowflake-arctic-embed-l-v2.0-ko
- [8] multilingual-e5-large FAQ · Microsoft · https://huggingface.co/intfloat/multilingual-e5-large
- [9] M3-Embedding(BGE-M3) · BAAI · 2024-02 · https://arxiv.org/abs/2402.03216
- [10] CLOVA Studio 임베딩 v2 · NAVER Cloud · https://guide.ncloud-docs.com/docs/clovastudio-explorer03
- [11] 임베딩 가격 · OpenAI / Voyage AI · 2026-11-19 확인 · https://developers.openai.com/api/docs/pricing , https://docs.voyageai.com/docs/pricing
- [12] bge-reranker-v2-m3-ko · https://huggingface.co/dragonkue/bge-reranker-v2-m3-ko
- [13] CPU 재순위 실측 · jacar.es · 2026-10-28 · https://jacar.es/?p=7587
- [14] pgvector README(v0.8.7) · https://github.com/pgvector/pgvector
- [15] An Analysis of Fusion Functions for Hybrid Retrieval · Bruch 외 · https://arxiv.org/abs/2210.11934
- [16] Better Than Whitespace · Ogundepo 외 · 2022-10 · https://arxiv.org/abs/2210.05481
- [17] n-Gram-based indexing for Korean text retrieval · Lee 외 · 1999(초록) · https://acnpsearch.tweb-dev.unibo.it/singlejournalindex/65299525
- [18] Doc2Query-- · Gospodinov 외 · ECIR 2023 · https://arxiv.org/abs/2301.03266
- [19] HyDE · Gao 외 · 2022-12 · https://arxiv.org/abs/2212.10496
- [20] Promptagator · Google · ICLR 2023 · https://arxiv.org/abs/2209.11755
- [21] Context-Aware Similar Question Generation · Hong 외 · https://arxiv.org/abs/2410.12444
- [22] Selective Question Answering under Domain Shift · Kamath 외 · ACL 2020 · https://arxiv.org/abs/2006.09462
- [23] Distribution-Shape QPP for RAG Retrieval Sufficiency · Veselý 외 · 2026-09 · https://arxiv.org/abs/2609.11646
- [24] vCache · Schroeder 외 · ICLR 2026 · https://arxiv.org/abs/2502.03771
- [25] MeanCache · 2024-03 · https://arxiv.org/abs/2403.02694

## C. 비용 · 지연 · 운영

주의: v3 코드의 LLM 공급자는 지금 OpenAI예요(`backend/app/agent/llm.py`, ADR agent-06 'OpenAI 유지' 권고 · 사용자 확인 대기). C1~C14는 Claude 쪽 값이고, OpenAI 값과 나란히 견준 것은 아래 'C-2'에 있어요. 제안 ①~⑦은 공급자와 상관없이 성립해요.

| # | 발견 | 출처 |
| --- | --- | --- |
| C1 | Claude 공식 값(100만 토큰당 입력/출력): Opus 5.5 $4/$20 · Sonnet 5.5 $2/$10 · Haiku 5.5 $0.10/$0.50(프롬프트 10만 토큰 이하). 출력은 입력의 5배 | C[1][5] |
| C2 | 프롬프트 캐시: 쓰기 5분 1.25배 · 1시간 2배, 읽기 Opus · Sonnet 5.5 0.05배 · Haiku 5.5 0.1배. 최소 길이 512토큰(짧으면 오류 없이 안 됨) | C[1][2][3] |
| C3 | Batch 50%(캐시 토큰까지), 결과 24시간 안. 토큰 세기 API는 무료 | C[1][2][4] |
| C4 | 캐시 절감 실측(Anthropic): 작은 분류 에이전트 83~86%, 고객 응대 72%. 세션이 짧으면(요청 중앙값 4번) 1.7배만 줄어요 — 우리 4턴 안팎 대화가 이쪽 | C[2] |
| C5 | 모델 · 생각 강도(effort)가 가장 큰 손잡이: 고객 응대 과제에서 상위 모델 기본 → 한 단계 아래 모델 low로 건당 −61%, 통과율 76.0 → 74.3%(이전 세대 측정) | C[2] |
| C6 | 답을 한 줄 형식으로 지시하자 출력 토큰 −39%, 비용 −13%, 정확도 같음. 생각 토큰도 출력 값 | C[2] |
| C7 | 싼 모델 먼저 · 어려우면 비싼 모델(FrugalGPT · RouteLLM · AutoMix): 비용 35~98%↓ · 성능 95% 유지(영어 벤치마크). 학습형 라우터는 다른 질문에서 점수가 떨어짐 | C[10]~[13] |
| C8 | 한국어 토큰: 영어 대비 o200k 1.38배 · 옛 Claude 1.88배(개인 측정 285편). 새 토크나이저는 영어 · 코드에서 늘고 한 · 중 · 일은 1.005~1.07배라 5.5 세대 한국어 할증은 작을 가능성(추정) | C[14][15] |
| C9 | 지연은 대부분 '생각': 첫 글자까지 Sonnet 5.5 low 2.29초 · medium 4.92초, Haiku 5.5 low 5.70초 · medium 8.97초, Opus 5.5 medium 13.0초(벤치마크 평균). Haiku 5.5는 low · medium · high에서 생각을 끌 수 있음 | C[6][17] |
| C10 | 응답 시간 한계: 0.1초 즉시 · 1초 흐름 유지 · 10초 주의 한계(1초 넘으면 처리 중 표시) | C[16] |
| C11 | 의미 캐시 적중: 실제 질문의 약 31%가 앞 질문과 비슷(MeanCache). 코사인 0.8에서 적중 61~69%지만 그중 2.7~7.5%가 틀림 | C[18][19] |
| C12 | 사례: Intercom Fin 해결 1건당 $0.99. Klarna는 비용 위주 자동화로 품질 저하를 인정(2025-05) | C[20][21][22] |
| C13 | 운영 상한: 등급별 월 지출 상한, 닿으면 429(`enforced_spend_limit_reached`). 사용량 · 비용 API는 4~24시간 늦음 → 실시간 차단엔 앱 안 계산 | C[3][7][8] |
| C14 | 로컬 대 API: Voyage 임베딩 $0.02~0.06 · 재순위 $0.02~0.05(100만 토큰), 2억 토큰 무료. int8 작은 임베딩은 CPU에서 한 건 10ms 미만(영어 · 서버 CPU) | C[23][24][25] |

조사 담당 계산(가정: 대화 1번 = 4턴, 고정 앞부분 3,000 + 이번 질문 · 근거 1,550 + 이전 대화 턴마다 +1,900토큰, 답 350토큰, 5분 캐시. 모든 턴을 LLM이 답할 때)

| 모델(설정) | 대화 1번(캐시 켬) | 대화 1번(캐시 끔) | 1,000대화 | 10,000대화 |
| --- | --- | --- | --- | --- |
| Claude Haiku 5.5 (low, 생각 끔) | $0.0021 | $0.0037 | $2.1 | $21 |
| Claude Sonnet 5.5 (low) | $0.041 | $0.073 | $41 | $411 |
| Claude Opus 5.5 (low) | $0.106 | $0.170 | $106 | $1,063 |

- 무료 모드가 턴의 70%를 맡으면(대화당 LLM 1.2턴): Haiku 1,000대화 약 $1, Sonnet $12~21, Opus $32~49.
- Haiku 먼저, 출력 검사에서 떨어질 때만 Sonnet으로 다시: 대화 비용 = $0.0021 + 4 × 실패율 × $0.0174. 실패율 20%면 1,000대화 $16(Sonnet만보다 −61%), 실패율 약 56%를 넘으면 Sonnet만이 더 쌈.
- 카드 미리 만들기(밤 Batch 생성 + 판정): 카드 1장 약 $0.025, 1,500장 약 $37(1회). 같은 질문을 매번 Sonnet으로 답하는 것보다 2~3번 넘게 쓰이면 쌈.

### C-2. OpenAI 값과 나란히 (덧붙인 조사, 공식 페이지 직접 확인 2026-11-19)

| # | 발견 | 출처 |
| --- | --- | --- |
| C15 | OpenAI 공식 값(100만 토큰당 입력/캐시 읽기/출력): gpt-6.1-terra $1.00/$0.05/$5.00 · gpt-6-luna $0.10/$0.01/$0.50 · text-embedding-3-small $0.02. 캐시 쓰기 30분 1.25배 · 12시간 2.5배(12시간은 Responses API만). Batch · Flex 50%. 입력이 27만 2천 토큰을 넘으면 그 요청 전체가 입력 2배 · 출력 1.5배. 설정 이름(`gpt-6.1-terra` · `gpt-6-luna` · `text-embedding-3-small`)은 공식 이름과 같음 | C[26][27] |
| C16 | 값 구조: gpt-6-luna는 입력 · 캐시 쓰기 · 캐시 읽기 · 출력 · Batch가 Claude Haiku 5.5와 똑같고, gpt-6.1-terra는 모든 단가가 Claude Sonnet 5.5의 절반 | C[1][26] |
| C17 | 캐시: OpenAI는 자동(최소 1,024토큰, 기본 수명 30분), Claude는 표시한 곳부터(최소 512토큰, 기본 5분 · 1시간은 쓰기 2배). 뜸하게 오는 믿집 대화는 OpenAI 쪽 캐시가 덜 식음. usage에 캐시 읽기 · 쓰기 토큰이 따로 나옴. 추론 토큰은 출력 값(effort none이 0을 보장하는지는 문서에 없음) | C[1][28] |
| C18 | 임베딩: Anthropic은 자체 임베딩 모델이 없고 Voyage를 안내. LLM을 Claude로 바꿔도 이미 넣은 1536차원 벡터(text-embedding-3-small)는 그대로 쓸 수 있고, 다시 넣는 건 임베딩 모델을 바꿀 때뿐. 질의 임베딩은 1만 대화 기준 월 약 $0.05 | C[26][31] |
| C19 | 운영: 등급별 월 사용 한도(Build $500 · Launch $5,000 등), 조직 · 프로젝트마다 지출 알림과 하드 상한(429). Usage API는 비용을 하루 단위로만 줌 → 실시간 차단엔 앱 안 계산(C13과 같음) | C[29] |
| C20 | 첫 글자까지(벤치마크 최근 평균): gpt-6-luna 추론 없음 1.54초 · low 2.45초, gpt-6.1-terra 추론 없음 2.87초 · low 3.14초. 같은 low에서 과제 1건 비용은 Claude 쪽이 7~9배(단가 차는 1~2배 → 토큰을 훨씬 많이 씀). 영어 위주 벤치마크라 방향만 참고 | C[17][30] |
| C21 | 정정: Voyage 재순위 `rerank-3`(2026-09) $0.05 · `rerank-3-lite` $0.02(100만 토큰), 2억 토큰 무료. 재순위 토큰 = 질의 토큰 × 문서 수 + 문서 토큰 합 → 후보 20개(각 300토큰) + 질의 60토큰이면 한 번 7,200토큰, 무료분을 넘긴 뒤 로컬과의 손익분기는 rerank-3 약 17만 회/월 · lite 약 42만 회/월 | C[31] |

같은 가정(위 표)으로 양쪽을 나란히 계산(조사 담당)

| 모델(설정) | 대화 1번 | 1,000대화 | 10,000대화 | 캐시 없을 때 10,000대화 | 무료 모드가 70% 맡을 때 10,000대화 |
| --- | --- | --- | --- | --- | --- |
| Claude Haiku 5.5 (생각 끔) | $0.0021 | $2.1 | $21 | $37 | $6~10 |
| OpenAI gpt-6-luna (none) | $0.0021 | $2.1 | $21 | $37 | $6~10 |
| Claude Sonnet 5.5 (low, 앞 생각 끔) | $0.041 | $41 | $411 | $732 | $122~209 |
| OpenAI gpt-6.1-terra (none) | $0.021 | $21 | $206 | $366 | $61~104 |

- 마지막 칸 범위의 아래쪽은 공용 앞부분 캐시가 살아 있을 때, 위쪽은 식었을 때예요. OpenAI(30분)는 아래쪽, Claude(5분)는 위쪽에 가까워요.
- 추론 · 생각 200토큰을 더하면 1,000 · 10,000대화가 terra $25 · $246, Sonnet $49 · $491, luna · Haiku $2.5 · $25예요.
- 계단 방식(싼 모델 → 검사 실패 턴만 위 모델, 실패율 20%): OpenAI luna → terra $9.1 · $91(terra만보다 −56%, 실패율 53%를 넘으면 terra만이 쌈), Claude Haiku → Sonnet $16 · $160(−61%, 손익분기 56%).
- 카드 1,500장 미리 만들기(생성 + 판정, Batch): OpenAI terra 약 $12, Claude Sonnet만 약 $23, Opus 생성 + Sonnet 판정 약 $37.
- 결론: 단가표만으로는 공급자를 고를 수 없어요. 같은 한국어 평가 세트를 양쪽에서 돌려 usage(입력 · 캐시 · 출력 · 추론 토큰)와 품질을 같이 재야 해요(유료라 허락 뒤).
- 확인 못 함(C-2): gpt-6.x 토크나이저의 한국어 토큰 배율, effort none이 추론 토큰 0을 보장하는지, Usage API 갱신 지연, 가격표 각주의 Background 할인(2시간 −30% · 8시간 −40%)과 Batch 문서(24시간 창만)가 서로 맞지 않는 점, 두 공급자의 한국어 상담 품질.

우리 구조에 맞춘 제안(C): ① 다시 쓰기는 작은 모델(생각 끔) 먼저, 검사 실패 때만 큰 모델 ② 요청 앞부분 순서 고정(도구 → 지침 → 이전 대화 → 이번 근거)으로 캐시 맞추기 ③ 카드 · 한 줄 결론 · 열쇠는 오프라인에서 미리 만들고 검수(실행 비용 0) ④ 사용자별 하루 상한을 토큰이 아니라 금액으로, 응답 usage로 앱 안에서 바로 계산 ⑤ 카드는 바로, LLM 답은 SSE로 흘리고 1초 넘으면 '답을 준비하고 있어요' ⑥ 한국어 토큰은 무료 토큰 세기로 먼저 재고, 조각 · 답 길이를 줄이기 ⑦ 로컬 작은 모델은 손익분기 식(월 호출 수 = 고정비 ÷ 호출당 값)으로 — 믿집 규모(월 4만 턴)는 새 인스턴스를 띄울 금전 이유는 없고, 기존 서버 남는 CPU면 지연 · 개인정보 면에서 나음.
피할 것(C): 토큰 수만 세는 상한 · 늦은 사용량 API로 실시간 차단, 실패 신호 없는 학습형 라우터, 느슨한 의미 캐시로 자유 답 재사용(금액 · 일정 답 금지), 기본 설정(생각 켬) 그대로 두기 · 대화 중 설정 바꾸기(캐시 깨짐), 비용만 보고 사람 · 업체 연결 줄이기.
확인 못 함(C): Claude 5.5 세대 한국어 토큰 배율(공식 없음), Haiku 5.5 생각 끔 첫 글자 시간, 한국 → API 왕복 지연, 2 vCPU 한국어 임베딩 지연, EC2 서울 공식 가격(AWS MCP 연결 실패로 제3자 값만).

C 출처
- [1] Pricing · Anthropic · 2026-11-19 확인 · https://platform.claude.com/docs/en/about-claude/pricing
- [2] Optimizing for cost and intelligence · Anthropic · 2026-11-19 확인 · https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence
- [3] Rate limits · Workspaces · Anthropic · https://platform.claude.com/docs/en/api/rate-limits · https://platform.claude.com/docs/en/manage-claude/workspaces
- [4] Token counting · Anthropic · https://platform.claude.com/docs/en/build-with-claude/token-counting
- [5] Models overview · Anthropic · https://platform.claude.com/docs/en/models/overview
- [6] Prompting Claude Haiku 5.5 · Anthropic · https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5
- [7] Usage and Cost Analytics API · Anthropic · https://platform.claude.com/docs/en/manage-claude/usage-cost-analytics-api
- [8] OpenTelemetry tracing(베타) · Anthropic · https://platform.claude.com/docs/en/manage-claude/opentelemetry
- [9] Prompt caching with Claude · Anthropic 블로그 · https://claude.com/blog/prompt-caching
- [10] FrugalGPT · Stanford · 2023-05 · https://arxiv.org/abs/2305.05176
- [11] RouteLLM · LMSYS · 2024-07-01 · https://lmsys.org/blog/2024-07-01-routellm/
- [12] AutoMix · NeurIPS 2024 · https://proceedings.neurips.cc/paper_files/paper/2024/hash/ecda225cb187b40ea8edc1f46b03ffda-Abstract.html
- [13] When Simple kNN Beats Complex Learned Routers · 2025-05 · https://arxiv.org/abs/2505.12601
- [14] The Non-English Token Tax — Korean Costs 1.4x · jangwook.net(개인 블로그) · 2026-06-23 · https://jangwook.net/en/blog/en/multilingual-llm-token-tax-experiment/
- [15] Claude Opus 4.7 token cost · GIGAZINE · 2026-04-20 · http://gigazine.net/gsc_news/en/20260420-claude-opus-4-7-token-cost
- [16] Response Times: The 3 Important Limits · NN/g · https://www.nngroup.com/articles/response-times-3-important-limits/
- [17] Anthropic 모델 성능 · Artificial Analysis · 2026-11-19 확인 · https://artificialanalysis.ai/providers/anthropic
- [18] GPT Semantic Cache · 2024-12 · https://arxiv.org/abs/2411.05276
- [19] MeanCache · IPDPS 2025 · https://arxiv.org/abs/2403.02694
- [20] Klarna 발표 · 2024-02-27 (A[17]과 같음)
- [21] Klarna CEO reverses course · Entrepreneur · 2025-05-09 (A[18]과 같음)
- [22] Fin pricing · Intercom · https://fin.ai/pricing
- [23] Pricing · Voyage AI · https://docs.voyageai.com/docs/pricing
- [24] CPU Optimized Embeddings · Hugging Face/Intel · 2024-03-15 · https://huggingface.co/blog/intel-fast-embedding
- [25] EC2 c7g.large 서울 가격 · DoiT(제3자) · https://www.doit.com/compute/spot/ap-northeast-2/c7g.large
- [26] API Pricing · OpenAI · 2026-11-19 확인(페이지에 날짜 없음) · https://developers.openai.com/api/docs/pricing
- [27] GPT-6.1 Terra · GPT-6 Luna 모델 문서 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/models/gpt-6.1-terra · https://developers.openai.com/api/docs/models/gpt-6-luna
- [28] Prompt caching · Batch · Reasoning 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/prompt-caching · https://developers.openai.com/api/docs/guides/batch · https://developers.openai.com/api/docs/guides/reasoning
- [29] Rate limits(사용 등급) · Usage API · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/rate-limits · https://developers.openai.com/api/docs/api-reference/usage
- [30] OpenAI 모델 성능 · Artificial Analysis · 2026-11-19 확인 · https://artificialanalysis.ai/providers/openai
- [31] Embeddings(Anthropic) · Voyage AI 요금(MongoDB 문서) · 2026-11-19 확인 · https://platform.claude.com/docs/en/build-with-claude/embeddings · https://www.mongodb.com/docs/voyageai/management/billing/ ([23]의 docs.voyageai.com 가격표는 예전 값이었어요)

## D. 짧은 답 · 쉬운 말 · 답 모양

한 줄: 첫 문장에 바로 답하고, 보이는 부분은 2~3문장, 나머지는 그 자리에서 펼쳐요. 길이 · 말투는 지시문에 맡기지 말고 코드로 지켜요. 답 길이와 만족도를 직접 잰 큰 규모 숫자는 찾지 못해서 글자 수 상한은 시작값이에요.

| # | 발견 | 출처 |
| --- | --- | --- |
| D1 | 첫 문장에서 갈려요(NN/g 2026-04, 사이트 AI 챗봇 8개): 사용자는 '도울 수 없어요'를 보면 바로 읽기를 멈추고, 둘째 문단의 해결책은 놓쳤어요. 답 먼저 · 더 볼 것은 후속 단추 · 문단 2~3문장 · 못 하는 일은 첫 문장에 + 차선책 | D[1] |
| D2 | 예/아니요 질문에 답이 너무 길다는 불만. 쉬운 질문엔 쉬운 답, 짧은 요약 뒤 '더 볼래요?'. 웹 사용자는 한 쪽 글의 약 20%만 읽음 | D[2] |
| D3 | 빈말('좋은 질문이에요')과 서식 없는 긴 글은 부담. 목록 · 굵게로 나눈 답은 괜찮음. 항목별 비용처럼 구체적인 답이 쓸모 | D[1] |
| D4 | 점진적 공개는 2층까지(3층 이상 길 잃음). 챗봇은 새 메시지 대신 그 자리에서 펼치기, 스트리밍 중에도 새 답 맨 위 유지 | D[3][4] |
| D5 | 문장 길이: GOV.UK 25단어 넘으면 나누기 · 문단 5문장 이하 · 용어는 처음 나올 때 풀기. NN/g 15~20단어. 한국어 공식 수치는 못 찾음(15~20단어 ≈ 40~60자, 추정) | D[5][6] |
| D6 | 인지 접근성(W3C): 한 문장 한 요점, 50단어 넘는 문단은 나누기, 3개 이상은 목록, 이중 부정 금지, 새 낱말은 눌러서 풀이. 한국장애인고용공단 '알기 쉬운 자료'도 같은 원칙 | D[7][10] |
| D7 | 토스 글쓰기: 다음 일을 짐작하게, 쓸모없는 낱말 빼기, 지금 꼭 알 것만, 누구나 아는 말. 모든 문구 해요체 · 능동문 · '~하면 ~할 수 있어요' · 명사 쌓기를 동사로 | D[8][9] |
| D8 | 출처는 거의 안 눌려요(Pew 2025): AI 요약 속 출처 클릭 1%. 출처가 붙으면 무작위 출처여도 신뢰가 오름(AAAI 2025) → 장식용 출처 위험 | D[11][12] |
| D9 | 출처는 주장 바로 옆, '출처' 대신 문서 이름, 누르면 해당 구절로(NN/g 2025-12) | D[13] |
| D10 | GOV.UK Chat(2026-03, 1만 명+ · 질문 2.6만): 정확도 76 → 90%, 쓸모 73% · 만족 64%. 좋았던 점은 분명한 답 · 관련 링크 · 단계 목록. 애매한 질문에 되묻기를 넣은 뒤 범위 안 답변율 88%. 평균 10.7초는 불만 | D[14] |
| D11 | 모를 때는 1인칭('제가 확실하지 않지만')이 사용자의 잘못된 의존을 줄임(FAccT 2024). 근거 인용을 먼저 뽑고 받쳐 줄 인용이 없는 주장은 지우기(Anthropic) | D[15][16] |
| D12 | 되묻기는 질이 전부: 질 높은 되묻기는 성과 · 만족 ↑, 낮으면 해로움(TOIS 2023). LLM은 애매해도 짐작해서 답하는 쪽으로 기움. 선택지는 단추로(NN/g 2026-03) | D[17][18][19] |
| D13 | 길이 지시는 잘 안 지켜짐(최대 길이 지시를 44~49% 어김). 짧게 답하도록 제한하자 큰 모델 정확도 +26%p(31개 모델). 입력이 길면 추론이 떨어짐 → 지시문도 짧게 | D[20][21][24] |
| D14 | 판정자는 긴 답을 좋아함: 사람 투표에서 길이가 가장 큰 스타일 요인(계수 약 0.25). ChatGPT 답 77% 장황 · 52% 틀림인데도 35%가 더 좋아함(CHI 2024) | D[22][23] |
| D15 | 없는 숫자: 답 길이와 만족도 · 이해도를 직접 잰 큰 규모 연구는 못 찾음(NN/g는 질적 연구) → 믿집 안에서 길이별 A/B로 맞추기 | — |

질문 종류별 답 틀(D 제안, 글자 수는 영어 기준을 옮긴 시작값): 예/아니요는 '네 · 아니요 · 경우에 따라 달라요'로 시작해 1~2문장 80자, 뜻은 'X는 ~예요' 2문장 90자, 방법 · 순서는 '먼저 할 것' + 번호 3개 150자, 비교는 조건별 결론('~가 중요하면 A') 2문장 120자, 원인은 가장 흔한 원인 1개 + 볼 곳 100자, 비용 · 기간은 계산 엔진 값과 기준(없으면 계산 단추), 하자는 단정하지 않기 + 확인 항목 2개, 분쟁은 믿집이 정할 수 없는 것 + 지금 할 수 있는 일, 추천 거절은 못 하는 것 + 대신 하는 것, 모를 때는 1인칭 + 확인할 곳 70자, 되묻기는 질문 1개 + 단추 2~4개 + '잘 모르겠어요'.
화면 모양(D 제안): 한 줄 답(굵게, 40자 이하) → 핵심 1~2문장(보이는 부분 합계 150자 이하) → 주의(돈 · 안전 · 법일 때만 한 줄) → '자세히' 접힌 층 하나(최대 3항목, 구체적인 이름표) → 근거(문장 끝 번호 + 문서 이름 2개까지) → 다음 할 일 단추 2~3개(12자 이하, 결과를 말하는 동사형).
쉬운 말 규칙(D 제안): 첫 문장은 답 · 한 문장 한 가지(40자 목표, 60자 상한) · 용어는 처음 나올 때 괄호 풀이(용어 사전 하나) · 원문 '-다'를 옮기지 않기 · 의무('해야 해요')는 법 · 규약 · 계약 근거가 있을 때만, 권장은 '-하는 게 좋아요' · 긍정 · 능동 · 빈말 빼기 · 명사 쌓기 풀기 · 숫자는 계산 엔진 값 + 기준 · 모를 땐 1인칭 + 갈 곳.
피할 것(D): 배경이나 빈말로 시작하기, 길이를 지시문에만 맡기고 긴 답에 점수 주기, 장식용 출처, 규정 · 분쟁에 확신에 찬 답(뉴욕시 MyCity 챗봇 사례), 아무 때나 되묻기.
확인 못 함(D): 한국어 문장 길이 공식 수치, 카카오 · 네이버 · 당근 글쓰기 가이드, 예/아니요 질문 대화 분석, 국어기본법 제14조 원문(2차 자료만).

D 출처
- [1] Less Chat, More Answer · NN/g · 2026-04-17 · https://www.nngroup.com/articles/less-chat-more-answer/
- [2] Product-Specific GenAI Needs to Write for the Web · NN/g · 2025-04-04 · https://www.nngroup.com/articles/genai-write-for-the-web/
- [3] Progressive Disclosure · NN/g · 2006-12-03 · https://www.nngroup.com/articles/progressive-disclosure/
- [4] 10 Guidelines for Designing Your Site's AI Chatbots · NN/g · 2026-04-24 · https://www.nngroup.com/articles/ai-chatbots-design-guidelines/
- [5] Writing guidelines: Clear language · GOV.UK · https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/clear-language/
- [6] Plain Language Is for Everyone, Even Experts · NN/g · 2017-10-08 · https://www.nngroup.com/articles/plain-language-experts/
- [7] Making Content Usable for People with Cognitive and Learning Disabilities · W3C · 2021-04-29 · https://www.w3.org/TR/coga-usable/
- [8] 토스 라이팅 원칙 8가지 · 토스 · 2022-11-15 · https://toss.tech/article/8-writing-principles-of-toss
- [9] Consumer UX guide(앱인토스) · 토스 · https://developers-apps-in-toss.toss.im/landing-page/landing-page-en/design/consumer-ux-guide
- [10] 발달장애인을 위한 알기 쉬운 자료 · 한국장애인고용공단 · 2023-08-11 · https://www.data.go.kr/data/15118470/fileData.do
- [11] Google users are less likely to click on links when an AI summary appears · Pew · 2025-07-22 · https://www.pewresearch.org/short-reads/2025/07/22/google-users-are-less-likely-to-click-on-links-when-an-ai-summary-appears-in-the-results/
- [12] Citations and Trust in LLM Generated Responses · AAAI 2025 · https://arxiv.org/abs/2501.01303
- [13] Explainable AI in Chat Interfaces · NN/g · 2025-12-12 · https://www.nngroup.com/articles/explainable-ai/
- [14] 5 things we learned testing GOV.UK Chat · GDS · 2026-03-16 · https://insidegovuk.blog.gov.uk/2026/03/16/5-things-we-learned-testing-gov-uk-chat-an-ai-assistant-for-government
- [15] "I'm Not Sure, But..." · FAccT 2024 · https://arxiv.org/abs/2405.00623
- [16] Reduce hallucinations · Anthropic 문서 · https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations
- [17] Users Meet Clarifying Questions · ACM TOIS 2023 · https://research.tudelft.nl/en/publications/users-meet-clarifying-questions-toward-a-better-understanding-of-
- [18] Modeling Future Conversation Turns to Teach LLMs to Ask Clarifying Questions · ICLR 2025 · https://arxiv.org/abs/2410.13788
- [19] Buttons and Checkboxes in GenUI · NN/g · 2026-03-06 · https://www.nngroup.com/articles/genui-buttons-and-checkboxes/
- [20] Following Length Constraints in Instructions · Meta · 2024-06 · https://arxiv.org/abs/2406.17744
- [21] Brevity Constraints Reverse Performance Hierarchies · 2026-03 · https://arxiv.org/abs/2604.00025
- [22] Does Style Matter? · LMSYS · 2024-08-29 · https://lmsys.org/blog/2024-08-28-style-control/
- [23] Is Stack Overflow Obsolete? · CHI 2024 · https://arxiv.org/abs/2308.02312
- [24] Same Task, More Tokens · ACL 2024 · https://arxiv.org/abs/2402.14848
- [25] NYC's AI Chatbot Tells Businesses to Break the Law · The Markup · 2024-03-29 · https://themarkup.org/news/2024/03/29/nycs-ai-chatbot-tells-businesses-to-break-the-law

## E. 다양한 질문 다루기 · 평가 · 개선 루프

한 줄: 질문은 긴 꼬리예요. 카드만으로 덮으면 업계 사례에서 약 40% 근처에서 멈췄고, 회사들은 '못 답한 대화 모으기 → 묶기 → 초안 → 사람 검수 → 배포'를 돌려 해결률을 한 달 1%p 안팎씩 올렸어요. held-out 75문항으로는 약 15~20%p보다 작은 차이를 가릴 수 없어요.

| # | 발견 | 출처 |
| --- | --- | --- |
| E1 | 비사실형 질문 6가지(방법 · 이유 · 근거 설명 · 비교 · 경험 · 논쟁), 유형마다 답 구조가 다름. 빙 질의 101만 개: 설명형 53.1% · 숫자형 26.1% · 예/아니요 7.5% | E[1][2] |
| E2 | 긴 꼬리: 의도로 덮는 비율이 약 40%에서 멈춤(a16z 인용). '의도 10~20개가 절반'은 업체 글뿐(근거 비공개) | E[4][5] |
| E3 | 분류 체계는 LLM이 만들고 작은 분류기가 돌림(Microsoft TnT-LLM) | E[3] |
| E4 | 범위 밖은 분류 정확도와 따로 움직임: CLINC150 범위 안 96.9% vs 범위 밖 찾기 40.3%. 같은 분야 안 범위 밖이 더 어려움(정밀도 46.3% vs 68.7%) | E[6][7] |
| E5 | 여러 의도: MixATIS류는 너무 쉬움, 자연스럽게 섞은 BlendX에서 최신 모델도 고전. 한국어판 KoBlendX 공개 | E[8] |
| E6 | 실제 질의 절반 넘게 모호(AmbigQA). '근거가 충분한가' 판정으로 멈추게 하면 답한 것 중 맞은 비율 +2~10%p(Google) | E[9][10] |
| E7 | 못 답한 질문 덮기 루프(DoorDash 2025-08): 넘어간 대화를 벡터로 묶기(코사인 0.70~0.90) → LLM이 정보 질문 묶음 초안 → 담당자 전부 검토 → 상담원 연결 78% → 43% | E[11] |
| E8 | 해결률은 매달 조금씩(Intercom 발표): 출시 23% → 1년 52% → 2025-10 66% | E[12] |
| E9 | 합성 질문은 걸러야 효과(+16%), 갈리는 것만 사람 라벨이면 같은 비용으로 최대 +21% | E[14][15] |
| E10 | LLM 판정자 편향: 순서 바꾸면 같은 판정 GPT-4 65%, 늘인 답에 속은 비율 모델별 8.7~91.3%, 기준 답을 주면 오판 70% → 15%, 자기 글 선호 | E[16][17] |
| E11 | 판정자를 사람에 맞추기(Shopify): 실제 대화 기준 세트, 전문가 3명+, kappa 0.61(사람끼리 0.69) | E[18] |
| E12 | RAG 지표: RAGAS 충실성-사람 일치 0.95 · 답 관련성 0.78. RAGChecker 주장 단위 진단이 사람 판단과 상관 61.9(저자 비교) | E[19][20][21] |
| E13 | 표본 크기(Anthropic): 같은 문항 짝 비교 · 같은 출처 묶음 오차. 3%p 차이 보려면 약 969문항 | E[22] |
| E14 | 외운 몫: 같은 모양 새 문제로 다시 재자 최대 −8%(GSM1k). 우리 'dev만 오름'과 같은 현상 | E[23] |
| E15 | 대화 기록 신호: 바로 다시 말하기를 실패 신호로(Alexa, 결함 −30%+). Intercom은 분모만 바꿔도 해결률 33% ↔ 50%가 된다는 예를 공개. 엄지 신호는 잡음이 많음 | E[12][24][25] |

E에서 계산한 우리 숫자(조사 담당 계산, 95% 신뢰구간 · 검정력 80%): held-out 75문항 16%의 구간 9.4~25.9%. 같은 75문항 전후 비교로 가릴 수 있는 최소 차이 약 14~18%p, 오류 0건이어도 오류율 상한 약 4%.

| 가려내고 싶은 차이 | 필요한 문항 수(짝 비교, 결과가 바뀌는 문항 20~30% 가정) |
| --- | --- |
| 15%p | 약 70~100 |
| 10%p | 약 155~235 |
| 5%p | 약 630~940 |

우리 구조에 맞춘 제안(E): 라벨을 주제 · 형태(정의 · 절차 · 비교 · 원인 · 수량 · 예/아니요 · 판단 · 질문 아님) · 기대 행동 세 축으로, '모를 때' 범위 관문 + 충분성 관문, 매주 덮기 루프, 열쇠는 평가 질문 밖에서만, 세트 넷(고정 회귀 · dev · 봉인 held-out · 매달 회전), 판정자는 기준 카드 · 근거를 주고 순서 바꿔 두 번.
확인 못 함(E): 한국어 가독성 공식, 한국 회사 사례, 실제 서비스의 여러 의도 비율, 엄지 버튼 응답률.

E 출처
- [1] A Non-Factoid Question-Answering Taxonomy · Bolotova 외 · SIGIR 2022 · https://doi.org/10.1145/3477495.3531926
- [2] MS MARCO · Microsoft · 2016-11 · https://arxiv.org/abs/1611.09268
- [3] TnT-LLM · Microsoft · KDD 2024 · https://arxiv.org/abs/2403.12173
- [4] The Empty Promise of Data Moats · a16z · 2019-05-09 · https://a16z.com/the-empty-promise-of-data-moats/
- [5] Why You Should Do Chatbot Traffic Analysis · QBox/Cyara · 2023-07-06 · https://cyara.com/blog/why-you-should-do-chatbot-traffic-analysis/
- [6] CLINC150 · Larson 외 · EMNLP 2019 · https://arxiv.org/abs/1909.02027
- [7] OOS Intent Detection robustness · Zhang 외 · 2022 · https://arxiv.org/abs/2106.04564
- [8] BlendX · 한양대 · LREC-COLING 2024 · https://arxiv.org/abs/2403.18277 (KoBlendX: https://github.com/HYU-NLP/BlendX)
- [9] AmbigQA · Min 외 · EMNLP 2020 · https://arxiv.org/abs/2004.10645
- [10] Sufficient Context · Google · ICLR 2025 · https://arxiv.org/abs/2411.06037
- [11] Enhancing chatbot knowledge with user-generated content · DoorDash · 2025-08-18 · https://careersatdoordash.com/blog/doordash-llm-chatbot-knowledge-with-ugc/
- [12] Fin outcomes · metrics · Intercom · 2025-10~2026 · https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-outcomes
- [13] Klarna 발표 · 2024-02-27 (A[17]과 같음)
- [14] Doc2Query-- · ECIR 2023 · https://arxiv.org/abs/2301.03266
- [15] CoAnnotating · EMNLP 2023 · https://arxiv.org/abs/2310.15638
- [16] Judging LLM-as-a-Judge(MT-Bench) · NeurIPS 2023 · https://arxiv.org/abs/2306.05685
- [17] LLM Evaluators Recognize and Favor Their Own Generations · NeurIPS 2024 · https://arxiv.org/abs/2404.13076
- [18] Lessons from Shopify Sidekick · 2025-08-26 (A[20]과 같음)
- [19] Ragas · 2023-09 · https://arxiv.org/abs/2309.15217
- [20] ARES · NAACL 2024 · https://arxiv.org/abs/2311.09476
- [21] RAGChecker · NeurIPS 2024 · https://arxiv.org/abs/2408.08067
- [22] Adding Error Bars to Evals · Anthropic · 2024-11 · https://arxiv.org/abs/2411.00640
- [23] GSM1k · Scale AI · NeurIPS 2024 · https://arxiv.org/abs/2405.00332
- [24] Feedback-Based Self-Learning(Alexa) · 2019-11 · https://arxiv.org/abs/1911.02557
- [25] User Feedback in Human-LLM Dialogues · EMNLP 2025 · https://arxiv.org/abs/2507.23158
