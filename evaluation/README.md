# 에이전트 평가

기준은 하나다: **고객에게 필요한 정보만, 쉽게**. 평가마다 사례 약 5,000개를 만들고, 코드 채점은 전부에, 판정 LLM은 층화 표본에만 쓴다.
CI에서 유료 호출은 0회다 (AGENTS.md 4장). 유료 실행은 단계마다 금액을 먼저 보이고 승인받은 뒤에만 한다.

| 폴더 · 파일 | 하는 일 |
| --- | --- |
| `plan/` | 공정 의견 사례 생성기(공정 스펙으로 공정마다 약 5,000개) · 공정 설정 · 공정별 표본 100개 |
| `router/` | 상담 라우터 평가 (바뀐 칸 · 공정 더하기/빼기 · 질문 · 범위 밖 · 답) |
| `expert/` | 공정 전문가 답 평가 (주제 10개 × 공정) |
| `dobae/` | 도배 상담 비교 평가 ('Claude에게 그냥 묻기' vs 믿집 상담, 사례 15개) |
| `common/` | 생성 · 실행 공통 도구, 사례 형식, 비용 계산 |
| `scorers/` | 공정 의견 코드 채점 규칙 · 어려운 용어 표 · 모범 답 |
| `judge/` | 판정 LLM 기준표 둘(공정 의견 `rubric_v1.md` · 전문가 답 `rubric_expert_v1.md`)과 스키마 |
| `run_agent.py` | 공정 의견 실행기 (기본은 호출 수 · 예상 비용만) |
| `check_cases.py` | 무료 점검 T0 (공정 의견 · 라우터 · 전문가 답) |
| `tests/` | 단위 테스트 (DB · Redis · LLM 없이) |

## 단계

| 단계 | 내용 | 비용 |
| --- | --- | --- |
| T0 | 사례 생성 · 상담 · 계산 코드에 다시 넣어 보기 · 규칙 모순 점검 · 단위 테스트 · 가짜 LLM(가짜 Batch 포함) 실행 | 무료 |
| T1 | 평가마다 dev 20개로 실제 토큰 · 비용을 잰다 | 승인 후 |
| T2 | 프롬프트를 바꿀 때 150개 | 승인 후 |
| T3 | 전체 약 5,000개 (`--batch`) | 승인 후 |

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py          # 공정 의견 (등록된 공정마다 4,995개)
uv run python ../evaluation/router/make_cases.py        # 라우터 4,980개
uv run python ../evaluation/expert/make_cases.py        # 전문가 답 4,980개
uv run python ../evaluation/check_cases.py              # T0 점검 (약 35초)
uv run pytest ../evaluation/tests                       # T0 단위 테스트 (약 20초)

uv run python ../evaluation/run_agent.py --trade dobae --split dev --sample 20 --judge 9         # 호출 수 · 예상 비용만
uv run python ../evaluation/run_agent.py --trade dobae --split dev --sample 20 --judge 9 --fake  # 가짜 LLM (무료)
uv run python ../evaluation/run_agent.py --trade dobae --split dev --sample 20 --judge 9 --live  # T1 (유료, 승인 후)
uv run python ../evaluation/run_agent.py --trade dobae --live --batch                           # T3 Batch (유료)
uv run python ../evaluation/run_agent.py --trade dobae --sample 20 --live --plan-prompt v2      # 프롬프트 v2 비교
uv run python ../evaluation/router/run.py --sample 20 [--fake | --live] [--batch]
uv run python ../evaluation/expert/run.py --sample 20 --judge 10 [--fake | --live] [--batch]
```

- `--sample N`은 `--stratify` 키(기본 `category`)의 층마다 고르게 뽑는다. 두 나눔을 같이 뽑으면 dev:held-out 2:1을 지킨다.
- 실행기는 `.env`에서 `ANTHROPIC_API_KEY` · `LLM_MODEL*` · `LLM_EFFORT*`만 읽는다. 역할별 모델: 공정 의견 `plan`,
  라우터 `router`, 전문가 답 `expert`, 판정 `judge` (`LLM_MODEL_JUDGE` · `LLM_EFFORT_JUDGE`, 비우면 `LLM_MODEL` · low).
- `--batch`: 에이전트 함수를 불러 요청 글만 모으고(호출 없음) `llm.parse_batch`와 같은 길(submit → wait → results)로 낸 뒤,
  결과를 `llm.parse` 자리에 끼워 다시 부른다. 그래서 요청 글 · 코드 검사 · 후처리가 실시간과 같다. Batch id는 결과 폴더의
  `batch.json`에 적어 두고, 기다리다 끊기면 같은 `--out`으로 다시 돌려 결과만 받는다.
- `--plan-prompt v2`: 같은 지식으로 `prompts/<지식 이름>_v2.md`를 써서 공정 에이전트를 다시 만든다. 결과 폴더 이름과 summary에 프롬프트 버전이 붙는다.

## 실행 흐름

```
공정 의견: 사례 card → spec.build(견적) + consult.service.plan_text → spec.agent.plan → scorers/trade_plan.score → judge (표본)
라우터:    사례 card · history · message → app.agent.consult.route(ROUTER_SYSTEM, …) → apply_route · normalize → router/score
전문가 답: 사례 card → consult.service.facts(집 정보 글) + 질문 → spec.agent.answer → expert/score → judge (표본)
결과:      <평가>/results/<날짜-시각>/raw.json(원문 · 사용량 · 점수) · summary.md(표)
```

## 공정 의견 코드 채점 (사례 전부)

`scorers/trade_plan.py`. 모델이 쓴 원문(코드 검사로 버리기 전) 기준이다.

| 검사 | 기준 |
| --- | --- |
| `no_digits` · `no_number_words` | 숫자(0~9)도, 말로 쓴 금액 · 기간 · 인원('하루면 끝나요' · '두 명')도 없다 |
| `step_keys` · `step_cover` | 단계 키가 계산 엔진 공정표 안에 있고 겹치지 않으며 단계마다 하나씩 있다 |
| `summary_len` · `summary_sent` · `item_len` | 요약 20~200자 · 1~2문장, 단계 · 실측 질문 120자, 주의 160자 이하 |
| `visit_count` · `caution_count` · `caution_source` | 실측 질문 3~6개, 주의 2~4개, 주의 출처가 지식 '출처' 목록 안 |
| `style` · `terms` | '-해요'체, 어려운 용어는 처음 나온 문장에서 쉬운 말로 풀었다 |
| `must` · `must_not` | 사례의 기대 규칙 (`plan/README.md`) |

규칙은 공정 스펙 화면 말에서 뽑는다: `sum.<칸>.<값>`(요약에 고른 값) · `not_chosen.<칸>.<값>`(고르지 않은 항목) ·
`check.<칸>`(모르는 칸을 실측 때 확인) · `after.<줄>`('실측 후' 줄이 왜 실측 뒤인지) · `order.<공정>`(같이 하는 공정과 순서) ·
`scope.<공정>` · `scope.etc`(고르지 않은 공정 · 믿집 밖 공사) · `prep.mention` · `empty.moving` · `sum.occupied.*`.
숫자로만 말할 수 있는 선택지(예: 싱크대 2.4m)는 요약 규칙을 만들지 않고, 꼭 언급할 예문과 겹치는 '언급하면 안 됨'은 뺀다.

`scorers/witness.py`는 규칙을 모두 지키는 모범 답이다(도배 · 목공은 손으로, 새 공정은 규칙 예문으로). T0에서 사례마다 이 답이
모든 검사를 통과하면 규칙끼리 모순이 없다는 증거이고, `--fake` 실행의 가짜 LLM 응답으로 쓴다.

라우터 · 전문가 답 채점은 `router/README.md` · `expert/README.md`에 있다.

## 판정 LLM (층화 표본만)

기준표 + 그 공정의 지식(SKILL.md)이 시스템 프롬프트다 (공정마다 같아 캐시된다). 화면에 보이는 답을 본다. 기준마다 1~5점과 이유 한 줄.

| 기준표 | 기준 |
| --- | --- |
| 공정 의견 `rubric-v1` | 필요한 정보만 · 쉬운 말 · 할 일이 분명함 · 틀린 내용 없음 |
| 전문가 답 `rubric-expert-v1` | 질문에 맞게 답함 · 필요한 정보만 · 쉬운 말 · 틀린 내용 없음 |

## 지난 실측 의견에 코드 채점을 돌려 본 결과 (무료)

`dobae/results`의 세 실행(Opus 5.5 · `wallpaper-v1`)에서 나온 도배 공정 의견 135개를 채점기로 다시 매겼다. 판정 LLM은 돌리지 않았다.

| 검사 | 통과 |
| --- | ---: |
| 숫자 · 말로 쓴 숫자 · 단계 키 · 단계 빠짐 · 길이 · 개수 · 말투 | 100% |
| 요약 1~2문장 | 99% (134/135) |
| 꼭 언급 | 99% (134/135, 사는 집인데 요약에 안 드러남 1) |
| 언급하면 안 됨 | 63% (85/135): 빈집 의견 90개 중 50개가 '빈집이라 짐 정리 없이 바로…'처럼 짐 이야기 |
| 어려운 용어 풀이 | 0% (0/135): 초배 135 · 정배 131 · 덧방 49 · 보양 47 · 퍼티 29 · 샌딩 17번을 풀지 않고 씀 |

- 실측 질문은 135개 모두 6개, 주의는 모두 4개로 늘 상한을 채웠다. 프롬프트 v2(`--plan-prompt v2`)가 이 셋을 다룬다.

## 비용

가격 출처: [Claude 가격](https://platform.claude.com/docs/en/about-claude/pricing) (2026-10-31 확인), $/MTok.

| 모델 | 입력 | 캐시 쓰기(5분) | 캐시 읽기 | 출력 | Batch 입력 · 출력 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Opus 5.5 | 4 | 5 | 0.20 | 20 | 2 · 10 |
| Sonnet 5.5 | 2 | 2.50 | 0.10 | 10 | 1 · 5 |
| Haiku 5.5 (프롬프트 10만 토큰 이하) | 0.10 | 0.125 | 0.01 | 0.50 | 0.05 · 0.25 |

호출 토큰 모양(평균, `common/cost.py`의 `SHAPES`). 도배 공정 의견만 실측이고 나머지는 글자 수 × 도배 글자당 토큰 비율 추정이다.

| 호출 | 입력(캐시 안 됨) | 시스템(캐시) | 출력(생각 포함) |
| --- | ---: | ---: | ---: |
| 도배 공정 의견 (실측 135번) | 390 | 3,231 | 1,260 |
| 목공 공정 의견 | 440 | 4,190 | 1,400 |
| 공정 의견 판정 | 1,800 | 4,900 | 700 |
| 라우터 (v5 시스템 6,111자) | 290 | 8,040 | 300 |
| 전문가 답 (10공정 평균 3,051자) | 100 | 4,010 | 400 |
| 전문가 답 판정 | 310 | 5,500 | 500 |

단계별 예상 (T1 20개 · T2 150개 · T3 약 5,000개. 판정: 공정 의견 9 · 45 · 500개, 전문가 답 10 · 50 · 500개).
T3는 실시간(캐시 맞음) 값이고, 괄호는 Batch를 캐시 없이 센 보수적 값이다. 시스템 프롬프트가 큰 라우터 · 전문가 답은
Batch에서 캐시가 맞지 않으면 오히려 비싸다.

| 평가 | 모델 | T1 | T2 | T3 |
| --- | --- | ---: | ---: | ---: |
| 공정 의견 두 공정 | Opus 5.5 | $1.89 | $11.03 | ($235.91) |
| 공정 의견 두 공정 | Sonnet 5.5 | $0.94 | $5.51 | ($117.95) |
| 공정 의견 두 공정 | Haiku 5.5 | $0.05 | $0.28 | ($5.90) |
| 라우터 | Opus 5.5 | $0.33 | $1.47 | $43.82 ($97.91) |
| 라우터 | Sonnet 5.5 | $0.16 | $0.73 | $21.91 ($48.95) |
| 라우터 | Haiku 5.5 | $0.01 | $0.04 | $1.30 ($2.45) |
| 전문가 답 | Opus 5.5 | $0.49 | $2.18 | $52.18 ($69.17) |
| 전문가 답 | Sonnet 5.5 | $0.25 | $1.09 | $26.09 ($34.58) |
| 전문가 답 | Haiku 5.5 | $0.01 | $0.06 | $1.42 ($1.73) |

실행기는 `--live` 없이 돌리면 고른 사례로 예상 비용 표를 다시 계산해 보여 준다.

## 한계

- 키워드 채점은 거칠다. '안 함' 맥락은 같은 문장의 부정 말로만 본다. 뉘앙스 · 질문에 맞는지는 판정 LLM으로 본다.
- 도배 공정 의견 입력은 숫자를 빼면 432가지라 4,995개는 구조마다 약 11~12번 반복이다. 전문가 답은 공정 · 주제마다
  질문 조각이 9~18개라 같은 질문이 집 정보만 바꿔 되풀이된다 (서로 다른 질문 dev 2,306 · held-out 1,074).
- 도배 · 목공 밖 공정은 스펙 화면 말로 만든 기본 말이라 라우터 고객 말 · 전문가 질문이 딱딱하다. 실제로 돌리기 전에
  `router/phrases.py` · `expert/phrases.py`에 그 공정 말을 더한다.
- 토큰 추정은 도배 공정 의견만 실측이다. 나머지는 T1에서 다시 잰다.
