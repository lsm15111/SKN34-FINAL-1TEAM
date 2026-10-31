# 목공 공정 의견 평가 사례

목공 공정 에이전트(`app/agent/carpentry.py`, 프롬프트 `carpentry-v1`)의 공정 의견을 평가하는 사례다.
사례 입력(집 조건 + 목공 선택)으로 계산 엔진을 돌려 견적을 만들고, 상담과 같은 입력 글로 `plan()`을 부른다.

- `make_cases.py`: 사례 4,995개를 만든다 (표준 라이브러리 + 계산 엔진, 시드 고정)
- `sample_100.jsonl`: 범주마다 고르게 고른 표본 100개 (dev 67 · held-out 33). 커밋한다
- `cases_5k.jsonl`: 전체. 다시 만들 수 있어 커밋하지 않는다
- 사례 형식: `../common/README.md`, 채점: `../README.md`

```bash
cd backend
uv run python ../evaluation/carpentry/make_cases.py   # cases_5k.jsonl · sample_100.jsonl을 다시 만들고 아래 표를 찍는다
uv run python ../evaluation/check_cases.py --agent carpentry
```

## 범주별 개수

범주 = 목공 항목 조합 (천장 몰딩 `molding` · 걸레받이 `base` · 방문 `door` · 천장 평탄화 `flatten` 중 하나 이상).

| 범주 (목공 항목) | dev | held-out | 합계 |
| --- | ---: | ---: | ---: |
| base | 222 | 111 | 333 |
| base+door | 222 | 111 | 333 |
| base+door+flatten | 222 | 111 | 333 |
| base+flatten | 222 | 111 | 333 |
| door | 222 | 111 | 333 |
| door+flatten | 222 | 111 | 333 |
| flatten | 222 | 111 | 333 |
| molding | 222 | 111 | 333 |
| molding+base | 222 | 111 | 333 |
| molding+base+door | 222 | 111 | 333 |
| molding+base+door+flatten | 222 | 111 | 333 |
| molding+base+flatten | 222 | 111 | 333 |
| molding+door | 222 | 111 | 333 |
| molding+door+flatten | 222 | 111 | 333 |
| molding+flatten | 222 | 111 | 333 |
| 합계 | 3,330 | 1,665 | 4,995 |

## 범주 안에서 고르게 채운 칸 (`strata`)

거주 × 같이 하는 공정 × 면적 기준(방문 범주는 × 문틀 교체 × 방문 개수)은 모든 조합을 돌려 쓰고, 나머지는 값마다 고르게 채운다.
두 칸씩 짝지은 값 조합 469가지와 방문 범주의 문틀 × 개수 짝 68가지가 모두 나온다.

| 칸 | 값별 개수 (전체) |
| --- | --- |
| `occupied` 사는 집 | yes 2,496 · no 2,499 |
| `other` 같이 하는 공정 | dobae 2,494 · none 2,501 |
| `basis` 면적 기준 | supply 1,665 · exclusive 1,663 · unknown 1,667 |
| `door_frame` 문틀 교체 (방문 범주) | yes 879 · no 887 · unknown 898 (방문 없음 2,331) |
| `doors` 방문 개수 (방문 범주) | 1~2개 681 · 3~4개 671 · 5~6개 656 · 모름 656 |
| `spaces` 공간 이름 수 | 없음 1,260 · 1개 1,245 · 2~3개 1,245 · 4~6개 1,245 |
| `size` 면적 크기 | S 1,665 · M 1,665 · L 1,665 |
| `balcony` 발코니 확장 | yes 2,505 · no 2,490 |
| `year` 준공 연도 | none 1,260 · old 1,245 · mid 1,245 · new 1,245 |
| `unknown` 모르겠어요로 둔 칸 | none 2,436 · 면적 기준 1,228 · 문틀 454 · 방문 개수 293 · 둘 이상 584 |

- 공간 이름은 문장 조각처럼 30개 중 번호 % 3 == 2인 10개를 held-out 전용으로 둔다 (dev 20개 · held-out 10개, 두 나눔이 같이 쓴 이름 0개). 15%는 띄어쓰기 잡음(`작은 방` · `드레스룸`)을 넣는다. 욕실 · 화장실은 범위 밖 공사 키워드와 겹쳐 넣지 않았다.
- 공정표 단계 키는 항목 조합과 거주로 14가지가 나온다 (예: `prep remove ceiling door trim finish` 494개).

## 사례마다 붙는 기대 검사 (개수)

| 꼭 언급 (`must`) | 개수 | 언급하면 안 됨 (`must_not`) | 개수 |
| --- | ---: | --- | ---: |
| `sum.item.molding` · `.base` · `.door` · `.flatten` | 2,664씩 | `scope` · `balcony.any` | 4,995씩 |
| `sum.door_frame.yes` · `.no` | 1,777 · 887 | `not_chosen.molding` · `.base` · `.door` · `.flatten` | 2,331씩 |
| `sum.occupied.yes` · `.no` | 2,496 · 2,499 | `empty.moving` | 2,499 |
| `prep.mention` | 2,496 | `other.trade` | 2,501 |
| `after.remove_ceiling` · `after.remove_trim` | 2,664 · 3,996 | | |
| `after.waste` · `after.moving` | 4,995 · 2,496 | | |
| `order.other` | 2,494 | | |
| `check.area_basis` · `check.doors` · `check.door_frame` | 1,667 · 656 · 898 | | |

## 사례 예

```json
{"id": "cp-d0224", "agent": "carpentry", "split": "dev", "category": "base",
 "strata": {"door_frame": "-", "doors": "-", "occupied": "yes", "other": "dobae", "basis": "unknown",
            "size": "M", "balcony": "yes", "year": "old", "spaces": "one", "unknown": "area_basis"},
 "input": {"common": {"area_m2": "102.5", "area_basis": "supply", "area_said": "31평 (공급 · 전용 모름)",
                      "occupied": true, "balcony_ext": true, "built_year": 1989},
           "trades": {"mokgong": {"items": ["base"], "spaces": ["거실 겸 주방"], "doors": null, "door_frame": null}},
           "other_trades": ["dobae"], "to_check": ["area_basis"]},
 "expect": {"step_keys": ["prep", "remove", "trim", "finish"], "after_visit": ["remove_trim", "waste", "moving"],
            "must": ["sum.item.base", "sum.occupied.yes", "prep.mention", "after.remove_trim", "after.waste",
                     "after.moving", "order.other", "check.area_basis"],
            "must_not": ["scope", "not_chosen.molding", "not_chosen.door", "not_chosen.flatten", "balcony.any"]},
 "tpl": ["space:18"]}
```

## 주의

- 숫자를 뺀 입력 글은 4,527가지다 (공간 이름 덕분). 같은 입력은 없다.
- 방문 개수는 입력 글에 나오지 않는다 (견적 줄 금액에만 반영). 개수를 몰라 기본값(3개)을 쓴 사례만 '고객이 몰라 기본값으로 둔 칸: 방문 개수'가 붙는다.
- 목공 지식에는 발코니 이야기가 없어서 발코니 언급은 늘 '언급하면 안 됨'이다.
