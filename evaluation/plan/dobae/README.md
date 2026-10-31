# 공정 의견 사례: 도배 (`dobae`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,995개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 도배 유형 × 천장 도배 9개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `economy-yes` | 저가형 · 합지 / 천장도 해요 | 370 | 185 |
| `economy-no` | 저가형 · 합지 / 벽만 해요 | 370 | 185 |
| `economy-unknown` | 저가형 · 합지 / 모르겠어요 | 370 | 185 |
| `basic-yes` | 기본형 · 실크 / 천장도 해요 | 370 | 185 |
| `basic-no` | 기본형 · 실크 / 벽만 해요 | 370 | 185 |
| `basic-unknown` | 기본형 · 실크 / 모르겠어요 | 370 | 185 |
| `unknown-yes` | 모르겠어요 / 천장도 해요 | 370 | 185 |
| `unknown-no` | 모르겠어요 / 벽만 해요 | 370 | 185 |
| `unknown-unknown` | 모르겠어요 / 모르겠어요 | 370 | 185 |
| 합계 | | 3,330 | 1,665 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade dobae   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade dobae       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade dobae --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
