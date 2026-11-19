# ChatGPT와 OpenAI API의 차이 · 믿집 답 형식 설계 (2026-11-19)

- 누가: 조사 담당(하위 에이전트) 혼자 했어요. 웹 검색 · 공식 문서 읽기만 했고 유료 API 호출은 0회예요. 코드는 고치지 않았어요.
- 맡은 범위: ChatGPT 제품층이 API 위에 더하는 것, 답 형식 · 구성.
  - 다른 조사가 맡은 것(API web_search 출처 주석, 이미지 API, 모델별 속도)은 깊게 보지 않았어요.
- 읽는 법
  - '확인'은 공식 문서 · 원문을 직접 열어 읽은 것이에요.
  - '2차'는 기사 · 분석 글로만 본 것이고, '추정'은 근거에서 미루어 본 것이에요.
  - 번호 [O1] · [S3] 같은 것은 맨 끝 출처 번호예요.
- 먼저 읽은 우리 코드 · 문서: `docs/v3/agents.md`, `docs/v3/agent-next.md`, `backend/app/agent/v3/answer.py` · `brief.py` · `templates.py` · `schemas.py` · `prompts/*_v1.md`, `backend/app/agent/llm.py`, `frontend/components/ai/AiAnswer.tsx`

## 0. 한눈에

| 묻는 것 | 결론 |
| --- | --- |
| 같은 모델인데 왜 다르게 느껴지나 | ChatGPT는 모델 하나가 아니라 **제품 묶음**이에요. 숨은 시스템 지시문, 성격 설정, 메모리 · 맞춤 지시, 모델 자동 고르기, 검색 자동 켜짐, 안전층, 그리고 **렌더러**(마크다운 · 출처 알약 · 상품 카드 · 후속 질문 단추)가 더해져요. API는 이것들이 거의 다 빠진 '맨 모델'이고 형식도 기본값이 달라요 |
| 가장 큰 차이 하나 | **형식 기본값**이에요. GPT-5 API는 기본으로 마크다운을 쓰지 않아요(확인, [O3]). ChatGPT는 마크다운을 그리는 화면을 전제로 해요 |
| ChatGPT 답 모양 | 첫 문장에 바로 답하고, 필요할 때만 굵게 · 목록 · 표를 써요. 출처는 그 문장 끝 알약으로 달고, 답 아래에 출처 패널이 있어요. 2026년에는 이모지 · 군더더기 후속 질문을 줄이는 쪽으로 바뀌었어요(2차) |
| 공개 근거 | Model Spec 2026-10-29판은 **자세한 스타일 지침을 거의 뺐어요**(확인, [O1]). 형식 지침은 그 전 판(2026-08-18)과 GPT-5 · 5.1 프롬프팅 가이드에 남아 있어요 |
| 우리가 따라 할 방법 | 마크다운 글을 받지 말고 **블록 JSON을 받아 화면이 그려요**. 우리는 이미 `Section · CalcBox · AskSlot · suggest` 블록 구조라 ChatGPT의 '렌더러 몫'을 코드가 맡을 수 있어요 |
| 추천 | **안 A '결론 + 펼침'을 기본**으로 해요. 방법 · 순서 · 비교 꼴에서만 **안 B '단계 · 비교 블록'**을 써요. LLM 모드가 켜지면 **안 C '블록 고르기 JSON'**으로 LLM은 블록 순서 · 문장 번호만 정해요 |

## 1. 지금 우리 답 형식 (코드에서 읽은 것)

| 자리 | 지금 모양 | ChatGPT와 비교 |
| --- | --- | --- |
| 답 단위 | `AgentAnswer` = `sections[]` + `calc[]` + `cards[]` + `ask` + `unknown[]` + `suggest[]` + `brief` | ChatGPT는 마크다운 글 한 덩이 + 출처 주석 + 위젯이에요. 우리는 처음부터 블록이라 렌더러를 우리가 쥐고 있어요 |
| 첫 줄 | `brief.lines` 1~3문장(질문 꼴 11가지 예산). '자세히 보기 · n문장 더'로 펼침 | ChatGPT의 '첫 문장 답'과 같은 방향이에요. 다만 '네 · 아니요'로 시작하는 결론 줄이 없어요(agent-next 6.4 한계) |
| 문장 | `Sentence{text, cites[]}`. 카드 · 조각 요약 · 정해 둔 글만, 출력 검사 통과분만 | ChatGPT는 문장마다 출처가 붙지 않아요. 우리가 더 촘촘해요 |
| 출처 | 묶음 끝 '출처 · 문서 이름 2~3개' 한 줄 | ChatGPT는 **문장 끝 알약 + 패널** 두 층이에요. 우리는 문장과 출처가 이어져 보이지 않아요 |
| 주의 · 팁 | `caution` · `tip` 줄('주의:' · '팁:') | ChatGPT엔 정해진 칸이 없어요. 우리 쪽이 화면에서 눈에 잘 띄어요 |
| 숫자 | `CalcBox`(계산 엔진 값을 옮김)만, 글에는 숫자를 만들지 않음 | ChatGPT는 숫자를 글 안에 써요. 우리 규칙상 따라 하지 않아요 |
| 되묻기 | `AskSlot` 질문 1개 + 단추 | ChatGPT 지침(유출본)도 '되묻기는 맨 앞에 한 번'이에요(2차, [S6]) |
| 다음 할 일 · 이어 물을 질문 | `cards[].choices`(화면 이동 단추) · `suggest[]`(글 단추) | ChatGPT의 후속 제안 단추와 같은 자리예요 |
| 형식 글자 | 마크다운 없음(문장은 `<p>`로 그림) | API 기본값과 같아요. 굵게 · 목록 · 표는 아직 없어요 |
| LLM 모드 | `structured()`가 `json_schema strict`로 `{"sentences":[{text,cites}]}`만 받음(`langchain_openai.ChatOpenAI`) | 블록 고르기 JSON으로 넓힐 자리가 이미 있어요(7.4) |

## 2. ChatGPT와 API의 차이 표

| 층 | ChatGPT (제품) | OpenAI API (맨 모델) | 답이 달라지는 까닭 | 확인 정도 · 출처 |
| --- | --- | --- | --- | --- |
| 시스템 지시문 | 대화마다 숨은 시스템 지시문이 붙어요. 날짜 · 도구 사용 · 성격 · 끝맺음 규칙이 들어 있다고 알려져요 | 개발자가 `instructions` · developer 메시지로 직접 써요. 다만 API에도 **짧은 숨은 지시문**(오늘 날짜, '답 장황함 기본값 3' 같은 줄)이 붙는다는 보고가 있어요 | 같은 질문이라도 ChatGPT는 '친절한 설명가' 지시를 받고 답해요 | ChatGPT 지시문: 유출본만 있고 OpenAI 미확인(2차, [S6][S7]). API 숨은 지시문: 2차 [S8] |
| 성격 · 말투 | 설정 → 개인 맞춤에 '기본 말투' 프리셋(전문적 · 친근함 · 솔직함 · 효율적 등)과 특성 조절(따뜻함 · 열정 · **머리글과 목록** · **이모지** 더/덜)이 있어요 | 없어요. 지시문으로 정해야 해요 | 사용자가 고른 말투 · 서식 양이 답에 얹혀요 | 기능 존재는 OpenAI 도움말 문서 제목으로 확인, 세부는 2차 [S1][S2] |
| 메모리 · 맞춤 지시 | 저장한 기억 · 지난 대화 참고 · 맞춤 지시(custom instructions)가 대화에 들어가요 | 없어요. 앱이 스스로 저장해 넣어야 해요 | 사용자를 '아는' 답이 나와요 | 확인(도움말 [O9]), 세부 동작은 판마다 달라 2차 |
| 대화 기록 관리 | 길면 '새롭고 관련 높은 것 우선'으로 잘라 넣어요. 사용자는 무엇이 잘렸는지 모를 수 있어요 | Responses API는 `previous_response_id`로 이어 갈 수 있지만, 얼마를 넣을지는 앱이 정해요 | ChatGPT는 앞 대화 맥락을 자동으로 끌어와요 | 확인(Model Spec [O1] 정의 절, 텍스트 가이드 [O5]) |
| 모델 자동 고르기 | GPT-5 출시 때 '빠른 모델 + 깊이 생각하는 모델 + 실시간 라우터' 구조였어요. 2026년 5월 GPT-5.5 Instant가 기본이 됐고, 9월에 Plus · Pro의 자동 Thinking 전환이 빠졌다는 보도가 있어요 | 모델 · `reasoning.effort`를 개발자가 정해요. 라우터 없음 | 어려운 질문엔 ChatGPT가 더 오래 생각한 답을 줄 수 있어요 | GPT-5 라우터 구조는 OpenAI 발표(페이지 403으로 직접 못 엶, 보도로 확인). 2026년 변경은 2차 [S3][S4] |
| 검색 자동 켜짐 | 최신 정보가 필요하면 **스스로 웹 검색**해요. '/'로 직접 켤 수도 있어요 | `web_search` 도구를 개발자가 켜야 해요 | ChatGPT 답엔 출처 알약이 붙고 최신 내용이 섞여요 | 확인(도움말 [O8]) |
| 도구 묶음 | 검색 · 파일 읽기 · 코드 실행(그림 · 표) · 이미지 생성 · 캔버스 · 쇼핑 조사 등이 한 화면에 묶여 있어요. 2026년에 GPT-5.5 쪽 캔버스 옆 칸이 빠졌다는 보도가 있어요 | 도구마다 따로 켜고, 실행 결과를 앱이 그려요 | ChatGPT는 '알아서 표 · 그림을 만들어 보여 주는' 경험이 나와요 | 쇼핑 조사: OpenAI 발표 [O10]. 캔버스 변경: 2차 [S4] |
| 안전층 | 모델 학습(안전한 완성) + 제품 쪽 거르기 · 연령별 모드(18세 미만 보호) | 모델 학습은 같고, 제품 쪽 거르기는 개발자 몫(moderation 등) | 민감 주제에서 ChatGPT 답이 더 조심스럽거나 안내가 붙어요 | Model Spec 변경 기록의 18세 미만 모드 확인 [O2]. 제품 거르기 세부는 추정 |
| 렌더러 | 마크다운(머리글 · 굵게 · 목록 · 표) · 수식 · 코드 칸 · **문장 끝 출처 알약 + 출처 패널** · 상품 카드 묶음 · 지도 · 장소 패널 · 이미지 | **글만** 돌려줘요. 출처는 `annotations` 칸으로 오고, 그리는 건 앱 몫이에요 | 같은 글도 ChatGPT에선 정리돼 보이고, 앱에선 기호가 그대로 보일 수 있어요 | 마크다운 기본값 차이 확인 [O3]. 알약 · 패널 모양 2차 [S5], 상품 카드 [O10] · 2차, 지도 패널 2차 [S9] |
| 후속 질문 제안 | 답 아래에 이어 물을 단추가 나오고, 글 끝에도 '…해 드릴까요?'가 붙곤 해요. 2026년엔 줄이는 방향이었다가 다시 늘었다는 불만도 있어요 | 없어요. 앱이 만들거나 LLM에게 따로 받아야 해요 | ChatGPT 답이 '대화가 이어지는' 느낌을 줘요 | Model Spec: 후속 질문은 대화형일 때만 기본 [O1]. 2026 변화는 2차 [S3][S10] |
| 스트리밍 표시 | 글자가 흘러나오고, 생각 중 · 검색 중 표시가 따로 있어요 | `stream=true`면 `response.output_text.delta` 같은 사건으로 와요. 그리는 건 앱 몫이에요 | 빨리 반응하는 느낌 | 사건 이름 확인 [O6] |
| 길이 | 제품 기본값 + 성격 설정 | `text.verbosity`(low · medium · high, 기본 medium으로 알려짐) + 지시문 | 같은 질문에 길이가 달라요 | 값 확인 [O4], 기본값은 2차 |

차이 핵심을 한 줄로: **ChatGPT 답의 '보기 좋음'은 절반이 모델 밖(지시문 · 렌더러 · 제품 기능)에서 와요.** 그 몫을 우리 코드가 맡으면 API로도 비슷한 경험을 만들 수 있어요.

## 3. ChatGPT 답 형식의 특징

### 3.1 답 구조

| 요소 | 관찰되는 모양 | 근거 | 확인 정도 |
| --- | --- | --- | --- |
| 첫 문장 결론 | 질문엔 사실 나열이 아니라 **바로 답**하고, 필요하면 짧은 이유 · 대안을 붙여요. 예: '프랑스 수도는?' → '파리예요'가 맞고, 나라 소개부터 하면 틀림 | Model Spec(2026-08-18판) 'Be clear and direct' | 확인 [O1b] |
| 굵게 · 목록 | '훑어보기를 돕도록 **아껴서**' 써요 | 같은 절 | 확인 [O1b] |
| 소제목 · 표 | 마크다운(머리글 · 굵게 · 표 · 코드 칸)과 LaTeX 수식이 기본이었어요. 2026-10-29판에서 이 절이 빠졌어요 | 'Use Markdown with LaTeX extensions'(08-18판), 변경 기록 | 확인 [O1b][O2] |
| 이모지 | 기본은 '전문적인 동료' 말투라 이모지를 쓰지 않아요. 사용자가 가볍게 말하면 맞춰 써요. GPT-5.5 Instant는 '쓸데없는 이모지'를 줄였다고 보도됐어요 | Model Spec 'Be suitably professional' 예시, 보도 | 확인 [O1b] · 2차 [S3] |
| 길이 | 복잡한 주제 · 단계 안내 · 민감한 일엔 길게, 단순 사실 · 수다엔 짧게. 쓸데없는 반복은 시간과 돈 낭비 | 'Have conversational sense' · 'Be thorough but efficient' | 확인 [O1b] |
| 마지막 요약 · 다음 질문 | 대화형일 때만 '문제가 풀렸는지 · 더 알려 드릴지' 묻는 게 기본이에요. 유출 지시문에는 반대로 '…해 드릴까요?'로 끝내지 말라는 줄이 있어요. 2026년 기본 모델은 끝 질문을 자주 생략한다고 보도됐어요 | Model Spec 'interactive vs programmatic', 유출본, 보도 | 확인 [O1] · 2차 [S6][S3] |
| 되묻기 | 꼭 필요한 되묻기 하나를 **맨 앞에서** 해요. 다음 단계가 뻔하면 묻지 않고 해요 | 유출 지시문 | 2차 [S6] |
| 짧은 답 지시 예 | '최대 2문장, 한 일(찾은 것)을 먼저, 맥락은 필요할 때만' · '짧은 문단을 쓰고, 선택지 · 목록 · 점검표를 달라고 할 때만 목록' | GPT-5.1 프롬프팅 가이드 | 확인 [O3b] |

### 3.2 출처 표시

| 요소 | 모양 | 확인 정도 |
| --- | --- | --- |
| 문장 끝 알약 | 근거가 되는 **문장 · 목록 줄 끝**에 붙어요. 사이트 아이콘 + 짧은 출판처 이름(잘림), 출처가 여럿이면 '+N' | 2차 [S5](2026-07 화면 분석) |
| 알약 누르기 | 알약에 붙은 작은 창에 출판처 · 제목 · 날짜 · 짧은 발췌. 여럿이면 1/2처럼 넘겨 봐요. 데스크톱은 올리기만 해도 미리 보기 | 도움말로 확인 [O8], 세부는 2차 [S5] |
| 출처 패널 | 답 아래 '출처' → 오른쪽 칸에 인용 출처 + 관련 링크 카드. 알약과 패널 카드가 서로 표시되지는 않아요. 2026-08에 '더 보기' 메뉴 안으로 숨었다는 보도가 있어요 | 도움말 [O8], 2차 [S5][S11] |
| 출처가 없을 때 | 검색하지 않은 답엔 알약이 없어요 | 도움말 [O8] |

### 3.3 이미지 묶음 · 카드가 나오는 때

| 모양 | 나오는 때 | 확인 정도 |
| --- | --- | --- |
| 상품 카드 묶음 | 쇼핑 의도 질문. 그림 · 값 · 평점 · 산 곳 링크가 있는 카드를 가로로 넘겨요. '쇼핑 조사'는 되묻고 구매 안내서를 만들어요 | OpenAI 발표 [O10], 세부 2차 [S12] |
| 지도 · 장소 패널 | 동네 가게 · 장소 질문 | 2차 [S9] |
| 이미지 묶음 | 사람 · 장소 · 물건처럼 '보면 알기 쉬운 것' 질문에서 검색 이미지가 위에 묶여 나와요 | 공식 문서를 찾지 못했어요(추정) |
| 생성 이미지 | 이미지 생성을 했을 때. 유출본은 '그린 뒤엔 아무 말도 하지 마'라고 적어요 | 2차 [S6] |

## 4. OpenAI가 공개한 형식 근거

| 자료 | 형식에 관해 말하는 것 | 우리에게 주는 것 | 확인 |
| --- | --- | --- | --- |
| Model Spec 2026-10-29판 | 5가지 가치로 다시 짜고 '**자세한 스타일 지침 대부분을 뺌**'. 남은 것: 기본은 대화형, `response_format` JSON 스키마나 '형식 없이 코드만'이면 프로그램용 출력. 되묻기 · 후속 질문 · 코드 칸은 **대화형일 때만** 기본. 프로그램용이면 '요청한 형식 그대로' | 우리는 JSON 스키마로 받으니 '프로그램용' 쪽이에요. 끝맺음 질문 · 군말이 덜 나와요. 대신 대화 맛(후속 단추)은 화면이 채워요 | [O1][O2] |
| Model Spec 2026-08-18판 | 'Be clear and direct'(바로 답, 서식은 아껴서) · 'Use Markdown with LaTeX'(기본 마크다운) · 'Be thorough but efficient'(반복 금지) · 'Be suitably professional'(동료 말투, 이모지 X) · 'Have conversational sense'(길이는 상황에 맞게) | 지시문 형식 규칙의 바탕으로 써요. 단 마크다운 기본값은 따르지 않아요(화면이 블록을 그림) | [O1b] |
| GPT-5 프롬프팅 가이드 | 'API의 GPT-5는 기본으로 최종 답에 마크다운을 쓰지 않아요'. 쓰게 하려면 '의미상 맞는 곳에만'(코드 · 목록 · 표) 지시. 긴 대화에선 지시가 흐려져 **3~5번 메시지마다 다시 넣으면** 잘 지켜요. 장황함은 `verbosity` 파라미터 + 지시문으로 조절 | 마크다운은 아예 금지하고 블록으로 받으면 흐려짐 문제가 없어요 | [O3] |
| GPT-5.1 프롬프팅 가이드 | 5.1은 가끔 장황해서 **구체적 길이 지시**를 잘 따라요. `<output_verbosity_spec>` 예: '최대 2문장'. 고객 응대 예: '알겠어요 · 감사해요' 같은 인사말 반복 금지, '빠르게 진행하는 게 존중'. 행사 안내 예: 짧은 문단, 이모지 · 느낌표 피하기 | 지시문에 꼴별 문장 수를 적되, 길이는 코드로 한 번 더 지켜요(agent-next 6.1-3) | [O3b] |
| GPT-5.2 가이드 | 5.1보다 깔끔한 형식 · 덜 장황, 5 · 5.1 지침은 대체로 그대로 통해요 | 판이 바뀌어도 같은 지시문 틀을 써요 | 검색 결과 요약으로만 봄(2차) [O3c] |
| Responses API `text.verbosity` | `low · medium · high`. 답 길이만 바꾸고 추론 길이는 아니에요. 지시문이 우선해요 | 우리 담당 글쓰기는 `low` | [O4] |
| Responses API `text.format` | `{"type":"json_schema","strict":true,"schema":…}`. 거절이면 `refusal` 칸, 길이 초과면 `status: incomplete`. 모든 칸 `required`, `additionalProperties: false`, 뿌리 `anyOf` 불가, 중첩 10단 · 속성 5,000개. 글 칸은 `pattern` · `format`만 지원(글자 수 제한은 스키마로 못 함). GPT-6 이후는 대화 중 `configuration_update`로 형식 바꾸기 가능. 처음 쓰는 스키마는 첫 요청이 느려요 | 블록 스키마는 얕게(2~3단), 글자 수는 코드로 자르기 | [O6] |
| 구조화 출력 스트리밍 | `response.output_text.delta` · `response.completed` · `response.incomplete` · `response.refusal.delta`. 글 조각과 `output_text.done`만으로 끝났다고 보면 안 되고 `response.completed`를 확인 | 블록 단위로 끊어 보내는 근거(7.5) | [O6] |
| `instructions`와 developer 메시지 | 한 번만 쓰면 `instructions`, `previous_response_id`로 이어 가면 첫 developer 메시지에 둬요. GPT-6.2부터 `instructions`는 캐시되지 않는 값으로 셈해요 | 고정 지시문은 developer 메시지로 두고 캐시를 노려요 | [O5] |
| 공식 블로그 'ChatGPT 스타일' | 'ChatGPT처럼 써라' 같은 공식 글은 찾지 못했어요. GPT-5.5 Instant 발표가 '더 촘촘하고 요점만 · 이모지 줄임 · 군더더기 후속 질문 줄임'을 말했다고 보도됐어요 | 방향만 참고 | 2차 [S3] |

## 5. API로 ChatGPT 같은 결과를 내는 법

### 5.1 방법 표

| 할 일 | 방법 | 믿집에 맞춘 선택 |
| --- | --- | --- |
| 지시문 형식 규칙 | ① 첫 문장에 답 ② 꼴별 문장 수(예/아니요 1~2, 방법 단계 ≤4) ③ 인사 · 되풀이 · 끝맺음 질문 금지 ④ 서식은 의미가 있을 때만 ⑤ 구체적 길이로 지시(5.1 가이드) | 지시문에 '마크다운 기호(`**` `#` `-` `|`)를 쓰지 마'를 넣고, 서식은 **블록 종류로만** 표현해요 |
| 마크다운 쓰는 때 · 안 쓰는 때 | 그릴 수 있는 화면이면 의미상 맞는 곳만, 아니면 금지(GPT-5 가이드) | 우리 화면은 블록을 그려요 → **글 칸 안 마크다운 금지**. 출력 검사에서 기호를 지워요 |
| 구조화 출력 | `text.format` json_schema strict로 블록 배열을 받아요. 블록 종류는 `enum`, 블록마다 칸이 다르면 `anyOf`(뿌리 말고 안쪽) | 지금 `{"sentences":[…]}` 스키마를 **블록 고르기 스키마**로 넓혀요(7.4) |
| 스트리밍하며 블록 그리기 | (가) 글자 흘리기: 부분 JSON을 이어 붙여 고쳐 읽기 (나) 블록 흘리기: 서버가 블록 하나가 닫힐 때마다 검사 뒤 SSE로 보내기 | **(나)**. 우리는 문장마다 숫자 · 인용을 검사한 뒤 보내야 해요(AGENTS.md 4장). 블록 순서는 결론 → 본문 → 계산 상자 → 출처 → 단추 |
| 출처 번호 달기 | 문장의 `cites`(K#### · card:…)를 답 안에서 **처음 나온 순서로 1, 2, 3** 번호를 매겨 알약으로 보여요. 번호 ↔ 조각은 서버가 표로 보냄 | LLM은 조각 ref만 내고 번호는 코드가 매겨요. 이번 턴에 보인 조각만 허용(지금 `check.section`의 `shown`) |
| 후속 질문 | (가) LLM이 답과 함께 2~3개 생성 (나) 질문 은행 · 카드 `keys`에서 고르기 | **(나)** 지금 `suggest` 방식 유지. 답할 수 있는 것만, 금액 · 기간 · 추천 질문 빼기(agents.md 10.8). LLM 모드에서도 생성 대신 후보 번호 고르기 |
| 이미지 자리 | ChatGPT는 검색 이미지 · 상품 그림을 붙여요 | 믿집이 가진 **설명 그림 목록**(용어 그림 · 시공 순서 그림)에서 카드가 가리키는 것만. 업체 · 제품 사진은 쓰지 않아요. 지금은 자리만 정의 |
| 길이 | `text.verbosity: low` + 지시문 + **코드 자르기** | 이미 `brief.BUDGET`이 있어요. LLM이 어겨도 코드가 '자세히'로 내려요 |
| 말투 | 지시문 + 예시 | 해요체 · 쉬운 말(agent-next 6.7). 이모지 0 |

### 5.2 출처 번호 흐름 (우리 RAG 조각으로)

| 단계 | 누가 | 무엇을 |
| --- | --- | --- |
| 1 | 검색 · 카드 | 이번 턴 조각 K1201 · K0877 · card:dobae-023@3 를 고름 |
| 2 | LLM(LLM 모드) 또는 카드(무료 모드) | 문장마다 `cites: ["K1201"]` 처럼 ref만 냄. 번호 · 링크 · 주소는 쓰지 않음 |
| 3 | 출력 검사 | 이번 턴에 보인 ref인지, 문장 · 조각 겹침 ≥ 0.18 인지 확인 |
| 4 | 코드 | 처음 나온 순서로 번호: K1201 → 1, K0877 → 2. 카드 ref는 카드가 인용한 조각 번호로 바꿔 보여요 |
| 5 | 화면 | 문장 끝 알약 `①` (344px에선 숫자만, 폰도 숫자만). 누르면 아래 칸에 문서 이름 · 발행처 · 종류 · 짧은 원문 |
| 6 | 화면 | 답 끝 '출처 2' 한 줄 → 펼치면 번호 순 목록. 보이는 문장을 받치는 출처만(agent-next 6.1-5: 1~2개) |

## 6. 다른 회사 사례

| 회사 | 답 형식 | 출처 표시 | 후속 · 기타 | 확인 정도 |
| --- | --- | --- | --- | --- |
| ChatGPT | 첫 문장 답 + 필요할 때 서식 | 문장 끝 알약 + 출처 패널 | 후속 단추 · 상품 카드 · 지도 | 2~3장 |
| Perplexity | 짧은 요약 글 + 숫자 인용 | 문장 끝 **[1] [2]** 위첨자, 위에 출처 카드 줄 | 답 뒤 '관련 질문' 3~4개 | 2차 [S13] |
| Claude (claude.ai) | **서식 최소**: 보통 대화 · 단순 질문은 목록 없이 글로, 목록은 요청받았거나 꼭 필요할 때만, 목록 한 줄은 1~2문장, 거절할 땐 목록 금지 | 웹 검색 답에 인용 | — | 확인(2026-11-09 공개 시스템 지시문 [O11]) |
| Claude API | Citations: 문서를 주면 답 글 덩이마다 `cited_text` · 문서 번호 · 위치가 와요. **사용자 정의 문서(조각 목록)**로 넣으면 조각 하나가 인용 단위. 스트리밍은 `citations_delta`. **구조화 출력과 함께 쓸 수 없어요**(400) | 출처 위치가 API에서 보장돼요 | — | 확인 [O12] |
| 네이버 AI 브리핑 | 여러 출처를 묶은 **요약 답을 먼저**, 아래에 관련 질문 | 출처 문서(블로그 · 기관 · 지도 · 쇼핑 등)를 카드로. 건강 분야는 기관 자료를 근거로 쓴다고 보도 | 2026-07 기준 검색의 약 27%에 나옴(보도) | 2차 [S14] |
| 오늘의집 | 대화형 상담 에이전트 자료를 **찾지 못했어요**. AI 방꾸미기(그림 생성 · 3D 배치)와 개인화 추천 피드는 확인 | — | — | 확인 못 함 [S15] |

- 시사점
  - 모두 '**요약 먼저 → 출처 가까이 → 이어 물을 질문**' 틀이에요.
  - Claude가 가장 서식을 아끼고, ChatGPT도 2026년에 그쪽으로 움직였어요(2차).
  - 좁은 화면인 우리에겐 '서식 최소 + 블록 몇 개'가 맞아요.
  - Claude API처럼 '인용 위치 보장'과 '구조화 출력'은 함께 쓰기 어려운 경우가 있어요. OpenAI 쪽은 우리가 ref를 JSON 칸으로 받고 코드로 검사해 이 문제를 피해요.

## 7. 믿집 답 블록 구성안

### 7.1 지킬 것

| 제약 | 블록 설계에 주는 규칙 |
| --- | --- |
| 금액 · 기간 숫자는 계산 엔진만 | 숫자는 `calc` 블록(계산 상자)에만. 다른 블록 글에 숫자가 있으면 출력 검사가 뺌(지금 규칙 그대로) |
| 해요체 | 모든 글 칸. 원문 '-다'는 옮기지 않음 |
| 좁은 화면(옆 AI 칸 344px, 폰 390px) | 표는 **2열까지**. 3열 이상은 '이름 : 설명' 줄 목록으로 바꿔요. 알약은 숫자만. 가로 넘김 묶음(캐러셀) 쓰지 않음. 단추 40px 이상 |
| 근거는 우리 RAG 조각 | 출처 블록은 조각 ref에서만 만들어요. 웹 링크 · 주소 없음 |
| 업체 · 제품 추천 안 함 | 상품 카드 · 업체 카드 블록 없음. 이미지 블록도 설명 그림만 |
| 서식 | 굵게는 결론 블록 하나만. 이모지 · 마크다운 기호 없음 |

### 7.2 블록 사전 (세 안이 같이 씀)

| 블록 | 지금 칸 | 언제 | 길이 상한 | 예시 |
| --- | --- | --- | --- | --- |
| `lead` 결론 | 새 칸(agent-next 6.5 `lead`) | 늘 맨 앞. 예/아니요 꼴은 '네, · 아니요, · 경우에 따라 달라요.'로 시작 | 1문장 · 40자, 굵게 | **경우에 따라 달라요. 벽 상태를 보고 정해요.** |
| `body` 핵심 | `brief.lines` | 결론 바로 뒤 | 1~2문장 · 문장당 60자 | 들뜬 곳이 많으면 뜯고 새로 바르는 편이 안전해요.① |
| `steps` 단계 | 새 칸(`Section.sentences` 중 순서 문장) | 방법 · 순서 꼴 | 3~4단계 · 단계당 30자 | 1 가구 옮기기 / 2 헌 벽지 뜯기 / 3 바탕 고르기 / 4 새로 바르기 |
| `compare` 비교 | 새 칸 | 비교 꼴. 2가지만 | 2열 × 3행 · 칸당 20자 | 실크 · 합지 / 물걸레 · 되는 편 · 약한 편 |
| `calc` 믿집 계산 | `calc[]` | 비용 · 기간 꼴, 프로젝트가 있을 때 | 상자 1~3개 | [믿집 계산] 표준견적서 합계 · 부가세 포함 (값은 계산 엔진) |
| `caution` 주의 | `caution` | 안전 · 하자 · 셀프 위험, 정해 둔 정책 글 | 1문장 · 60자 | 전기 · 가스에 닿는 일은 전문 업체에 맡기는 게 안전해요. |
| `ask` 되묻기 | `ask` | 답을 바꾸는 빈 칸이 있을 때. 대화당 1회 | 질문 40자 + 단추 2~4 + '잘 모르겠어요' | 지금 살면서 공사하세요? [네] [아니요] [잘 모르겠어요] |
| `unknown` 모름 | `unknown[]` | 근거가 없을 때 | 2문장 | 이 질문은 믿집 자료로 확인하지 못했어요. 실측 때 업체에 물어보시면 정확해요. |
| `sources` 출처 | `Section.sources` | 근거 문장이 있을 때 | 보이는 줄 1개, 펼치면 3개 | 출처 2 · 표준시방서 · 소비자원 안내 |
| `more` 자세히 | `sections` 전체 | 숨긴 문장이 있을 때 | 그 자리 펼침, 2층까지 | 자세히 보기 · 3문장 더 |
| `next` 다음 할 일 | `cards[].choices` | 단계에 맞는 화면 이동 | 단추 2개 · 12자 | [표준견적서 보기] [업체 보기] |
| `follow` 이어 물을 질문 | `suggest[]` | 답할 수 있는 후보가 있을 때 | 2~3개 · 20자 | 덧방해도 돼요? |
| `figure` 설명 그림 | 새 칸(자리만) | 카드가 그림을 가리킬 때만 | 1장, 344px 너비, 설명 한 줄 | (몰딩 위치 그림) 몰딩은 천장과 벽이 만나는 곳의 띠예요. |

### 7.3 구성안 세 가지

| | 안 A '결론 + 펼침' | 안 B '단계 · 비교 블록' | 안 C 'LLM 블록 고르기' |
| --- | --- | --- | --- |
| 한 줄 | 지금 짧은 답 시제품에 결론 줄 · 문장 알약만 더해요 | 방법 · 순서 · 비교 꼴에만 목록 · 2열 표 블록을 써요 | LLM 모드에서 LLM이 블록 순서와 문장 번호만 골라요. 글은 코드가 붙여요 |
| 블록 순서 | lead → body → calc → caution → sources → more → next → follow | lead → steps 또는 compare → caution → sources → more → next → follow | 스키마가 허용한 블록 중 LLM이 고른 순서(lead는 늘 맨 앞으로 코드가 고정) |
| 쓰는 꼴 | 예/아니요 · 뜻 · 원인 · 비용 · 기간 · 추천 · 하자 · 그 밖 | 방법 · 순서 · 비교 | 모든 꼴(LLM 모드) |
| 보이는 길이 | 결론 40자 + 핵심 ≤2문장 ≈ 150자 | 결론 40자 + 단계 4개 × 30자 ≈ 160자 | 꼴 예산 그대로(코드가 자름) |
| LLM 호출 | 0회 | 0회 | 담당 글쓰기 1회(지금 자리 그대로) |
| 필요한 일 | 카드 416장에 `lead` 쓰기(오프라인 · 검수), 화면에 알약 · 굵은 결론 | 카드에 `steps` · `compare` 칸 더하기, 화면에 목록 · 2열 표 | 블록 고르기 스키마 · 지시문 v2 · eval |
| 위험 | 한 카드의 여러 열쇠 질문이 결론이 다를 수 있음(6.5) | 표가 좁은 칸에서 답답할 수 있음 → 2열 3행 상한 | LLM이 고른 문장이 질문과 어긋남 → 출력 검사 + 무료 답으로 되돌림 |
| 추천 | **기본** | A와 같이 씀(꼴에 따라) | 공급자 · 비용을 정한 뒤 |

### 7.4 안 C 스키마 모양 (OpenAI `text.format` strict)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["form", "lead", "blocks", "follow"],
  "properties": {
    "form": {"type": "string", "enum": ["yesno","define","howto","order","compare","cause","price","period","defect","reco","other"]},
    "lead": {
      "type": "object", "additionalProperties": false, "required": ["verdict", "text", "cites"],
      "properties": {
        "verdict": {"type": "string", "enum": ["yes", "no", "depends", "info"]},
        "text": {"type": "string"},
        "cites": {"type": "array", "items": {"type": "string"}, "maxItems": 2}
      }
    },
    "blocks": {
      "type": "array", "maxItems": 4,
      "items": {
        "type": "object", "additionalProperties": false, "required": ["kind", "sentence_ids", "rows"],
        "properties": {
          "kind": {"type": "string", "enum": ["body", "steps", "compare", "caution"]},
          "sentence_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
          "rows": {"type": ["array", "null"], "maxItems": 3,
                   "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}}
        }
      }
    },
    "follow": {"type": "array", "items": {"type": "string"}, "maxItems": 3}
  }
}
```

- `sentence_ids`는 이번 턴에 넘긴 검사된 문장(카드 · 조각 요약)의 번호예요. LLM은 새 문장을 거의 쓰지 않아요(`lead.text` 하나만).
- `follow`는 넘긴 후보 질문 번호만 허용해요(생성 아님).
- `rows`(비교 표)의 칸 글도 출력 검사를 거쳐요. 숫자가 있으면 그 줄을 빼요.
- 글자 수 제한은 스키마로 걸 수 없어요([O6] 지원 목록). 코드가 자르고 넘치면 '자세히'로 내려요.
- 지금 `llm.structured()`가 `langchain_openai`의 `json_schema strict`를 써요. `text.verbosity`를 같이 넘길 수 있는지는 확인하지 못했어요(LangChain 판에 달림, 추정).

### 7.5 스트리밍 순서 (세 안 공통)

| 순서 | 보내는 것 | 까닭 |
| --- | --- | --- |
| 0 | '답을 찾고 있어요' 자리 표시 | 빨리 반응 |
| 1 | `lead`(검사 뒤) | 첫 문장이 답 |
| 2 | `body` · `steps` · `compare` 블록 하나씩(블록마다 검사 뒤) | 숫자 · 인용 검사는 문장이 끝나야 할 수 있어요 |
| 3 | `calc` | 계산 엔진 값이라 바로 보낼 수 있어요. 글 뒤에 둬 '설명 → 값' 순서로 읽혀요 |
| 4 | `caution` · `sources` · `more` | 덧붙임 |
| 5 | `next` · `follow` | 마지막 |
| 끝 | 완료 신호(저장 commit 뒤) | AGENTS.md 4장 |

- 무료 모드는 답이 한 번에 만들어져요. 블록을 나눠 보내도 체감 차이는 작아요. 그래서 LLM 모드에서 먼저 해요(추정).

### 7.6 예시 (모양 보기용, 실제 카드 글 아님)

안 A · 예/아니요 꼴 "도배할 때 몰딩도 꼭 바꿔야 해요?"

| 블록 | 화면 |
| --- | --- |
| lead | **아니요, 꼭 바꾸지 않아도 돼요.** |
| body | 몰딩이 들뜨거나 색이 바랬으면 같이 바꾸는 집이 많아요.① 바꿀지는 실측 때 업체와 정해요. |
| sources | 출처 1 · (목공 시방 조각 이름) |
| more | 자세히 보기 · 2문장 더 |
| next | [표준견적서 보기] |
| follow | 몰딩만 칠해도 돼요? · 걸레받이도 바꿔요? |

안 B · 방법 꼴 "셀프로 벽지 뜯을 때 어떻게 해요?"

| 블록 | 화면 |
| --- | --- |
| lead | **물을 적셔 불린 뒤 위에서부터 뜯어요.** |
| steps | 1 전기 차단기 내리기 · 2 콘센트 덮개 떼기 · 3 물 뿌려 불리기 · 4 위에서 아래로 뜯기 |
| caution | 콘센트 주변은 물이 닿지 않게 해요. |
| sources | 출처 1 · (도배 시방 조각 이름) |
| follow | 뜯고 나서 바로 발라도 돼요? |

안 A · 비용 꼴 "우리 집 도배 얼마예요?"

| 블록 | 화면 |
| --- | --- |
| lead | **믿집이 이 집 조건으로 계산한 표준견적서 금액이에요.** (정해 둔 글 `PRICE_DEEP`) |
| calc | [믿집 계산] 표준견적서 합계 · 부가세 포함 (값은 계산 엔진 `standard.total`) |
| body | 업체 견적이 아니라 공공 기준으로 계산한 참고 금액이에요. |
| next | [표준견적서 보기] [업체 보기] |

## 8. 고를 것 · 다음 일

| 고를 것 | 선택지 | 조사 담당 추천 |
| --- | --- | --- |
| 기본 구성 | A만 / A + B / C까지 | **A + B**(LLM 0회 그대로) |
| 출처 모양 | 묶음 끝 한 줄(지금) / 문장 끝 숫자 알약 + 끝 한 줄 | **숫자 알약 + 끝 한 줄**. 알약은 보이는 문장에만 |
| 결론 줄 굵게 | 굵게 / 보통 | 굵게(결론 블록 하나만) |
| 후속 질문 수 | 0~3 | 2개(좁은 칸) |
| 그림 블록 | 지금 만들기 / 자리만 | 자리만(설명 그림 목록이 생기면) |

- 할 일 순서(제안)
  1. 카드 `lead` 칸 초안 · 검사 규칙(agent-next 6.5)
  2. 화면 `AiAnswer`에 결론 블록 · 숫자 알약 · 출처 아래 칸
  3. 카드 `steps` · `compare` 칸(방법 · 순서 · 비교 꼴 카드부터)
  4. LLM 모드 지시문 v2(형식 규칙 + 블록 고르기 스키마) + eval
- 못 한 것
  - ChatGPT 실제 화면은 캡처 · 측정하지 않았어요(알약 · 이미지 묶음 모양은 2차 자료).
  - OpenAI 도움말 · 블로그 몇 곳은 403으로 직접 열지 못했어요(검색 결과 요약으로 봄).
  - 2026년 ChatGPT 모델 이름 · 자동 고르기 변화는 보도끼리 엇갈려요. 확정하지 않았어요.

## 9. 출처

공식 (직접 열어 읽음)

- [O1] OpenAI Model Spec 2026-10-29판 — https://model-spec.openai.com/2026-10-29.html , 원문 저장소 https://github.com/openai/model_spec (`model_spec.md`의 'Adapt to interactive and programmatic use', 정의 절)
- [O1b] OpenAI Model Spec 2026-08-18판 — https://model-spec.openai.com/2026-08-18.html ('Be clear and direct', 'Use Markdown with LaTeX extensions', 'Be thorough but efficient', 'Be suitably professional', 'Have conversational sense')
- [O2] Model Spec 변경 기록 — https://github.com/openai/model_spec/blob/main/CHANGELOG.md (v2026.10.29 'Removes most detailed style guidance')
- [O3] GPT-5 프롬프팅 가이드(Markdown · verbosity 절) — https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
- [O3b] GPT-5.1 프롬프팅 가이드 — https://developers.openai.com/cookbook/examples/gpt-5/gpt-5-1_prompting_guide
- [O3c] GPT-5.2 프롬프팅 가이드(검색 결과 요약으로만) — https://cookbook.openai.com/examples/gpt-5/gpt-5-2_prompting_guide
- [O4] GPT-5 새 파라미터와 도구(verbosity) — https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_new_params_and_tools
- [O5] 텍스트 생성 가이드(`instructions` · developer 메시지 · `output_text`) — https://developers.openai.com/api/docs/guides/text
- [O6] 구조화 출력 가이드(`text.format`, 지원 스키마, 스트리밍 사건) — https://developers.openai.com/api/docs/guides/structured-outputs
- [O7] ChatKit 가이드(위젯 · 파일 첨부, Agent Builder 2026-11-30 종료) — https://developers.openai.com/api/docs/guides/chatkit
- [O8] Searching the web with ChatGPT(자동 검색 · 인용 · 출처 버튼, 검색 결과 요약으로 봄) — https://help.openai.com/en/articles/9237897-searching-the-web-with-chatgpt
- [O9] Memory FAQ(검색 결과 요약으로 봄) — https://help.openai.com/en/articles/8590148-memory-faq , 지난 대화 참고 https://help.openai.com/en/articles/10303002-how-does-memory-use-pastconversations , 특성(Characteristics) https://help.openai.com/en/articles/20001038-characteristics-in-chatgpt (403, 제목만 확인)
- [O10] ChatGPT shopping research 발표 — https://openai.com/index/chatgpt-shopping-research
- [O11] Claude 시스템 지시문(Opus 5.5, 2026-11-09 'lists_and_bullets') — https://platform.claude.com/docs/en/release-notes/system-prompts/claude-opus-5-5
- [O12] Claude Citations — https://platform.claude.com/docs/en/build-with-claude/citations

2차 (기사 · 분석 · 유출본)

- [S1] TechRadar, ChatGPT 성격 설정 — https://www.techradar.com/ai-platforms-assistants/chatgpt/chatgpts-new-personality-settings-let-you-pick-the-vibe-and-it-ranges-from-corporate-calm-to-chaotic-bestie
- [S2] Engadget, 따뜻함 · 열정 조절 — https://www.engadget.com/ai/you-can-now-tweak-how-warm-and-enthusiastic-chatgpts-responses-are-204003009.html
- [S3] 9to5Mac, GPT-5.5 Instant(이모지 · 후속 질문 줄임) — https://9to5mac.com/2026/05/05/gpt-5-5-instant-makes-chatgpt-more-accurate-while-nixing-gratuitous-emojis/ , TechCrunch https://techcrunch.com/2026/05/05/openai-releases-gpt-5-5-instant-a-new-default-model-for-chatgpt/
- [S4] Mixed News, Plus · Pro 자동 Thinking 전환 종료 — https://mixed-news.com/en/chatgpt-plus-pro-stop-switching-to-thinking-gpt-5-5-retires-october-14/ , Let's Data Science https://letsdatascience.com/news/openai-updates-gpt-55-instant-behaviour-in-chatgpt-67c5e5c5
- [S5] AI UX Playground, ChatGPT 인용 화면 분석(2026-07-10) — https://aiuxplayground.com/teardowns/chatgpt/citations
- [S6] GPT-5 ChatGPT 시스템 지시문 유출본(진위 미확인) — https://gist.github.com/maoxiaoke/f6d5b28f9104cd856a2622a084f46fd7 , 보도 https://dataconomy.com/2025/08/12/reddit-post-claims-gpt-5-system-prompt-leak
- [S7] Forte Labs, Claude 4 · ChatGPT 5 시스템 지시문 안내 — https://fortelabs.com/blog/a-guide-to-the-claude-4-and-chatgpt-5-system-prompts/
- [S8] Simon Willison, GPT-5 API의 숨은 시스템 지시문 — https://simonwillison.net/2025/Aug/15/gpt-5-has-a-hidden-system-prompt/
- [S9] Birdeye, ChatGPT 지도 · 장소 패널 — https://birdeye.com/blog/chatgpts-new-local-map-knowledge-panel-experience-what-it-is-and-how-to-show-up-well/
- [S10] OpenAI 커뮤니티, 후속 제안 불만(GPT-5.6) — https://community.openai.com/t/serious-report-conversational-behavior-regression-and-forced-follow-up-suggestions-in-gpt-5-6/1391006 , PCWorld https://pcworld.com/article/3085980/chatgpt-quietly-fixed-its-most-annoying-habit.html
- [S11] Relevant Audience, 출처 버튼 위치 변경 — https://www.relevantaudience.com/geo/chatgpt-sources-button-buried/
- [S12] MacRumors, 쇼핑 카드 — https://www.macrumors.com/2025/04/29/chatgpt-gains-new-shopping-features/
- [S13] Perplexity 인용 방식 분석 — https://llmpulse.ai/blog/how-perplexity-works/ , https://amicitable.pages.dev/blog/perplexity-ai-citations
- [S14] 네이버 AI 브리핑 보도 · 분석 — https://www.newsis.com/view/NISX20251215_0003441461 , https://news.tf.co.kr/read/economy/2313941.htm , https://inblog.ai/ko/glossary/naver-ai-briefing , https://v.daum.net/v/20260626060325750
- [S15] 오늘의집 AI 관련 — https://apps.apple.com/kr/app/id6744433353 , https://yozm.wishket.com/magazine/detail/2958
