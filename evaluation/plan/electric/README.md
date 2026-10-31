# 공정 의견 사례: 전기·조명 (`electric`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,998개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 전기 공사 7개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (조명 교체 범위*, 바꿀 조명 개수*, 조명 종류*, 콘센트 · 스위치 교체 범위*, 바꿀 콘센트 · 스위치 개수*, 늘릴 콘센트 자리*). *는 조건이 켜질 때만 묻는 칸

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `lights` | 조명 교체 | 476 | 238 |
| `outlets` | 콘센트 · 스위치 교체 | 476 | 238 |
| `points` | 콘센트 자리 늘리기 | 476 | 238 |
| `lights+outlets` | 조명 교체 + 콘센트 · 스위치 교체 | 476 | 238 |
| `lights+points` | 조명 교체 + 콘센트 자리 늘리기 | 476 | 238 |
| `outlets+points` | 콘센트 · 스위치 교체 + 콘센트 자리 늘리기 | 476 | 238 |
| `lights+outlets+points` | 조명 교체 + 콘센트 · 스위치 교체 + 콘센트 자리 늘리기 | 476 | 238 |
| 합계 | | 3,332 | 1,666 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade electric   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade electric       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade electric --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
