# 공정 의견 사례: 바닥재 (`floor`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,977개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 바닥재 종류 × 지금 바닥 21개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `vinyl_18-yes` | 장판 · 얇은 것 / 걷어 내요 | 158 | 79 |
| `vinyl_18-no` | 장판 · 얇은 것 / 그 위에 깔아요 | 158 | 79 |
| `vinyl_18-unknown` | 장판 · 얇은 것 / 모르겠어요 | 158 | 79 |
| `vinyl_22-yes` | 장판 · 두꺼운 것 / 걷어 내요 | 158 | 79 |
| `vinyl_22-no` | 장판 · 두꺼운 것 / 그 위에 깔아요 | 158 | 79 |
| `vinyl_22-unknown` | 장판 · 두꺼운 것 / 모르겠어요 | 158 | 79 |
| `decotile-yes` | 데코타일 / 걷어 내요 | 158 | 79 |
| `decotile-no` | 데코타일 / 그 위에 깔아요 | 158 | 79 |
| `decotile-unknown` | 데코타일 / 모르겠어요 | 158 | 79 |
| `engineered-yes` | 강마루 / 걷어 내요 | 158 | 79 |
| `engineered-no` | 강마루 / 그 위에 깔아요 | 158 | 79 |
| `engineered-unknown` | 강마루 / 모르겠어요 | 158 | 79 |
| `laminate-yes` | 강화마루 / 걷어 내요 | 158 | 79 |
| `laminate-no` | 강화마루 / 그 위에 깔아요 | 158 | 79 |
| `laminate-unknown` | 강화마루 / 모르겠어요 | 158 | 79 |
| `porcelain-yes` | 포세린 타일 / 걷어 내요 | 158 | 79 |
| `porcelain-no` | 포세린 타일 / 그 위에 깔아요 | 158 | 79 |
| `porcelain-unknown` | 포세린 타일 / 모르겠어요 | 158 | 79 |
| `unknown-yes` | 모르겠어요 / 걷어 내요 | 158 | 79 |
| `unknown-no` | 모르겠어요 / 그 위에 깔아요 | 158 | 79 |
| `unknown-unknown` | 모르겠어요 / 모르겠어요 | 158 | 79 |
| 합계 | | 3,318 | 1,659 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade floor   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade floor       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade floor --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
