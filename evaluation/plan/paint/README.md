# 공정 의견 사례: 도장 (`paint`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,995개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 칠할 곳 15개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (페인트 종류*, 퍼티 범위*, 칠할 방문 개수*). *는 조건이 켜질 때만 묻는 칸

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `wall` | 벽 | 222 | 111 |
| `ceiling` | 천장 | 222 | 111 |
| `door` | 방문 · 문틀 | 222 | 111 |
| `balcony` | 베란다 (탄성코트) | 222 | 111 |
| `wall+ceiling` | 벽 + 천장 | 222 | 111 |
| `wall+door` | 벽 + 방문 · 문틀 | 222 | 111 |
| `wall+balcony` | 벽 + 베란다 (탄성코트) | 222 | 111 |
| `ceiling+door` | 천장 + 방문 · 문틀 | 222 | 111 |
| `ceiling+balcony` | 천장 + 베란다 (탄성코트) | 222 | 111 |
| `door+balcony` | 방문 · 문틀 + 베란다 (탄성코트) | 222 | 111 |
| `wall+ceiling+door` | 벽 + 천장 + 방문 · 문틀 | 222 | 111 |
| `wall+ceiling+balcony` | 벽 + 천장 + 베란다 (탄성코트) | 222 | 111 |
| `wall+door+balcony` | 벽 + 방문 · 문틀 + 베란다 (탄성코트) | 222 | 111 |
| `ceiling+door+balcony` | 천장 + 방문 · 문틀 + 베란다 (탄성코트) | 222 | 111 |
| `wall+ceiling+door+balcony` | 벽 + 천장 + 방문 · 문틀 + 베란다 (탄성코트) | 222 | 111 |
| 합계 | | 3,330 | 1,665 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade paint   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade paint       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade paint --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
