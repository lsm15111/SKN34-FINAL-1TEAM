# T6. 믿집(MitJip) 에이전트 기술 검증 — 모델·프레임워크·MCP·평가·한국어 검색·비전·튜터링

- 작성일: 2026-11-08 · 범위: 조사 질문 1~9 · 용도: 기술 선택, `AGENTS.md`·`.env.example` 사실 검증
- 신뢰도 표기: **[공식 문서]** 벤더·프로젝트 공식 페이지/저장소/API, **[논문]** arXiv·학회, **[블로그]** 기업·개인 블로그·언론, **[커뮤니티]** 포럼·제3자 정리·벤치 저장소
- 확인 표기: **확인 11-08** = 오늘 WebFetch로 원문을 직접 열어 확인함 · **사전 지식** = 조사자 지식(2026-06 이전), 이번에 원문 재확인 못 함 · **미확인** = 확인 실패 · **상충** = 출처끼리 다름
- 조사 한계: WebSearch를 약 17회 쓴 시점에 세션 공용 검색 한도가 소진되어, 이후에는 이미 아는 공식 URL만 WebFetch로 열어 확인했다. 그래서 일부 항목(CPU 추론 지연 수치, 일부 모델 라이선스, OpenAI study mode 원문)은 '사전 지식/미확인'으로 남겼다.

---

## 0. 결론 요약

1. `.env.example`의 값 6개(모델 ID·effort·Jev·임베딩·rerank·arq 주석)는 **모두 실재하거나 사실과 맞다.** `gpt-6.1-terra`는 OpenAI 공식 모델 목록에 있는 현행 모델이다(2026-10-26 출시).
2. 다만 **AGENTS.md '공급자 하나' 규칙과 충돌**한다. 현재 `.env`는 OpenAI + OpenRouter(Jev) + Voyage = 공급자 3개다. 규칙 문구를 고치거나, Jev·Voyage를 측정 후 빼야 한다.
3. **Jev는 LLM이 아니라 분류·결정 전용 모델**이다. Chat Completions가 아니라 OpenRouter **Decisions API(`/api/alpha/decisions`, alpha 경로)** 로 부르며, 한국어 지원은 공식 문서에 적혀 있지 않다 → 의도 200 세트로 직접 측정한 뒤 채택한다.
4. `text-embedding-3-small`은 폐기 예정이 없지만 **한국어 검색에선 약한 편**이다(여러 한국어 벤치에서 BGE-M3·KURE·Upstage보다 낮음). 코퍼스가 작으므로 **pg_bigm(2-gram) + 벡터 하이브리드(RRF)** 로 보완하고, RAG 30 세트로 A/B 해서 정한다.
5. MCP 최신 스펙은 **2026-07-28**판이다. 무상태로 바뀌어 `initialize` 핸드셰이크와 `Mcp-Session-Id`가 없어졌다. Python SDK는 **`mcp` 2.3.0**(2026-10-02)이고, 서버 클래스가 `FastMCP`에서 `MCPServer`로 바뀌었다.
6. 프레임워크는 **OpenAI Agents SDK 0.24.0 고정 + 파이썬 코드 오케스트레이터(handoff 미사용)** 를 권장한다. 차선은 얇은 래퍼다.
7. 평가: **OpenAI Evals 플랫폼은 2026-11-30 종료**(10-31부터 읽기 전용)이므로 쓰지 않는다. pytest(결정적 지표, CI) + promptfoo(LLM 판정, 수동·야간) 조합을 권장한다.
8. 사진 분석은 **"체크리스트 초안 + 사용자 확인"** 까지만 맡긴다. 개수 세기·위치 찾기·미세 얼룩 판별은 2026년 벤치에서도 약하다.
9. 튜터링은 학생용 '답 숨기기(소크라테스식)'가 아니라 **"답 먼저 → 이유 → 확인 질문 1개 → 다음 단계 선제 안내"** 가 소비자에게 맞다.

### 0-1. `.env.example` 검증표

| 키 = 값 | 실재 | 핵심 사실 (출처·신뢰도) | 권장 |
|---|---|---|---|
| `OPENAI_AGENT_MODEL=gpt-6.1-terra` | ✅ 실재 | 공식 모델 목록에 `gpt-6.1-terra`(GPT-6.1 Terra). 스냅샷은 같은 이름 하나뿐(날짜 스냅샷 없음). 1M 토큰당 입력 $1 / 캐시 입력 $0.05 / 출력 $5, 컨텍스트 1,050,000(최대 입력 922,000), 최대 출력 128,000, 지식 컷오프 2026-06-01, 텍스트+이미지 입력. 설명은 "시각 추론·정밀한 컴퓨터 사용·자연스러운 글쓰기용 빠르고 효율적인 모델" [공식 문서, 확인 11-08]. 출시일은 OpenAI 체인지로그 2026-10-26, llmgateway 타임라인 2026-10-15 → **상충**(공식 우선) | 유지. 날짜 스냅샷이 없어 동작이 조용히 바뀔 수 있으니 eval 로그에 모델명과 실행일을 남긴다. 대량·단순 작업은 같은 공급자의 `gpt-6-luna`($0.10/$0.50)를 검토한다 |
| `OPENAI_REASONING_EFFORT=low` | ✅ 유효 | terra 지원값: `none`, `low`, `medium`(기본), `high`, `xhigh`, `max`. `minimal`은 terra 목록에 없다 [공식 문서, 확인 11-08] | 유지. llm.py에서 에이전트별로 덮어쓸 수 있게 한다. `minimal`로 바꾸면 400 오류가 날 수 있다(Astra·6.1-sol은 일부 값 미지원 시 400 [공식 문서]) |
| `OPENROUTER_API_KEY` + `JEV_MODEL=typesafe/jev-1.14` | ✅ 실재 | OpenRouter 모델 API: id `typesafe/jev-1.14`, 이름 "TypeSafe: Jev 1.14", 생성 2026-10-14, 엔드포인트 스냅샷 `typesafe/jev-1.14-20261014`, 컨텍스트 262,144, 입력 $0.042/1M·출력 $0, `supported_parameters` 빈 배열 [공식 문서, 확인 11-08]. TypeSafe의 'System One' 결정 모델로 글을 만들지 않고 Choice/Noul/Score/Box 타입 답과 확률을 돌려준다. 호출은 `POST https://openrouter.ai/api/alpha/decisions` [공식 문서]. 한국어 지원 언급 없음 → **미확인** | 조건부 유지: ① AGENTS.md 공급자 규칙 수정 ② `~typesafe/jev-latest` 말고 1.14 고정 ③ 의도 200으로 정확도·보정(ECE)을 재고 채택 ④ 탈락 시 `gpt-6-luna` enum 분류로 대체(공급자 1개 유지) |
| `OPENAI_EMBEDDING_MODEL=text-embedding-3-small` | ✅ 실재, 폐기 예정 없음 | 기본 1536차원, 최대 입력 8192, $0.02/1M, OpenAI 자체 보고 MTEB 62.3% [공식 문서]. 폐기 목록에 없음 [공식 문서, 확인 11-08]. 한국어: AutoRAG 한국어 벤치 top-1 0.5439 (bge-m3 0.6754, Upstage 0.6579, KoE5 0.6930) [커뮤니티] | 기준선으로 유지하되 RAG 30에서 `text-embedding-3-large`, 로컬 bge-m3/KURE-v1과 A/B. 하이브리드 검색(pg_bigm)은 필수 |
| `VOYAGE_RERANK_MODEL=rerank-3` | ✅ 실재 | 2026-09-30 출시, 현행 "최고 정확도" 재순위 모델, 컨텍스트 32K, $0.05/1M, 신규 계정 2억 토큰 무료 [공식 문서·블로그, 확인 11-08]. 다국어 평가 51개 데이터셋·31개 언어(한국어 포함 여부 **미확인**) [블로그] | 세 번째 공급자다. 코퍼스가 작아 재순위 이득이 작을 수 있으니 RAG 30에서 '재순위 없음 vs rerank-3'를 비교한 뒤 결정한다 |
| pyproject 주석 "arq는 2025-10부터 유지보수 전용" | ✅ 맞음 | README에 "maintenance only mode, see #510". 이슈 #510은 2025-10-18 Samuel Colvin 작성, 치명적 보안 문제만 고치고 새 수정은 기대하지 말라는 내용 [공식 문서, 확인 11-08]. 최신 0.28.0(2026-04-16), Python 3.9~3.14 [공식 문서] | MVP는 유지(버전 고정). 장기 대안은 taskiq·SAQ 등(현재 상태 **미확인**) |

### 0-2. `AGENTS.md` 규칙 검증표

| 규칙 | 기술 사실 | 충돌·주의 | 권장 |
|---|---|---|---|
| LLM SDK 호출은 `app/agent/llm.py` 한 곳, 공급자 하나 | Agents SDK는 모델 객체에 OpenAI 클라이언트를 주입할 수 있어(`OpenAIResponsesModel(openai_client=...)`, 사전 지식) 클라이언트 생성을 llm.py에 모을 수 있다 | `.env`에 OpenRouter·Voyage가 있어 **공급자 3개** | 문구 예: "생성형 LLM 공급자는 OpenAI 하나. 분류(Jev)·재순위·임베딩 같은 보조 API도 `app/agent/llm.py`(또는 같은 패키지의 단일 모듈)에서만 호출하고 CI에서는 전부 스텁" |
| 입구: 코드 라우터 + 직접 학습 분류기 → 낮으면 Jev 1회 → 낮으면 되묻기 | Jev는 `probabilities`·`confidence`를 준다. 문서도 "실수 비용으로 임계값을 정하고 라벨 샘플로 튜닝하며 버전을 고정하라"고 권한다 [공식 문서] | Jev 한국어 **미확인**, Decisions API 경로가 `alpha` | 임계값 τ_model·τ_jev를 의도 데이터 dev 분할로 정한다. 분류기는 temperature scaling 후 쓴다(6장) |
| 대화는 SSE | `Runner.run_streamed()` → `stream_events()` [공식 문서] | 스트리밍 중에는 숫자 대조를 할 수 없다 | 숫자가 없는 가이드 대화는 바로 스트리밍, 숫자가 들어가는 답은 버퍼 → 검증 → 전송 |
| 견적 도착 뒤 설명은 worker | arq는 유지보수 전용이지만 동작한다 | — | 작업에 멱등 키, 재시도 1회 |
| 에이전트 DB 쓰기 금지 (예외: `request_schedule_change` 승인 대기 건) | 규칙은 도구·DB 권한 수준에서 강제해야 지켜진다 | Agents SDK `SQLAlchemySession`을 쓰면 대화 기록을 **프레임워크가** DB에 쓴다 → 문구가 모호 | "에이전트 **도구**는 DB 쓰기 금지. 대화 기록·사용량 기록은 오케스트레이터 코드가 쓴다"로 명확히. MCP 서버의 DB 역할은 SELECT + `schedule_change_requests` INSERT만 GRANT하고 RLS로 본인 프로젝트만(4.4) |
| 출력은 Pydantic 검사, 숫자는 계산 엔진과 대조해 다르면 버림 | Structured Outputs(strict json_schema)와 `client.responses.parse(text_format=Model)` [공식 문서]. Agents SDK output guardrail은 **마지막 에이전트에만** 돈다 [공식 문서] | 오케스트레이터가 에이전트를 각각 `Runner.run`으로 부르면 각자가 '마지막 에이전트'라 괜찮다. handoff 체인을 쓰면 중간 에이전트가 검사에서 빠진다 | 숫자는 **슬롯 방식**(LLM은 `⟦total_min⟧` 같은 키만 쓰고 숫자는 코드가 채움) + 정규식으로 남은 숫자 검사(5.2) |
| 호출 상한: 에이전트별 도구 4회, 턴당 하위 호출 3회, 사용자별 일일 토큰 | SDK `max_turns`는 모델 호출 루프 횟수 기준이고 넘으면 `MaxTurnsExceeded` [공식 문서]. 사용량은 `result.context_wrapper.usage`(requests, input/output/total tokens, 요청별 항목) [공식 문서] | `max_turns`는 '도구 4회'와 의미가 다르다 | 도구 카운터를 실행 컨텍스트에 두고 tool input guardrail로 5번째 호출을 거부한다. 하위 호출 3회는 오케스트레이터 코드 카운터. 일일 토큰은 Redis `INCRBY usage:{user}:{yyyymmdd}` |
| 믿집 일정 MCP 서버 1개 직접 제작 (도구 5개) | 스펙 2026-07-28, Python SDK `mcp` 2.3.0 `MCPServer` [공식 문서] | SDK 문서 일부(ASGI 마운트·CORS)는 아직 `Mcp-Session-Id`를 언급하지만 스펙은 제거 → **상충** | 클라이언트(Agents SDK)와 서버의 `mcp` 메이저 버전을 맞추고 통합 테스트로 확인 |
| eval 세트, CI는 LLM 호출 0(스텁) | Agents SDK `agents.testing.ScriptedModel`(0.21.0부터), `RunConfig(tracing_disabled=True)` [공식 문서] | 트레이싱은 기본 ON이라 OpenAI로 업로드되고, 민감 데이터 포함도 기본 True [공식 문서] | CI: `OPENAI_AGENTS_DISABLE_TRACING=1`, 외부 네트워크 차단(pytest-socket·respx 등), Jev·임베딩·rerank도 스텁 |

---

## 1. 모델·API·벤더 현황 (질문 1)

### 1.1 OpenAI 라인업과 가격 (2026-11)

공식 모델 페이지는 처음 쓰는 사람에게 **GPT-6 Astra**를 권하고, Sol·Terra·Luna를 비용·처리량 조절용 대안으로 둔다 [공식 문서, https://developers.openai.com/api/docs/models, 확인 11-08]. 아래 가격은 Standard 등급, 1M 토큰당, 입력 272K 이하 기준이다 [공식 문서, https://developers.openai.com/api/docs/pricing, 확인 11-08].

| 모델 ID | 출시 (체인지로그) | 입력 / 캐시 입력 / 출력 | 성격·비고 |
|---|---|---|---|
| `gpt-6-astra` | 2026-09-03 | $10 / $1 / $50 | 최고 성능. `none` effort·temperature·top_p·logprobs 미지원, 도구 호출은 Responses API 필요 |
| `gpt-6.1-sol` | 2026-09-29 | $2 / $0.10 / $10 | Astra에 가까운 성능, 복잡한 업무·코딩. `none`·`minimal` 미지원. 멀티에이전트 베타 |
| **`gpt-6.1-terra`** | **2026-10-26** | **$1 / $0.05 / $5** | 시각 추론·컴퓨터 사용·글쓰기. effort none~max, 기본 medium |
| `gpt-6-luna` | 2026-09-22 | $0.10 / $0.01 / $0.50 | 가장 효율적, 대량·단순 작업. 텍스트+이미지 입력, effort none~max, 기본 medium, 지식 컷오프 2026-05-18 |
| `gpt-6-sol` | 2026-09-22 | $2 / $0.20 / $10 | |
| `gpt-5.6-sol` / `-terra` / `-luna` | 2026-07-09 | $4/$0.40/$20 · $2/$0.20/$12 · $0.20/$0.02/$1.20 | 이전 세대 |
| `text-embedding-3-small` / `-large` | 2024 | $0.02 / $0.13 (입력만) | 임베딩. 더 새로운 OpenAI 임베딩 모델은 문서에 없음 |

- 등급별 배수: Batch·Flex는 Standard의 50%, Fast(구 Priority)는 2배 [공식 문서].
- 프롬프트 캐시 쓰기: terra는 30분 보존 쓰기 $1.25/1M. 2026-10-20부터 12시간 캐싱이 추가되었고 쓰기는 입력 단가의 2.5배 [공식 문서, 체인지로그].
- 내장 도구 가격: 웹 검색 1천 회당 $10(+검색 콘텐츠 토큰), File search 1천 회당 $2.50, 저장 GB·일당 $0.10 [공식 문서].
- terra 기본 한도(Build 등급): 5,000 RPM / 1,000,000 TPM [공식 문서]. MVP 규모에는 충분하다.
- 모델 페이지 기준 terra 지원 기능: 스트리밍, Structured Outputs, function calling, file search, 이미지 입력, 웹 검색, 프롬프트 캐싱. MCP는 Responses API의 내장 도구로 지원. 파인튜닝·predicted outputs는 미지원. 엔드포인트는 Responses·Chat Completions·Batch [공식 문서, https://developers.openai.com/api/docs/models/gpt-6.1-terra, 확인 11-08].

**비용 감각(추정):** 대화 1턴에 입력 6천 토큰(시스템 프롬프트+RAG)·출력 600토큰이면 terra 기준 약 $0.006 + $0.003 ≈ $0.009다. 캐시가 맞으면 입력이 20분의 1로 줄어든다. 사용자별 일일 토큰 상한은 "상한 토큰 × 단가"로 월 예산을 역산해 정한다.

### 1.2 Responses API 핵심

- **reasoning effort**: `reasoning={"effort": "low"}`. 값은 모델마다 다르며 `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` 중 일부를 지원한다. `max`는 2026-07-09(GPT-5.6과 함께) 추가, `xhigh`는 2025-12 추가 [공식 문서, https://developers.openai.com/api/docs/guides/reasoning, 확인 11-08]. 2026-09-03부터는 대화 중간에 effort를 바꿔도 캐시된 프롬프트 앞부분이 유지된다 [공식 문서, 체인지로그].
- **무상태 운용**: `store=false`(또는 ZDR)면 reasoning 항목에 `encrypted_content`가 기본 포함되어, 이력을 우리 DB에 두고 다중 턴을 이어갈 수 있다 [공식 문서].
- **Structured Outputs**: `text.format`에 `{"type": "json_schema", "strict": true, ...}`. 파이썬은 `client.responses.parse(model=..., input=..., text_format=PydanticModel)` 후 `response.output_parsed`. 거절(`refusal`)과 `max_output_tokens`로 잘린 `incomplete` 상태는 스키마를 안 따를 수 있으니 따로 검사한다. JSON mode(`json_object`)는 유효 JSON만 보장하고 스키마는 보장하지 않는다 [공식 문서, https://developers.openai.com/api/docs/guides/structured-outputs, 확인 11-08].
- **데이터 정책**: API 데이터는 기본적으로 학습에 쓰지 않는다. 남용 모니터링 로그는 최대 30일. Responses는 기본 30일간 상태를 저장(`store`)하고, ZDR이면 `store`가 항상 false. 한국 데이터 레지던시는 **저장만** 가능하고 처리(추론)는 미국·EU·UAE만이며, 영업 승인 필요·신형 모델 10% 할증, 도메인 `kr.api.openai.com` [공식 문서, https://developers.openai.com/api/docs/guides/your-data, 확인 11-08].
- **종료·폐기 중 믿집 관련 항목** [공식 문서, https://developers.openai.com/api/docs/deprecations, 확인 11-08]:
  - Assistants API: 2026-08-26 **종료됨** → Responses·Conversations API로 이전.
  - Reusable prompts(v1/prompts), **Evals 플랫폼**, Agent Builder: **2026-11-30 종료**(Evals는 10-31부터 읽기 전용). Evals 이전 경로는 Promptfoo, Agent Builder 대체는 Agents SDK.
  - Chat Completions: 폐기 공지 없음.
  - `text-embedding-3-*`: 폐기 공지 없음.
- **새 서버 호스팅 제품**: "Agents API"가 2026-09-10 퍼블릭 베타로 나왔다(자동화, 백그라운드 compaction 등) [공식 문서, 체인지로그]. 믿집은 DB 쓰기 금지·호출 상한·개인정보를 우리 코드로 통제해야 하므로 쓰지 않는 편이 낫다(판단).
- **OpenAI Python SDK**: v3 계열. Agents SDK 0.21.0이 `openai>=3.0.0,<4`(HTTPX2 지원)로 올렸다 [공식 문서, 릴리스 노트].

### 1.3 OpenAI Agents SDK (파이썬, `openai-agents`)

- **버전**: 최신 안정 **0.24.0 (2026-10-15)**, MIT, Python ≥3.10 [공식 문서, https://pypi.org/project/openai-agents/, 확인 11-08]. 직전: 0.23.1(10-02), 0.22.3(09-17), 0.22.0(08-19), 0.21.0(08-15).
- **차기 변경 경고**: GitHub에 0.24.0-alpha.6(11-03, pre-release, PyPI 미배포)이 있고, Runner 별칭 제거, `Session.interrupt()` → `Turn.cancel()`, `Subagent.submit()` → `start()`, Agent 선언 불변화 등 **비호환 변경**이 예고되어 있다 [공식 문서, https://github.com/openai/openai-agents-python/releases, 확인 11-08]. → `openai-agents==0.24.0`으로 고정한다.
- 최근 비호환 이력: 0.22.0에서 실패·미완료 응답이 `ModelBehaviorError`를 던지게 바뀜, 0.23.0에서 strict tool·승인 복원 등 마이그레이션 항목 추가 [공식 문서].
- **기능 요약** [공식 문서]:

| 기능 | 핵심 | 믿집에 쓰는 법 |
|---|---|---|
| Handoffs | LLM에게 `transfer_to_<agent>` 도구로 보인다. **통제권이 넘어가** 받은 에이전트가 대화를 이어받는다. `handoff()`로 `on_handoff`, `input_type`, `input_filter`, `is_enabled` 조정 가능. 권한 검사는 `on_handoff` 첫머리에서 예외를 던져 막는다 | **쓰지 않음.** 통제권 이전은 호출 상한·출력 검증·SSE 흐름을 깨기 쉽다 |
| Agents as tools | `Agent.as_tool()`로 전문 에이전트를 도구처럼 부르며 호출자가 통제를 유지한다 | 공정 에이전트 → 목공/도배 서브에이전트 호출에 사용 가능(또는 코드 분기) |
| Guardrails | input guardrail은 **첫 에이전트만**, output guardrail은 **최종 출력을 낸 에이전트만**, tool guardrail은 모든 function tool 호출마다(handoff·hosted tool·as_tool 제외). input guardrail은 기본 병렬(`run_in_parallel=True`)이라 트립와이어 전에 토큰·도구가 이미 쓰였을 수 있고, `run_in_parallel=False`면 막힌 뒤에 에이전트가 안 돈다. 예외: `InputGuardrailTripwireTriggered`, `OutputGuardrailTripwireTriggered`, `ToolInputGuardrailTripwireTriggered`, `ToolOutputGuardrailTripwireTriggered` | 도구 횟수 상한·DB 쓰기 금지 확인은 **tool guardrail**, 숫자 검사는 output 검증(코드) |
| Sessions | `SQLiteSession`, `AsyncSQLiteSession`, `RedisSession`, **`SQLAlchemySession.from_url("user_123", url="postgresql+asyncpg://...", create_tables=True)`**, `OpenAIConversationsSession`, `EncryptedSession`(암호화+TTL), `AdvancedSQLiteSession`, `OpenAIResponsesCompactionSession`, MongoDB, Dapr | PostgreSQL에 대화 이력 저장(오케스트레이터 쓰기로 분류) |
| Tracing | 기본 ON, `BatchTraceProcessor`가 OpenAI Traces로 몇 초마다 내보낸다. 끄기: `OPENAI_AGENTS_DISABLE_TRACING=1`, `set_tracing_disabled(True)`, `RunConfig.tracing_disabled`. `trace_include_sensitive_data` 기본 True. ZDR 조직은 트레이싱 불가. 외부 프로세서: Langfuse, Logfire, LangSmith, Phoenix, MLflow, Braintrust, W&B, Datadog 등 | 운영은 민감 데이터 제외(False), CI는 끔 |
| MCP | `HostedMCPTool`(OpenAI 쪽에서 서버를 호출 → 서버가 인터넷에 공개되어야 함), `MCPServerStreamableHttp`, `MCPServerSse`(MCP 쪽에서 폐기 예정), `MCPServerManager` | 내부망 일정 MCP 서버를 `MCPServerStreamableHttp`로 연결(4.5) |
| HITL | 승인 대기 interruption, `RunState`로 재개, 거절 시 `"approval_rejected"` 메시지 | 믿집은 화면 버튼으로 승인하므로 SDK 승인 기능은 불필요 |
| 실행 제어 | `max_turns`(초과 시 `MaxTurnsExceeded`), `error_handlers={"max_turns":..., "model_refusal":..., "invalid_final_output":...}`. structured output 검증 실패 시 SDK가 재시도하지 않는다 | 상한 초과 시 "되묻기" 폴백 반환 |
| 사용량 | `result.context_wrapper.usage`(requests, input_tokens, output_tokens, total_tokens, `request_usage_entries`, 캐시·reasoning 토큰 세부) | 일일 토큰 상한 집계 |
| 테스트 | `agents.testing.ScriptedModel`, `assistant_message()`, `function_call()`, `model.calls`, `model.assert_complete()` | CI LLM 0회(5.5) |

### 1.4 Jev (`typesafe/jev-1.14`, OpenRouter)

- **정체**: TypeSafe의 결정 모델이며 'System One' 계열의 첫 모델이다. 앱 상태(`state`, 텍스트·이미지)와 타입이 정해진 질문(`questions`)을 보내면 답과 확률을 돌려준다. 질문 타입은 **Choice**(선택지와 선택지별 확률·confidence), **Noul**(조건이 참일 확률), **Score**(순서 척도), **Box**(이미지 안 위치, 1.14부터)다. 이유나 설명은 돌려주지 않는다 [공식 문서, https://openrouter.ai/docs/guides/community/jev, 확인 11-08].
- **ID·버전**: `typesafe/jev-1.14`(현행), `~typesafe/jev-latest`(최신 추적 별칭), `typesafe/jev-1.13`(유지), `typesafe/jev-router`. 1.14는 2026-10-14 출시, Jev 얼리 액세스는 2026-09-15 [공식 문서·블로그, https://openrouter.ai/blog/insights/what-is-jev/ (2026-09-21 게시, 10-16 갱신)].
- **호출 방식**: `POST https://openrouter.ai/api/alpha/decisions`, 헤더 `Authorization: Bearer $OPENROUTER_API_KEY`. 별도로 TypeSafe SDK용 `POST https://openrouter.ai/api/v1/systemone`이 있다. Chat Completions 호환 여부는 문서에 없고, 모델 API의 `supported_parameters`도 비어 있다 [공식 문서].
- **응답 예(튜토리얼, 영어 티켓)**: `"team": {"type": "choice", "choice": "payments", "confidence": 0.67, "probabilities": {...}}`, `usage.cost`(USD) 포함, `model` 필드에 날짜 스냅샷 표시 [공식 문서, https://openrouter.ai/docs/guides/community/jev-tutorial].
- **한계**: 텍스트 약 32,000바이트를 넘거나 이미지가 들어가면 더 느리고 덜 정확한 장문 모드로 돈다. 확률은 실행마다 조금씩 다르다. 벤더는 "보정되어 0.8이면 집계상 약 80% 맞는다"고 주장한다(독립 검증 없음) [공식 문서·블로그].
- **한국어**: 공식 문서·블로그 어디에도 지원 언어가 없다 → **미확인**.
- **믿집 적용 예(스케치, 실행 검증 안 함)**:

```json
{
  "model": "typesafe/jev-1.14",
  "state": {"utterance": "거실 벽지 들뜬 거 부분 도배만 해도 돼요?", "stage": "견적_전"},
  "questions": {
    "intent": {
      "type": "choice",
      "instructions": "사용자 발화의 의도는 무엇인가?",
      "criteria": {
        "guide": "자재·시공 방법을 배우려는 질문",
        "process_wallpaper": "도배 공정 범위·방법 결정",
        "quote_explain": "받은 견적의 항목·금액 설명 요청",
        "schedule": "일정 조회·변경",
        "out_of_scope": "인테리어와 무관하거나 불명확"
      }
    }
  }
}
```

### 1.5 Voyage AI (`rerank-3`) — MongoDB 소유

- 현행 재순위 모델은 `rerank-3`(최고 정확도, 대부분 용도에 추천)과 `rerank-3-lite`(지연·비용 우선), 둘 다 32K 토큰. `rerank-2.5`·`rerank-2.5-lite`·`rerank-2`·`rerank-1` 등은 legacy로 아직 호출 가능하다(종료일 없음) [공식 문서, https://docs.voyageai.com/docs/reranker, 확인 11-08].
- 가격: rerank-3 $0.05/1M, rerank-3-lite $0.02/1M, 신규 2억 토큰 무료 [공식 문서, https://docs.voyageai.com/docs/pricing].
- 발표(2026-09-30): 9개 도메인 95개 데이터셋, NDCG@10. rerank-2.5 대비 평균 +0.96%, 다국어 +0.52%, 긴 문서 +3.35%. Cohere Rerank v4.0 Pro 대비 +2.72%, Qwen3-Reranker-8B 대비 +3.02%. 다국어는 51개 데이터셋·31개 언어지만 한국어 명시는 없다. **모두 벤더 자체 평가**다 [블로그, https://blog.voyageai.com/2026/09/30/rerank-3/].
- OpenRouter에도 `mongodb/rerank-3`("VoyageAI by MongoDB: rerank-3", 엔드포인트 `voyageai/rerank-3-20260930`)로 올라와 있다 [공식 문서, OpenRouter 모델 API]. 다만 OpenRouter를 거쳐 재순위를 부르는 방법은 **미확인**이다. 만약 된다면 OpenRouter 하나로 Jev와 재순위를 묶어 공급자를 2개로 줄일 수 있다.
- Voyage 임베딩(참고): `voyage-4-large`($0.12), `voyage-4`($0.06), `voyage-4-lite`($0.02), 공개 가중치 `voyage-4-nano`. `voyage-multilingual-2`는 legacy [공식 문서, https://docs.voyageai.com/docs/embeddings].

### 1.6 임베딩: `text-embedding-3-small`과 한국어 대안

**A. MTEB(kor, v2) Retrieval, nDCG@10** — KURE-v3 모델 카드에 실린 표로 저자 자체 측정이다 [공식 문서(모델 카드), https://huggingface.co/nlpai-lab/KURE-v3, 확인 11-08]

| 모델 | 파라미터 | 평균 | Ko-StrategyQA | AutoRAG | PubHealthQA | MIRACL |
|---|---|---|---|---|---|---|
| nlpai-lab/KURE-v3 | 1.1B | **0.8027** | 0.8192 | 0.9324 | 0.8639 | 0.7489 |
| Qwen3-Embedding-8B | 7.6B | 0.7826 | **0.8363** | 0.8276 | 0.8721 | 0.6783 |
| Qwen3-Embedding-4B | 4.0B | 0.7737 | 0.8270 | 0.8431 | 0.8693 | 0.6803 |
| dragonkue/snowflake-arctic-embed-l-v2.0-ko | 0.6B | 0.7653 | 0.8050 | 0.9093 | 0.8337 | 0.6685 |
| nlpai-lab/KURE-v1 | 0.6B | 0.7616 | 0.7999 | 0.8708 | 0.8193 | 0.6816 |
| BAAI/bge-m3 | 0.6B | 0.7509 | 0.7941 | 0.8301 | 0.8041 | 0.7015 |
| Qwen3-Embedding-0.6B | 0.6B | 0.7140 | 0.7586 | 0.8338 | 0.8107 | 0.6023 |

- KURE-v3: Apache-2.0, 기본 2048차원(Matryoshka로 1024·512·256), 최대 8,192토큰. 모델 트리상 기반은 Ministral-3-3B → Nemotron-3-Embed-1B. 1024차원에서도 원 점수의 약 99%를 유지한다고 보고. 공개일은 미표기(인용은 2026) [공식 문서].

**B. KURE-v1 모델 카드 평균(top-10 NDCG)** [공식 문서(모델 카드), https://huggingface.co/nlpai-lab/KURE-v1]: KURE-v1 0.6947 > bge-m3 0.6872 > arctic-embed-l-v2.0 0.6819 > multilingual-e5-large 0.6637 > jina-v3 0.6529 > **text-embedding-3-large 0.6167**. KURE-v1은 bge-m3 미세조정, 1024차원, 최대 8192, MIT.

**C. AutoRAG 한국어 임베딩 벤치(질의 수가 적음, 정확도 증분으로 보아 약 114개 추정)** [커뮤니티, https://github.com/Marker-Inc-Korea/AutoRAG-example-korean-embedding-benchmark]

| 모델 | top-1 | Recall@3 | Recall@5 | NDCG@5 |
|---|---|---|---|---|
| KU-HIAI-ONTHEIT-large-v1.1 | **0.7193** | **0.8860** | **0.9298** | 0.3834 |
| KoE5 | 0.6930 | 0.8772 | 0.9035 | 0.3697 |
| bge-m3 | 0.6754 | 0.8684 | **0.9298** | **0.3894** |
| Upstage Embedding(구버전) | 0.6579 | 0.8421 | 0.8947 | 0.3822 |
| openai text-embedding-3-large | 0.6053 | 0.7895 | 0.8421 | 0.3586 |
| gte-multilingual-base | 0.5877 | 0.8070 | 0.8596 | 0.3637 |
| **openai text-embedding-3-small** | **0.5439** | 0.7281 | 0.8070 | 0.3553 |
| multilingual-e5-large-instruct | 0.4649 | 0.6667 | 0.7632 | 0.3487 |

- **Upstage 현행**: `solar-embedding-2-query`/`-passage`(1024차원, 8k, Solar Embedding 2는 `microsoft/harrier-oss-v1-0.6b` 미세조정). `solar-embedding-1-large-*`와 별칭 `embedding-query/passage`는 **2026-12-31 폐기** [공식 문서, https://console.upstage.ai/docs/capabilities/embed, 확인 11-08]. AutoRAG 표의 Upstage 수치는 구버전 기준이다.
- **OpenAI**: 임베딩 문서에 다국어 성능 설명이 없다 [공식 문서].
- **해석**: 세 표 모두 text-embedding-3 계열이 한국어 전용·다국어 오픈 모델보다 낮다. 다만 B·C는 질의 수가 작고, A는 KURE 저자 측정이라 편향 가능성이 있다.
- **믿집 선택지**:
  - **A안(공급자 1개 유지, 기본)**: text-embedding-3-small 유지 + pg_bigm 하이브리드. 부족하면 `-large`로 올린다(단가 6.5배지만 코퍼스가 작아 절대 비용은 미미). `-large`는 3072차원이라 pgvector HNSW 인덱스 한도(vector 2,000차원)를 넘으므로 `halfvec`(4,000) 또는 `dimensions` 파라미터로 줄여야 한다(`dimensions`는 사전 지식).
  - **B안(로컬)**: bge-m3·KURE-v1(568M, 1024차원)을 EC2 CPU로 돌린다. 문서 임베딩은 오프라인 일괄, 질의 임베딩만 실시간. fp32 기준 메모리 약 2GB대(추정), 지연 미측정. 운영 부담이 늘고 공급자 규칙과는 무관(자체 모델)하다.
  - **C안**: Upstage `solar-embedding-2` → 새 공급자가 추가된다.
  - 결정은 RAG 30에서 Recall@5·nDCG@10으로 한다. KURE-v3(2048차원)를 쓰면 `halfvec` 또는 1024 Matryoshka가 필요하다.

### 1.7 arq

- README: "In maintenance only mode", 이슈 #510 링크 [공식 문서, https://github.com/python-arq/arq, 확인 11-08].
- 이슈 #510 "Maintenance only mode": 2025-10-18, samuelcolvin. Pydantic 팀이 arq에 큰 노력을 들일 시간이 없고, 치명적 보안 문제는 고치지만 새 수정은 기대하지 말라는 내용. 대안 추천은 없다(활동 로그에 taskiq 비교표 커밋 링크만 있음) [공식 문서, https://github.com/python-arq/arq/issues/510].
- PyPI 최신 0.28.0(2026-04-16), 0.27.0(2026-02-02), Python 3.9~3.14, MIT [공식 문서, https://pypi.org/project/arq/].
- **판단**: 공지 뒤에도 0.27·0.28이 나왔으니 최소 유지보수는 되고 있다. MVP(견적 설명 비동기 작업)에는 충분하다. `arq==0.28.0`으로 고정하고, 작업 함수는 프레임워크 독립적으로 짜서 나중에 taskiq 등으로 옮기기 쉽게 한다.

---

## 2. 에이전트 설계 패턴과 근거 (질문 2)

### 2.1 핵심 자료 요약

| 자료 | 날짜 | 핵심 주장 | 신뢰도·URL |
|---|---|---|---|
| Anthropic, *Building effective agents* | 2024-12-19(이후 갱신됨) | workflow(미리 정한 코드 경로)와 agent(LLM이 스스로 경로 결정)를 구분한다. 가장 단순한 해법부터 시작하고, 프레임워크는 프롬프트를 가리는 추상화를 만들 수 있으니 API 직접 사용부터. 원칙 3가지: 단순성, 투명성(계획 단계 노출), 도구 문서화·테스트(ACI). 도구는 실수하기 어렵게 인자를 바꾸는 **poka-yoke**로 설계 | [블로그] https://www.anthropic.com/engineering/building-effective-agents |
| Anthropic, *How we built our multi-agent research system* | 2025-06-13 | 리드 에이전트 + 병렬 서브에이전트(orchestrator-worker). 단일 Opus 4보다 내부 평가에서 90.2% 앞섬. 에이전트는 채팅의 약 4배, 멀티에이전트는 약 **15배 토큰**. BrowseComp 분산의 80%를 토큰 사용량이 설명. 모두 같은 맥락이 필요하거나 의존성이 많은 작업, 코딩, 저가치 작업엔 부적합. 평가는 실제 질의 약 20개로 시작, LLM 판정(0~1 루브릭) + 사람 평가 | [블로그] https://www.anthropic.com/engineering/multi-agent-research-system |
| Cognition, *Don't Build Multi-Agents* | 2025-06-12 | 원칙 ① 맥락 공유(메시지가 아니라 전체 trace) ② 행동에는 암묵적 결정이 있고 결정이 충돌하면 결과가 나쁘다. Flappy Bird 예(배경·새를 따로 만들게 하면 스타일 불일치). 기본은 단일 스레드 선형 에이전트, 길면 맥락 압축 모델 | [블로그] https://cognition.com/blog/dont-build-multi-agents |
| Cognition, *Multi-Agents: What's Actually Working* | 2026-04-22 | **쓰기는 단일 스레드로 두고 추가 에이전트는 행동이 아니라 지능을 보탠다.** 통하는 패턴: 깨끗한 맥락의 리뷰 루프(Devin Review는 PR당 평균 약 2개 버그 발견, 약 58%가 심각), 큰 모델을 도구로 부르는 '스마트 친구', 작업을 쪼개 자식을 조율하는 매니저. 실패: 약한 주 모델은 언제 상위 모델에 물어야 할지 모름, 매니저가 지나치게 지시적, 부모·자식이 상태를 공유한다고 착각, 무구조 스웜은 "대부분 주의 분산" | [블로그] https://cognition.com/blog/multi-agents-working |
| OpenAI, *A practical guide to building agents* | 2025-04(사전 지식, PDF에 날짜 표기 없음) | 에이전트가 맞는 곳: 복잡한 판단, 유지하기 어려운 규칙, 비정형 데이터 의존. 아니면 결정적 해법으로 충분. 구성요소: 모델·도구·지시. 모델은 가장 강한 것으로 eval 기준선 → 작은 모델로 교체. **먼저 단일 에이전트 역량을 최대화**. 분리 기준: 조건문이 많은 복잡한 로직, 도구 과부하(개수보다 유사·중복이 문제, 잘 정의된 15개+도 되고 겹치는 10개 미만도 실패). 멀티에이전트: 매니저(agents as tools) vs 분산(handoff). 가드레일은 다층 방어(관련성·안전 분류기, PII 필터, 모더레이션, 도구 위험 등급, 규칙 기반, 출력 검증). 사람 개입 조건: 실패 임계 초과, 고위험 행동 | [블로그] https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf |
| HumanLayer, *12-Factor Agents* | 2025(저장소 © 2026) | 운영 품질의 '에이전트'는 대부분 결정적 코드에 LLM 단계를 군데군데 넣은 것. 12요소: 자연어→도구 호출, 프롬프트 소유, 맥락 창 소유, 도구=구조화 출력, 실행 상태와 업무 상태 통합, 간단한 API로 시작·정지·재개, 사람 연락도 도구 호출로, **제어 흐름 소유**, 오류를 맥락에 압축, **작고 집중된 에이전트**, 어디서든 트리거, 무상태 리듀서(+13 필요한 맥락 미리 가져오기). 코드 Apache-2.0, 글 CC BY-SA 4.0 | [커뮤니티] https://github.com/humanlayer/12-factor-agents |
| Anthropic, *Effective context engineering for AI agents* | 2025-09-29 | 맥락 창은 '주의 예산'이 있는 유한 자원이고 길어질수록 회상이 떨어진다(context rot). 시스템 프롬프트는 '적절한 고도'(하드코딩 if-else와 모호한 지시의 중간), 도구는 최소·비중복, 예시는 다양한 대표 예 몇 개. 사전 검색 + 필요 시 검색(just-in-time) 혼합. 긴 작업은 compaction, 구조화 노트, 서브에이전트(1,000~2,000토큰 요약 반환) | [블로그] https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| LangChain, *Context Engineering for Agents* | 2025-07-02 | 맥락 전략 4가지: write(창 밖에 저장), select(관련 정보만 가져옴), compress(필요한 토큰만), isolate(서브에이전트로 분리) | [블로그] https://www.langchain.com/blog/context-engineering-for-agents (검색 결과 요약으로만 확인) |

### 2.2 패턴별 적합 작업·실패 모드

| 패턴 | 맞는 작업 | 대표 실패 모드 | 막는 법 | 믿집 적용 |
|---|---|---|---|---|
| 증강 LLM(단일 호출 + 검색·도구) | 한 번에 끝나는 질의응답 | 검색 실패 시 그럴듯한 환각 | 근거가 없으면 "모름"+되묻기, 출처 표시 | 가이드 단발 질문 |
| Prompt chaining | 고정 하위 단계로 나뉘는 작업 | 앞 단계 오류가 전파, 지연 증가 | 단계 사이에 **코드 게이트**(스키마·숫자 검사) | **견적 설명(worker)**: 계산 엔진 결과 → 설명 생성 → 숫자 검증 → 저장 |
| Routing | 범주가 뚜렷하고 따로 다루는 게 나은 입력 | 경계 의도 오분류, 과신 | 보정된 신뢰도 + 임계값 + 되묻기, '범위 밖' 클래스 | **입구 관문**(코드 라우터 + 분류기 + Jev + 되묻기), 공정 에이전트의 목공/도배 코드 분기 |
| Parallelization: 분할 | 서로 독립인 하위 작업 | 비용 증가, 병합 충돌 | **읽기 전용 작업만** 병렬 | RAG 검색 + 일정 조회 동시 실행, 가드레일 병렬 |
| Parallelization: 투표 | 판정 안정화 | 비용 k배 | 평가에서만 사용 | LLM 판정 k=3 |
| Orchestrator-workers | 하위 작업을 미리 알 수 없는 작업 | 과잉 위임, 토큰 약 15배, 중복 작업, 모호한 위임 지시 | 위임마다 목표·출력 형식·경계를 명시, 횟수 상한 | 믿집 하위 작업은 대부분 예측 가능 → **LLM 오케스트레이터 대신 코드 오케스트레이터**, 턴당 하위 호출 3회 |
| Evaluator-optimizer | 기준이 분명하고 반복이 실제로 개선되는 작업 | 무한 루프, 평가자 편향, 비용 | **재시도 1회 상한**, 평가 기준은 코드로 | 숫자 검증 실패 시 1회 재생성, 일정 공지 초안 다듬기 |
| 자율 에이전트 | 단계 수를 예측할 수 없는 개방형 문제 | 오류 누적, 비용 폭증 | 샌드박스, 상한, 사람 확인 | **MVP 부적합** |
| 분산 handoff | 상담 주체가 완전히 바뀌는 흐름 | 통제권 이전으로 상한·최종 검증 누락, 맥락 유실 | 입력 필터, 첫·마지막 가드레일 | **쓰지 않음** |
| 매니저(agents as tools) | 전문 에이전트를 도구처럼 호출 | 매니저가 지나치게 지시적이거나 맥락 부족, 부모·자식이 상태 공유를 착각 | 자식은 결과를 구조화해 위로 보고, 상태는 명시적으로 전달 | 공정 에이전트 → 목공/도배 서브에이전트 |
| 단일 스레드 쓰기 | 쓰기 충돌 방지 | 병렬 작성자 간 스타일·결정 충돌 | 쓰기 지점 1곳 | **쓰기는 `request_schedule_change`(대기 건) 하나**, 실제 반영은 사용자 버튼 → API |

### 2.3 믿집 권장 구조

```
사용자 ─SSE─ FastAPI /chat
  └ 오케스트레이터(파이썬 코드, LLM 아님): 턴당 하위 호출 ≤3, 사용자 일일 토큰 확인
      1) 입구 관문: 규칙 라우터 → 의도 분류기(보정) → [낮음] Jev 1회 → [낮음] 되묻기
      2) 분기
         ├ 가이드 에이전트 (RAG + 용어집 + 학습자 상태, 도구 ≤4회)
         ├ 공정 에이전트 → 코드 분기 → 목공 / 도배 서브에이전트
         ├ 공정표 에이전트 ─MCP→ 일정 MCP 서버 (조회·미리보기·변경요청(대기)·공지초안)
         └ 견적 설명: 견적 도착 이벤트 → arq worker (계산 결과 → 설명 → 숫자 검증)
      3) 출력 검증(Pydantic, 숫자 대조) → 통과분만 전송·저장(저장은 오케스트레이터)
  승인 버튼 → FastAPI /schedule-requests/{id}/approve (에이전트 경로 아님)
```

- 근거: 흐름이 예측 가능하므로 Anthropic의 routing·chaining과 OpenAI의 '단일 에이전트 먼저', 12-factor의 '제어 흐름 소유', Cognition의 '단일 스레드 쓰기'에 맞춘다.
- 에이전트마다 보이는 도구를 4개 이하로 둔다(OpenAI: 겹치는 도구가 오선택을 부름, Anthropic: 최소·비중복 도구).
- 맥락은 서브에이전트에 필요한 것만 넘기고 서브에이전트는 구조화 요약을 돌려준다(Anthropic 맥락 엔지니어링, LangChain의 isolate).

---

## 3. 프레임워크 비교 (질문 3, 2026-11 기준)

### 3.1 버전·라이선스 [공식 문서, 각 PyPI, 확인 11-08]

| 항목 | OpenAI Agents SDK | LangGraph | Pydantic AI | Google ADK | 얇은 래퍼(직접) |
|---|---|---|---|---|---|
| 최신 | **0.24.0** (2026-10-15) | **1.2.20** (2026-11-05) | **2.66.0** (2026-11-04) | **2.14.0** (2026-11-07) | `openai` v3 SDK (정확한 최신 버전 미확인) |
| 라이선스 | MIT | MIT | MIT | Apache-2.0 | MIT(openai-python, 사전 지식) |
| Python | ≥3.10 | ≥3.10 | ≥3.11 | ≥3.11 | — |
| 안정성 | 0.x, 잦은 마이그레이션, 차기 alpha에 비호환 변경 예고 | 1.x(2025-10-17 1.0), Production/Stable, 일부 버전 yank 이력 | 2.x, 거의 매일 마이너 릴리스 | 2.x, ADK 2.0 | 의존성 최소 |
| 공급자 중립성 | OpenAI 중심(Responses·Chat Completions + 100여 LLM 지원 주장) | 중립 | 중립(문자열로 모델 교체) | Gemini 최적화, LiteLlm 등 래퍼로 타사 | 단일(OpenAI) |
| 멀티에이전트 | handoff, agents as tools | 그래프 노드·서브그래프 | 에이전트 위임, Pydantic Graph | 계층형 에이전트, Workflow Runtime(라우팅·fan-out/in·루프·재시도) | 코드 분기 |
| 가드레일 | input/output/tool guardrail 내장 | 노드로 직접 구현 | 출력 검증·도구 승인 | 콜백 | 직접 |
| 상태·세션 | Sessions 다수(SQLAlchemy+asyncpg 포함) | 체크포인터(Postgres 체크포인터는 별도 패키지, 이번에 문서 미확인) | 메시지 이력 직접 관리, 내구 실행(Temporal·DBOS·Prefect) | 세션 서비스 | 직접 |
| HITL | 승인 interruption + RunState | `interrupt()` + `Command(resume=...)`, 체크포인터·thread_id 필수 | 도구 승인 내장 | — | 화면 버튼이면 불필요 |
| 스트리밍 | `run_streamed` 이벤트 | 여러 stream 모드 | 지원 | 지원 | Responses 스트림 이벤트 |
| MCP 클라이언트 | 내장(Streamable HTTP·hosted) | 어댑터(사전 지식) | 핵심 기능 | MCP 도구 지원(`mcp` extra) | `mcp` 클라이언트 직접 |
| 트레이싱 | 내장(OpenAI Traces) + 외부 | LangSmith 중심 | Logfire(OTel) | Google Cloud 쪽(사전 지식) | 직접 |
| CI 스텁 | `agents.testing.ScriptedModel` | 가짜 모델 직접(사전 지식) | `TestModel`, `FunctionModel`, `models.ALLOW_MODEL_REQUESTS = False` | `adk eval` | 가짜 클라이언트 |

출처: https://pypi.org/project/openai-agents/ · https://pypi.org/project/langgraph/ · https://pypi.org/project/pydantic-ai/ · https://pypi.org/project/google-adk/ · https://docs.langchain.com/oss/python/langgraph/interrupts · https://pydantic.dev/docs/ai/guides/testing/ · https://adk.dev/agents/models/

### 3.2 팀 제약별 적합도

| 팀 제약 | Agents SDK | LangGraph | Pydantic AI | ADK | 얇은 래퍼 |
|---|---|---|---|---|---|
| llm.py 한 곳·공급자 하나 | ◎ 클라이언트 주입 | ○ | ○ | △ Gemini 중심 | ◎ |
| 에이전트 DB 쓰기 금지 | ○ 도구·DB 권한으로 강제(어느 것이든 같음) | ○ | ○ | ○ | ○ |
| 호출 상한(도구 4·하위 3·일일 토큰) | ○ tool guardrail + usage | ○ 그래프 카운터 | ○ | ○ | ◎ 직접 루프 |
| SSE | ◎ | ◎ | ◎ | ○ | ○ 직접 매핑 |
| HITL = 화면 버튼 | 불필요(무관) | interrupt 불필요 | 불필요 | 불필요 | ◎ |
| CI 스텁 | ◎ ScriptedModel | ○ | ◎ TestModel | ○ | ○ |
| MCP 연결 | ◎ | ○ | ◎ | ○ | △ 직접 연결 |
| 3주 안 완성(11-08→11-27) | ◎ | △ 학습 비용 | ○ | △ | ○(루프·스트리밍·MCP 직접 구현 부담) |

### 3.3 추천

**1순위: OpenAI Agents SDK 0.24.0을 '부품'으로만 쓰고, 오케스트레이션은 파이썬 코드로 한다.**

- 이유: 공급자가 OpenAI 하나라 SDK의 장점(Responses API, MCP 클라이언트, 스트리밍 이벤트, 세션, tool guardrail, usage, ScriptedModel)을 그대로 쓰고 직접 만들 양을 줄인다. 오케스트레이터는 코드이므로 프레임워크 추상화가 제어 흐름을 가리지 않는다(Anthropic·12-factor 권고와 일치).
- 사용 규칙(AGENTS.md에 추가 권장): handoff 금지, `Agent` + `Runner.run(_streamed)` + function tool + `MCPServerStreamableHttp`만 사용, `max_turns=5`, 에이전트당 도구 ≤4개, `output_type`은 Pydantic 모델, `ModelSettings`는 llm.py에서만 만든다.
- 고정: `openai-agents==0.24.0`, `openai>=3,<4`, `mcp==2.3.*`.
- 출구 전략: llm.py 경계 덕분에 SDK가 문제를 일으키면 얇은 래퍼로 바꿀 수 있다.

**2순위: 얇은 래퍼.** 팀이 SDK 학습을 원치 않거나 0.x의 변경이 부담이면 Responses API 직접 호출 + 직접 도구 루프(100~200줄 규모)로 간다. 이 경우 MCP는 `mcp` 클라이언트로 도구 목록을 받아 function tool로 바꾼다.

**비추천:** LangGraph(짧은 흐름에는 과함, 그래프·체크포인터 학습 비용), ADK(Gemini 중심), Pydantic AI(좋은 대안이지만 2.x 릴리스가 매우 잦고, OpenAI 단일 공급자에서는 Agents SDK의 내장 MCP·트레이싱이 더 직접적임).

**llm.py 스케치(실행 검증 안 함, API 이름은 사전 지식 포함):**

```python
# app/agent/llm.py — LLM·보조 API 호출의 유일한 진입점
from openai import AsyncOpenAI
from openai.types.shared import Reasoning
from agents import ModelSettings, OpenAIResponsesModel
from app.core.config import settings

_openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=30, max_retries=2)

def agent_model() -> OpenAIResponsesModel:
    return OpenAIResponsesModel(model=settings.OPENAI_AGENT_MODEL, openai_client=_openai)

def agent_settings(effort: str | None = None) -> ModelSettings:
    # store=False: 상태는 우리 DB(SQLAlchemySession)에 둔다
    return ModelSettings(reasoning=Reasoning(effort=effort or settings.OPENAI_REASONING_EFFORT), store=False)

async def decide_intent_with_jev(utterance: str, stage: str) -> dict:
    ...  # httpx로 POST https://openrouter.ai/api/alpha/decisions (CI에서는 스텁)

async def embed(texts: list[str]) -> list[list[float]]:
    ...  # text-embedding-3-small
```

---

## 4. MCP (질문 4)

### 4.1 최신 스펙: 2026-07-28

- 현재(Current) 프로토콜 버전은 **2026-07-28**이다. 버전 문자열은 하위 호환이 깨진 마지막 날짜를 뜻한다 [공식 문서, https://modelcontextprotocol.io/specification/versioning, 확인 11-08].
- 2025-11-25판 대비 주요 변경 [공식 문서, https://modelcontextprotocol.io/specification/2026-07-28/changelog, 확인 11-08]:
  1. Streamable HTTP에서 **프로토콜 수준 세션과 `Mcp-Session-Id` 헤더 제거**. 호출 간 상태가 필요하면 서버가 만든 핸들을 일반 도구 인자로 넘긴다.
  2. **무상태화**: `initialize`/`notifications/initialized` 핸드셰이크 제거. 모든 요청이 `_meta`에 프로토콜 버전(`io.modelcontextprotocol/protocolVersion`)과 클라이언트 능력을 담는다. 버전이 안 맞으면 `UnsupportedProtocolVersionError`.
  3. 서버는 **`server/discover`** RPC를 반드시 구현한다(지원 버전·능력·정체 광고).
  4. HTTP GET 엔드포인트와 `resources/subscribe`를 `subscriptions/listen`(장기 POST 응답 스트림)으로 대체.
  5. `ping`, `logging/setLevel` 제거(로그 레벨은 요청별 `_meta`).
  6. tasks를 코어에서 공식 확장(`io.modelcontextprotocol/tasks`)으로 이동.
  7. Multi Round-Trip Requests(MRTR): 서버가 `InputRequiredResult`를 돌려주면 클라이언트가 원 요청을 재시도하며 정보를 채운다(서버 발신 요청 대체).
  8. 모든 결과에 `resultType` 필수.
  9. **SSE 재개·재전달 제거**: 응답 스트림이 끊기면 진행 중 요청은 잃고, 클라이언트는 새 요청 ID로 다시 보내야 한다 → **쓰기 도구는 멱등이어야 한다.**
  - 부가: Streamable HTTP POST에 `Mcp-Method`·`Mcp-Name` 헤더 필수, `tools/list` 결정적 순서 권장(프롬프트 캐시 적중률↑), 목록 결과에 `ttlMs`·`cacheScope` 필수, 입력/출력 스키마에 JSON Schema 2020-12 허용, OpenTelemetry 추적 문맥 전파 규약.
  - 폐기(Deprecated): Roots·Sampling·Logging, HTTP+SSE 전송, Dynamic Client Registration(→ Client ID Metadata Documents).

### 4.2 인증 요구 사항 (2026-07-28판) [공식 문서, https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization, 확인 11-08]

- 인증은 **선택(OPTIONAL)** 이다. HTTP 전송이면 이 스펙을 따르는 것을 권하고(SHOULD), stdio는 따르지 말고 환경에서 자격 증명을 가져온다.
- 역할: MCP 서버 = OAuth 2.1 **리소스 서버**, MCP 클라이언트 = OAuth 2.1 클라이언트, 토큰 발급은 별도(또는 같이 호스팅된) **인가 서버**.
- MCP 서버는 **Protected Resource Metadata(RFC 9728)** 를 반드시 구현한다. 인가 서버는 RFC 8414 메타데이터나 OIDC Discovery 중 하나 이상을 제공한다.
- 클라이언트 등록: Client ID Metadata Documents(권장), 사전 등록, Dynamic Client Registration(폐기 예정, 하위 호환용) 중 하나.
- 클라이언트는 PKCE를 쓰고, 인가·토큰 요청 모두에 **`resource` 파라미터(RFC 8707, 서버의 정규 URI)** 를 넣는다. 인가 응답의 `iss`를 검증한다(RFC 9207).
- 토큰은 매 HTTP 요청의 `Authorization: Bearer` 헤더로만 보내고 URL 쿼리에 넣지 않는다.
- 서버는 토큰이 **자신을 대상(audience)으로 발급되었는지** 검증하고, 다른 토큰을 받거나 다른 곳으로 넘기면 안 된다(token passthrough 금지). 무효·만료 토큰은 401.
- 401 응답에 `WWW-Authenticate: Bearer resource_metadata="...", scope="..."`를 넣는 것을 권장. 런타임 스코프 부족은 **403 + `error="insufficient_scope"`** 로 필요한 스코프를 한 번에 알린다(step-up).
- 서버 측 응답 코드: 401(인증 필요·토큰 무효), 403(스코프·권한 부족), 400(잘못된 인가 요청).

### 4.3 Python SDK (`mcp` v2) 사용법

- 최신 **`mcp` 2.3.0 (2026-10-02)**, 직전 2.2.0(09-07), 2.1.x(08월). v2부터 서버 예제는 `from mcp.server import MCPServer`를 쓴다(v1의 `FastMCP`에 해당). 실행은 `uv run mcp run server.py --transport streamable-http`, 기본 엔드포인트 `http://localhost:8000/mcp` [공식 문서, https://pypi.org/project/mcp/, https://py.sdk.modelcontextprotocol.io/, 확인 11-08]. PyPI 페이지에 지원 프로토콜 버전 표기는 없다 → 2026-07-28 지원 여부는 **미확인**(What's new in v2 문서 확인 필요).
- 기존 ASGI 앱에 붙이기: `mcp.streamable_http_app()`이 Starlette 앱을 돌려준다. `Mount("/", app=...)`이면 엔드포인트는 `/mcp`. 자체 라우트는 `Mount("/")`보다 앞에 둔다. 마운트된 하위 앱의 lifespan은 안 돌기 때문에 **호스트 lifespan에서 `async with mcp.session_manager.run():`** 에 들어가야 하고, 안 하면 첫 요청이 "Task group is not initialized" 오류를 낸다. 브라우저 클라이언트는 CORS에서 `Mcp-*` 헤더 허용과 `expose_headers=["Mcp-Session-Id"]`가 필요하다고 적혀 있다 [공식 문서, https://py.sdk.modelcontextprotocol.io/run/asgi/]. → 스펙은 세션 헤더를 없앴는데 SDK 문서에는 남아 있어 **상충**. SDK가 2025-11-25판 호환을 같이 지원해서일 가능성이 있다(추정).
- 인증: `TokenVerifier`(비동기 `verify_token(token) -> AccessToken | None`)와 `AuthSettings(issuer_url, resource_server_url, required_scopes, validate_token_resource)`를 **같이** 넘긴다. SDK가 `/.well-known/oauth-protected-resource/mcp`에서 RFC 9728 메타데이터를 내보내고, 미인증 요청에 `WWW-Authenticate`가 담긴 401을 준다. 도구 안에서는 **`get_access_token()`** 으로 검증기가 만든 `AccessToken`(client_id, scopes, 추가 클레임)을 읽는다. SDK 서버는 토큰을 발급하지 않으며, 예전 방식인 `auth_server_provider=`는 새 서버에서 쓰지 말라고 한다 [공식 문서, https://py.sdk.modelcontextprotocol.io/run/authorization/].
- 독립 프로젝트 **FastMCP**(Prefect, `fastmcp` 4.1.6, 2026-11-03)도 계속 유지된다. FastMCP 1.0이 2024년에 공식 SDK에 들어갔다. `JWTVerifier(jwks_uri, issuer, audience, required_scopes, public_key, algorithm)`로 JWT를 검증해 `FastMCP(auth=verifier)`로 붙인다 [공식 문서, https://pypi.org/project/fastmcp/, https://gofastmcp.com/servers/auth/token-verification]. 믿집은 공식 SDK 하나로 통일하는 편이 의존성이 적다.

### 4.4 '로그인 필수·본인 프로젝트만'을 MCP 서버에서 구현하기

믿집 일정 MCP 서버의 클라이언트는 **우리 백엔드(FastAPI/worker)뿐**이다. 그래서 브라우저 OAuth 왕복 없이 **백엔드가 짧은 수명의 내부 JWT를 발급**하고 MCP 서버가 리소스 서버로서 검증하는 구조가 가장 단순하다. 스펙상 인증은 선택이지만 이 구조는 리소스 서버 쪽 요구(audience 검증, Bearer 헤더, 401/403)를 그대로 따른다. 외부 클라이언트(ChatGPT 등)에 공개할 때만 인가 서버·PRM·PKCE 전체를 갖추면 된다(판단).

1. **토큰 발급(FastAPI, 채팅 턴마다)**: `sub=user_id`, `project_id=현재 화면의 프로젝트`, `aud=https://schedule-mcp.internal/mcp`(정규 URI), `scope="schedule:read schedule:request"`, `exp=5분`. 로그인 세션이 없으면 발급하지 않는다 → 로그인 필수.
2. **프로젝트 ID는 LLM 인자로 받지 않는다(poka-yoke).** 도구는 `project_id`를 인자로 두지 말고 토큰 클레임에서만 읽는다. 프롬프트 주입으로 남의 프로젝트를 고르는 IDOR/confused deputy를 원천 차단한다.
3. **도구 안 확인**: `tok = get_access_token()` → 없거나 스코프가 부족하면 401/403. `request_schedule_change`만 `schedule:request` 스코프 요구.
4. **DB 이중 방어**: MCP 서버 전용 DB 역할에 SELECT와 `schedule_change_requests` INSERT만 GRANT하고 RLS를 켠다.

```sql
-- 스케치(실행 검증 안 함)
CREATE ROLE mcp_schedule LOGIN;
GRANT SELECT ON projects, schedules, schedule_alerts TO mcp_schedule;
GRANT INSERT ON schedule_change_requests TO mcp_schedule;
ALTER TABLE schedules ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_schedules ON schedules FOR SELECT TO mcp_schedule
  USING (project_id IN (SELECT id FROM projects
                        WHERE owner_id = current_setting('app.user_id')::bigint));
ALTER TABLE schedule_change_requests ENABLE ROW LEVEL SECURITY;
CREATE POLICY pending_only ON schedule_change_requests FOR INSERT TO mcp_schedule
  WITH CHECK (status = 'pending'
              AND project_id IN (SELECT id FROM projects
                                 WHERE owner_id = current_setting('app.user_id')::bigint));
-- 트랜잭션마다: SET LOCAL app.user_id = '<토큰 sub>';
```

5. **멱등성**: 2026-07-28판은 끊긴 스트림을 재개하지 않고 재전송하게 하므로 `request_schedule_change`에 `idempotency_key`(턴 ID)를 두고 UNIQUE 제약을 건다.
6. **도구 주석**: `get_schedule`·`list_schedule_alerts`·`preview_schedule_change`·`draft_schedule_notice`는 `readOnlyHint: true`. `request_schedule_change`는 대기 건 생성만 하므로 `destructiveHint: false`, `idempotentHint: true`. Agents SDK 0.24.0은 MCP 주석을 변환된 도구에 노출한다 [공식 문서, 릴리스 노트].
7. **네트워크**: MCP 서버는 Docker Compose 내부 네트워크에만 둔다(외부 포트 없음). 그래서 OpenAI가 서버를 직접 부르는 `HostedMCPTool`은 쓰지 않는다.
8. **승인**: UI의 승인 버튼 → FastAPI(사용자 세션 인증) → 실제 일정 반영. 에이전트 경로를 거치지 않는다.

**서버 스케치(v2 import 경로는 미확인, v1 경로 기준이라 마이그레이션 가이드 확인 필요):**

```python
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier          # v1 경로(사전 지식)
from mcp.server.auth.settings import AuthSettings                        # v1 경로(사전 지식)
from mcp.server.auth.middleware.auth_context import get_access_token     # v1 경로(사전 지식)

class MitjipToken(AccessToken):
    user_id: int
    project_id: int

class InternalJWTVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> MitjipToken | None:
        ...  # 서명·exp·aud(=resource_server_url)·scope 검증, 실패 시 None

mcp = MCPServer(
    "mitjip-schedule",
    token_verifier=InternalJWTVerifier(),
    auth=AuthSettings(
        issuer_url="https://api.mitjip.internal",
        resource_server_url="https://schedule-mcp.internal/mcp",
        required_scopes=["schedule:read"],
    ),
)

@mcp.tool()
async def get_schedule() -> dict:
    tok = get_access_token()
    return await schedule_repo.read(user_id=tok.user_id, project_id=tok.project_id)
```

### 4.5 OpenAI Agents SDK에서 원격 MCP 서버 붙이기 [공식 문서, https://openai.github.io/openai-agents-python/mcp/, 확인 11-08]

- 직접 연결: `MCPServerStreamableHttp(params={"url": ..., "headers": {"Authorization": f"Bearer {token}"}, "timeout": 10}, cache_tools_list=True, max_retry_attempts=3, tool_filter=..., client_session_timeout_seconds=...)`를 async context manager로 열고 `Agent(mcp_servers=[server])`에 넣는다.
- 사용자별 토큰: 내장 기능은 없고, 헤더는 생성 시 한 번 정해진다 → **턴마다 새 인스턴스**를 만든다(문서의 예와 SDK 설계에서 나온 추론). `tool_meta_resolver`로 호출마다 `_meta`를 넣을 수 있지만 Authorization 헤더는 바꾸지 못한다.
- `params["auth"]`를 쓸 때는 설치된 `mcp` 메이저에 맞춰 v1은 `httpx.Auth`, v2는 `httpx2.Auth`를 쓴다.
- 도구 필터: `create_static_tool_filter(allowed_tool_names=[...])` 또는 `ToolFilterContext`를 받는 함수. 공정표 에이전트에만 `request_schedule_change`를 노출한다.
- 승인: 로컬 서버도 `require_approval`(always/never/도구별/함수)을 줄 수 있지만, 믿집은 화면 버튼이 승인이므로 쓰지 않는다.
- 여러 서버: `MCPServerManager`, 실패 서버 `reconnect(failed_only=True)`.

```python
# 스케치
from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp, create_static_tool_filter

async def run_schedule_agent(user_msg: str, turn_token: str):
    async with MCPServerStreamableHttp(
        name="mitjip-schedule",
        params={"url": settings.SCHEDULE_MCP_URL,
                "headers": {"Authorization": f"Bearer {turn_token}"}, "timeout": 10},
        cache_tools_list=True,
        tool_filter=create_static_tool_filter(allowed_tool_names=[
            "get_schedule", "list_schedule_alerts", "preview_schedule_change",
            "request_schedule_change"]),
    ) as server:
        agent = Agent(name="공정표", instructions=..., model=llm.agent_model(),
                      model_settings=llm.agent_settings(), mcp_servers=[server],
                      output_type=ScheduleReply)
        return await Runner.run(agent, user_msg, max_turns=5)
```

---

## 5. 평가 (질문 5)

### 5.1 세트별 지표

| 세트(개수) | 무엇을 재나 | 지표 | LLM 필요 | CI 가능 |
|---|---|---|---|---|
| 의도 200 | 입구 분류기·Jev·되묻기 | 정확도, **macro-F1**, 클래스별 P/R, 혼동행렬, **ECE**(10~15구간)·신뢰도 다이어그램, 위험-커버리지 곡선(임계값별 자동 처리율 vs 정확도), Jev 폴백률·되묻기율 | 분류기는 불필요, Jev 비교는 1회 측정 | ✅(분류기) |
| RAG 30 | 검색 | **Recall@5**, **nDCG@10**, MRR, 하이브리드 vs 벡터 vs 키워드 비교 | 불필요(질의 임베딩 캐시) | ✅ |
| RAG 30(답) | 근거 일치 | 답의 주장마다 인용 청크가 뒷받침하는지(지지율), 인용 정확도 | 판정 LLM 또는 사람 | 수동 |
| 공정표 15 | 일정 계산 | 날짜·선후관계·겹침 없음 등 **정확 일치** | 불필요 | ✅ |
| 오케스트레이터 30 | 경로 | **trajectory 일치**: 기대 에이전트, 도구 호출 집합·순서, 상한 준수, 되묻기 여부 | 녹화 응답(ScriptedModel)이면 불필요 | ✅ |
| 상담 10 | 다중 턴 상담 품질 | 루브릭 LLM 판정(정확성·근거·안전·말투), **pass^k**(k=3) | 필요 | 수동·야간 |
| 가이드 50 | 튜터링 | 루브릭(9.4) + 숫자 0건 + 용어집 일치 | 필요 | 수동·야간 |
| 견적 설명 | 숫자 환각·설명 품질 | 문장 단위 숫자 대조 통과율(목표 100%), 항목 누락률, 루브릭 | 검사기는 불필요, 품질은 필요 | ✅(검사기) |

- **보정**: temperature scaling은 검증셋 NLL을 최소화하는 온도 T 하나로 로짓을 나눠 정확도는 그대로 두고 ECE를 낮춘다(Guo et al., 2017) [논문, 사전 지식, https://arxiv.org/abs/1706.04599]. 사전학습 트랜스포머는 도메인 안에서는 비교적 잘 보정되지만 도메인 밖(OOD)에서는 나빠진다(Desai & Durrett, 2020) [논문, 사전 지식, https://arxiv.org/abs/2003.07892] → 의도 200에 범위 밖 문장을 꼭 넣는다.
- **pass^k**: 같은 과제를 k번 돌려 모두 성공해야 통과로 보는 일관성 지표(τ-bench, Yao et al., 2024) [논문, 사전 지식, https://arxiv.org/abs/2406.12045].
- **LLM 판정 편향**: 위치·장황함·자기 선호 편향이 보고되었다(Zheng et al., 2023) [논문, 사전 지식, https://arxiv.org/abs/2306.05685] → 판정 모델은 생성 모델과 다르게(예: 생성 terra, 판정 `gpt-6.1-sol`, 같은 공급자), 루브릭은 항목별 이진/3점, 사람 라벨 20~30개와 일치도(Cohen's κ)를 잰다.
- **사실 분해 평가**: 긴 답을 원자 사실로 나눠 각각 지지 여부를 보는 방식(FActScore, Min et al., 2023) [논문, 사전 지식, https://arxiv.org/abs/2305.14251]은 RAG 근거 일치 판정에 응용할 수 있다.
- Anthropic 연구 시스템 글의 실무 교훈: 실제 질의 약 20개로 일찍 시작하고, 루브릭 LLM 판정 + 사람 평가를 함께 쓴다 [블로그].

### 5.2 숫자 환각 검사 설계

1. **1차(예방): 숫자 슬롯 방식.** 계산 엔진 결과를 `{"total_min": 1200000, "total_max": 1500000, "wallpaper_area_m2": 84.5, ...}` 같은 키-값으로 주고, LLM에게는 숫자 대신 `⟦total_min⟧` 같은 슬롯만 쓰게 한다. 렌더링은 코드가 하고 허용되지 않은 키가 나오면 버린다.
2. **2차(검출): 문장 단위 숫자 추출·대조.** 슬롯을 채운 뒤에도 남은 숫자가 있으면 정규화해 허용 집합과 비교한다.

```python
# 스케치
import re
from decimal import Decimal

NUM = re.compile(r"(?P<n>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<u>만\s*원|천\s*원|원|만|%|㎡|m²|평|일|개|롤)?")
HANGUL_NUM = re.compile(r"[일이삼사오육칠팔구십백천만억]+\s*(원|평|일)")   # '삼백만 원' 같은 한글 숫자 금지

def normalize(n: str, u: str | None) -> Decimal:
    v = Decimal(n.replace(",", ""))
    u = (u or "").replace(" ", "")
    return v * 10000 if u in ("만원", "만") else v * 1000 if u == "천원" else v

def sentence_ok(sentence: str, allowed: set[Decimal]) -> bool:
    if HANGUL_NUM.search(sentence):
        return False
    return all(normalize(m["n"], m["u"]) in allowed for m in NUM.finditer(sentence))
```

3. **허용 집합**은 계산 엔진이 만든 값만 넣는다(합계·항목·단가·수량·범위 양 끝·비율). 파생 값(차액·평당가)이 필요하면 엔진이 미리 계산해 넣는다. 범위("120만~150만 원")는 양 끝을 각각 대조한다.
4. 실패 문장은 버리고, 핵심 문장이 빠지면 1회만 재생성(evaluator-optimizer 1회 상한), 그래도 실패하면 "숫자는 견적표를 확인하세요" 고정 문구로 대체한다.
5. 프롬프트에 "숫자는 아라비아 숫자로만, 계산하지 말 것"을 넣지만 **검사기가 최종 권한**이다.

### 5.3 도구 비교 [공식 문서, 각 PyPI·저장소, 확인 11-08]

| 도구 | 최신 | 라이선스 | 강점 | 약점·주의 | 믿집 판단 |
|---|---|---|---|---|---|
| OpenAI Evals 플랫폼 / Graders | — | — | 대시보드 기반 | **2026-11-30 종료, 10-31부터 읽기 전용**, 공식 이전 경로는 Promptfoo [공식 문서]. Graders(RFT용) 별도 존속 여부는 **미확인** | **쓰지 않음** |
| promptfoo | 저장소에 릴리스 표기 없음(미확인) | MIT | 선언형 설정, 로컬 실행, CLI·CI, 레드팀, 모델 비교. **OpenAI에 인수**(2026-03-09 발표), 오픈소스·MIT 유지 명시 [공식 문서·블로그] | 판정 비용은 LLM 호출. `llm-rubric`·python assert 같은 단언 종류는 사전 지식 | **LLM 판정 세트의 본체** |
| DeepEval | 4.3.3 (2026-11-04) | Apache-2.0 | pytest 통합(`deepeval test run`), G-Eval·DAG, RAG 지표, 에이전트 지표(Tool Correctness, Task Completion), 다중 턴 지표. Confident AI 로그인은 선택 | 대부분 지표가 LLM 판정 | promptfoo 대신 pytest만 쓰고 싶을 때 |
| Ragas | 0.4.3 (2026-01-13) | Apache-2.0 | RAG 지표 | 마지막 릴리스 후 약 10개월 공백(활발도 낮음, 추정) | 선택 사항. Recall@k·nDCG는 직접 계산이 더 간단 |
| Inspect AI | 0.3.288 (2026-11-07) | MIT | 영국 AI Security Institute, 200개+ 내장 평가, 도구 사용·다중 턴·모델 판정 | Python ≥3.11, 학습 비용 | 과함(발표 후 검토) |
| Langfuse(셀프호스트) | v4 문서 | 핵심 라이선스는 페이지에 명시 없음, 일부 기능 EE 라이선스 키 | 트레이싱·데이터셋·프롬프트·판정 | **PostgreSQL + ClickHouse + Redis/Valkey + S3 + web/worker** 필요. Docker Compose는 단일 VM·HA·백업 없음 [공식 문서] | EC2 소규모엔 부담 → OpenAI Traces 또는 Langfuse Cloud(요금제 미확인) |

출처: https://github.com/promptfoo/promptfoo · https://pypi.org/project/deepeval/ · https://pypi.org/project/ragas/ · https://pypi.org/project/inspect-ai/ · https://langfuse.com/self-hosting · https://developers.openai.com/cookbook/examples/evaluation/moving-from-openai-evals-to-promptfoo (검색 결과로만 확인)

### 5.4 소규모 팀 조합 추천

- **L0 — CI(LLM 0회)**: pytest + scikit-learn(`classification_report`, `confusion_matrix`, ECE 직접 계산), 자체 Recall@k·nDCG 함수, 공정표 정확 일치, 숫자 검사기 단위 테스트, Agents SDK `ScriptedModel`로 오케스트레이터 30의 경로·도구 순서·상한 검사. 환경: `OPENAI_AGENTS_DISABLE_TRACING=1`, Jev·임베딩·rerank 스텁, 외부 네트워크 차단.
- **L1 — 수동·야간(LLM 사용)**: promptfoo로 상담 10·가이드 50·견적 설명 품질을 루브릭 판정. 판정 모델은 `gpt-6.1-sol`, k=3 반복으로 pass^3, 결과 JSON을 저장소에 남겨 회귀 비교.
- **L2 — 관측**: OpenAI Traces(내장, `trace_include_sensitive_data=False`) 또는 Langfuse Cloud. 셀프호스트 Langfuse는 발표(12-08) 후 검토.
- **목표선 예시(팀 합의 필요)**: 의도 macro-F1 ≥0.90·자동 처리 구간 정확도 ≥0.97, RAG Recall@5 ≥0.90, 공정표 15/15, 숫자 검사 통과 100%, 상담 pass^3 ≥0.8.

---

## 6. 한국어 의도 분류 '직접 학습' 모델 (질문 6)

### 6.1 후보

| 후보 | 크기 | 라이선스 | 특징·근거 |
|---|---|---|---|
| `skt/A.X-Encoder-base` | 약 149M(카드 표기 0.1B) | Apache-2.0 | ModernBERT 구조, 16,384토큰, transformers ≥4.51, Flash Attention 2 권장(필수 아님), "최대 3배 빠른 추론"(A100 차트, 자체 주장). KoBEST 평균 85.50 vs klue/roberta-base 76.44, KLUE 평균 86.10 vs 85.19(YNAT 86.50 vs 86.48) [공식 문서(모델 카드, 자체 보고), https://huggingface.co/skt/A.X-Encoder-base]. 공개 연도 2025 |
| `klue/roberta-base` | 약 110M | 모델 카드에 표기 없음 → **확인 필요** | KLUE 기준 모델. 토크나이저는 `BertTokenizer`(AutoTokenizer가 자동 선택) [공식 문서, https://huggingface.co/klue/roberta-base]. 파생 미세조정 모델 499개 |
| `kakaobank/kf-deberta-base` | — | **확인 필요** | KoBEST 83.25, KLUE 85.80 (A.X 카드 비교표) |
| KoELECTRA-base-v3 | 약 110M | Apache-2.0(사전 지식) | 2020년 모델, 뉴스·위키 등 학습(사전 지식) |
| KcBERT / KcELECTRA | — | **미확인** | 네이버 뉴스 댓글로 학습해 구어체·오타에 강하다(사전 지식). 사용자 입력이 구어체라 후보 가치 있음 |
| multilingual-e5-small/base/large + 로지스틱 회귀 | 118M/278M/560M(사전 지식) | MIT(사전 지식) | 학습 없이 임베딩 + 선형 분류. `query: ` 접두어 필요(사전 지식). 모델 카드 로드 실패 → **미확인** |
| KURE-v1 / bge-m3 + 로지스틱 회귀 | 568M | MIT | 한국어 검색 상위권(1.6절). 분류용 임베딩으로도 강할 것으로 기대(추정). 무거움 |
| SetFit 1.2.0 (2026-09-04) | 문장 임베딩 모델 크기 | Apache-2.0 | 소량 학습. 저자 주장: Customer Reviews에서 클래스당 8개로 RoBERTa-large 전체(3천 개) 미세조정과 경쟁. 어떤 Sentence Transformer와도 동작, `SetFitHead` 지원, `onnx` extra [공식 문서, https://pypi.org/project/setfit/]. 논문 Tunstall et al., 2022 [논문, 사전 지식, https://arxiv.org/abs/2209.11055] |

### 6.2 클래스 10~20개, 학습 수백~수천 문장일 때 추천

- **데이터**: 의도 200은 **평가 전용**(학습 금지). 학습용은 의도당 50~150문장(총 1~3천)을 목표로, 실제 사용자 문장 + 팀 작성 + LLM 패러프레이즈(오프라인 생성 후 사람 검수)로 만든다. `out_of_scope`(인테리어 무관·불명확) 클래스를 반드시 둔다.
- **1단계(하루, 기준선)**: multilingual-e5-base 또는 KURE-v1 임베딩 + `LogisticRegression(class_weight="balanced")`. 학습·재학습이 몇 초라 데이터 반복이 빠르다.
- **2단계(기준선이 목표에 못 미치면)**: `skt/A.X-Encoder-base` 또는 `klue/roberta-base` 전체 미세조정(3~5 에폭, max_len 64, 학습률 2e-5~5e-5 범위 탐색, 사전 지식). 수천 문장 규모에서는 보통 미세조정이 가장 정확하다(사전 지식). 개선폭이 1~2%p 이하면 운영이 단순한 기준선을 채택한다.
- **클래스당 20개 미만이면**: SetFit(한국어 문장 임베딩 모델 기반).
- **라이선스 정리 필요**: 발표·공개 저장소에 쓰려면 A.X-Encoder(Apache-2.0)·KURE(MIT/Apache-2.0)가 깔끔하다. klue/roberta·kf-deberta·KcBERT는 라이선스를 직접 확인한다.

### 6.3 신뢰도 보정과 임계값

1. 학습/검증/평가 분할 → 검증셋에서 온도 T 학습(temperature scaling) → 평가셋에서 보정 전후 ECE 비교.
2. 위험-커버리지 곡선으로 τ_model을 고른다(예: "자동 라우팅 구간 정확도 ≥0.97이 되는 최저 τ").
3. τ_model 미만 → Jev 1회(입구 분류에만) → Jev `confidence`가 τ_jev 미만이거나 두 결과가 다르면 되묻기(선택지 2~3개 버튼).
4. 임계값은 '실수 비용' 기준으로 정한다. 일정 변경 의도 오분류는 비용이 크고, 가이드 질문 오분류는 작다 → 의도별 임계값을 달리할 수 있다.

### 6.4 CPU 추론·ONNX

- Hugging Face Optimum으로 ONNX 내보내기 → ONNX Runtime CPU, 동적 int8 양자화(사전 지식). 배치 1, `intra_op_num_threads`를 vCPU 수로, 기동 시 warmup.
- 공개 수치 예: 오래된 ORT 1.2, BERT-base, 시퀀스 128, FP32에서 단일 스레드 294ms / 8스레드 111ms(Xeon W2123) [커뮤니티, https://nightr.gitbook.io/nnopt/applications/1_bert]. 의도 문장은 보통 32토큰 이하라 훨씬 짧고, 최신 ORT·int8이면 더 빠를 것으로 본다(추정). **배포할 EC2 인스턴스에서 p50/p95를 꼭 직접 잰다.**
- 모델은 FastAPI 프로세스에 한 번 로드하거나 별도 경량 컨테이너로 둔다. 모델 파일·라벨맵·온도 T·임계값을 한 묶음으로 버전 관리한다.

---

## 7. PostgreSQL 한국어 검색 (질문 7)

### 7.1 pgvector 최신과 AWS RDS 지원

- **upstream**: 최신 0.8.7(2026-10-01). 0.8.6(07-29), 0.8.5(07-08), 0.8.4(06-30), **0.8.3(06-17, HNSW vacuum 중 인덱스 손상 가능성 수정)**, 0.8.2(02-25), 0.8.1(2025-09-04, PG18 지원), **0.8.0(2024-10-30, iterative index scan 추가)**, 0.7.0(2024-04-29, `halfvec`·`sparsevec`·binary quantize 추가). 0.9.0은 미출시(HNSW 비동기 I/O, PG13·14 지원 중단) [공식 문서, https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md, 확인 11-08].
- **RDS for PostgreSQL 17 지원 확장** [공식 문서, https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html, 확인 11-08]:

| 확장 | RDS PG17 | 버전(마이너별) |
|---|---|---|
| `vector`(pgvector) | ✅ | 17.6·17.7: 0.8.0 / 17.8·17.9: 0.8.1 / 17.9R2·17.10·17.10R2·17.11: **0.8.2** |
| `pg_bigm` | ✅ | 17.6·17.7: 1.2_20240606 / 17.8 이후: **1.2_20250903** |
| `pg_trgm` | ✅ | 1.6 |
| `pg_cron` | ✅ | 1.6.5 → 17.8 이후 1.6.7 |
| PGroonga | ❌ | 표에 없음 |
| textsearch_ko, mecab | ❌ | 표에 없음 |
| rum, pg_search, zhparser | ❌ | 표에 없음 |

  - 확장 버전은 엔진 업그레이드 때 자동으로 오르지 않는다 → `ALTER EXTENSION vector UPDATE;` 필요 [공식 문서].
- **주의**: RDS 최고 pgvector는 0.8.2라 0.8.3의 HNSW vacuum 손상 수정이 아직 없다. 믿집 코퍼스(가이드 수백~수천 청크)는 **인덱스 없이 정확 검색**해도 충분히 빠를 것으로 보이며(추정), pgvector는 기본이 정확 최근접 탐색이라 재현율이 완벽하다 [공식 문서]. → MVP는 HNSW 없이 시작, 1만 청크를 넘으면 HNSW 검토.
- **HNSW 기본값**: `m=16`, `ef_construction=64`, `hnsw.ef_search=40`. **Iterative scan**(0.8.0+): `SET hnsw.iterative_scan = strict_order | relaxed_order;`, `hnsw.max_scan_tuples`(기본 20,000), `hnsw.scan_mem_multiplier`(기본 1), IVFFlat은 `ivfflat.max_probes`. 근사 인덱스는 필터를 인덱스 스캔 **뒤에** 적용하므로 `WHERE project_id=...` 같은 필터가 있으면 iterative scan이나 부분 인덱스·파티션을 쓴다 [공식 문서, https://github.com/pgvector/pgvector].
- **차원 한도(인덱스)**: `vector` 2,000, `halfvec` 4,000. 예: `CREATE INDEX ON items USING hnsw ((embedding::halfvec(3)) halfvec_l2_ops);` → 1536차원(te3-small)은 그대로, 2048(KURE-v3)·3072(te3-large)는 halfvec 필요 [공식 문서].
- **하이브리드**: pgvector README가 Postgres 전문 검색과 함께 쓰고 결과는 **Reciprocal Rank Fusion이나 cross-encoder**로 합치라고 안내한다 [공식 문서]. RRF는 Cormack et al.(SIGIR 2009) [논문, 사전 지식].

### 7.2 한국어 전문 검색 선택지

| 방식 | RDS | 원리 | 장단점 |
|---|---|---|---|
| 내장 FTS(`simple` 설정) | ✅ | 공백 단위 토큰 | 한국어 사전이 없어 '도배를/도배는'처럼 조사가 붙은 어절이 서로 안 맞는다(사전 지식) |
| `pg_trgm` | ✅ | 3-gram | 2음절 단어(도배·장판·몰딩)는 3-gram이 안 나와 인덱스 효율이 낮다(사전 지식) |
| **`pg_bigm`** | ✅ | 2-gram GIN 인덱스, `LIKE '%..%'` 가속, `likequery()`, `bigm_similarity()`(사전 지식) | 한중일처럼 띄어쓰기·형태 변화가 많은 언어에 맞고 2음절 검색 가능. 인덱스가 크다 |
| PGroonga | ❌ | 전 언어 전문 검색 | RDS 불가 → 로컬·자체 운영 PG에서만 |
| textsearch_ko(mecab-ko) | ❌ | 형태소 기반 tsvector | RDS 불가 |
| 앱 형태소 분석 + `tsvector('simple')` | ✅ | Kiwi(`kiwipiepy`) 등으로 명사·어근을 뽑아 공백으로 이어 저장 | BM25가 아니라 `ts_rank`. 분석기 라이선스 확인 필요(사전 지식) |

### 7.3 하이브리드(RRF) SQL 스케치

```sql
-- $1 = 질의 임베딩, $2 = 키워드(앱에서 조사 제거·2음절 이상)
WITH v AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS r
  FROM guide_chunks ORDER BY embedding <=> $1 LIMIT 40
), k AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY bigm_similarity(body, $2) DESC) AS r
  FROM guide_chunks WHERE body LIKE likequery($2)
  ORDER BY bigm_similarity(body, $2) DESC LIMIT 40
)
SELECT id, SUM(1.0 / (60 + r)) AS rrf
FROM (SELECT * FROM v UNION ALL SELECT * FROM k) u
GROUP BY id ORDER BY rrf DESC LIMIT 8;
-- 인덱스: CREATE INDEX ON guide_chunks USING gin (body gin_bigm_ops);
```

### 7.4 권장 구성

1. RDS는 **17.10 이상**(pgvector 0.8.2, pg_bigm 1.2_20250903).
2. 로컬 Docker는 `pgvector/pgvector:pg17` 같은 이미지에 pg_bigm이 없을 수 있다(추정) → pg_bigm을 소스로 빌드하는 Dockerfile을 두어 RDS와 확장을 맞춘다.
3. 검색: 벡터 top-40 + pg_bigm top-40 → RRF → (선택) rerank-3 → 상위 5~8개를 LLM에 넣는다.
4. RAG 30에서 '벡터만 / bigm만 / RRF / RRF+rerank' 4가지를 Recall@5·nDCG@10으로 비교해 결정한다.

---

## 8. 사진 분석(비전 LLM)으로 실측 전 상태 파악 (질문 8)

### 8.1 근거

- **DefectBench**(arXiv 2603.20148, 2026-03-20, HKUST 등): 공개 건물 결함 데이터셋 12개를 합쳐 이미지 1,488장·결함 4,527개(균열·재료 손실·표면 얼룩·외부 부착물, 곰팡이는 한 원천 데이터셋에만 있음). 결과: '무엇' 인식은 재현율이 높고(Gemini-3 R=0.9711), **개수 세기는 대부분 모델의 MAE가 1.0 근처 이상**이며 표면 얼룩에서 오차가 특히 크다. '어디' 위치 찾기는 최고 검출 F1이 0.4226(Gemini-3-pro-preview)에 그친다. 여러 턴 프롬프트에서 앞선 오분류가 전파된다. 저자 결론은 "정량 매핑보다 정성 추론에 쓸모"다. 평가 모델 수가 본문에서 18·24·16으로 엇갈린다 → **논문 내 상충** [논문, https://arxiv.org/html/2603.20148, 확인 11-08].
- **OpenAI 비전 문서의 한계 목록**: 개수는 근사치일 수 있음, 체스판 같은 공간 추론 약함, 회전·뒤집힌 이미지 오해, 파노라마·어안 이미지, 작은 글씨, 의료 영상 부적합, 원본 파일명·메타데이터는 처리하지 않음, CAPTCHA 차단 [공식 문서, https://developers.openai.com/api/docs/guides/images-vision, 확인 11-08].
- 하수관 결함 연구: GPT-4o가 재현율은 높고 정밀도는 낮아 오탐이 많았고 o3가 가장 좋았다 [논문, 검색 요약으로만 확인, https://www.cambridge.org/core/journals/cambridge-prisms-water/article/multiclass-sewer-defect-detection-with-visionlanguage-models/5A50F4D3610089FF1771B78D1FE69AB3].
- ChatGPT-4o 구조 결함 연구(Springer, 2025-06): 복잡한 환경·특수 결함 이미지에서 정보 추출에 한계 [논문, 검색 요약으로만 확인].
- **국내 서비스 사례(2026)**: 핸드맨(누수·보일러·욕실 사진 → AI가 예상 원인·긴급도·해결책 안내), 데코더(사진·유튜브로 스타일·제품·예산 분석, 하자 사진으로 심각도·대략 비용), INPE(AI 견적, 평균 30% 절감 주장), 미소(텍스트로 곰팡이 진단 후 시공 연결). 모두 업체 홍보 자료이고 **정확도 검증 자료는 찾지 못했다** [블로그/업체, https://handman.co.kr/, https://decodar.work/, https://inpe.kr/ai-estimate.html, https://welaunch.kr/...].
- 공식 출시 근거: gpt-6.1-terra는 '시각 추론'을 내세운다 [공식 문서]. 다만 terra의 비전 정확도에 대한 공개 벤치는 확인하지 못했다(**미확인**).

### 8.2 항목별 가능성 (판단, 정확도 수치 근거 없음)

| 항목 | 가능성 | 이유 | 권장 처리 |
|---|---|---|---|
| 우물천장 유무 | 중~높음 | 천장 전체 사진에서 단차가 크게 보인다 | 자동 제안 + 확인 |
| 몰딩 종류(천장 몰딩 유무·형태, 걸레받이) | 중 | 근접 사진이 있으면 형태 구분 가능, 원거리는 어렵다 | 근접 사진 요청, 선택지 4~5개 + '모름' |
| 기존 벽지 종류(합지 vs 실크) | 낮음~중 | 광택·엠보 질감 단서가 조명에 크게 좌우된다 | 측광 근접 사진 + "표면에 비닐 코팅감이 있나요?" 같은 확인 질문 |
| 곰팡이·얼룩 | 중(재현율↑ 정밀도↓ 예상) | 그림자·오염과 혼동, 얼룩은 벤치에서 오차가 큼 | '의심'으로만 표시, 확정 진단 금지, 현장 확인 안내 |
| 들뜸 | 낮음 | 입체감이라 정면 사진에서 잘 안 보인다 | 비스듬한 조명 사진 요청, 사용자 확인 |
| 문 개수 | 낮음 | 한 장에 다 안 보이고, 개수 세기가 약하다 | 사용자 입력 또는 평면도가 정답, 사진은 보조 |

### 8.3 설계

- **출력 스키마**: 항목마다 `value`(enum) + `"unknown"` 선택지 + `confidence`(low/med/high) + `evidence`(어느 사진 어디에서 봤는지 한 줄) + `needs_user_check: bool`. Structured Outputs로 강제한다.
- **사람 확인 필수**: 결과는 '사전 체크리스트 초안'으로만 보여 주고, 사용자가 확인한 값만 견적·공정 입력에 쓴다. 계산 엔진이 비전 결과를 바로 쓰지 않게 한다.
- **촬영 가이드**: 벽면별 정면 1장, 천장 1장, 몰딩·걸레받이 근접 1장, 문제 부위 근접+비스듬한 조명 1장. 어안·파노라마는 피한다(OpenAI 한계).
- **비용 절감**: 1차는 `detail: low`(512×512 이내)로 전체 분류, '모름'·'의심' 항목만 해당 사진을 `high`로 다시 본다(사전 지식 기반 설계).
- **평가**: 라벨링한 실제 사진 50~100장으로 항목별 정확도·'모름' 비율을 잰다. 곰팡이는 정밀도·재현율을 따로 본다.

### 8.4 비용 추정

- 패치 방식 모델은 32px 패치 수 `ceil(w/32)×ceil(h/32)`에 모델 배수(대부분 1.2)를 곱해 토큰을 센다. 예: gpt-6-astra `high`에서 1024×1024 ≈ 1,229토큰 [공식 문서]. 문서의 패치 방식 목록에 **terra는 없다** → terra 토큰 산식은 **미확인**.
- 같은 산식이라고 가정하면 1MP 사진 1장 ≈ 1.2천 토큰 ≈ $0.0012(terra 입력가), 사진 10장 + 출력 1천 토큰이면 1회 분석 약 $0.02 내외(추정).

### 8.5 개인정보 처리

- **EXIF**: 위치 정보가 있으면 집 주소를 추정할 수 있다. 서버 업로드 단계에서 픽셀만 다시 저장해 메타데이터를 지운다(예: Pillow로 새 이미지 저장, 사전 지식). 모델은 메타데이터를 처리하지 않지만 [공식 문서] 원본을 그대로 보내면 메타데이터도 외부로 전송된다.
- **얼굴·사람**: 얼굴 감지 시 블러하거나 재촬영을 요청한다. 가족사진 액자·거울에 비친 사람도 주의한다.
- **주소 단서**: 현관 동·호수, 우편물·택배 송장, 창밖 풍경을 피하도록 촬영 전에 안내하고, 감지되면 경고한다.
- **외부 전송**: OpenAI API는 기본적으로 학습에 쓰지 않고 남용 모니터링 로그를 최대 30일 보관한다. `store=false`로 응답 상태 저장을 끈다. 한국 레지던시는 저장만 되고 처리는 해외다 [공식 문서].
- **보관**: 원본은 비공개 버킷에 짧게 두고, 분석 결과(구조화 값)만 오래 보관한다. 처리 목적·보관 기간·국외 이전을 개인정보 처리방침에 적는다. 사진 속 정보가 법상 개인정보·위치정보에 해당하는지는 **법률 검토 필요(미확인)**.

---

## 9. 초보를 '공부한 소비자'로 만드는 튜터링 대화 설계 (질문 9)

### 9.1 2024~2026 사례

| 사례 | 날짜 | 핵심 | 신뢰도·URL |
|---|---|---|---|
| Google LearnLM | 블로그 2024-05-14, 논문 v3 2025-08-22 | 학습과학 5원칙: **능동 학습 유도**(연습·적절한 고생 + 즉시 피드백), **인지 부하 관리**(관련 있고 구조화된 정보를 여러 형태로), **학습자 적응**(목표·필요에 맞춰 조정, 자료에 근거), **호기심 자극**, **메타인지 심화**(계획·점검·성찰). 논문은 교수법을 시스템 지시로 지정하는 '교수법 지시 따르기'로 학습시켰고, 전문가 평가에서 GPT-4o 대비 +31%, Claude 3.5 Sonnet 대비 +11%, Gemini 1.5 Pro 대비 +13% 선호 | [블로그] https://blog.google/outreach-initiatives/education/google-learnlm-gemini-generative-ai/ · [논문] https://arxiv.org/abs/2412.16429 |
| Google, *Towards Responsible Development of GenAI for Education* | 2024-05 제출, v4 2025-12-02 | 학습과학 원칙을 교육 벤치 7개로 바꾸고, 교사·학습자 평가로 LearnLM-Tutor 검증 | [논문] https://arxiv.org/abs/2407.12687 |
| Gemini Guided Learning | 2025-08 초 | Google의 학습 모드(언론 요약) | [블로그] 언론 요약으로만 확인 |
| OpenAI ChatGPT study mode | 2025-07-29 | 새 모델이 아니라 교사·과학자·교육 전문가와 만든 **커스텀 시스템 지시**. 질문으로 목표와 이해 수준을 파악한 뒤 맞춘다. 정보를 단계적으로 내놓아 과부하를 막는다. 끌 수 있다. 대화마다 일관되지 않은 동작과 실수가 있을 수 있다고 인정하고, 나중에 본 모델에 학습시킬 계획 | [블로그] https://www.engadget.com/ai/chatgpts-study-mode-will-guide-students-to-an-answer-stey-by-step-180614172.html (OpenAI 원문 403으로 미열람) |
| Anthropic learning mode | 2025-04(Claude for Education) → 2025-08-14 전체 | 스타일 메뉴의 'Learning'. 답을 바로 주지 않고 스스로 풀게 이끄는 소크라테스식. Claude Code에는 'Explanatory'(결정 과정 설명)와 'Learning'(사용자에게 #TODO 코드 5~10줄 작성을 요청) 출력 스타일 | [블로그] https://www.engadget.com/ai/anthropic-brings-claudes-learning-mode-to-regular-users-and-devs-170018471.html |
| Khanmigo(Khan Academy) | 2023~2025 | 몇 문장 지시로는 일관성이 안 나와 프롬프트 재실행 평가와 버전 관리가 필요했다. 프롬프트가 길수록 일부 지시가 무시되어 부분별 프롬프트로 나누고 루브릭으로 평가했다. 비판: 배경지식이 없는 학습자에게 소크라테스식은 혼란을 주고 다른 AI로 답을 복사해 가는 일이 있었다는 보고 | [블로그] https://blog.khanacademy.org/?p=14782 (검색 요약) · 비판은 신뢰도 낮은 2차 자료 |
| 선제적 AI 도우미 연구 | CHI 2025 | 선제 제안형 채팅 도우미를 넣자 생산성·경험에 유의한 이득, 다만 설계 요소에 따른 뉘앙스가 있다 | [논문] https://arxiv.org/abs/2410.04596 |

### 9.2 원칙 → 믿집 설계

핵심 판단: 믿집 사용자는 시험을 보는 학생이 아니라 **돈과 집을 건 결정을 앞둔 소비자**다. 그래서 답을 숨기는 소크라테스식이 아니라 **"답 먼저 → 왜 그런지 → 확인 질문 1개 → 다음에 알아야 할 것 선제 안내"** 로 간다. Khanmigo 비판(배경지식 없는 학습자에게 소크라테스식은 역효과)과 OpenAI·Anthropic이 학습 모드를 '켜고 끄는 선택'으로 둔 점이 근거다.

| 원칙(근거) | 믿집 구현 |
|---|---|
| 학습 목표 명시(LearnLM 적응·메타인지) | 단계별 '공부한 소비자' 체크리스트. 도배 예: ① 용어(합지/실크, 초배, 부분/전체 도배, 몰딩, 걸레받이) ② 견적 읽기(면적 산정 방식, 자재비·인건비·부자재, 철거·보양·폐기물) ③ 품질 판단(들뜸·이음매·곰팡이 처리) ④ 업체에 물을 질문 목록 |
| 선제 안내(CHI 2025, proactive) | 트리거: 공정 단계 이벤트(견적 도착, 공정 D-3), 학습자 상태의 빈칸, 사진 분석의 '모름/의심' 항목, 견적 항목 누락. **턴당 선제 팁 1개**, "그만 보기" 제공 |
| 인지 부하 관리(LearnLM, study mode) | **점진 공개**: 한 줄 답 → "왜?" 펼치기 → 심화. 한 턴에 새 용어 ≤3개(NN/g의 progressive disclosure 개념, 사전 지식, https://www.nngroup.com/articles/progressive-disclosure/) |
| 능동 학습·이해 확인(LearnLM, study mode) | 핵심 개념 뒤 확인 질문 1개(선택형 버튼 2~3개). 강제 퀴즈 금지, 건너뛰기 허용 |
| 근거·일관성(Khanmigo 교훈) | **용어집은 DB에서 관리**하고 LLM은 정의를 RAG로 받아 그대로 쓴다. 프롬프트는 짧은 부분별로 나누고 eval로 회귀 확인 |
| 메타인지 | "지금 결정할 것 / 나중에 결정할 것" 요약, 학습 진행률 UI |

### 9.3 학습자 모델(가벼운 knowledge tracing)

- 고전 BKT(Corbett & Anderson, 1994)는 개념별로 '알 확률'을 두고 맞힘·틀림으로 베이즈 갱신하며, DKT(Piech et al., 2015)는 RNN으로 대량 상호작용 데이터를 학습한다 [논문, 사전 지식, https://arxiv.org/abs/1506.05908]. 믿집은 데이터가 적으니 **BKT식 간단 갱신**이면 충분하다(판단).

```text
learner_concepts(user_id, concept_id, state ∈ {unseen, introduced, checked, mastered},
                 p_known float, last_seen_at, evidence jsonb)
갱신(오케스트레이터 코드가 수행; 에이전트는 DB 쓰기 금지 규칙 준수):
  설명함 → state=introduced, p_known += (1 - p_known) * 0.3
  확인 질문 정답 → p_known 상승(예: 0.85 이상이면 mastered), 오답 → 하락 + 재설명 예약
```

- 가이드 에이전트는 Pydantic 출력에 `concepts_introduced: list[str]`, `check_question: {...} | None`만 내고, 갱신은 코드가 한다(AGENTS.md 쓰기 금지 규칙과 일치).

### 9.4 가이드 50 평가 루브릭 예시(항목별 0/1)

1. 질문에 대한 답이 첫 문장에 있다.
2. 사실이 RAG 근거·용어집과 일치한다(근거 없는 주장 0개).
3. 한 턴의 새 용어가 3개 이하이고 각 용어가 쉬운 말로 풀려 있다.
4. 사용자 단계(견적 전/후, 공정 D-n)에 맞는 내용이다.
5. 확인 질문이 있으면 1개이고 답이 명확하다.
6. 선제 팁이 있으면 1개이고 현재 단계와 관련 있다.
7. 숫자가 없다(숫자는 견적 설명 에이전트 담당).
8. 업체 비방·법률·안전 단정이 없다.

---

## 10. 미확인·상충 목록

| 항목 | 상태 | 비고 |
|---|---|---|
| gpt-6.1-terra 출시일 | 상충 | OpenAI 체인지로그 2026-10-26 vs llmgateway 2026-10-15 → 공식 우선 |
| Jev 한국어 지원·정확도 | 미확인 | 공식 문서에 언어 언급 없음. 의도 200으로 직접 측정 필요 |
| Jev Chat Completions 호환 | 미확인 | Decisions API(alpha) 전용으로 보임(`supported_parameters` 빈 배열) |
| Voyage rerank-3의 한국어 성능 | 미확인 | 31개 언어 평가, 한국어 명시 없음, 벤더 자체 평가 |
| OpenRouter 경유 rerank-3 호출 방법 | 미확인 | `mongodb/rerank-3`로 등재는 확인 |
| `mcp` 2.3.0의 2026-07-28 지원 여부 | 미확인 | PyPI에 표기 없음, What's new in v2 문서 확인 필요 |
| SDK 문서의 `Mcp-Session-Id` 언급 vs 스펙 제거 | 상충 | 구판 호환 지원 때문일 가능성(추정) |
| v2 SDK 인증 클래스 import 경로 | 미확인 | 4.4 스케치는 v1 경로 기준 |
| gpt-6.1-terra 이미지 토큰 산식 | 미확인 | 비전 문서의 패치 방식 목록에 terra 없음 |
| terra 비전 정확도 공개 벤치 | 미확인 | 없음 |
| DefectBench 평가 모델 수 | 상충(논문 내부) | 18·24·16 |
| OpenAI Graders(RFT용) 존속 | 미확인 | Evals 플랫폼은 11-30 종료 확인 |
| promptfoo 최신 버전 | 미확인 | 저장소 페이지에 릴리스 표기 없음 |
| Langfuse 핵심 라이선스·Cloud 요금제 | 미확인 | 셀프호스트 페이지에 라이선스 명시 없음 |
| klue/roberta, kf-deberta, KcBERT 라이선스 | 미확인 | 모델 카드 미표기 또는 미열람 |
| multilingual-e5 카드 세부(크기·접두어·라이선스) | 미확인 | 카드 로드 실패, 사전 지식으로만 기재 |
| BERT류 ONNX CPU 지연(현행 ORT, 짧은 문장) | 미확인 | 오래된 커뮤니티 수치만 확인, 직접 측정 필요 |
| taskiq·SAQ 현재 상태 | 미확인 | 검색 한도 소진 |
| OpenAI study mode 원문 | 미확인 | openai.com 403, 언론 기사로 대체 |
| OpenAI 'A practical guide' 발행일 | 미확인 | PDF에 날짜 없음, 2025-04는 사전 지식 |
| 사진 속 정보의 법적 성격(개인정보·위치정보) | 미확인 | 법률 검토 필요 |
| LangGraph Postgres 체크포인터 현행 문서 | 미확인 | interrupts 문서에 없음 |

---

## 11. 출처 목록 (모두 2026-11-08 접근)

**[공식 문서]**
- OpenAI 모델 목록: https://developers.openai.com/api/docs/models
- gpt-6.1-terra: https://developers.openai.com/api/docs/models/gpt-6.1-terra
- gpt-6-luna: https://developers.openai.com/api/docs/models/gpt-6-luna
- OpenAI 가격: https://developers.openai.com/api/docs/pricing
- OpenAI 폐기 목록: https://developers.openai.com/api/docs/deprecations
- OpenAI 체인지로그: https://developers.openai.com/api/docs/changelog
- OpenAI 임베딩 가이드: https://developers.openai.com/api/docs/guides/embeddings
- OpenAI reasoning 가이드: https://developers.openai.com/api/docs/guides/reasoning
- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI 비전 가이드: https://developers.openai.com/api/docs/guides/images-vision
- OpenAI 데이터 정책: https://developers.openai.com/api/docs/guides/your-data
- Agents SDK PyPI: https://pypi.org/project/openai-agents/ · 릴리스: https://github.com/openai/openai-agents-python/releases
- Agents SDK 문서: https://openai.github.io/openai-agents-python/ (mcp/, guardrails/, tracing/, running_agents/, sessions/, handoffs/, testing/, usage/)
- OpenRouter Jev 가이드: https://openrouter.ai/docs/guides/community/jev · 튜토리얼: https://openrouter.ai/docs/guides/community/jev-tutorial · 공급자: https://openrouter.ai/typesafe
- OpenRouter 모델 API: https://openrouter.ai/api/v1/models/typesafe/jev-1.14/endpoints · https://openrouter.ai/api/v1/models/voyageai/rerank-3/endpoints
- Voyage reranker: https://docs.voyageai.com/docs/reranker · 임베딩: https://docs.voyageai.com/docs/embeddings · 가격: https://docs.voyageai.com/docs/pricing
- Upstage 임베딩: https://console.upstage.ai/docs/capabilities/embed
- arq: https://github.com/python-arq/arq · https://github.com/python-arq/arq/issues/510 · https://pypi.org/project/arq/
- LangGraph: https://pypi.org/project/langgraph/ · https://docs.langchain.com/oss/python/langgraph/interrupts
- Pydantic AI: https://pypi.org/project/pydantic-ai/ · https://pydantic.dev/docs/ai/guides/testing/
- Google ADK: https://pypi.org/project/google-adk/ · https://adk.dev/agents/models/
- MCP: https://modelcontextprotocol.io/specification/latest · https://modelcontextprotocol.io/specification/versioning · https://modelcontextprotocol.io/specification/2026-07-28/changelog · https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
- MCP Python SDK: https://pypi.org/project/mcp/ · https://py.sdk.modelcontextprotocol.io/ · https://py.sdk.modelcontextprotocol.io/run/authorization/ · https://py.sdk.modelcontextprotocol.io/run/asgi/
- FastMCP: https://pypi.org/project/fastmcp/ · https://gofastmcp.com/servers/auth/token-verification
- pgvector: https://github.com/pgvector/pgvector · https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md
- AWS RDS PostgreSQL 확장: https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html
- 평가 도구: https://github.com/promptfoo/promptfoo · https://pypi.org/project/deepeval/ · https://pypi.org/project/ragas/ · https://pypi.org/project/inspect-ai/ · https://langfuse.com/self-hosting
- 모델 카드: https://huggingface.co/nlpai-lab/KURE-v3 · https://huggingface.co/nlpai-lab/KURE-v1 · https://huggingface.co/skt/A.X-Encoder-base · https://huggingface.co/klue/roberta-base · https://pypi.org/project/setfit/

**[블로그]**
- Anthropic: https://www.anthropic.com/engineering/building-effective-agents (2024-12-19) · https://www.anthropic.com/engineering/multi-agent-research-system (2025-06-13) · https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents (2025-09-29)
- Cognition: https://cognition.com/blog/dont-build-multi-agents (2025-06-12) · https://cognition.com/blog/multi-agents-working (2026-04-22)
- OpenAI 가이드 PDF: https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- OpenRouter Jev 소개: https://openrouter.ai/blog/insights/what-is-jev/ (2026-09-21, 10-16 갱신)
- Voyage rerank-3: https://blog.voyageai.com/2026/09/30/rerank-3/
- LangChain 맥락 엔지니어링: https://www.langchain.com/blog/context-engineering-for-agents (2025-07-02, 검색 요약)
- Google LearnLM: https://blog.google/outreach-initiatives/education/google-learnlm-gemini-generative-ai/ (2024-05-14)
- Engadget(study mode 2025-07-29, Claude learning mode 2025-08-14) — 9.1 표의 URL
- OpenAI의 Promptfoo 인수: https://openai.com/blog/openai-to-acquire-promptfoo (검색 결과, 2026-03-09)
- 국내 업체: https://handman.co.kr/ · https://decodar.work/ · https://inpe.kr/ai-estimate.html

**[논문]**
- DefectBench: https://arxiv.org/html/2603.20148 (2026-03-20)
- LearnLM: https://arxiv.org/abs/2412.16429 · LearnLM-Tutor: https://arxiv.org/abs/2407.12687
- Need Help?(CHI 2025): https://arxiv.org/abs/2410.04596
- 사전 지식으로 인용: Guo 2017(1706.04599), Desai & Durrett 2020(2003.07892), Zheng 2023(2306.05685), τ-bench 2024(2406.12045), FActScore 2023(2305.14251), SetFit 2022(2209.11055), DKT 2015(1506.05908), KLUE 2021(2105.09680), RRF(Cormack et al., SIGIR 2009), BKT(Corbett & Anderson, 1994)

**[커뮤니티]**
- 12-Factor Agents: https://github.com/humanlayer/12-factor-agents
- AutoRAG 한국어 임베딩 벤치: https://github.com/Marker-Inc-Korea/AutoRAG-example-korean-embedding-benchmark
- llmgateway 타임라인: https://llmgateway.io/timeline
- ONNX BERT 지연 정리: https://nightr.gitbook.io/nnopt/applications/1_bert
