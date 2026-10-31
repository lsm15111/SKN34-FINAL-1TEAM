# 공정 의견 사례: 필름 (`film`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,950개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 필름 붙일 곳 22개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (필름 등급, 필름 붙일 방문 개수*). *는 조건이 켜질 때만 묻는 칸

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `door` | 방문 문짝 | 150 | 75 |
| `frame` | 방문 문틀 | 150 | 75 |
| `entrance` | 현관문 (안쪽) | 150 | 75 |
| `molding` | 천장 몰딩 | 150 | 75 |
| `closet` | 붙박이장 문 | 150 | 75 |
| `kitchen` | 주방 문짝 | 150 | 75 |
| `door+frame+entrance+molding+closet+kitchen` | 방문 문짝 + 방문 문틀 + 현관문 (안쪽) + 천장 몰딩 + 붙박이장 문 + 주방 문짝 | 150 | 75 |
| `door+frame` | 방문 문짝 + 방문 문틀 | 150 | 75 |
| `door+entrance` | 방문 문짝 + 현관문 (안쪽) | 150 | 75 |
| `door+molding` | 방문 문짝 + 천장 몰딩 | 150 | 75 |
| `door+closet` | 방문 문짝 + 붙박이장 문 | 150 | 75 |
| `door+kitchen` | 방문 문짝 + 주방 문짝 | 150 | 75 |
| `frame+entrance` | 방문 문틀 + 현관문 (안쪽) | 150 | 75 |
| `frame+molding` | 방문 문틀 + 천장 몰딩 | 150 | 75 |
| `frame+closet` | 방문 문틀 + 붙박이장 문 | 150 | 75 |
| `frame+kitchen` | 방문 문틀 + 주방 문짝 | 150 | 75 |
| `entrance+molding` | 현관문 (안쪽) + 천장 몰딩 | 150 | 75 |
| `entrance+closet` | 현관문 (안쪽) + 붙박이장 문 | 150 | 75 |
| `entrance+kitchen` | 현관문 (안쪽) + 주방 문짝 | 150 | 75 |
| `molding+closet` | 천장 몰딩 + 붙박이장 문 | 150 | 75 |
| `molding+kitchen` | 천장 몰딩 + 주방 문짝 | 150 | 75 |
| `closet+kitchen` | 붙박이장 문 + 주방 문짝 | 150 | 75 |
| 합계 | | 3,300 | 1,650 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade film   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade film       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade film --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
