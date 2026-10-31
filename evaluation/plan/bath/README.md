# 공정 의견 사례: 욕실 (`bath`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,968개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 고칠 욕실 수 × 욕실 공사 범위 12개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (기존 타일*, 욕조*, 욕실 천장재*). *는 조건이 켜질 때만 묻는 칸

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `1-full` | 1칸 / 전체 공사 | 276 | 138 |
| `1-fixtures` | 1칸 / 도기 · 수전만 | 276 | 138 |
| `1-unknown` | 1칸 / 모르겠어요 | 276 | 138 |
| `2-full` | 2칸 / 전체 공사 | 276 | 138 |
| `2-fixtures` | 2칸 / 도기 · 수전만 | 276 | 138 |
| `2-unknown` | 2칸 / 모르겠어요 | 276 | 138 |
| `3-full` | 3칸 / 전체 공사 | 276 | 138 |
| `3-fixtures` | 3칸 / 도기 · 수전만 | 276 | 138 |
| `3-unknown` | 3칸 / 모르겠어요 | 276 | 138 |
| `unknown-full` | 모르겠어요 / 전체 공사 | 276 | 138 |
| `unknown-fixtures` | 모르겠어요 / 도기 · 수전만 | 276 | 138 |
| `unknown-unknown` | 모르겠어요 / 모르겠어요 | 276 | 138 |
| 합계 | | 3,312 | 1,656 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade bath   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade bath       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade bath --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
