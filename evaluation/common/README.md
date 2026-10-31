# 평가 공통 도구 · 사례 형식

평가마다 사례를 만들고(`plan/make_cases.py` · `router/make_cases.py` · `expert/make_cases.py`) 돌리는
(`run_agent.py` · `router/run.py` · `expert/run.py`) 데 같이 쓰는 것이다.

| 파일 | 하는 일 |
| --- | --- |
| `gen.py` | 시드 난수, 조합 격자 · 고른 배치, dev:held-out 2:1, 층화 표본, 문장 조각 dev/held-out 분리, 글자 3-gram 근사 중복, 잡음, 나눔 점검(`split_report`), jsonl · 표 |
| `house.py` | 집 조건 값 (면적 · 면적 기준 · 준공 연도 · 공간 이름), 무작위 상담 카드(`random_card`) |
| `trades.py` | 공정 스펙(REGISTRY) 어댑터: 카드 검사 · normalize, 견적(`spec.build`), 공정 의견 입력 글(`consult.service.plan_text`), 전문가 입력 글(`consult.service.facts`), 에이전트 · 출처 · 지식 |
| `runner.py` | 실행 공통: 에이전트 함수를 그대로 부르고 `llm.parse` 자리만 바꾼다 (live · fake · batch · fake-batch), 표본 고르기, 비용 표 |
| `cost.py` | 모델 가격, 사용량 → 비용, 호출 토큰 모양(`SHAPES`)과 실행 전 비용 추정 |

## 생성 규칙

- 시드를 고정한다 (`gen.SEED`, `gen.rng(이름)`). 같은 코드면 같은 파일이 나온다.
- dev:held-out = 2:1. 프롬프트를 고칠 때는 dev만 보고, held-out은 마지막 확인에만 쓴다.
- 범주별로 고르게: `balanced_rows`가 핵심 칸은 모든 조합을 돌려 쓰고, 나머지 칸은 값마다 고르게 채운다.
- 문장 조각: 묶음마다 번호 % 3 == 2인 조각은 held-out 전용이다 (`Fragments`). 같은 조각이 두 나눔에 나오지 않는다.
- 근사 중복: 수는 `#`로(라우터는 수를 남긴다), 공백은 지운 뒤 글자 3-gram Jaccard가 0.8 이상이면 다시 뽑는다.
- 전체 사례(`cases_5k.jsonl`)는 다시 만들 수 있어 커밋하지 않는다. 커밋은 생성기와 표본 100개(`sample_100.jsonl`)만 한다.

## 사례 jsonl 형식

공통 키: `id`(접두어 - 나눔 첫 글자 + 번호) · `split`(dev · heldout) · `category`(층화 기본 키) · `strata`(그 밖에 고르게
채운 칸, `--stratify strata.<칸>`) · `input` · `expect` · `tpl`(쓴 조각, 두 나눔 겹침 점검용).

| 평가 | `input` | `expect` |
| --- | --- | --- |
| 공정 의견 (`plan/<공정>/`, `trade` 키 있음) | `card`: 상담 카드 JSON(normalize한 것), `area_said`: 고객이 말한 면적 꼴 | `step_keys` · `after_visit`(계산 엔진), `must` · `must_not`(규칙 id) |
| 라우터 (`router/`) | `card` · `history`(앞 대화) · `message`(이번 고객 말) | `effect`(바뀐 칸 → 값), `questions`(넘길 공정), `out_of_scope`, `reply_has`, `ideal`(모범 출력) |
| 전문가 답 (`expert/`, `trade` · `topic` 키 있음) | `card` · `context`(전문가가 받는 집 정보 글) · `question` | `groups`(답에 있어야 할 말), `ideal`(모범 답) |

상담 카드: `trades` · `area_m2`(㎡ 소수 한 자리 문자열) · `area_basis` · `occupied` · `balcony_ext` · `built_year` ·
`values`(공정 → 칸 → 값, multi는 목록) · `spaces` · `to_check`('모르겠어요'로 스펙 기본값을 넣은 칸, 예: `dobae.grade`).
