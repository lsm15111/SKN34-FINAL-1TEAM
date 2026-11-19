# OpenAI API의 출처 · 이미지 · 도구 · 속도 조사 (2026-11-19)

> 2026-11-19 밤 바로잡음(`review-2026-11-19.md` 1.6): F1 이미지 결과 `include`는 원 결과를 볼 때만 넣고, 개수는 `image_settings.max_results` · F2 캐시 활용 40~80%는 'Responses가 Chat Completions보다 나았다(내부 시험)'예요(추론 항목 때문이 아님) · F5 카카오는 'AI 학습 불허 · 외부 LLM 전송 제한'만 운영자 답변으로 확인했고, 네이버 보관 한도 · 신청 중단 날짜는 확인 못 했어요 · F8 속도는 이동 평균이라 날짜와 같이 적어요(11-19 luna none 1.58초 · terra low 3.10초).

- 누가: 하위 에이전트 하나가 웹 검색 · 공식 문서 읽기로 조사했어요. 유료 API 호출 0회, 코드 수정 없음.
- 앞 조사: 가격 · 지연 C15~C21은 [agent-web.md](agent-web.md) C-2에 있어요. 여기서는 겹치지 않게 도구 · 출처 · 이미지 · 속도만 더 봤어요.
- 읽는 법
  - **확인**: 공식 문서 · 원문 페이지에서 직접 읽은 것. **추정**: 확인한 값으로 조사 담당이 계산하거나 짐작한 것. **확인 못 함**: 찾지 못한 것.
  - 출처 번호 T[n]은 맨 끝에 모았어요.
  - help.openai.com(ChatGPT 도움말)과 네이버 개발자센터는 페이지를 직접 열지 못해(403 · 차단) 검색 결과 요약과 2차 자료로 봤어요. 해당 줄에 적어 뒀어요.

## 0. 한눈에

| 질문 | 답 | 조건 | 근거 |
| --- | --- | --- | --- |
| API로 부르면 ChatGPT처럼 출처(링크)가 오나 | **아니오(그냥 부르면)** · **예(`web_search` 도구를 켜면)** | 모델 지식만으로 답하면 출처가 없어요. Responses API에서 `web_search` 도구를 켜야 답에 `url_citation` 주석이 붙어요. 화면에 보여 줄 때는 눌리는 링크로 보여야 해요(의무) | 확인 T[1] |
| 이미지가 같이 오나 | **아니오(그냥 부르면)** · **예(`web_search` + 이미지 설정)** | `search_content_types`에 `image`를 넣고 `include`에 `web_search_call.results`를 넣어야 이미지 결과(`image_url` · `thumbnail_url` · `source_website_url` · `caption`)가 답과 따로 와요. 이미지 저작권 · 표시 조건은 문서에 없음 | 확인 T[1] |
| 우리 RAG(`file_search` 대신 자체)에서 출처 | 이미 됨 | 지금 코드가 근거 조각 `[K번호]` 인용을 검사(`knowledge.service.verify_cites`)하고 자료에 `source_url`이 있어요. 출처 표시는 우리 손에 있어요 | 코드 확인 |
| 속도 | 첫 글자 1.5~3.1초(API 기준) | gpt-6-luna 추론 없음 1.54초 · gpt-6.1-terra 추론 없음 2.87초 · low 3.14초. 출력 초당 luna 85~95 · terra 57~63토큰 | 확인 T[11b][12] |
| ChatGPT보다 빠르게 | 견줄 수 없음(ChatGPT 웹 체감 지연 확인 못 함) | 다만 지금 v3 대화는 답을 다 만든 뒤 문장을 흘려서, 사용자가 보는 첫 글자 = 답 전체 시간이에요. 여기부터 고치면 체감이 가장 크게 줄어요 | 코드 확인 · 추정 |
| 추천 | **RAG + 우리 쪽 도구(계산 엔진 · 프로젝트 · 업체 · 일정 MCP) + 자체 이미지 자료** | `web_search`는 끄고, 쓰더라도 허용 도메인(공공 기준 · 제조사)만, 관리자 · 오프라인 자료 만들기에만 | 5절 |

## 1. ChatGPT 제품의 출처 · 이미지와 API 비교

| 제품 기능 | ChatGPT(웹 · 앱)에서 보이는 모습 | API에 같은 것이 있나 | 확인 정도 |
| --- | --- | --- | --- |
| 검색 출처 | 검색을 쓴 답에 문장 안 인용(눌러서 출처 보기), 인용이 안 보이면 답 아래 'Sources' 패널에 인용 출처와 관련 링크 | 있음: Responses `web_search`의 `url_citation`(`url` · `title` · `start_index` · `end_index`). 참고한 전체 목록은 `include: ["web_search_call.action.sources"]` | 제품: 검색 결과 요약(T[5]) · API: 확인 T[1] |
| 여러 출처 · 인용 강조 | 한 답에 여러 인용, 인용을 누르면 받쳐 주는 문장 강조(2025-04 발표) | 주석에 글 위치(start/end)가 있어 우리 화면에서 직접 그려야 함 | 제품: 2차 자료 T[6] · API: 확인 T[1] |
| 이미지 묶음 | 답 위쪽에 이미지가 붙기도 하고, 이미지를 누르면 출처 링크. 2025년 말 답 속 웹 이미지를 늘림(2차 보도) | 있음: `web_search` 이미지 결과(답 글과 따로 옴). 표시 · 저작권 규칙은 API 문서에 없음 | 제품: T[5] 요약 · T[7] 2차 · API: 확인 T[1] |
| 쇼핑 카드 | 상품 카드(사진 · 가격 · 별점 · 짧은 설명), 광고가 아니라고 안내. 2026-01 '쇼핑 리서치' 모드 보도 | **없음**: API 문서에 상품 카드 · 쇼핑 결과 형식이 없어요 | 제품: 2차 T[6] · API: T[1]에 없음(확인 못 함이 아니라 문서에 없음) |
| 지도 · 주식 차트 · 날씨 | 검색 출시 때 지도 · 주가 차트 등 결과 형식 | 일부만: `sources`에 `oai-sports` · `oai-weather` · `oai-finance` 같은 실시간 피드 표시. 화면 위젯은 없음 | 제품: 2차 T[7] · API: 확인 T[1] |
| 검색 제공자 | 질문을 다시 써서 Bing 등 제휴 검색에 보냄. 계정 · IP는 넘기지 않는다고 안내 | API 쪽 제공자는 문서에 없음 | T[5] 요약 |
| 사진으로 검색 | 올린 사진으로 웹 검색(2025-06) | 사진 입력(비전)은 있음. 사진 → 검색은 우리 쪽에서 묶어야 함 | 2차 T[7] |

정리: ChatGPT의 출처 · 이미지는 **모델이 '학습해서' 붙이는 게 아니라 검색 도구 결과**예요. API도 같은 검색 도구를 켜야 출처 · 이미지가 오고, 카드 · 패널 같은 화면은 전부 우리가 만들어야 해요.

## 2. OpenAI API 도구별 정리

### 2-1. 도구 표

| 도구 | 출처 · 이미지 | 주요 설정 | 값 | 지연 | 믿집에 쓸 곳 | 확인 정도 |
| --- | --- | --- | --- | --- | --- | --- |
| `web_search` (Responses) | `url_citation` 주석, 이미지 결과(`image_url` · `thumbnail_url` · `source_website_url` · `caption`) | `filters.allowed_domains` 또는 `blocked_domains` 최대 100개(http 빼고, 하위 도메인 포함) · `user_location`(`type: approximate`, `country` 두 글자 · `city` · `region` · `timezone`) · `search_context_size` low/medium(기본)/high · `external_web_access: false`(캐시만) · `return_token_budget` · `tool_choice: required`로 강제 | 1,000회 $10 + 검색 내용 토큰은 모델 값 | 문서에 숫자 없음. 오래 걸리면 `background: true` 권고 | 공공 기준 · 제조사 사이트에서 근거 찾기(허용 도메인만) | 확인 T[1][2] |
| `web_search` (Chat Completions) | 전용 검색 모델(`gpt-5-search-api`)만, 항상 검색 | 도메인 제한 · 전체 sources · 예산 조절 없음 | 위와 같음 | — | 안 씀 | 확인 T[1] |
| `file_search` (벡터 스토어) | `file_citation`(`file_id` · `filename` · `index`), 쪽 번호 · 조각 글은 주석에 없음. 조각 글은 `include: ["file_search_call.results"]` | `max_num_results`(기본 10, 최대 50) · 속성 필터(파일당 16개) · `ranking_options.hybrid_search`(의미 + 키워드, RRF) · `score_threshold` · 기본 조각 800토큰/겹침 400 | 1,000회 $2.50(Responses만) · 저장 1GB 무료, 넘으면 GB당 하루 $0.10 | 문서에 숫자 없음 | 지금 자체 RAG(BM25 + pgvector)와 기능이 겹침 → 바꿀 이유 약함 | 확인 T[2][3][4] |
| 사진 입력(비전) | — | `input_image`(URL · base64 · `file_id`) · `detail` low/high/original/auto · PNG/JPEG/WEBP/GIF | 1024×1024 high ≈ 1,229토큰(gpt-6-astra 예시 식). terra면 장당 약 $0.0012, luna 약 $0.00012(추정, 같은 식이라 가정) | 입력 토큰만큼 | 고객 벽 사진 → 상태 설명 · 되묻기. **한국어 글자 인식 · 개수 세기 · 정확한 위치는 약하다고 문서가 밝힘** | 확인 T[8] · 값은 추정 |
| `image_generation` (Responses 도구) | base64 이미지(PNG 기본 · WebP · JPEG), `partial_images` 1~3장 미리 흘림 | 도구 안 `model`로 `gpt-image-2` · `gpt-image-2.5-flare`(빠름) · `gpt-image-1-mini` 등. `action` generate/edit | gpt-image-2 이미지 토큰 입력 $8 · 출력 $30(100만). 장당 값 · 지연은 문서에서 못 찾음 | 확인 못 함 | 쓰지 않는 게 맞음: 만든 사진은 실제 시공 · 자재가 아님(오해 위험) | 확인 T[2][9] |
| 원격 MCP | 도구 결과 그대로 | `server_url`(공개 주소 또는 Secure MCP Tunnel) · `allowed_tools` · `require_approval`(기본 승인 필요) · `authorization`(매번 보냄) | 도구 정의 · 호출 토큰만, 호출당 요금 없음 | 도구 목록 가져오기 한 단계 더(목록 항목을 맥락에 두면 다시 안 가져옴) | 믿집 일정 MCP. 다만 OpenAI 서버가 우리 MCP를 부르려면 밖에 열어야 함 → 우리 서버에서 MCP 클라이언트로 부르는 지금 규칙(AGENTS.md 4절)이 더 안전 | 확인 T[13] |
| 함수 도구(function calling) | 우리 결과 그대로 | 우리가 실행 · 검사 | 토큰만 | 도구 한 번마다 모델 왕복 1회 추가 | 계산 엔진 · 프로젝트 · 업체 · 일정 조회. 지금 `chat_tools`가 이 방식 | 확인 T[14] · 코드 |

### 2-2. Chat Completions와 Responses

| 항목 | Chat Completions | Responses | 확인 정도 |
| --- | --- | --- | --- |
| 내장 도구(web · file · 이미지 생성 · MCP · 코드 실행) | 없음(직접 구현) | 있음 | 확인 T[14] |
| 대화 상태 | 매 턴 전체 messages를 보냄 | `previous_response_id` · Conversations API · 직접 재생. 이어 붙여도 이전 입력 토큰은 다시 값을 냄 | 확인 T[14] |
| 추론 + 도구 | GPT-5.4부터 `reasoning_effort`가 none이 아니면 도구 호출 안 됨. luna 문서도 같은 제한 | 추론 항목을 다음 턴에 넘김 → 캐시 활용 40~80% 좋아짐(회사 내부 시험) | 확인 T[10][14] |
| 스트리밍 | `delta` 조각 | 타입이 있는 이벤트(`response.output_text.delta` 등) | 확인 T[14] |
| 구조화 출력 | `response_format.json_schema` | `text.format` | 확인 T[14] |
| 앞으로 | 계속 지원, 새 프로젝트는 Responses 권고. Assistants API는 2026-08-26 종료 | — | 확인 T[14] |
| 12시간 캐시 | 안 됨 | 됨 | 확인 T[15] |

코드 확인: `agent/llm.py`는 `langchain_openai.ChatOpenAI`를 써요. 설치된 langchain-openai 1.7.4는 모델 이름이 `gpt-6`으로 시작하고 도구가 있으면 자동으로 Responses API로 보내요(`_use_responses_api`). 그래서 `chat_tools`(terra, effort low + 도구)는 Responses로 가고, `structured`(도구 없음)는 Chat Completions로 가요. 위 '추론 + 도구' 제한에 걸리지 않아요.

### 2-3. 모델별 지원

| 모델 | web search | file search | 이미지 생성(도구) | MCP | 함수 | 사진 입력 | 추론 단계 | 출처 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6.1-terra (지금 대화 모델) | 예 | 예 | 예 | 예 | 예(도구 호출은 Responses 필요) | 예 | none · low · medium(기본) · high · xhigh · max | 확인 T[11] |
| gpt-6-luna (지금 가벼운 모델) | 예 | 예 | 예 | 예 | 예(Chat Completions는 effort none일 때만) | 예 | 같음 | 확인 T[10] |
| 이미지 출력 | 두 모델 모두 글만 출력. 이미지는 도구로만 | | | | | | | 확인 T[10][11] |
| 검색 품질 주의 | web search 문서: gpt-5는 minimal보다 높아야 검색, gpt-5.4 none은 결과 품질이 낮을 수 있음. gpt-6.x none에서의 검색 품질은 문서에 없음 | | | | | | | 확인 T[1] · gpt-6.x는 확인 못 함 |

## 3. 이미지를 보여 주는 다른 길 (우리 쪽에서 붙이기)

| 길 | 방법 | 값 | 약관 · 저작권 | 위험 | 판단 |
| --- | --- | --- | --- | --- | --- |
| 자체 자료 이미지 색인 | 시방서 그림 · 시공 안내서 사진 · 우리 화면 캡처를 잘라 저장하고, **글 설명(캡션)을 달아** 지금 BM25 + pgvector에 같이 넣음. 답의 근거 조각에 이미지 id를 묶어 카드로 보냄 | 캡션은 오프라인 1회(비전 모델 또는 사람). OpenAI 임베딩은 글만 받음 → 이미지 자체 임베딩은 안 됨 | 국가건설기준(KCS · KDS) 그림에 공공누리 유형이 붙어 있는지 확인 못 함 → 자료별로 확인 뒤 넣기. 출처(기준 이름 · 번호)는 항상 함께 | 낮음(우리가 고른 것만 나감) | **추천** |
| 업체 포트폴리오 사진 | 업체가 올린 시공 사진을 공정 · 자재 태그와 함께 저장하고 해당 업체 카드에만 보여 줌 | 저장 비용만 | 업체 가입 약관에 '믿집 화면 표시 · 크기 조정' 허락 줄이 필요(추정, 법률 검토 필요). 사진 속 개인정보 · 위치 정보 지우기(지금 `files.service`가 위치 정보 지움) | 업체 광고처럼 보임 → 답 본문이 아니라 업체 카드 안에서만, 추천 사유와 분리 | 업체 화면에서만 |
| 네이버 이미지 검색 API | `GET /search/v1/image`(NAVER API HUB), `display` 1~100, 응답 `link` · `thumbnail` · 크기 | 문서에 요금 없음, 하루 25,000회 | 개정 약관(2차 자료): '네이버 검색 결과를 그대로 보여 주는 목적'만, AI 학습 · 요약에 쓰기 금지, 결과 화면 광고 금지, 기기 24시간 · 서버 21일 보관 한도. 검색 API 신규 신청은 7-31부터 막힘(기존 2027-06-30까지) | LLM에 넣거나 요약하면 약관 위반 가능 | **안 씀** |
| 카카오(다음) 이미지 검색 | 다음 검색 API | 월 · 일 쿼터(값은 쿼터 메뉴, 확인 못 함) | 운영자 답변(2026-09): 상업 서비스는 되나 결과 재판매 · AI 입력 불가, 외부 LLM API로 보내기 제한. 출처 표시는 강제하지 않음 | 위와 같음 | **안 씀** |
| Bing 이미지 검색 | 2025-08-11 Bing Search API 전체 종료. 대체는 Azure 에이전트의 'Grounding with Bing'(원 결과가 아니라 모델 답, 사이트 · 검색 URL 표시 의무라는 2차 자료) | — | — | — | 없음 |
| OpenAI `web_search` 이미지 결과 | 위 2-1 | 1,000회 $10 + 토큰 | 이미지 권리 · 표시 규칙이 문서에 없음 → 원 사이트 이미지를 우리 화면에 띄우는 책임은 우리에게(추정) | 남의 시공 사진 · 상품 사진이 섞여 업체 광고 · 저작권 문제 | 끄는 쪽 |

저작권 참고(법률 자문 아님)

| 항목 | 내용 | 확인 정도 |
| --- | --- | --- |
| 검색용 작은 썸네일 | 대법원 2006. 2. 9. 2005도7793: 검색 서비스용 작은 썸네일(가로 3cm × 세로 2.5cm 정도)은 정당한 인용으로 본 사례로 소개됨 | 판례 해설(2차) T[19] |
| 상세보기 이미지 | 대법원 2010. 3. 11. 2009다76256: 포털 이미지 검색 상세보기가 직접 침해는 아니라고 본 사례로 소개됨 | 판례 해설(2차) T[19] |
| 출처 표시 | 저작권법 제37조(출처의 명시), 공정이용 제35조의5. 썸네일 판례는 '검색'이 목적일 때 이야기 → 우리처럼 답 속에 남의 사진을 넣어 서비스 일부로 쓰면 그대로 들어맞는다고 보기 어려움(추정) | 조문 T[20] · 적용은 추정 |

## 4. 속도

### 4-1. 모델별 숫자 (Artificial Analysis, OpenAI API, 최근 5일 평균, 2026-11-19 확인)

| 모델(추론) | 첫 글자까지(초) | 출력 초당 토큰 | 답 350토큰 다 받기(추정, 초) | 확인 정도 |
| --- | --- | --- | --- | --- |
| gpt-6-luna (추론 없음) | 1.54 | 85 | 약 5.7 | 확인 T[12] · 합은 추정 |
| gpt-6-luna (low) | 2.45 | 87 | 약 6.5 | 같음 |
| gpt-6-luna (medium, 기본) | 5.29 | 95 | 약 9.0 | 같음 |
| gpt-6.1-terra (추론 없음) | 2.87 | 60 | 약 8.7 | 확인 T[11b] · 합은 추정 |
| gpt-6.1-terra (low, 지금 대화 설정) | 3.14 | 57 | 약 9.3 | 같음 |
| gpt-6.1-terra (medium, 기본) | 5.14 | 60 | 약 11 | 같음 |
| gpt-6.2-sol (low) | 2.02 | 확인 못 함 | — | 확인 T[12] |
| gpt-5.4 nano (추론 없음) · mini (추론 없음) | 1.37 · 1.48 | 확인 못 함 | — | 확인 T[12] |

- '첫 글자'는 추론 시간을 포함해요. 영어 위주 벤치마크라 한국어 답에서는 다를 수 있어요.
- 350토큰 = agent-web.md C 표의 답 길이 가정. 합 = 첫 글자 + 350 ÷ 초당 토큰(벤치마크의 초당 값에 첫 글자 시간이 섞여 조금 크게 나옴).
- 도구를 한 번 부를 때마다 모델 왕복이 한 번 더 들어요(첫 글자 시간이 한 번 더 붙음, 추정).

### 4-2. ChatGPT 웹과 비교

| 항목 | 값 | 확인 정도 |
| --- | --- | --- |
| ChatGPT 웹 · 앱 체감 첫 글자 시간 | **확인 못 함**. 웹 화면만 따로 잰 2026년 공개 측정을 찾지 못했어요 | — |
| 비슷한 숫자 | @IT(2026-08-24) 'ChatGPT' 첫 글자 중앙값 0.70~0.73초 — 제목에 'API 경유 비교'라 웹 화면 값이 아님 · Artificial Analysis 'GPT-5 (ChatGPT)' API 0.77초 | 2차 T[16] · T[12] |
| 판단 | ChatGPT 대비 '몇 배 빠르다'는 지금 근거로 말할 수 없어요. 목표는 절대값으로 잡는 게 맞아요: 정해 둔 답 · 카드 0.1초대, LLM 답은 첫 문장 2초 안 · 전체 6초 안(NN/g 1초 · 10초 한계, agent-web.md C10) | 추정 |

### 4-3. 지금 코드에서 본 것

| 관찰 | 영향 | 확인 정도 |
| --- | --- | --- |
| `chat/router.py`의 `/ai/turns`는 `service.ai_turn`이 답을 **다 만든 뒤** 문장을 `token` 이벤트로 흘려요 | 사용자 첫 글자 = 입구 분류 + 검색 + (도구 왕복) + LLM 답 전체. terra low면 LLM 부분만 약 9초(추정) | 코드 확인 |
| 이유: AGENTS.md 4절 '문장 단위로 숫자를 검사한 뒤 보낸다' | 진짜 스트리밍으로 바꿔도 문장이 끝날 때마다 검사 후 보내면 규칙을 지킬 수 있어요 → 첫 문장은 첫 글자 + 문장 하나(약 40토큰) ≈ luna 2초 · terra 3.8초(추정) | 추정 |
| `chat_tools`는 terra + effort low 고정, `structured`는 역할별(trade만 luna none) | 대화 답도 luna none을 먼저 쓰고 검사 실패 때만 terra로 → 평균 지연 · 비용 함께 줄어요 | 코드 확인 · 효과는 추정 |

### 4-4. 줄이는 방법

| 방법 | 공식 문서가 말하는 것 | 믿집에서 기대 | 값 | 확인 정도 |
| --- | --- | --- | --- | --- |
| 진짜 스트리밍 + 문장 단위 검사 | 먼저 읽기 시작하게 함. 첫 글자는 앞선 추론 · 도구 시간에 달림 | 첫 문장 약 2~4초(지금 6~10초+ 대비) | 0 | 문서 확인 T[17] · 효과 추정 |
| 코드 경로(정해 둔 답 · 카드) | '이미 답을 알면 LLM을 쓰지 말라' | 0.1초대. 자주 묻는 질문 · 단계 안내는 여기로 | 0 | 확인 T[17] |
| 작은 모델 · 추론 낮추기 | 가장 빠른 모델 중 품질 기준을 넘는 것, 쉬운 일엔 낮은 effort | terra low → luna none: 첫 글자 3.14 → 1.54초, 초당 57 → 85 | 오히려 쌈 | 확인 T[12][17] |
| 짧은 출력 | 출력 토큰을 줄이면 시간이 줄어요 | 350 → 200토큰이면 luna 약 1.8초 · terra 약 2.6초 짧아짐 | 줄어듦 | 확인 T[17] · 계산 추정 |
| 프롬프트 캐시 | 앞부분이 같으면 입력 처리 시간이 줄어요(퍼센트 없음). 최소 1,024토큰, 기본 30분 | 앞부분 순서 고정(도구 → 지침 → 이전 대화 → 근거) | 캐시 읽기 0.05~0.1배 | 확인 T[15] |
| Fast 모드(`service_tier: "fast"`, 옛 priority) | 최대 2.5배 빠름 · 지연 고름(숫자는 회사 발표) | 대화 턴만 켜기. 갑자기 늘면 일부가 기본 속도로 내려가고 `service_tier: "default"`로 옴 | 2배(terra 입력 $2 · 출력 $10, luna $0.20 · $1.00) | 확인 T[2][18] |
| 병렬화 | 독립 조회는 동시에 | 근거 검색 · 프로젝트 조회 · 업체 조회를 함께 시작 | 0 | 확인 T[17] |
| 호출 수 줄이기 | 여러 단계를 한 요청으로 | 항상 필요한 정보는 코드가 먼저 읽어 넣기(AGENTS.md 4절과 같음) → 도구 왕복 없앰 | 줄어듦 | 확인 T[17] |
| 미리 계산 | — | 카드 · 한 줄 결론을 밤에 Batch로(50%) | 줄어듦 | agent-web.md C-2 |
| `web_search` 더하기 | 숫자 없음, 오래 걸리면 background 권고 | 지연이 **늘어요**(검색 + 결과 읽기). 실시간 답에는 맞지 않음 | +$0.01/회 + 토큰 | 확인 T[1] · 효과 추정 |

## 5. 우리 에이전트에 맞는 방안

가정(추정): 대화 1턴 LLM 비용 terra 약 $0.005 · luna 약 $0.0005(agent-web.md C-2 표 ÷ 4턴). web_search 검색 내용 토큰은 회당 수천 토큰이라 가정(문서에 수 없음).

| 방안 | 턴당 추가 값(추정) | 속도 | 근거 없는 숫자 위험 | 저작권 위험 | 업체 광고 위험 | 판단 |
| --- | --- | --- | --- | --- | --- | --- |
| A. RAG만(지금) | 0 | 기준 | 낮음(인용 검사 있음) | 낮음 | 낮음 | 바탕으로 유지 |
| B. RAG + `web_search`(허용 도메인만) | $0.01 + 검색 토큰 → terra 턴 값의 약 3배, luna 약 20배 이상 | 느려짐 | 중간: 웹 글의 가격 · 기간을 그대로 말할 수 있음 → 숫자 검사로 버려야 함 | 중간: 인용은 링크라 괜찮지만 이미지 결과는 위험 | 높음(허용 도메인 밖이면): 업체 블로그 · 광고 글이 근거로 들어옴 | 대화에는 끔. 관리자 · 오프라인 자료 보강에만, 도메인은 공공 기준 · 제조사로 묶기 |
| C. RAG + 자체 이미지 자료 | 거의 0(오프라인 캡션 1회) | 같음(카드로 바로) | 낮음 | 자료별 이용 조건 확인 뒤 낮음 | 낮음 | **추천** |
| D. 도구 추가(계산 엔진 · 프로젝트 · 업체 · 일정 MCP) | 도구 왕복마다 입력 토큰 더 | 왕복마다 +1.5~3초(추정). 항상 쓰는 정보는 코드가 먼저 넣으면 0 | **가장 낮음**: 숫자가 계산 엔진에서 나옴(AGENTS.md 3절) | 없음 | 업체 조회는 코드가 고른 3곳만(4절 규칙) | **추천**(이미 `chat/tools.py`가 일부) |
| E. 사진 입력(고객 벽 사진) | 장당 약 $0.0012(terra) · $0.0001(luna) | +입력 처리 | 중간: 사진으로 면적 · 수량을 짐작하면 안 됨 → 상태 설명 · 되묻기에만 | 고객 사진이라 낮음(위치 정보 지움) | 없음 | 다음 단계 후보 |
| F. 이미지 생성 | 장당 값 확인 못 함 | 느림 | — | 낮음 | 오해 위험 높음(실제 시공처럼 보임) | 안 씀 |

추천

1. **바탕은 A + D**: 근거 글은 자체 RAG, 숫자는 계산 엔진 도구, 프로젝트 · 업체는 코드가 먼저 읽어 넣기. 일정은 우리 서버의 MCP 클라이언트로(원격 MCP를 OpenAI에 열지 않기).
2. **이미지는 C**: 시방서 그림 · 시공 안내 사진 · 화면 캡처에 캡션과 출처를 달아 지금 색인에 넣고, 답 아래 카드로 보여 주기. 업체 포트폴리오는 업체 카드 안에서만.
3. **속도는 순서대로**: ① 문장 단위 검사를 지키는 진짜 스트리밍 ② 대화 답 luna none 먼저 · 실패 때만 terra ③ 정해 둔 답 · 카드 넓히기 ④ 캐시 순서 고정 ⑤ 그래도 느리면 대화 턴만 Fast 모드(2배 값).
4. **`web_search`는 대화에서 끔**. 쓰려면 Responses + `allowed_domains`(예: 국가건설기준센터 · 조달청 · 제조사) + `user_location.country: "KR"` + 이미지 결과 끔으로, 관리자용 자료 보강에만. 인용을 보여 줄 때는 눌리는 링크 의무를 지키기.
5. **외부 이미지 검색 API(네이버 · 카카오)는 쓰지 않기**: 둘 다 결과를 AI에 넣거나 요약하는 것을 막고 있어요(2차 자료 · 운영자 답변).

## 6. 확인 못 함

- ChatGPT 웹 · 앱의 체감 첫 글자 시간(웹 화면만 잰 공개 측정 없음).
- ChatGPT 도움말(help.openai.com) 원문: 403으로 못 열어 검색 요약만 봤어요. 쇼핑 카드 · 이미지 표시의 2026년 현재 모습.
- `web_search`의 회당 지연, 검색 내용 토큰 수, gpt-6.x 추론 none에서 검색 품질, 이미지 결과의 권리 · 표시 조건.
- `image_generation` 장당 값 · 지연(가격표는 토큰 단가만, 계산기는 못 봄).
- gpt-6.1-terra · gpt-6-luna의 사진 토큰 식(문서 예시는 gpt-6-astra), Fast 모드에서 두 모델의 실제 속도.
- 네이버 검색 API 약관 원문(개발자센터 접속 차단, 2차 자료만), 카카오 이미지 검색 쿼터 값.
- 국가건설기준(KCS · KDS) 그림의 공공누리 유형.
- 업체 포트폴리오 재사용에 필요한 약관 문구(법률 검토 필요).

## 출처

- T[1] Web search 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/tools-web-search
- T[2] API Pricing(내장 도구 · 이미지 · Fast · Flex) · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/pricing
- T[3] File search 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/tools-file-search
- T[4] Retrieval(벡터 스토어) 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/retrieval
- T[5] ChatGPT search 도움말 · OpenAI Help Center(403, 검색 결과 요약으로 봄) · https://help.openai.com/en/articles/9237897-chatgpt-search · 요약 참고 https://nhimg.org/chatgpt-search-explained
- T[6] ChatGPT 쇼핑 · 여러 인용(2025-04) · MacRumors · https://www.macrumors.com/2025/04/29/chatgpt-gains-new-shopping-features/ · 도움말 https://help.openai.com/en/articles/11128490 (403)
- T[7] ChatGPT 답 속 이미지 확대 · 이미지로 검색(2차 보도) · Search Engine Land(403, 검색 요약) · https://searchengineland.com/chatgpt-more-images-answers-465098 · The Decoder · https://the-decoder.com/openai-updates-chatgpt-search-with-smarter-answers-and-image-searchopenai-updates-chatgpt-search-with-smarter-answers-and-image-search/ · ChatGPT search 출시(2024-10-31) · https://9to5google.com/2024/10/31/chatgpt-search-launch/
- T[8] Images and vision 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/images-vision
- T[9] Image generation 도구 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/tools-image-generation · https://developers.openai.com/api/docs/guides/image-generation
- T[10] GPT-6 Luna 모델 문서 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/models/gpt-6-luna
- T[11] GPT-6.1 Terra 모델 문서 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/models/gpt-6.1-terra
- T[11b] GPT-6.1 Terra 성능 · Artificial Analysis · 2026-11-19 확인 · https://artificialanalysis.ai/models/gpt-6-1-terra
- T[12] OpenAI 모델 성능 · GPT-6 Luna 성능 · Artificial Analysis · 2026-11-19 확인 · https://artificialanalysis.ai/providers/openai · https://artificialanalysis.ai/models/gpt-6-luna
- T[13] Connectors and MCP servers 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- T[14] Migrate to the Responses API · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/migrate-to-responses
- T[15] Prompt caching 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/prompt-caching
- T[16] ChatGPT · Gemini · Claude Sonnet 5 속도 실측(API 경유) · @IT · 2026-08-24 · https://atmarkit.itmedia.co.jp/ait/articles/2608/24/news049.html
- T[17] Latency optimization 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/latency-optimization
- T[18] Fast mode(옛 Priority processing) 가이드 · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/priority-processing
- T[19] 판례 해설: 대법원 2005도7793 · 2009다76256 · 네플라 · https://www.nepla.ai/case/대법원/2005도7793 · https://www.nepla.ai/case/대법원/2009다76256
- T[20] 저작권법(제35조의5 공정이용 · 제37조 출처의 명시) · 국가법령정보센터 · https://www.law.go.kr/법령/저작권법
- T[21] 네이버 이미지 검색 API · NAVER API HUB 문서 · 2026-11-19 확인 · https://api.ncloud-docs.com/docs/naver-api-hub-search-image
- T[22] 네이버 검색 API 약관 개정(2차 자료) · 브런치 · https://brunch.co.kr/@ainote/123 · API HUB 개요 · https://api.ncloud-docs.com/docs/naver-api-hub-overview
- T[23] 다음 검색 API 외부 LLM 전달 · 표시 요건 문의(운영자 답변 2026-09-03 · 09-07) · Kakao DevTalk · https://devtalk.kakao.com/t/api-llm/151458 · 쿼터 안내 · https://developers.kakao.com/docs/ko/daum-search/common
- T[24] Bing Search API 종료(2025-08-11) · The Register · https://www.theregister.com/2025/05/15/bing_search_apis_retired/ · Azure 공지 요약 · https://mc.merill.net/message/AZ492574
- T[25] Embeddings 가이드(글 임베딩만) · OpenAI · 2026-11-19 확인 · https://developers.openai.com/api/docs/guides/embeddings
- 코드: `backend/app/agent/llm.py` · `backend/app/config.py` · `backend/app/chat/router.py` · `backend/app/knowledge/service.py` · `backend/.venv/.../langchain_openai/chat_models/base.py`(`_use_responses_api`)
