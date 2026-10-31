# 공정 의견 사례: 창호 (`window`)

`../make_cases.py`가 공정 스펙으로 만든 파일이다. 손으로 고치지 않고 다시 만든다.

- 전체 4,941개: `cases_5k.jsonl` (커밋 안 함)
- 표본 100개: `sample_100.jsonl` (커밋, dev 67 · held-out 33)
- 범주: 바꿀 창 × 창 종류 × 유리 27개
- 범주 안 격자: 거주 × 같이 하는 공정 × 면적 기준 × 범주 밖 칸 (바꿀 창 개수*). *는 조건이 켜질 때만 묻는 칸

| 범주 | 값 | dev | held-out |
| --- | --- | ---: | ---: |
| `all-pvc-low_e` | 집 전체 창 / PVC 이중창 / 로이 복층유리 | 122 | 61 |
| `all-pvc-clear` | 집 전체 창 / PVC 이중창 / 일반 복층유리 | 122 | 61 |
| `all-pvc-unknown` | 집 전체 창 / PVC 이중창 / 모르겠어요 | 122 | 61 |
| `all-system-low_e` | 집 전체 창 / 알루미늄 시스템창 / 로이 복층유리 | 122 | 61 |
| `all-system-clear` | 집 전체 창 / 알루미늄 시스템창 / 일반 복층유리 | 122 | 61 |
| `all-system-unknown` | 집 전체 창 / 알루미늄 시스템창 / 모르겠어요 | 122 | 61 |
| `all-unknown-low_e` | 집 전체 창 / 모르겠어요 / 로이 복층유리 | 122 | 61 |
| `all-unknown-clear` | 집 전체 창 / 모르겠어요 / 일반 복층유리 | 122 | 61 |
| `all-unknown-unknown` | 집 전체 창 / 모르겠어요 / 모르겠어요 | 122 | 61 |
| `some-pvc-low_e` | 몇 개만 / PVC 이중창 / 로이 복층유리 | 122 | 61 |
| `some-pvc-clear` | 몇 개만 / PVC 이중창 / 일반 복층유리 | 122 | 61 |
| `some-pvc-unknown` | 몇 개만 / PVC 이중창 / 모르겠어요 | 122 | 61 |
| `some-system-low_e` | 몇 개만 / 알루미늄 시스템창 / 로이 복층유리 | 122 | 61 |
| `some-system-clear` | 몇 개만 / 알루미늄 시스템창 / 일반 복층유리 | 122 | 61 |
| `some-system-unknown` | 몇 개만 / 알루미늄 시스템창 / 모르겠어요 | 122 | 61 |
| `some-unknown-low_e` | 몇 개만 / 모르겠어요 / 로이 복층유리 | 122 | 61 |
| `some-unknown-clear` | 몇 개만 / 모르겠어요 / 일반 복층유리 | 122 | 61 |
| `some-unknown-unknown` | 몇 개만 / 모르겠어요 / 모르겠어요 | 122 | 61 |
| `unknown-pvc-low_e` | 모르겠어요 / PVC 이중창 / 로이 복층유리 | 122 | 61 |
| `unknown-pvc-clear` | 모르겠어요 / PVC 이중창 / 일반 복층유리 | 122 | 61 |
| `unknown-pvc-unknown` | 모르겠어요 / PVC 이중창 / 모르겠어요 | 122 | 61 |
| `unknown-system-low_e` | 모르겠어요 / 알루미늄 시스템창 / 로이 복층유리 | 122 | 61 |
| `unknown-system-clear` | 모르겠어요 / 알루미늄 시스템창 / 일반 복층유리 | 122 | 61 |
| `unknown-system-unknown` | 모르겠어요 / 알루미늄 시스템창 / 모르겠어요 | 122 | 61 |
| `unknown-unknown-low_e` | 모르겠어요 / 모르겠어요 / 로이 복층유리 | 122 | 61 |
| `unknown-unknown-clear` | 모르겠어요 / 모르겠어요 / 일반 복층유리 | 122 | 61 |
| `unknown-unknown-unknown` | 모르겠어요 / 모르겠어요 / 모르겠어요 | 122 | 61 |
| 합계 | | 3,294 | 1,647 |

## 다시 만들기 (저장소 루트에서)

```bash
cd backend
uv run python ../evaluation/plan/make_cases.py --trade window   # 사례 · 표본 · 이 README
uv run python ../evaluation/check_cases.py --trade window       # 무료 점검 (T0)
uv run python ../evaluation/run_agent.py --trade window --fake  # 가짜 LLM으로 채점 흐름 (무료)
```
