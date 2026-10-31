# 공정 의견 사례: 주방 (`kitchen`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,992개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 싱크대 배치 4개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (싱크대 길이, 상판, 함께 바꿀 것)

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `straight` | 일자 | 832 | 416 |
| `l_shape` | ㄱ자 | 832 | 416 |
| `parallel` | 평행형 | 832 | 416 |
| `unknown` | 모르겠어요 | 832 | 416 |
| 합계 | | 3,328 | 1,664 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade kitchen   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade kitchen       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade kitchen --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
