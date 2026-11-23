# OpenAI 길 (LLM_PROVIDER=openai)

2026-11-23 사용자 결정: "OpenAI API로 연결해 놔" → 고른 안 "OpenAI용 코드 새로 짜기", 범위 "도면 읽기 빼고 다".

## 무엇이 OpenAI로 가나

| 기능 | 부르는 함수(llm.py) | OpenAI 모델 · 추론 강도 | 비고 |
| --- | --- | --- | --- |
| 비서 대화(고객 · 업체) | `claude_stream`(assistant) | gpt-6.1-terra · low | 새 길 |
| 조사 담당 | `claude_stream`(research) + `web_search` | gpt-6.1-terra · low | 새 길 |
| 기억 뽑기 | `claude_json`(memory) | gpt-6-luna · none | 새 길 |
| 먼저 말 걸기 판정 · 문장, 업체 요약 문장 | `claude_json`(nudge) | gpt-6-luna · none | 새 길 |
| v3 답 흐름(비서 `answer_question` 안) | `structured` | terra · 가벼운 역할은 luna | 전부터 있던 LangChain 길 |
| v2 대화 | `chat_tools` | gpt-6.1-terra | 전부터 있던 LangChain 길 |
| 도면 읽기 | 옮기지 않음 | - | OpenAI 길에서는 꺼짐(공공 링크만 보여요) |
| 임베딩 | `embed_texts` | text-embedding-3-small | 공급자와 상관없이 OpenAI. 키가 있으면 켜져요 |

- 모델 · 강도는 `.env`의 `OPENAI_AGENT_MODEL` · `OPENAI_REASONING_EFFORT` · `OPENAI_LIGHT_MODEL` · `OPENAI_LIGHT_EFFORT`를 써요. Claude가 Sonnet · Opus를 쓰는 자리는 agent 모델, Haiku 자리는 light 모델이에요.
- 켜는 법: `LLM_PROVIDER=openai` + `OPENAI_API_KEY`. Anthropic 키는 없어도 돼요.

## 어떻게 바꾸나

`agent/llm.py` 한 곳에서만 바꿔요. 부르는 쪽(비서 runtime · 조사 · 기억 · 먼저 말 걸기 · 업체 도구)은 Claude 꼴을 그대로 써요.

| Claude 꼴 | OpenAI Responses 꼴 |
| --- | --- |
| system(글 · 글 블록) | `instructions` 한 덩이 |
| 글 · 그림 블록 | 메시지(`input_text` · `input_image` data URL) |
| `tool_use` · `tool_result` | `function_call` · `function_call_output`(차례 그대로) |
| 생각 블록 · 서버 도구 블록 | 보내지 않아요(`store=false`, 앞 응답 id를 쓰지 않음) |
| 도구 정의 | 함수 도구(`strict` 끔, 입력은 부르는 쪽이 검사) |
| `tool_choice` auto · none · any · tool | auto · none · required · 함수 지정 |
| 웹 검색 · 가져오기 | `web_search` 하나(한국 · 서울 시간대), 부름 상한은 `max_tool_calls` |
| 끝: refusal · max_tokens · tool_use · end_turn | 거절 · `incomplete`(max_output_tokens / content_filter) · 함수 부름 · 완료 |
| 구조화 답(json_schema) | `text.format` json_schema(엄격, SDK `to_strict_json_schema`) |

- 웹 부름(`web_search_call`)은 Claude 서버 도구 블록 꼴(`server_tool_use` + `web_search_tool_result` · `web_fetch_tool_result`)로 바꿔 돌려줘요. 그래서 조사 진행 기록 · 링크 뽑기 · 항목 규칙이 Claude 길과 같아요.
- OpenAI가 인용 주소에 붙이는 `utm_source=openai`는 떼요(검색 결과 주소와 같은 페이지로 맞추게).
- 오류 · 장부는 Claude 길과 같아요: 요청 거절(400 · 413 · 422)은 `LLMRejected`, 실패 · 끊김은 `LLMError`, 거절 · 잘림 · 꼴 틀림은 `LLMBadOutput`. 끊긴 호출은 보수적 추정치로 남겨요.

## 조사(웹 검색)에서 달라지는 것

| | Claude 길 | OpenAI 길 |
| --- | --- | --- |
| 페이지 열기 | 우리가 부른 `web_fetch`: robots.txt를 지키고 대화에 나온 주소만 | OpenAI `web_search`가 스스로 엶. API 문서에 robots.txt를 지키는지 적혀 있지 않아요 |
| 막은 곳 | `blocked_domains`로 검색 · 열기를 막음 | 막을 칸이 없어 지시문에 적고, 링크 · 기록 · 항목에서 코드가 걸러요 |
| 가져온 글 | 숫자 근거로 씀 | 오지 않아요. 숫자 근거는 목표 · 집 조건뿐이라 근거 없는 숫자 문장은 빠져요 |
| 검색 결과 제목 | 있음 | 없어서 도메인으로 보여요. 결과 카드는 인용 제목으로 채워요 |
| 결과 추리기(코드 실행) | 있음 | 없음 |
| 진행 말 | 도구 앞 한 문장 | OpenAI가 도구 앞에 글을 쓸 때만 |

- OpenAI 크롤러 문서(https://developers.openai.com/api/docs/bots, 2026-11-23 읽음)는 사용자가 시킨 열람(ChatGPT-User)에는 "robots.txt rules may not apply"라고 적어요. API `web_search`가 어느 이름으로 여는지는 적혀 있지 않아요.
- 제조사 그림(`linkimage`)은 두 길 모두 우리 코드가 robots.txt를 보고 읽어요.

## 비용

- 가격(공식 https://developers.openai.com/api/docs/pricing, 2026-11-23 확인, 100만 토큰당): gpt-6.1-terra 입력 $1 · 캐시 읽기 $0.05 · 30분 캐시 쓰기 $1.25 · 출력 $5, gpt-6-luna 입력 $0.10 · 읽기 $0.01 · 쓰기 $0.125 · 출력 $0.50. 입력이 27만 2천 토큰을 넘으면 비싼 표예요. 웹 검색은 1,000번에 $10(검색 글 토큰은 입력 토큰에 들어요).
- 장부(`usage/prices.py`): OpenAI 입력 토큰에서 캐시 읽기 · 쓰기를 뺀 값을 입력으로, 쓰기는 30분 칸에 적어요. 웹 부름은 검색 · 열기 · 찾기를 모두 한 번씩 세요(상한 쪽으로 안전).
- 상한은 그대로예요(사용자 하루 · 새 계정 · 서비스 하루 · 전체 · 턴).

## 확인

- 시험(유료 호출 0회): `tests/test_v4_openai.py` 6개(꼴 바꾸기 · 토큰 · 비서 턴 · 조사 · 구조화 답 · 스트림 실패 · 진짜 SDK에 가짜 HTTP). 관련 기존 시험(LLM · 장부 · 조사 · 비서 턴 · 기억 · 먼저 말 걸기 · 업체 요약 · 도면 없음) 310개도 통과했어요.
- 실측(2026-11-23, `evaluation/v4/openai_live.py`, 평가 DB, OpenAI 키만):

| 확인 | 결과 |
| --- | --- |
| 비서 턴 3번 | 모두 LLM 모드. '오늘 뭐 하면 돼요?' 4.3초(오늘 할 일 카드), '실크벽지랑 합지는 뭐가 달라요?' 4.7초(비교 · 지식 카드), '많이 고르는 실크벽지 제품 알아봐 줘' 11.0초(답 흐름으로 답함, 조사는 시작 안 함) |
| 조사: 자재 | 12.4초 · $0.042, 진행 기록 7줄(진행 말 2 · 검색 · 읽기), 항목 4개 모두 제조사 사진, 다른 자료 링크 4 |
| 조사: 믿집 밖 업체 | 13.1초 · $0.052, 12.0초 · $0.030(두 번). 링크는 모델이 끝 글에 고른 1곳씩만 남았어요 |
| 기억 뽑기 | 2개(거실 색 · 직접 칠하기) 맞게 뽑음 |
| 캐시 셈 | 같은 요청 두 번의 입력 토큰이 2,929로 같고, 첫 번 쓰기 2,926 → 둘째 읽기 2,926. 입력 토큰에 쓰기 · 읽기가 들어 있음을 확인 |
| 쓴 돈 | $0.153(OpenAI 키) |

- Claude 길과 다른 점: 같은 지시문이라도 도구 고르는 결이 달라요('알아봐 줘'에 조사 대신 답 흐름). 믿집 밖 업체 조사는 링크가 적게 남아요. 지시문을 OpenAI에 맞춰 고치려면 판을 새로 만들고 평가해야 해요(아직 안 함).
