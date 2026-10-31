# 공정 의견 사례: 목공 (`mokgong`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,995개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 목공 항목 15개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (방문 개수*, 문틀 교체*). *는 조건이 켜질 때만 묻는 칸

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `molding` | 천장 몰딩 | 222 | 111 |
| `base` | 걸레받이 | 222 | 111 |
| `door` | 방문 | 222 | 111 |
| `flatten` | 천장 평탄화 | 222 | 111 |
| `molding+base` | 천장 몰딩 + 걸레받이 | 222 | 111 |
| `molding+door` | 천장 몰딩 + 방문 | 222 | 111 |
| `molding+flatten` | 천장 몰딩 + 천장 평탄화 | 222 | 111 |
| `base+door` | 걸레받이 + 방문 | 222 | 111 |
| `base+flatten` | 걸레받이 + 천장 평탄화 | 222 | 111 |
| `door+flatten` | 방문 + 천장 평탄화 | 222 | 111 |
| `molding+base+door` | 천장 몰딩 + 걸레받이 + 방문 | 222 | 111 |
| `molding+base+flatten` | 천장 몰딩 + 걸레받이 + 천장 평탄화 | 222 | 111 |
| `molding+door+flatten` | 천장 몰딩 + 방문 + 천장 평탄화 | 222 | 111 |
| `base+door+flatten` | 걸레받이 + 방문 + 천장 평탄화 | 222 | 111 |
| `molding+base+door+flatten` | 천장 몰딩 + 걸레받이 + 방문 + 천장 평탄화 | 222 | 111 |
| 합계 | | 3,330 | 1,665 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade mokgong   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade mokgong       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade mokgong --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
