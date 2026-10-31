# 도배 공정 의견 평가 사례

도배 공정 에이전트(`app/agent/wallpaper.py`, 프롬프트 `wallpaper-v1`)의 공정 의견을 평가하는 사례다.
사례 입력(집 조건 + 도배 선택)으로 계산 엔진을 돌려 견적을 만들고, 상담과 같은 입력 글로 `plan()`을 부른다.

- `make_cases.py`: 사례 4,995개를 만든다 (표준 라이브러리 + 계산 엔진, 시드 고정)
- `sample_100.jsonl`: 범주마다 고르게 고른 표본 100개 (dev 67 · held-out 33). 커밋한다
- `cases_5k.jsonl`: 전체. 다시 만들 수 있어 커밋하지 않는다
- 사례 형식: `../common/README.md`, 채점: `../README.md`

```bash
cd backend
uv run python ../evaluation/wallpaper/make_cases.py   # cases_5k.jsonl · sample_100.jsonl을 다시 만들고 아래 표를 찍는다
uv run python ../evaluation/check_cases.py --agent wallpaper
```

## 범주별 개수

범주 = 등급 × 천장. 모름(`gradeunk` · `ceilunk`)은 상담 기본값(기본형 · 천장 포함)으로 계산하고 `to_check`에 남긴다.

| 범주 (등급-천장) | dev | held-out | 합계 |
| --- | ---: | ---: | ---: |
| basic-ceil | 370 | 185 | 555 |
| basic-ceilunk | 370 | 185 | 555 |
| basic-wall | 370 | 185 | 555 |
| economy-ceil | 370 | 185 | 555 |
| economy-ceilunk | 370 | 185 | 555 |
| economy-wall | 370 | 185 | 555 |
| gradeunk-ceil | 370 | 185 | 555 |
| gradeunk-ceilunk | 370 | 185 | 555 |
| gradeunk-wall | 370 | 185 | 555 |
| 합계 | 3,330 | 1,665 | 4,995 |

## 범주 안에서 고르게 채운 칸 (`strata`)

거주 × 같이 하는 공정 × 면적 기준은 모든 조합을 돌려 쓰고(조합마다 차이 1 이하), 나머지는 값마다 고르게 채운다.
두 칸씩 짝지은 값 조합 249가지가 모두 나온다.

| 칸 | 값별 개수 (전체) |
| --- | --- |
| `occupied` 사는 집 | yes 2,496 · no 2,499 |
| `other` 같이 하는 공정 | mokgong 2,497 · none 2,498 |
| `basis` 면적 기준 | supply 1,666 · exclusive 1,665 · unknown 1,664 |
| `size` 면적 크기 (공급 대략 ~24 · 25~35 · 36평~) | S 1,665 · M 1,665 · L 1,665 |
| `balcony` 발코니 확장 | yes 2,502 · no 2,493 |
| `year` 준공 연도 | none 1,251 · old(~1999) 1,251 · mid(2000~2012) 1,251 · new(2013~) 1,242 |
| `unknown` 모르겠어요로 둔 칸 | none 1,479 · 하나 2,223 · 둘 1,108 · 셋 185 |

- 면적 값: 공급은 평(80%) 또는 ㎡, 전용은 ㎡(70%) 또는 실평수, 모름은 평. 흔한 평형(18 · 24 · 32 · 34평, 전용 59 · 84㎡ 등)과 범위 안 아무 값을 반씩 쓴다.
- 공정표 단계 키: 빈집 `paper finish` 2,499 · 사는 집 `prep paper finish` 2,496.

## 사례마다 붙는 기대 검사 (개수)

| 꼭 언급 (`must`) | 개수 | 언급하면 안 됨 (`must_not`) | 개수 |
| --- | ---: | --- | ---: |
| `sum.grade.basic` · `sum.grade.economy` | 3,330 · 1,665 | `scope` | 4,995 |
| `sum.ceiling` | 4,995 | `not_chosen.ceiling` | 1,665 |
| `sum.occupied.yes` · `.no` | 2,496 · 2,499 | `empty.moving` | 2,499 |
| `prep.mention` | 2,496 | `other.trade` | 2,498 |
| `after.removal` · `after.waste` · `after.moving` | 4,995 · 4,995 · 2,496 | `balcony.none` | 2,493 |
| `order.other` | 2,497 | | |
| `check.area_basis` · `check.grade` · `check.include_ceiling` | 1,664 · 1,665 · 1,665 | | |
| `balcony.check` | 2,502 | | |

## 사례 예

```json
{"id": "wp-d0741", "agent": "wallpaper", "split": "dev", "category": "economy-ceilunk",
 "strata": {"occupied": "no", "other": "mokgong", "basis": "supply", "size": "L", "balcony": "yes",
            "year": "old", "grade": "economy", "ceiling": "unknown", "unknown": "include_ceiling"},
 "input": {"common": {"area_m2": "198.3", "area_basis": "supply", "area_said": "60평", "occupied": false,
                      "balcony_ext": true, "built_year": 1997},
           "trades": {"dobae": {"grade": "economy", "include_ceiling": true}},
           "other_trades": ["mokgong"], "to_check": ["include_ceiling"]},
 "expect": {"step_keys": ["paper", "finish"], "after_visit": ["removal", "waste"],
            "must": ["sum.grade.economy", "sum.ceiling", "sum.occupied.no", "balcony.check", "after.removal",
                     "after.waste", "order.other", "check.include_ceiling"],
            "must_not": ["scope", "empty.moving"]}}
```

## 주의

- 도배 입력 글은 칸 값의 조합이라 숫자를 빼면 432가지뿐이다. 4,995개는 구조마다 숫자(면적 · 금액 · 준공 연도)만 바꾼 반복이 약 11~12번이다. 그래서 글자 3-gram 근사 중복 거르기는 쓰지 않고 '같은 입력 금지'만 한다. 5,000개 전체 실행(T3)은 같은 구조를 여러 번 재는 것이라, 구조 432가지를 한 번씩 도는 실행과 견줘 보고 정한다.
- 자유 글 칸이 없어 문장 조각 dev/held-out 분리는 쓰지 않는다. held-out은 같은 분포에서 따로 뗀 사례다.
