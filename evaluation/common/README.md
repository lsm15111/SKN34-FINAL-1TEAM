# 평가 공통 도구 · 사례 형식

에이전트마다 평가 사례를 만들고(`<agent>/make_cases.py`) 돌리는(`run_agent.py`) 데 같이 쓰는 것이다.

| 파일 | 하는 일 |
| --- | --- |
| `gen.py` | 시드 난수, 조합 격자 · 고른 배치, dev:held-out 2:1, 층화 표본, 문장 조각 dev/held-out 분리, 글자 3-gram 근사 중복, 잡음, jsonl · 표 |
| `house.py` | 집 조건 값 (면적 · 면적 기준 · 준공 연도). 상담 코드와 같은 ㎡ 환산 |
| `trades.py` | 사례 입력 → 계산 엔진 입력 · 견적 · 공정 에이전트 입력 글 (상담 코드에서 옮긴 얇은 어댑터) |
| `cost.py` | 모델 가격, 사용량 → 비용, 실행 전 비용 추정 |

## 생성 규칙

- 표준 라이브러리만 쓴다. 계산 엔진(`app.calc`)과 기준 단가(`app.refprice`)는 표준 라이브러리만 쓰는 순수 함수라 불러 쓴다.
- 시드를 고정한다 (`gen.SEED`, `gen.rng(에이전트 이름)`). 같은 코드면 같은 파일이 나온다.
- dev:held-out = 2:1. 프롬프트를 고칠 때는 dev만 보고, held-out은 마지막 확인에만 쓴다.
  - `assign_splits`: 칸 조합마다 dev, dev, held-out 차례로 붙인다. 범주 개수를 3의 배수로 두면 범주마다 정확히 2:1이다.
- 범주별로 고르게: `balanced_rows`가 핵심 칸은 모든 조합을 돌려 쓰고(조합마다 차이 1 이하), 나머지 칸은 값마다 고르게 채운다.
- 문장 조각: 묶음마다 번호 % 3 == 2인 조각은 held-out 전용이다 (`Fragments`). 같은 조각이 두 나눔에 같이 나오지 않는다.
- 근사 중복: 수는 `#`로, 공백은 지운 뒤 글자 3-gram Jaccard가 0.8 이상이면 거른다 (`NearDup`, 나눔별). 고객 말처럼 글이 있는 사례에 쓴다.
  - 공정 의견 사례는 입력이 칸 값의 조합이라 3-gram 거르기 대신 '같은 입력 금지'와 고른 배치로 중복을 막는다. 숫자만 다른 입력 글이 몇 가지인지는 생성기가 찍는다.
- 잡음(`noisy`): 띄어쓰기 없앰 · 일부 없앰 · 넣음, 천장→천정, 평→펑, 맞춤법(돼요→되요 등), 요→여, 반말(예요.→임.), 꼬리(ㅠㅠ), 문장부호 없앰. 규칙이라 두 나눔이 같이 쓴다.
- 전체 사례 파일(`<agent>/cases_5k.jsonl`)은 다시 만들 수 있어 커밋하지 않는다(`evaluation/.gitignore`). 커밋은 생성기와 표본 100개(`sample_100.jsonl`)만 한다.

## 사례 jsonl 형식 (공정 의견)

한 줄에 사례 하나. 키 순서는 아래와 같다.

| 키 | 값 |
| --- | --- |
| `id` | `wp-d0001`처럼 에이전트 접두어(`wp` 도배 · `cp` 목공) - 나눔 첫 글자 + 나눔 안 번호 |
| `agent` | 평가 대상 (`run_agent.py --agent`) |
| `split` | `dev` · `heldout` |
| `category` | 층화 기본 키. 범주마다 개수가 같다 (도배: `등급-천장`, 목공: 항목 조합) |
| `strata` | 그 밖에 고르게 채운 칸. `--stratify strata.<칸>`으로 층을 바꿀 수 있다 |
| `input` | 에이전트에 들어갈 집 조건 + 공정 선택 (아래) |
| `expect` | 기대 검사. 계산 엔진 결과와 규칙 표로 만든다 (아래) |
| `tpl` | (선택) 쓴 문장 조각 `묶음:번호`. 두 나눔 겹침 점검용 |

`input`

```json
{
  "common": {"area_m2": "112.4", "area_basis": "supply", "area_said": "34평",
             "occupied": true, "balcony_ext": false, "built_year": 1998},
  "trades": {"dobae": {"grade": "basic", "include_ceiling": true}},
  "other_trades": ["mokgong"],
  "to_check": ["area_basis"]
}
```

- `common`: 상담 카드의 공통 칸. `area_m2`는 ㎡ 소수 한 자리 문자열(계산 엔진 `Decimal`), `area_said`는 고객이 말한 꼴로 참고만 한다.
- `trades`: 평가하는 공정 칸만 둔다 (계획의 카드 구조 `trades: {key: {field: value}}`를 따름).
  - 도배 `dobae`: `grade`(economy · basic), `include_ceiling`
  - 목공 `mokgong`: `items`(molding · base · door · flatten), `spaces`(공간 이름), `doors`(방문 개수, 방문이 없으면 null), `door_frame`(문틀까지, 방문이 없으면 null)
- `other_trades`: 같이 하는 다른 공정. 이 에이전트는 입력 글의 '…을 같이 해요' 한 줄만 본다.
- `to_check`: 고객이 '모르겠어요'라고 해 상담 기본값(`trades.DEFAULTS`)으로 둔 칸. 값은 이미 기본값으로 들어 있다.

`expect`

| 키 | 값 |
| --- | --- |
| `step_keys` | 계산 엔진 공정표 단계 키 (순서대로). 의견의 단계 키는 이 안에서 하나씩 |
| `after_visit` | 계산 엔진에서 상태가 '실측 후'인 줄 키 |
| `must` | 꼭 언급할 규칙 id. 뜻과 키워드는 `scorers/trade_plan.py`의 `RULES` |
| `must_not` | 언급하면 안 되는 규칙 id |

규칙 id는 `무엇.세부` 꼴이다: `sum.*` 요약에 드러낼 것, `prep.*` · `after.*` · `order.*` · `check.*` · `balcony.*` 조건 반영, `not_chosen.*` 고르지 않은 항목, `empty.*` 빈집, `other.*` 같이 하지 않는 공정, `scope` 범위 밖 공사.

다른 에이전트(라우터 · 전문가 답변 · 가견적)도 `id · agent · split · category · strata · expect`는 같게 두고 `input`만 그 에이전트 입력 모양으로 바꾼다.
