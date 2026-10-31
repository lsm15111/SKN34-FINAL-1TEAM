# 공정 의견 사례: 타일 (`tile`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,998개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 타일 붙일 곳 7개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (타일 크기, 지금 타일)

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `kitchen` | 주방 벽 | 476 | 238 |
| `entrance` | 현관 바닥 | 476 | 238 |
| `balcony` | 베란다 바닥 | 476 | 238 |
| `kitchen+entrance` | 주방 벽 + 현관 바닥 | 476 | 238 |
| `kitchen+balcony` | 주방 벽 + 베란다 바닥 | 476 | 238 |
| `entrance+balcony` | 현관 바닥 + 베란다 바닥 | 476 | 238 |
| `kitchen+entrance+balcony` | 주방 벽 + 현관 바닥 + 베란다 바닥 | 476 | 238 |
| 합계 | | 3,332 | 1,666 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade tile   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade tile       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade tile --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
